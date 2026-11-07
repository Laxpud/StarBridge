"""按当前安装读取官方 Java API 资料，不使用结构化适配清单限制可查类型。

搜索只读取 Javadoc 自带索引；正文按选中的类／成员加载，不预先扫描全部 HTML。
资料证明的是安装文档写了什么，不证明当前算例对象存在、调用成功或 API 没有副作用。
"""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from starbridge.tools.catalog.javadoc import Element, Page, installation_version


MAX_RESPONSE_BYTES = 32768


class DocumentationBudgetError(ValueError):
    """最低资料及其来源、诊断仍无法放入响应时明确拒绝，不将其报告成无 API。"""


def _budget():
    """预算只约束成功 result；索引扫描、HTML 解析和缓存仍可能读取完整材料。"""
    return {'max_bytes': MAX_RESPONSE_BYTES, 'serialized_bytes': 0,
            'encoding': 'UTF-8 JSON; ensure_ascii=False, allow_nan=False, default separators',
            'scope': 'result_only_excludes_service_envelope_and_protocol',
            'source_reference_root': 'result',
            'io_globally_bounded': False,
            'io_notice': 'Indexes and selected HTML pages may be fully loaded and parsed; this is not a scan or cache memory budget.'}


def _response_size(result):
    """按实际输出分隔符计量，并把计数字段本身的位数计入预算。"""
    for _ in range(4):
        size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if result['budget']['serialized_bytes'] == size:
            return size
        result['budget']['serialized_bytes'] = size
    return len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))


def _require_budget(result):
    """签名、版本、来源和错误不能以静默删除的方式满足预算。"""
    size = _response_size(result)
    if size > MAX_RESPONSE_BYTES:
        raise DocumentationBudgetError(
            f'Documentation response requires {size} bytes with its current metadata and explicit excerpt diagnostics; '
            f'limit is {MAX_RESPONSE_BYTES}. Signatures, sources and errors were not truncated. '
            'Select a named member or narrower query where possible; this is not evidence that an API is unavailable.')
    return result


def _body_texts(result):
    """只选择可以明确摘录的正文；不裁剪签名、链接、继承来源、参数标签或错误。"""
    records = [(result, '#/source')] if 'description' in result else []
    records.extend((record, f'#/members/{index}/source') for index, record in enumerate(result.get('members', [])))
    for record, source_ref in records:
        if record.get('description'):
            yield record, 'description', record, 'description', source_ref
        for index, note in enumerate(record.get('notes', [])):
            if note.get('text'):
                yield note, 'text', record, f'notes[{index}].text', source_ref
        for name in ('examples', 'deprecation'):
            for index, text in enumerate(record.get(name, [])):
                if text:
                    yield record[name], index, record, f'{name}[{index}]', source_ref


def _fit_first_page(result, refresh):
    """为最低一行资料保留来源与错误，仅在超预算时逐步摘录最长正文。

    已有类注记摘录保留原长度与位置；新摘录通过 JSON Pointer 指向当前 result 的完整 source，
    避免每个参数注记都重复复制绝对路径。截短的示例只是正文片段，不是完整可执行源码。
    后续成员不会为凑够 limit 而压缩本页已返回的正文，而是在完整条目边界续页。
    """
    refresh()
    while _response_size(result) > MAX_RESPONSE_BYTES:
        texts = list(_body_texts(result))
        if not texts:
            return _require_budget(result)
        container, key, record, field, source_ref = max(
            texts, key=lambda item: len(json.dumps(item[0][item[1]], ensure_ascii=False).encode('utf-8')))
        text = container[key]
        container[key] = text[:len(text) // 2]
        truncations = record.setdefault('content_truncations', [])
        existing = next((item for item in truncations if item['field'] == field), None)
        if existing is None:
            truncations.append({'field': field, 'total_chars': len(text),
                                'returned_chars': len(container[key]), 'reason': 'response_budget_excerpt',
                                'full_text_ref': source_ref})
        else:
            existing['returned_chars'] = len(container[key])
            existing['response_budget_excerpt'] = True
        refresh()
    return result


def _stamp(path):
    """以文件身份和修改信息使进程内缓存失效；不跨安装复用解析结果。"""
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=8)
def _index(path, stamp):
    """解析官方 JS 中的 JSON 数组而不执行脚本，同时保留材料内容摘要。"""
    data = Path(path).read_bytes()
    text = data.decode('utf-8')
    start = text.find('[')
    if start < 0:
        raise ValueError(f'Javadoc index has no JSON array: {path}')
    entries, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError(f'Unsupported Javadoc index: {path}')
    return entries, hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=32)
