"""按任务读取安装内用户指南，保留宏代码和操作前提，不执行文档中的程序。

复用 Oxygen 的标题／摘要索引而非扫描整套 HTML。正文只解析指定主题，代码保持
发布时的换行；窗口截断与示例的可编译性是两回事，均不能冒充运行依据。
"""

from functools import lru_cache
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

from starbridge.tools.catalog.javadoc import Element, Page, installation_version
from .api_docs import DocumentationBudgetError, MAX_RESPONSE_BYTES

MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_TOPIC_BYTES = 2 * 1024 * 1024
INDEX_NAME = 'oxygen-webhelp/app/search/index/htmlFileInfoList.js'
TOPIC_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.html\Z')


def _stamp(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_bytes(path, expected, maximum):
    """按输入预算读取一次常规文件，并拒绝读前／读后已改变的来源。"""
    with path.open('rb') as stream:
        info = os.fstat(stream.fileno())
        actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if not stat.S_ISREG(info.st_mode) or actual != expected:
            raise ValueError('Documentation source changed or is not a regular file')
        if info.st_size > maximum:
            raise ValueError(f'Documentation source exceeds the {maximum}-byte input budget')
        data = stream.read(maximum + 1)
        if len(data) > maximum or _stamp(path) != expected:
            raise ValueError('Documentation source exceeded its budget or changed during reading')
    return data


def _raw(node):
    if node.tag == 'br':
        return '\n'
    return ''.join(_raw(child) if isinstance(child, Element) else child for child in node.children)


@lru_cache(maxsize=4)
def _index(path, stamp):
    """只解码已知 JS 赋值中的 JSON 数组；不运行 JS，不补猜未识别的索引结构。"""
    data = _read_bytes(Path(path), stamp, MAX_INDEX_BYTES)
    text = data.decode('utf-8-sig')
    prefix = re.match(r'\s*(?:var|let|const)\s+htmlFileInfoList\s*=\s*', text)
    if not prefix:
        raise ValueError('Unsupported user-guide index assignment')
    entries, end = json.JSONDecoder().raw_decode(text, prefix.end())
    if text[end:].strip() not in ('', ';') or not isinstance(entries, list):
        raise ValueError('Unsupported user-guide index suffix or payload')
    rows, omitted, seen = [], 0, set()
    for entry in entries:
        fields = entry.split('@@@', 2) if isinstance(entry, str) else []
        if len(fields) != 3 or not TOPIC_PATTERN.fullmatch(fields[0]) or fields[0] in seen:
            omitted += 1
            continue
        topic, title, summary = fields
        title, summary = unescape(title), unescape(summary)
        seen.add(topic)
        rows.append((topic, title, summary, (title + ' ' + summary).casefold()))
    return tuple(rows), frozenset(seen), omitted, hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=32)
def _matches(path, stamp, query):
    """复用命中序列；英文词从词首匹配，避免table误命中suitable/repeatable。

    允许英文词尾延伸以保留table/tables等常见检索，不做词干还原或语义召回；
    非ASCII词仍按子串匹配，不能把中文连续文字当成一个英文单词。精确标题优先。
    """
    rows, _, _, _ = _index(path, stamp)
    words = query.split()
    patterns = [re.compile(('(?<![a-z0-9])' if word.isascii() and word[0].isalnum() else '')
                           + re.escape(word)) for word in words]
    selected = [index for index, row in enumerate(rows) if all(pattern.search(row[3]) for pattern in patterns)]
    selected.sort(key=lambda index: (rows[index][1].casefold() != query,
                                    -sum(bool(pattern.search(rows[index][1].casefold())) for pattern in patterns),
                                    rows[index][1].casefold(), rows[index][0]))
    return tuple(selected)


