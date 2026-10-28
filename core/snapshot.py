"""编译兼容快照的集合与字段目录，复用属性目录的成员校验和只读调用管线。"""

import hashlib
import json
from pathlib import Path

from .catalog import _keys, _require, load, read_json
from .execution import ADAPTERS, _binary_class, _literal, _member, _pipeline, _text, load_execution


def load_snapshot(catalog_path, execution_path, snapshot_path):
    """核对版本、成员指纹与节点引用，生成没有 setter 的快照执行计划。

    集合布局单独维护在 snapshot.json，API 声明与成员映射仍与按需读写共用。
    节点图允许集合递归以表达嵌套循环；运行时按对象身份和深度限制阻止死循环。
    本函数不连接 STAR，不创建工作目录或会话活动标记。
    """
    catalog = load(catalog_path)
    rules = read_json(execution_path)
    # 先完整核对共享成员表，避免快照接受按需读写入口已经拒绝的映射。
    load_execution(catalog_path, execution_path)
    methods = {name: _member(catalog, name, entry) for name, entry in rules['members'].items()}
    source = read_json(snapshot_path)
    _keys(source, 'schema_version target nodes collections', 'snapshot')
    _require(type(source['schema_version']) is int and source['schema_version'] == 1,
             'Unsupported snapshot mapping schema_version')
    _require(source['target'] == catalog['target'] == rules['target'],
             'Snapshot catalog version mismatch')
    _require(isinstance(source['nodes'], dict) and bool(source['nodes']), 'Missing snapshot nodes')

    def field(entry, where, *, root=False):
        """区分值、记录、集合和常量，拒绝额外字段及不具备上下文的调用。"""
        _require(isinstance(entry, dict), f'Invalid snapshot field: {where}')
        if 'literal' in entry:
            _keys(entry, 'output literal', where)
            _require(not root, 'Root snapshot collections cannot be literals')
            _text(entry['output'], 'snapshot output')
            _literal(entry['literal'])
            return dict(entry)
        kinds = set(entry) & {'adapter', 'record', 'collection'}
        _require(len(kinds) == 1, f'Snapshot field requires one value kind: {where}')
        kind = next(iter(kinds))
        _keys(entry, 'output read ' + kind + (' select' if kind == 'adapter' else ''), where)
        _require(not root or kind == 'collection', 'Snapshot roots must be collections')
        if entry['output'] is None:
            _require(kind == 'adapter' and entry['adapter'] == 'quantity' and entry['select'] == [],
                     'Only a complete quantity can be expanded into snapshot fields')
        else:
            _text(entry['output'], 'snapshot output')
        if kind == 'adapter':
            _require(isinstance(entry['adapter'], str) and entry['adapter'] in ADAPTERS,
                     f'Unknown snapshot adapter: {where}')
            _require(isinstance(entry['select'], list)
                     and all(isinstance(key, str) and key for key in entry['select']),
                     'Snapshot select must be a list of non-empty keys')
        else:
            _require(isinstance(entry[kind], str) and entry[kind] in source['nodes'],
                     f'Unknown snapshot node: {where}')
        read = _pipeline(catalog, methods, entry['read'], where + '.read')
        _require(read['root'] == ('simulation' if root else 'object'),
                 f'Invalid snapshot pipeline root: {where}')
        for step in read['steps']:
            for argument in step['arguments']:
                if 'context' in argument:
                    _require(not root and argument['context'] == 'object',
                             f'Snapshot pipeline has no requested context: {where}')
        return {**entry, 'read': read}

    def fields(entries, where):
        """同一字段组不重复写字段；variant 可以显式覆盖基础组的值。"""
        _require(isinstance(entries, list), f'Snapshot fields must be a list: {where}')
        result, outputs = [], set()
        for index, entry in enumerate(entries):
            compiled = field(entry, f'{where}[{index}]')
            names = {compiled['output']} if compiled['output'] is not None else {
                'definition', 'unit', 'si_unit', 'raw_value', 'si_value'}
            _require(not (names & (outputs | {'name', 'object_type', 'read_error', 'unsupported'})),
                     f'Duplicate or reserved snapshot output: {where}')
            outputs.update(names)
            result.append(compiled)
        return result

    # 每个节点先编译基础字段，再编译有明确声明类的附加字段。
    nodes = {}
    for name, node in source['nodes'].items():
        _text(name, 'snapshot node ID')
        _keys(node, 'fields variants require_variant', 'node ' + name)
        _require(type(node['require_variant']) is bool and isinstance(node['variants'], list),
                 f'Invalid snapshot variants: {name}')
        variants, classes = [], set()
        for variant in node['variants']:
            _keys(variant, 'java_class fields', 'variant ' + name)
            _text(variant['java_class'], 'variant class')
            java_class = _binary_class(catalog, variant['java_class'])
            _require(java_class not in classes, f'Duplicate snapshot variant: {java_class}')
            classes.add(java_class)
            variants.append({'java_class': java_class, 'fields': fields(variant['fields'], name + '.variant')})
        _require(not node['require_variant'] or bool(variants), f'Required snapshot variants are missing: {name}')
        nodes[name] = {'fields': fields(node['fields'], name), 'variants': variants,
                       'require_variant': node['require_variant']}
    _require(isinstance(source['collections'], list) and bool(source['collections']),
             'Snapshot requires root collections')
    collections, outputs = [], set()
    for index, entry in enumerate(source['collections']):
        compiled = field(entry, f'collections[{index}]', root=True)
        _require(compiled['output'] not in outputs | {
            'schema_version', 'simulation_name', 'session_path', 'modified', 'inspection_complete', 'read_errors'},
            'Duplicate or reserved snapshot collection output')
        outputs.add(compiled['output'])
        collections.append(compiled)
    fingerprint = json.dumps({'execution': rules, 'snapshot': source},
                             ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'schema_version': 1, 'target': source['target'],
            'catalog_id': hashlib.sha256(fingerprint.encode('utf-8')).hexdigest(),
            'nodes': nodes, 'collections': collections}


def prepare_snapshot():
    """读取随仓库分发的明确版本目录；实际 server 匹配由 Java 在读取前核对。"""
    root = Path(__file__).resolve().parents[1] / 'catalogs' / '2602'
    return load_snapshot(root / 'generated' / 'catalog.json', root / 'execution.json', root / 'snapshot.json')