def _page(path, stamp):
    """只缓存有界数量的已选正文；返回的 HTML 树只读，不放入结果供调用者修改。"""
    data = Path(path).read_bytes()
    return Page(data.decode('utf-8')).root, hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=4)
def _types(doc, stamp):
    """复用完整类型位置表，避免每次读取一个成员都重新解析数万条文件路径。"""
    root = Path(doc).resolve()
    entries, digest = _index(str(root / 'type-search-index.js'), stamp)
    paths = {}
    for entry in entries:
        package, label = entry.get('p'), entry.get('l')
        if isinstance(package, str) and isinstance(label, str):
            relative = entry.get('u') or f"{package.replace('.', '/')}/{label}.html"
            url = urlsplit(relative)
            if url.scheme or url.netloc:
                raise ValueError('Type index contains an external page')
            path = (root / unquote(url.path)).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Type index escapes the selected documentation root')
            paths[f'{package}.{label}'] = path
    return paths, {path: name for name, path in paths.items()}, digest


def _anchors(section):
    """保留成员区段内所有官方锚点，包括泛型签名的类型擦除别名。"""
    return {node.attrs['id'] for node in section.walk() if node.attrs.get('id')}


def _raw(node):
    """保留示例代码的换行与缩进，不把 Java 行注释后的代码折叠到同一行。"""
    return ''.join(_raw(child) if isinstance(child, Element) else child for child in node.children)


def _range(offset, limit):
    """资料分页采用独立小页面，避免默认把一个大类的全部成员送入上下文。"""
    if type(offset) is not int or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be an integer from 1 to 100')