def _render(article):
    """生成可续读的正文字符流，并标记原样代码在该流中的半开区间。

    只规范化说明文字的排版空白；pre 内容不缩进、不修复、不拼成可执行宏。
    表格按行／单元格分隔，图片只保留替代文字，脚本及样式不进入正文。
    """
    parts, buffer, codes = [], [], []
    position = 0

    def append(text):
        nonlocal position
        parts.append(text)
        position += len(text)

    def flush():
        value = re.sub(r'[^\S\n]+', ' ', ''.join(buffer))
        value = re.sub(r' *\n *', '\n', value)
        value = re.sub(r'\n{3,}', '\n\n', value).strip()
        buffer.clear()
        if value:
            append(value + '\n\n')

    blocks = {'p', 'div', 'section', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
              'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'table', 'tr', 'blockquote'}

    def visit(node):
        if not isinstance(node, Element):
            buffer.append(node)
            return
        if node.tag in ('script', 'style', 'svg'):
            return
        if node.tag == 'pre':
            flush()
            code = _raw(node)
            start = position
            append(code)
            codes.append({'index': len(codes), 'start': start, 'end': position,
                          'sha256': hashlib.sha256(code.encode('utf-8')).hexdigest(),
                          'source_form': 'published_code_block', 'compilation': 'not_performed'})
            append('\n\n')
            return
        if node.tag in blocks or node.tag == 'br':
            buffer.append('\n')
        if node.tag in ('td', 'th'):
            buffer.append(' | ')
        if node.tag == 'img':
            buffer.append('[image: ' + node.attrs.get('alt', 'no alternative text') + ']')
        for child in node.children:
            visit(child)
        if node.tag in blocks:
            buffer.append('\n')

    visit(article)
    flush()
    return ''.join(parts), tuple(codes)


@lru_cache(maxsize=8)
def _topic(path, stamp):
    """缓存八个有输入上限的已选主题；缓存文本而非保留整棵 HTML 树。"""
    data = _read_bytes(Path(path), stamp, MAX_TOPIC_BYTES)
    page = Page(data.decode('utf-8-sig')).root
    main = next(page.walk(tag='main'), None)
    article = next(main.walk(tag='article'), None) if main else None
    if article is None:
        raise ValueError('User-guide topic has no supported main/article body')
    text, codes = _render(article)
    title = next(page.walk(tag='title'), None)
    html = next(page.walk(tag='html'), None)
    metadata = list(page.walk(tag='meta'))
    aliases = [node.attrs.get('content', '') for node in metadata if node.attrs.get('name') == 'TopicAlias']
    links, seen = [], set()
    for node in article.walk(tag='a'):
        href = node.attrs.get('href')
        if href and href not in seen:
            seen.add(href)
            links.append((href, node.text()))
    for node in metadata:
        href = node.attrs.get('content')
        if node.attrs.get('name') == 'DC.relation' and href and href not in seen:
            seen.add(href)
            links.append((href, ''))
    return {'text': text, 'code_blocks': codes, 'links': tuple(links),
            'title': title.text() if title else None,
            'declared_language': html.attrs.get('lang') if html else None,
            'api_aliases': tuple(aliases), 'sha256': hashlib.sha256(data).hexdigest()}


def _measure(result):
    for _ in range(5):
        size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if result['budget']['serialized_bytes'] == size:
            return size
        result['budget']['serialized_bytes'] = size
    return len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))


def _require(result):
    if _measure(result) > MAX_RESPONSE_BYTES:
        raise DocumentationBudgetError('User-guide metadata exceeds the response budget; no source or error was silently removed')
    return result


