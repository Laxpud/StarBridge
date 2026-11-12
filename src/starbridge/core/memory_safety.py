"""在记忆写入前识别常见认证值，只检查拟写内容，不读取引用材料或执行代码。

这是防止明显凭据误存的保底，不是项目机密分类器或通用 DLP。普通版本、路径、
执行 ID 和随机标识不按熵值拦截；个人隐私、项目授权及保存范围仍由 AI 与用户判断。
模块不打印输入，不把匹配片段、散列或用户自定义键名放入异常。
"""

import re
from urllib.parse import parse_qsl, unquote, urlsplit


MEMORY_WRITE_METHODS = frozenset({'record_memory', 'update_memory'})
MEMORY_WRITE_POLICY = (
    '写记忆前只检查拟写内容：知识、代码、默认参数、证据及引用均不得含认证凭据、个人隐私或未经授权的项目机密。'
    '优先省略、参数化或用无敏感内容的引用；无法安全表达就不写。确需项目敏感信息时先确认保存位置和入库范围，'
    '允许记忆或提交不等于允许公开。不得为此额外读取原始材料、运行算例或生成报告。'
)

# 1. 只认有明确认证语义的字段，不把 token、key、session_id 等通用标识一概当作秘密。
_CREDENTIAL_LABELS = frozenset({
    'apikey', 'apitoken', 'accesstoken', 'refreshtoken', 'idtoken', 'authtoken', 'bearertoken',
    'clientsecret', 'secret', 'secretkey', 'awssecretaccesskey', 'password', 'passwd', 'pwd', 'privatekey',
})
_AUTH_LABELS = frozenset({'authorization', 'proxyauthorization'})
_COOKIE_LABELS = frozenset({'cookie', 'setcookie'})
_QUERY_LABELS = _CREDENTIAL_LABELS | {
    'token', 'signature', 'sig', 'xamzsignature', 'xgoogsignature', 'xamzsecuritytoken',
}
# 凭据参数仍可描述类型与来源，但其 default/value/enum 等实际取值必须检查。
_CONTRACT_METADATA = frozenset({
    'type', 'description', 'title', 'required', 'units', 'minLength', 'maxLength',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'pattern', 'format',
})
_SAFE_FIELDS = frozenset({
    'entry', 'changes', 'arguments', 'method', 'memory_id', 'project_dir', 'expected_revision',
    'problem', 'applicability', 'approach', 'certainty', 'title', 'tags', 'exceptions', 'recipe',
    'code', 'imports', 'parameters', 'effect', 'scope', 'language', 'declarations',
    'evidence', 'summary', 'kind', 'references', 'limitations', 'evidence_ids', 'evidence_id',
    'schema_version', 'revision', 'created_at', 'updated_at', 'source', 'observed_effect', 'evidence_scope',
    'default', 'value', 'const',
    'enum', 'example', 'examples', 'items', 'properties', 'headers', 'stored_knowledge', 'legacy_archive',
}) | _CONTRACT_METADATA
_PLACEHOLDER = re.compile(
    r'(?:<(?:redacted|token|api[_-]?key|private[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|password|secret|credential|authorization|value|your_[a-z0-9_]+)>|'
    r'\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{\{[A-Za-z_][A-Za-z0-9_]*\}\}|\{[A-Za-z_][A-Za-z0-9_]*\}|'
    r'%[A-Za-z_][A-Za-z0-9_]*%|redacted|replace_me|your_(?:api_key|token|password|secret)|\*{3,}|\.{3}|…)', re.I)
_PROVIDER_TOKEN = re.compile(
    r'(?<![A-Za-z0-9_])(?:sk-(?:(?:proj|svcacct)-[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{40,})|'
    r'(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|'
    r'github_pat_[A-Za-z0-9_]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})(?![A-Za-z0-9_])')
_PRIVATE_KEY = re.compile(
    r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'
    r'[\s\\nrt\"\x27+]*(?:(?:Proc-Type|DEK-Info):[^\r\n]*[\r\n]+[ \t]*){0,2}[A-Za-z0-9+/=]{32,}')