def _text(value, field):
    """拒绝空白选择，避免一次无意的空查询变成全部资料导出。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be non-empty text')
    return value.strip()


class Documentation:
    """绑定一份安装的版本材料与官方文档，查询不需要启动 STAR 或取得许可证。"""

    def __init__(self, installation):
        if not isinstance(installation, str) or not Path(installation).is_absolute():
            raise ValueError('installation must be an absolute STAR installation directory')
        self.root = Path(installation).resolve(strict=True)
        self.version, self.version_sources = installation_version(self.root)
        self.doc = self.root / 'doc/client/html'

    def source(self, path, digest=None, anchor=None):
        """输出可追溯路径、摘要和可打开 URI；锚点来自官方 HTML／索引而非猜测。"""
        result = {'path': str(path), 'installation_relative': path.relative_to(self.root).as_posix(),
                  'uri': path.as_uri() + ('#' + quote(anchor, safe='(),.') if anchor else '')}
        if digest is not None:
            result['sha256'] = digest
        return result

    def base(self):
        """每次响应声明资料来源与证据边界，不把查询成功解释为执行验证。"""
        return {'installation': str(self.root), 'version': self.version,
                'version_sources': self.version_sources, 'evidence': 'installed_official_javadoc',
                'limitations': ['Documentation is not runtime validation.',
                    'No match does not prove an API or operation is unavailable.',
                    'Search covers index labels, not all documentation prose or external macro libraries.',
                    'Text marked in content_truncations is incomplete; a truncated example is not complete executable source.']}

    def load_index(self, kind):
        """将缺失、损坏的索引作为明确失败报告，不用空索引冒充无匹配。"""
        path = self.doc / f'{kind}-search-index.js'
        entries, digest = _index(str(path), _stamp(path))
        return entries, self.source(path, digest)

    def types(self):
        """沿官方类型索引建立类型到页面的对应，包括嵌套类型，不依赖目录白名单。"""
        path = self.doc / 'type-search-index.js'
        paths, reverse, digest = _types(str(self.doc), _stamp(path))
        return paths, reverse, self.source(path, digest)

    def local_path(self, relative, origin=None):
        """只解析文档根内的本地引用；外部资料只返回链接，不隐式联网。"""
        url = urlsplit(relative)
        if url.scheme or url.netloc:
            raise ValueError('External documentation is not a local Javadoc page')
        path = ((origin.parent if origin else self.doc) / unquote(url.path)).resolve()
        if not path.is_relative_to(self.doc.resolve()):
            raise ValueError('Javadoc reference escapes the selected documentation root')
        return path

    def link(self, href, origin, paths):
        """把类型链接转换为可继续查询的对象；无法映射的链接仍保留真实位置。"""
        url = urlsplit(href)
        if url.scheme or url.netloc:
            return {'uri': href, 'local': False,
                    **({'member': unquote(url.fragment)} if url.fragment else {})}
        path = self.local_path(href, origin) if url.path else origin
        result = {**self.source(path, anchor=unquote(url.fragment)), 'local': True}
        if path in paths:
            result['java_class'] = paths[path]
        if url.fragment:
            result['member'] = unquote(url.fragment)
        return result

    def content(self, node, path, reverse, context_page=None):
        """保留说明、参数／返回约定和文中示例；类级长关系列表分页，不冒充全部已读。

        context_page 仅用于类说明的关联链接。特别长的类注记只给明确标记的文字摘录，
        完整位置仍由来源文件提供；成员说明不套用类注记的固定阈值，只有最低一行仍
        超过总响应预算时才由 _fit_first_page 明确摘录，签名及参数标签保持完整。
        """
        description = [item.text() for item in node.walk('block')]
        notes, truncations = [], []
        for group in node.walk('notes', 'dl'):
            label = None
            for child in group.children:
                if not isinstance(child, Element):
                    continue
                if child.tag == 'dt':
                    label = child.text()
                elif child.tag == 'dd':
                    text = child.text()
                    if context_page is not None and len(text) > 4000:
                        truncations.append({'field': f'notes[{len(notes)}].text',
                                            'total_chars': len(text), 'returned_chars': 4000,
                                            'reason': 'class_note_excerpt',
                                            'full_text': self.source(path, anchor=node.attrs.get('id'))})
                        text = text[:4000]
                    notes.append({'label': label, 'text': text})
        links = node.links()
        link_page = {}
        if context_page is not None:
            offset, limit = context_page
            end = offset + limit
            link_page = {'links_next_offset': end if end < len(links) else None,
                         'links_coverage': {'total': len(links), 'offset': offset,
                                            'returned': len(links[offset:end]), 'truncated': end < len(links)},
                         'content_truncations': truncations}
            links = links[offset:end]
        return {'description': '\n\n'.join(description),
                'description_status': 'present' if description else 'not_provided',
                'notes': notes,
                'deprecation': [item.text() for item in node.walk('deprecation-block')],
                'examples': [_raw(item).strip() for item in node.walk(tag='pre')],
                'links': [self.link(href, path, reverse) for href in links], **link_page}

    def search(self, query, kind='all', offset=0, limit=20):
        """在官方类名／成员索引中查找相关候选，正文由 read 单独展开。

        关键词按空白分词且全部匹配；类名和方法名可以组合。不会自行翻译中文、
        补猜方法或依据无命中生成不存在结论；来源失败与分页截断分别报告。完整候选
        在32 KiB成功结果预算内分页，索引扫描及排序本身仍没有全局资源预算。
        """
        query = _text(query, 'query')
        _range(offset, limit)
        if kind not in ('all', 'type', 'member'):
            raise ValueError('kind must be all, type or member')
        words = query.casefold().split()
        matches, sources, errors, counts = [], [], [], {}
        for selected in (('type', 'member') if kind == 'all' else (kind,)):
            try:
                entries, source = self.load_index(selected)
            except (OSError, ValueError) as error:
                errors.append({'index': selected, 'type': type(error).__name__, 'message': str(error)})
                continue
            sources.append(source)
            counts[selected] = len(entries)
            for entry in entries:
                package, label = entry.get('p'), entry.get('l')
                owner = entry.get('c') if selected == 'member' else label
                if not all(isinstance(value, str) for value in (package, label, owner)):
                    continue
                java_class = f'{package}.{owner}'
                searchable = (java_class + (' ' + label if selected == 'member' else '')).casefold()
                if not all(word in searchable for word in words):
                    continue
                exact = query.casefold() in (label.casefold(), java_class.casefold(), label.split('(')[0].casefold())
                matches.append((not exact, java_class, label, selected, entry))
        matches.sort(key=lambda item: item[:4])
        hits = []
        result = {**self.base(), 'read_status': 'ok', 'query': query, 'matches': hits,
                  'next_offset': None, 'page_end_reason': 'results_end', 'budget': _budget(),
                  'coverage': {'scope': 'official_type_and_member_index_labels', 'kind': kind,
                               'indexed_entries': counts, 'matched': len(matches),
                               'returned': 0, 'offset': offset, 'truncated': False,
                               'sources': sources, 'errors': errors}}

        def refresh():
            """区分当前页与整个查询；末页也不冒充本页包含全部匹配。"""
            end = offset + len(hits)
            complete = len(hits) == len(matches)
            result['next_offset'] = end if end < len(matches) else None
            result['page_end_reason'] = ('offset_beyond_matches' if offset > len(matches) else
                                         'results_end' if end >= len(matches) else
                                         'limit' if len(hits) == limit else 'response_budget')
            result['coverage'].update(returned=len(hits), truncated=end < len(matches), selection_complete=complete)
            result['read_status'] = ('unavailable' if errors and not sources else
                                     'partial' if errors or not complete else 'ok')

        refresh()
        _require_budget(result)
        # 只为本页尝试返回的候选解析路径；预算到达时保留整项到下一页，不截坏标签或来源。
        for _, java_class, label, selected, entry in matches[offset:offset + limit]:
            member = unquote(entry.get('u') or label) if selected == 'member' else None
            owner = entry.get('c') if selected == 'member' else label
            relative = f"{entry['p'].replace('.', '/')}/{owner}.html"
            # 成员索引的 u 是签名锚点，类型索引的 u 才是页面位置。
            if selected == 'type':
                relative = entry.get('u') or relative
            hit = {'kind': selected, 'java_class': java_class, 'label': label,
                   'source': self.source(self.local_path(relative), anchor=member)}
            if member is not None:
                hit['member'] = member
            hits.append(hit)
            refresh()
            if _response_size(result) > MAX_RESPONSE_BYTES:
                if len(hits) == 1:
                    return _require_budget(result)
                hits.pop()
                refresh()
                break
        return _require_budget(result)

    def read(self, java_class, member=None, offset=0, limit=20):
        """读取精确类型或成员；成员可为简单名称或完整锚点，保留重载与继承声明来源。

        不指定 member 时只展开本类成员的一页，并列出继承来源及数量；指定成员时，
        先从本类和官方继承列表定位，再仅加载本页命中的声明。不会将父类内容复制成
        子类自有成员，也不会因当前页面未声明该方法就断言 API 不存在。预算分页同时
        推进本类链接列表，保留 next_offset 和 links_next_offset 共用 offset 的语义；
        正文摘录在 content_truncations 说明，完整签名、来源和错误不能静默删除。
        """
        java_class = _text(java_class, 'java_class')
        member = _text(member, 'member') if member is not None else None
        _range(offset, limit)
        paths, reverse, index_source = self.types()
        base = self.base()
        if java_class not in paths:
            return _require_budget({**base, 'read_status': 'not_found_in_index', 'java_class': java_class,
                    'coverage': {'scope': 'selected_installation_type_index', 'source': index_source},
                    'next_step': 'Search the selected installation index; absence is not proof of API unavailability.',
                    'budget': _budget()})
        path = paths[java_class]
        page, digest = _page(str(path), _stamp(path))
        signature = page.part('type-signature')
        if not signature:
            raise ValueError(f'Unsupported Javadoc type page: {path}')
        description = next(page.walk('class-description'), None)
        if description is None:
            raise ValueError(f'Javadoc class description is unavailable: {path}')
        own = {section.attrs['id']: section for section in page.walk('detail', 'section')
               if section.attrs.get('id') and next(section.walk('member-signature'), None) is not None}

        def selected(anchor, declared_name=None, aliases=()):
            """完整锚点精确选择重载；构造器简单名和泛型别名取官方声明，不猜类型。"""
            if member is None or member == anchor or member in aliases:
                return True
            return '(' not in member and member in (anchor.split('(')[0], declared_name)

        candidates = [(path, anchor, False) for anchor, section in own.items()
                      if selected(anchor, section.part('element-name'), _anchors(section))]
        inherited, seen = [], set(candidates)
        for group in page.walk('inherited-list'):
            links = [self.link(href, path, reverse) for href in group.links()]
            members = [link for link in links if link.get('member')]
            owners = [link for link in links if not link.get('member')]
            inherited.append({'sources': owners, 'member_count': len(members)})
            if member is not None:
                for link in members:
                    if not selected(link['member']):
                        continue
                    key = (Path(link['path']) if link.get('local') else link['uri'], link['member'], True)
                    if key not in seen:
                        candidates.append(key)
                        seen.add(key)
        results, errors = [], []
        class_links = description.links() if member is None else []
        # 先取得不带链接条目的类正文；同一 offset 的成员与类链接随后成行加入，保持两个
        # 游标的原有列表含义，又避免预算分别截短后产生互相跳过或反复重读的续页位置。
        context = ({**self.content(description, path, reverse, (offset, 0)), 'inherited_groups': inherited}
                   if member is None else {'class_context': 'signature_only'})
        result = {**base, 'read_status': 'ok',
                  'java_class': java_class, 'signature': signature, 'source': self.source(path, digest),
                  **context, 'members': results, 'next_offset': None,
                  'page_end_reason': 'results_end', 'budget': _budget(),
                  'coverage': {'scope': 'declared_members' if member is None else 'declared_and_linked_inherited_members',
                               'member_filter': member, 'matched': len(candidates), 'returned': 0,
                               'offset': offset, 'truncated': False, 'errors': errors,
                               'inheritance_expansion': 'named_member_only',
                               'external_documentation_read': False}}
        rows = 0
        total_rows = max(len(candidates), len(class_links))

        def refresh():
            """按接纳的完整行计覆盖；已返回的错误也消耗成员位置，避免反复读取同一坏项。"""
            end = offset + rows
            processed = min(rows, max(0, len(candidates) - offset))
            complete = processed == len(candidates)
            result['next_offset'] = end if end < len(candidates) else None
            result['coverage'].update(returned=len(results), processed=processed,
                                      truncated=end < len(candidates), selection_complete=complete)
            result['page_end_reason'] = ('offset_beyond_entries' if offset > total_rows else
                                         'results_end' if end >= total_rows else
                                         'limit' if rows == limit else 'response_budget')
            links_complete = True
            if member is None:
                links_complete = len(result['links']) == len(class_links)
                result['links_next_offset'] = end if end < len(class_links) else None
                result['links_coverage'].update(returned=len(result['links']),
                    truncated=end < len(class_links), selection_complete=links_complete,
                    continuation='Use the same offset parameter; member and class-link cursors share a page boundary.')
            excerpted = bool(result.get('content_truncations')) or any(item.get('content_truncations') for item in results)
            result['coverage']['text_excerpted'] = excerpted
            result['read_status'] = ('partial' if errors or excerpted or not complete or not links_complete else
                                     'ok' if candidates or member is None else 'not_found_in_page')

        for index in range(offset, min(offset + limit, total_rows)):
            previous_results, previous_errors = len(results), len(errors)
            previous_links = len(result.get('links', []))
            if index < len(candidates):
                owner_path, anchor, is_inherited = candidates[index]
                if not isinstance(owner_path, Path):
                    errors.append({'member': anchor, 'source': owner_path, 'reason': 'external_documentation_not_read'})
                else:
                    try:
                        owner_page, owner_digest = _page(str(owner_path), _stamp(owner_path))
                        section = next((item for item in owner_page.walk('detail', 'section')
                                        if anchor in _anchors(item)), None)
                        if section is None or not section.part('member-signature'):
                            raise ValueError(f'Member detail not found: {owner_path}#{anchor}')
                        results.append({'declaring_class': reverse.get(owner_path), 'member': anchor,
                            'inherited': is_inherited, 'signature': section.part('member-signature'),
                            'source': self.source(owner_path, owner_digest, anchor),
                            **self.content(section, owner_path, reverse)})
                    except (OSError, ValueError) as error:
                        errors.append({'member': anchor, 'source': self.source(owner_path, anchor=anchor),
                                       'type': type(error).__name__, 'message': str(error)})
            if index < len(class_links):
                result['links'].append(self.link(class_links[index], path, reverse))
            rows += 1
            refresh()
            if rows == 1:
                # 至少一行连同完整签名、来源、继承与错误必须能表示；只能摘录正文。
                _fit_first_page(result, refresh)
            elif _response_size(result) > MAX_RESPONSE_BYTES:
                del results[previous_results:]
                del errors[previous_errors:]
                if member is None:
                    del result['links'][previous_links:]
                rows -= 1
                refresh()
                break
        if rows == 0:
            _fit_first_page(result, refresh)
        return _require_budget(result)


def documentation(installation=None, session_id=None):
    """从显式安装或已绑定会话选择资料；会话版本冲突时拒绝，不借用相近版本。

    会话方式只读身份文件，不连接客户端。外部包装启动器若不能定位安装，调用者
    需显式指定真实安装目录；显式目录模式报告文档版本，不冒充活会话已验证版本。
    """
    if (installation is None) == (session_id is None):
        raise ValueError('Provide exactly one of installation or session_id')
    if session_id is None:
        return Documentation(installation)
    from .catalog import read_json
    from .session_store import session_directory, session_version
    state = read_json(session_directory(session_id) / 'session.json')
    executable = Path(state['star']).resolve()
    root = next((parent for parent in executable.parents
                 if (parent / 'star/RELEASE_NOTES').is_file()), None)
    if root is None:
        raise ValueError('Cannot locate documentation from the session launcher; provide the actual installation')
    result = Documentation(str(root))
    if result.version != session_version(state):
        raise ValueError('Installed documentation version differs from the bound session version')
    return result