class GuideDocumentation:
    """选择本机指南语言包；不自动切换版本、语言，也不下载教程依赖。"""

    def __init__(self, installation, language='en'):
        if not isinstance(installation, str) or not Path(installation).is_absolute():
            raise ValueError('installation must be an absolute installation root')
        if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2}(?:[-_][A-Za-z]{2})?', language):
            raise ValueError('language must be a documentation directory language code')
        self.root = Path(installation).resolve(strict=True)
        self.version, self.version_sources = installation_version(self.root)
        self.language = language
        self.directory = self.root / 'doc' / language / 'online/STARCCMP'

    def _local(self, relative):
        path = (self.directory / relative).resolve(strict=True)
        if not path.is_relative_to(self.directory.resolve()) or not path.is_relative_to(self.root):
            raise ValueError('User-guide reference escapes the selected installation or language root')
        return path

    def _base(self):
        return {'schema_version': 1, 'source_kind': 'installed_user_guide',
                'installation': str(self.root), 'version': self.version, 'version_sources': self.version_sources,
                'requested_language': self.language, 'read_status': 'ok',
                'budget': {'max_bytes': MAX_RESPONSE_BYTES, 'serialized_bytes': 0,
                           'scope': 'result_only_excludes_service_envelope_and_protocol',
                           'max_index_bytes': MAX_INDEX_BYTES, 'max_topic_bytes': MAX_TOPIC_BYTES,
                           'index_cache_entries': 4, 'topic_cache_entries': 8},
                'coverage': {'errors': [], 'search_scope': 'official_title_and_summary_index',
                             'full_text_search': False, 'scripts_executed': False,
                             'version_scope': 'Installation and guide package; historical examples may target earlier releases',
                             'external_content_retrieved': False, 'link_targets_verified': False,
                             'rendering': 'Main/article text; prose whitespace normalized, pre code retained',
                             'non_text_content': 'not_rendered_except_image_alt_text'}}

    def _prepare(self, result):
        """核对指南包版本，索引缺失／格式变化与无命中分别表达。"""
        package = self.root / 'doc' / self.language / 'PACKAGE_VERSION'
        package = package.resolve(strict=True)
        if not package.is_relative_to(self.root):
            raise ValueError('Guide package metadata escapes the installation')
        data = _read_bytes(package, _stamp(package), 65536)
        match = re.search(r'^package\.number=(\S+)\s*$', data.decode('utf-8-sig'), re.M)
        if not match:
            raise ValueError('Guide package version metadata is missing')
        number = match.group(1)
        if number.split('_', 1)[0] != self.version['build']:
            raise ValueError('Guide package version differs from the selected installation')
        result['guide_package'] = {'number': number, 'path': str(package), 'sha256': hashlib.sha256(data).hexdigest()}
        path = self._local(INDEX_NAME)
        stamp = _stamp(path)
        rows, names, omitted, digest = _index(str(path), stamp)
        result['index_source'] = {'path': str(path), 'uri': path.as_uri(), 'sha256': digest}
        result['coverage'].update(indexed_topics=len(rows), omitted_index_entries=omitted)
        if omitted:
            result['read_status'] = 'partial'
        return path, stamp, rows, names

    def search(self, query, offset=0, limit=20):
        """按全部关键词匹配标题／摘要；不搜索正文，不据空命中判定缺少操作能力。"""
        if not isinstance(query, str) or not query.strip() or len(query) > 1024:
            raise ValueError('query must contain 1 to 1024 characters')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('offset must be nonnegative and limit must be from 1 to 100')
        result = self._base()
        result.update(query=query, matches=[], next_offset=None)
        try:
            path, stamp, rows, _ = self._prepare(result)
            matches = _matches(str(path), stamp, ' '.join(query.casefold().split()))
            result['coverage'].update(total_matches=len(matches), offset=offset, returned=0,
                matching='All terms; ASCII alphanumeric-start terms match word prefixes, others match substrings; exact title first')
            for position in range(offset, min(len(matches), offset + limit)):
                topic, title, summary, _ = rows[matches[position]]
                result['matches'].append({'topic': topic, 'title': title, 'summary': summary,
                                          'read_method': 'read_guide', 'body_read': False})
                result['coverage']['returned'] = len(result['matches'])
                result['next_offset'] = position + 1 if position + 1 < len(matches) else None
                if _measure(result) > MAX_RESPONSE_BYTES:
                    result['matches'].pop()
                    result['coverage']['returned'] = len(result['matches'])
                    result['next_offset'] = position
                    if not result['matches']:
                        raise DocumentationBudgetError('One complete guide index entry exceeds the response budget')
                    break
        except (OSError, ValueError) as error:
            if isinstance(error, DocumentationBudgetError):
                raise
            result['read_status'] = 'unavailable'
            result['coverage']['errors'].append({'type': type(error).__name__, 'message': str(error)})
        return _require(result)

    def read(self, topic, offset=0, limit_chars=12000, link_offset=0, link_limit=20, expected_sha256=None):
        """按正文字符窗口续读，单独分页相关链接，保留代码窗口的完整性标记。

        offset计Unicode码点而非文件字节；sha256绑定原HTML。重复翻页使用期望摘要，
        来源变化时不给新旧混合文字。只有已列入本语言索引的平面HTML主题可读取。
        """
        if not isinstance(topic, str) or not TOPIC_PATTERN.fullmatch(topic):
            raise ValueError('topic must be the local HTML topic name returned by search_guide')
        for value, name in ((offset, 'offset'), (link_offset, 'link_offset')):
            if type(value) is not int or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if type(limit_chars) is not int or not 1 <= limit_chars <= 24000:
            raise ValueError('limit_chars must be from 1 to 24000')
        if type(link_limit) is not int or not 1 <= link_limit <= 100:
            raise ValueError('link_limit must be from 1 to 100')
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)):
            raise ValueError('expected_sha256 must be a lowercase SHA256 digest')
        result = self._base()
        result.update(topic=topic, text='', code_blocks=[], links=[], next_offset=None, links_next_offset=None)
        try:
            _, _, _, names = self._prepare(result)
            if topic not in names:
                result['read_status'] = 'not_found_in_index'
                return _require(result)
            path = self._local(topic)
            page = _topic(str(path), _stamp(path))
            result.update(title=page['title'], declared_language=page['declared_language'],
                          source={'path': str(path), 'uri': path.as_uri(), 'sha256': page['sha256']},
                          api_aliases=list(page['api_aliases']))
            if expected_sha256 is not None and expected_sha256 != page['sha256']:
                result['read_status'] = 'source_changed'
                return _require(result)
            links = page['links']
            for href, label in links[link_offset:link_offset + link_limit]:
                parsed = urlsplit(unquote(href))
                relative = parsed.path or topic
                while relative.startswith('./'):
                    relative = relative[2:]
                local_topic = relative if not parsed.scheme and not parsed.netloc and relative in names else None
                result['links'].append({'href': href, 'label': label, 'topic': local_topic,
                                        'anchor': parsed.fragment or None,
                                        'retrieved': False, 'readable_as_indexed_topic': local_topic is not None})
            link_end = link_offset + len(result['links'])
            result['links_next_offset'] = link_end if link_end < len(links) else None
            result['coverage'].update(links_total=len(links), links_offset=link_offset,
                                      links_returned=len(result['links']), code_blocks_total=len(page['code_blocks']),
                                      code_completeness='Window completeness only; standalone macro structure and behavior are not verified')
            text = page['text']

            def window(count):
                end = min(len(text), offset + count)
                result['text'] = text[offset:end]
                result['next_offset'] = end if end < len(text) else None
                result['range'] = {'unit': 'Unicode_code_points', 'offset': offset, 'end': max(offset, end),
                                   'returned_chars': len(result['text']), 'total_chars': len(text)}
                result['code_blocks'] = [{**code, 'complete_in_window': offset <= code['start'] and end >= code['end'],
                                           'returned_start': max(offset, code['start']), 'returned_end': min(end, code['end'])}
                                          for code in page['code_blocks'] if code['start'] < end and code['end'] > offset]
                result['coverage']['full_body_returned'] = offset == 0 and end == len(text)
                return _measure(result)

            # 缩小字符窗口而非截断来源或代码标记；无法容纳元数据时明确拒绝。
            requested = min(limit_chars, max(0, len(text) - offset))
            if window(requested) > MAX_RESPONSE_BYTES:
                low, high = 0, requested
                while low < high:
                    middle = (low + high + 1) // 2
                    if window(middle) <= MAX_RESPONSE_BYTES:
                        low = middle
                    else:
                        high = middle - 1
                window(low)
                if low == 0 and requested:
                    raise DocumentationBudgetError('Guide metadata leaves no room for body text; request fewer links')
        except (OSError, ValueError, RecursionError) as error:
            if isinstance(error, DocumentationBudgetError):
                raise
            result['read_status'] = 'unavailable'
            result['coverage']['errors'].append({'type': type(error).__name__, 'message': str(error)})
        return _require(result)