_URL = re.compile(r'\b(?:https?|ftp|ssh|postgres(?:ql)?|mysql|rediss?|amqps?|mongodb(?:\+srv)?)://[^\s<>\"\x27)]+', re.I)
_AUTH_VALUE = re.compile(r'^(?:Bearer|Basic|Token|ApiKey)\s+(.+)$', re.I)
_AUTH_HEADER = re.compile(r'\b(?:Proxy-)?Authorization[\"\x27]?\s*[:=]\s*[\"\x27]?((?:Bearer|Basic|Token|ApiKey)[ \t]+[^\r\n\"\x27,;]+)', re.I)
_BEARER_VALUE = re.compile(r'\bBearer[ \t]+([A-Za-z0-9._~+/=-]{12,})', re.I)
_COOKIE_VALUE = re.compile(r'(?:^|[;\s])(?:__Host-|__Secure-)?(?:session(?:id)?|jsessionid|sid|auth(?:_token)?|access_token|refresh_token|connect\.sid)\s*=\s*([^;\r\n]+)', re.I)
_COOKIE_HEADER = re.compile(r'\b(?:Set-)?Cookie[\"\x27]?\s*[:=]\s*[\"\x27]?([^\r\n\"\x27]+)', re.I)
# 代码中的参数读取不等于实际凭据；这里只匹配带认证字段名的引号内字面量和 .env 赋值。
_LABEL_PATTERN = r'(?:api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|client[_-]?secret|secret[_-]?key|aws[_-]?secret[_-]?access[_-]?key|password|passwd|pwd|private[_-]?key|secret)'
_QUOTED_ASSIGNMENT = re.compile(r'\b' + _LABEL_PATTERN + r'[\"\x27\]\)]?\s*[:=]\s*([\"\x27])([^\r\n]*?)\1', re.I)
_ENV_ASSIGNMENT = re.compile(r'^\s*(?:export\s+)?' + _LABEL_PATTERN + r'\s*=\s*([^\s\"\x27;]+)', re.I | re.M)


def _label(value):
    """仅统一认证字段的大小写和分隔符，不修改或持久化原输入。"""
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def _placeholder(value):
    """显式占位符可以入库；不把任意大写单词或高熵标识误当成占位符/凭据。"""
    return not value.strip() or _PLACEHOLDER.fullmatch(value.strip()) is not None


def safe_field_path(path):
    """诊断只保留协议字段和列表索引；任意用户键名不进入响应或异常。"""
    result = []
    for part in path:
        if len(result) >= 31:
            return result + ['<nested>']
        if type(part) is int:
            result.append(part)
        elif isinstance(part, str) and (part in _SAFE_FIELDS or re.fullmatch(r'<(?:key|field):\d+>', part)):
            result.append(part)
        else:
            result.append('<field>')
    return result


_CATEGORIES = frozenset({'private_key', 'provider_token', 'credential_url', 'authenticated_url',
                         'unreviewable_url', 'authentication_header', 'authentication_cookie',
                         'credential_assignment', 'credential_value', 'sensitive_data'})


class MemorySensitiveDataError(ValueError):
    """只携带检测类别和安全字段位置，不持有匹配值、原文或其散列。"""

    def __init__(self, category, path):
        self.category = category if isinstance(category, str) and category in _CATEGORIES else 'sensitive_data'
        self.field_path = safe_field_path(path)
        super().__init__(f'Memory write rejected: {self.category} at {self.field_path}. '
                         'Remove authentication values or use explicit non-sensitive placeholders.')


def sensitive_data_rejection(error):
    """Core、CLI 和 MCP 共用同一无原文拒绝封套，不附上原始请求供自动重放。"""
    return {'status': 'rejected', 'error': {'type': 'MemorySensitiveDataError',
            'message': str(error), 'category': error.category, 'field_path': error.field_path},
            'recovery': {'automatic_retry': False,
                         'instruction': '移除认证值或改用明确占位符，检查保存和入库范围后再提交；'
                                        '不回传原内容，不为此读取外部材料或重做 STAR 任务。'}}


def memory_argument_rejection(path=()):
    """记忆输入的格式错误也不回显枚举值、未知键名或 SDK 的原始校验文本。"""
    return {'status': 'rejected', 'error': {'type': 'ArgumentValidationError',
            'message': 'Memory write arguments do not match the published contract; input content is omitted.',
            'argument_path': safe_field_path(path)},
            'recovery': {'automatic_retry': False,
                         'instruction': '核对已知写入格式，只提交无敏感内容的知识及精简证据；不重做算例。'}}


def _check_url(text, path):
    """只在本地解析认证 URL，不连接地址、不打开引用或验证凭据是否可用。"""
    for match in _URL.finditer(text):
        raw = match.group()
        # 无效主机/IPv6 也不能遮住已经明确出现的 user:password@ 或认证查询参数。
        authority = re.split(r'[/#?]', raw.split('://', 1)[1], maxsplit=1)[0]
        userinfo = authority.rsplit('@', 1)[0] if '@' in authority else ''
        if ':' in userinfo and not _placeholder(unquote(userinfo.split(':', 1)[1])):
            raise MemorySensitiveDataError('credential_url', path)
        try:
            url = urlsplit(raw)
            queries = (url.query, url.fragment.split('?', 1)[-1])
        except ValueError:
            queries = (raw.partition('?')[2].split('#', 1)[0], raw.partition('#')[2].split('?', 1)[-1])
        for query in queries:
            try:
                pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=1024)
            except ValueError:
                # 不解析无限参数，也不将无法安全检查的 URL 当作已通过。
                raise MemorySensitiveDataError('unreviewable_url', path) from None
            for key, value in pairs:
                if _label(key) in _QUERY_LABELS and not _placeholder(value):
                    raise MemorySensitiveDataError('authenticated_url', path)


