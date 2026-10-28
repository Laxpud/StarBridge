"""从本机 Javadoc 提取候选 API；不启动 STAR，也不据方法名推断可写性。"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


class Element:
    """保留签名所需的 HTML 层次，正文不进入生成目录。"""

    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self, css=None, tag=None):
        """按类名或标签遍历子树；调用方自行限制到声明或成员区域。"""
        if ((css is None or css in self.attrs.get('class', '').split())
                and (tag is None or tag == self.tag)):
            yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk(css, tag)

    def text(self):
        """规范化签名排版空白；字符串字面量内的空白可能有语义，必须保留。"""
        def raw(node):
            return ''.join(raw(child) if isinstance(child, Element) else child
                           for child in node.children)
        value = raw(self)
        parts = re.split(r'("(?:\\.|[^"\\])*")', value)
        return ''.join(part if index % 2 else re.sub(r'\s+', ' ', part)
                       for index, part in enumerate(parts)).strip()

    def part(self, css):
        """读取一个签名字段；无参数方法可能没有 parameters 节点。"""
        return next((item.text() for item in self.walk(css)), '')

    def links(self):
        """保留类型与注解的链接，区分显示名称相同而所属包不同的类型。"""
        return sorted({unquote(item.attrs['href']) for item in self.walk(tag='a')
                       if 'href' in item.attrs})


class Page(HTMLParser):
    """解析 Javadoc HTML5；void 元素不入栈，避免 wbr 破坏签名范围。"""

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        """将新元素挂到当前父节点；只有需要闭合的元素改变解析栈。"""
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        """处理自闭合写法，确保其后的签名字段不会被误收为子元素。"""
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        """结束对应节点；HTML 中省略的中间闭合标签也一并退出。"""
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        """保留解码后的文本，稍后只在签名边界规范化排版空白。"""
        self.stack[-1].children.append(data)


def source_record(root, path):
    """使用安装相对路径和内容摘要标识材料，使不同机器的生成结果可比较。"""
    return {'path': path.relative_to(root).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def installation_version(root):
    """从同一安装的两份版本材料交叉核对 Build，拒绝手填版本冒充检测值。"""
    root = Path(root).resolve(strict=True)
    values = []
    sources = []
    for name in ('star/RELEASE_NOTES', 'star/version_info.properties'):
        path = root / name
        values.append(dict(re.findall(r'^([a-z_]+)=(.*?)$', path.read_text(), re.M)))
        sources.append(source_record(root, path))
    release = values[0].get('presentation_version', '').strip('"')
    build = values[0].get('release_number', '').strip('"')
    if (not release or not build or build != values[1].get('base_version')):
        raise ValueError('Missing or conflicting STAR installation version metadata')
    return {'release': release, 'build': build}, sources


def type_index(doc):
    """读取 Javadoc 类型索引，包含嵌套类型；不靠类名拆点猜测文件路径。"""
    text = (doc / 'type-search-index.js').read_text()
    entries, _ = json.JSONDecoder().raw_decode(text[text.index('['):])
    return {f"{item['p']}.{item['l']}": f"{item['p'].replace('.', '/')}/{item['l']}.html"
            for item in entries if item.get('p', '').startswith('star.')}


def parse_type(root, doc, name, relative, paths):
    """提取声明、成员签名及属性候选；返回需保留的本地继承声明所在类型。"""
    path = doc / relative
    page = Page(path.read_text()).root
    signature = page.part('type-signature')
    if not signature:
        raise ValueError(f'Unsupported Javadoc type page: {relative}')
    members, properties, inherited = {}, {}, set()
    for section in page.walk('detail', 'section'):
        node = next(section.walk('member-signature'), None)
        if node is None:
            continue
        anchor = section.attrs['id']
        if anchor in members:
            raise ValueError(f'Duplicate Javadoc member: {name}#{anchor}')
        method = node.part('element-name')
        annotations = node.part('annotations')
        members[anchor] = {
            'name': method, 'signature': node.text(),
            'return_type': node.part('return-type'),
            'parameters': node.part('parameters'),
            'modifiers': node.part('modifiers'), 'annotations': annotations,
            'links': node.links(),
        }
        # 仅注解明确标记的成员成为属性候选。link、readOnly 等原样保留，
        # 不把嵌套注解或默认值猜成已确认的运行时约束。
        if re.search(r'@StarBeanProperty\b', annotations):
            properties[anchor] = {'member': anchor, 'metadata': annotations,
                                  'status': 'discovered', 'adapter': None}

    # 继承列表指向真正声明类；保留引用而非复制成当前类自己的方法。
    inherited_members = []
    for group in page.walk('inherited-list'):
        for link in group.walk(tag='a'):
            url = urlsplit(link.attrs.get('href', ''))
            if url.scheme or url.netloc or not url.path:
                continue
            target = (path.parent / unquote(url.path)).resolve()
            owner = paths.get(target)
            if owner and owner != name:
                inherited.add(owner)
                if url.fragment:
                    inherited_members.append({'type': owner, 'member': unquote(url.fragment)})
    return {
        'java_class': name, 'signature': signature,
        'links': next(page.walk('type-signature')).links(),
        'source': source_record(root, path),
        'members': dict(sorted(members.items())),
        'property_candidates': dict(sorted(properties.items())),
        'inherited_members': sorted(
            [dict(pair) for pair in {tuple(sorted(x.items())) for x in inherited_members}],
            key=lambda x: (x['type'], x['member'])),
        'status': 'discovered',
    }, inherited


def generate(root, selected):
    """生成确定性的候选目录，自动包含本地继承声明；空选择表示全部 STAR 类型。"""
    root = Path(root).resolve(strict=True)
    target, sources = installation_version(root)
    doc = root / 'doc/client/html'
    index = type_index(doc)
    roots = sorted(set(selected or index))
    missing = set(roots) - index.keys()
    if missing:
        raise ValueError(f'Unknown Javadoc types: {sorted(missing)}')
    paths = {(doc / relative).resolve(): name for name, relative in index.items()}
    sources.append(source_record(root, doc / 'type-search-index.js'))
    pending, types = set(roots), {}
    while pending:
        name = min(pending)
        pending.remove(name)
        types[name], dependencies = parse_type(root, doc, name, index[name], paths)
        pending.update(dependencies - types.keys())
    return {'schema_version': 1, 'target': target,
            'generator': 'starbridge-javadoc-v1', 'sources': sources,
            'scope': {'roots': roots, 'indexed_types': len(index),
                      'includes_inherited': True},
            'types': dict(sorted(types.items())), 'bindings': {}}