def _check_text_form(text, path):
    """检查少量明确格式，不进行熵值判断、网络校验或任意编码解包。"""
    if _PRIVATE_KEY.search(text):
        raise MemorySensitiveDataError('private_key', path)
    if _PROVIDER_TOKEN.search(text):
        raise MemorySensitiveDataError('provider_token', path)
    _check_url(text, path)
    for match in _AUTH_HEADER.finditer(text):
        value = _AUTH_VALUE.fullmatch(match.group(1).strip())
        if value and not _placeholder(value.group(1)):
            raise MemorySensitiveDataError('authentication_header', path)
    for match in _BEARER_VALUE.finditer(text):
        value = match.group(1)
        if not _placeholder(value) and (len(value) >= 24 or re.search(r'[0-9._~+/=-]', value)):
            raise MemorySensitiveDataError('authentication_header', path)
    for match in _COOKIE_HEADER.finditer(text):
        for cookie in _COOKIE_VALUE.finditer(match.group(1)):
            if not _placeholder(cookie.group(1)):
                raise MemorySensitiveDataError('authentication_cookie', path)
    for match in _QUOTED_ASSIGNMENT.finditer(text):
        if not _placeholder(match.group(2)):
            raise MemorySensitiveDataError('credential_assignment', path)
    if not any(part in ('code', 'declarations') for part in path):
        # Java/Python 代码中的未加引号赋值可能只是变量或函数调用，不将其当作 .env 字面量。
        for match in _ENV_ASSIGNMENT.finditer(text):
            value = match.group(1)
            if not _placeholder(value) and not value.startswith(('System.getenv(', 'parameters.get(', 'os.environ[', 'os.getenv(')):
                raise MemorySensitiveDataError('credential_assignment', path)


def _check_text(text, path):
    """兼顾原文和常见源码字面量转义；不求值代码或递归解包任意编码。"""
    _check_text_form(text, path)
    escape = chr(92)
    normalized = text.replace(escape + '"', '"').replace(escape + "'", "'")
    for letter, character in (('n', '\n'), ('r', '\r'), ('t', '\t')):
        normalized = normalized.replace(escape + letter, character)
    if normalized != text:
        _check_text_form(normalized, path)


def ensure_safe_memory_data(value, path=()):
    """遍历拟写 JSON 的键和值，拒绝实际认证值，保留参数契约、占位符和普通标识。

    1. 所有文本先检查明确格式，因此代码、引用或任意嵌套字段都不能作为藏匿入口。
    2. 对有认证语义的字段及参数 default/value/enum 继续传递上下文；描述与类型不作值处理。
    3. 自定义键名以位置代称；迭代遍历与容器去重避免环或深层输入导致诊断溢出。
    非 JSON 类型及大小仍交原格式校验，不额外读取文件，也不自动修改用户内容。
    """
    pending = [(value, safe_field_path(path), None)]
    seen = set()
    while pending:
        item, location, hint = pending.pop()
        if isinstance(item, str):
            _check_text(item, location)
            if hint == 'credential' and not _placeholder(item):
                raise MemorySensitiveDataError('credential_value', location)
            if hint == 'authorization':
                auth = _AUTH_VALUE.fullmatch(item.strip())
                if not _placeholder(item) and (auth is None or not _placeholder(auth.group(1))):
                    raise MemorySensitiveDataError('authentication_header', location)
            if hint == 'cookie':
                if any(not _placeholder(match.group(1)) for match in _COOKIE_VALUE.finditer(item)):
                    raise MemorySensitiveDataError('authentication_cookie', location)
        elif isinstance(item, (dict, list)):
            context = (id(item), hint)
            if context in seen:
                continue
            # 同一对象在普通字段与凭据默认值下复用时，必须按两种语义分别检查。
            seen.add(context)
            children = []
            if isinstance(item, list):
                children = [(child, safe_field_path([*location, index]), hint) for index, child in enumerate(item)]
            else:
                for index, (key, child) in enumerate(item.items()):
                    if not isinstance(key, str):
                        continue
                    _check_text(key, safe_field_path([*location, f'<key:{index}>']))
                    label = _label(key)
                    selected = ('credential' if label in _CREDENTIAL_LABELS else
                                'authorization' if label in _AUTH_LABELS else
                                'cookie' if label in _COOKIE_LABELS else
                                hint if key not in _CONTRACT_METADATA else None)
                    segment = key if key in _SAFE_FIELDS else f'<field:{index}>'
                    children.append((child, safe_field_path([*location, segment]), selected))
            pending.extend(reversed(children))
        elif hint in ('credential', 'authorization') and type(item) in (int, float):
            raise MemorySensitiveDataError('credential_value' if hint == 'credential' else 'authentication_header', location)
