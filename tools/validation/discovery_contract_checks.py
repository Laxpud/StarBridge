#!/usr/bin/env python3
"""用隔离会话与受控传输验收发现 Core 的 R6/R7/R8 契约，不启动 STAR。

这些检查覆盖引用、缓存和遍历编排；不能证明真实 CSO 树、Java 描述符、
属性 getter 或 setter 的行为。stdout 只输出可保存的 JSON 验收概要。
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import discovery
from core.discovery_rules import property_id


def descriptor(name='setting', **changes):
    """构造规则可识别的元数据，不提供实际 Java 方法或当前值。"""
    return {'name': name, 'display_name': name, 'description': 'Fixture metadata',
            'property_type': 'double', 'hidden': False, 'attributes': {},
            'getter': {'owner': 'fixture.Settings', 'name': 'get' + name.title(),
                       'parameter_types': [], 'public': True, 'static': False,
                       'annotations': [{'type': 'star.locale.annotation.StarBeanProperty', 'values': {}}]},
            'setter': None, **changes}


def identity(key):
    """用稳定 key 表示同一对象，路径可包含不同父级或循环边。"""
    return {'key': key, 'name': 'setting-' + key, 'java_class': 'fixture.Settings', 'parent_key': None}


class FakeTransport:
    """返回确定性树与局部错误，使验证聚焦 Core 的去重和覆盖报告。"""

    def __init__(self, graph=None, properties=None, partial=False, proxy=False):
        self.graph = graph or {'root': []}
        self.properties = properties or [descriptor()]
        self.partial = partial
        self.proxy = proxy
        self.calls = []

    def __call__(self, session_dir, action, timeout, **values):
        if action != 'discovery':
            raise AssertionError('Contract fixture must not execute catalog or mutation requests')
        request = values['discovery_request']
        path = request.get('target', {}).get('path', [identity('root')])
        key = path[-1]['key']
        self.calls.append((request['action'], key))
        node = {**identity(key), 'kind': 'object', 'path': path,
                'children_state': 'not_loaded', 'property_state': 'not_loaded'}
        result = {'node': node, 'state': 'complete', 'next_offset': None,
                  'fingerprint': 'stable-' + key, 'errors': [], 'truncations': []}
        if request['action'] == 'describe':
            result['properties'] = self.properties
            if self.partial and key == 'b':
                result.update(state='partial', errors=[{'reason': 'fixture_descriptor_error'}],
                              truncations=[{'reason': 'fixture_descriptor_budget'}])
        elif request['action'] == 'browse':
            result['children'] = [{**identity(child), 'kind': 'object', 'path': path + [identity(child)]}
                                  for child in self.graph.get(key, [])]
            if self.proxy and key == 'root':
                result['children'].append({'kind': 'proxy', 'key': None, 'name': 'Unknown proxy',
                    'java_class': 'fixture.Proxy', 'path': path, 'reason': 'fixture_unsupported_proxy'})
            if self.partial and key == 'a':
                result.update(state='partial', errors=[{'reason': 'fixture_children_error'}],
                              truncations=[{'reason': 'fixture_children_budget'}])
        else:
            raise AssertionError('Unexpected discovery request')
        return {'discovery': result}


class DiscoveryContracts(unittest.TestCase):
    """每个检查使用独立临时会话，结束后移除引用密钥、缓存和计划材料。"""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='starbridge-discovery-contract-')
        self.addCleanup(self.directory.cleanup)
        self.session = self.directory.name
        self.state_path = Path(self.session) / 'session.json'
        self.state_path.write_text(json.dumps({'session_token': 'public-fixture-token',
            'catalog_target': {'release': '2602', 'build': '21.02.007'}}), encoding='utf-8')

    def test_cycle_and_duplicate_edges_expand_each_identity_once(self):
        """循环和不同路径的同一对象不能触发无界展开或重复命中。"""
        transport = FakeTransport({'root': ['a', 'b', 'a'], 'a': ['b'], 'b': ['a']})
        result = discovery.search_settings(self.session, 'setting', expand=True,
            max_nodes=30, max_depth=10, operate=transport)
        expanded = [key for action, key in transport.calls if action == 'browse']
        self.assertCountEqual(expanded, ['root', 'a', 'b'])
        identities = [(item['node']['key'], (item['property'] or {}).get('property_id'))
                      for item in result['matches']]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertLess(result['coverage']['visited_nodes'], 30)

    def test_partial_responses_and_proxy_remain_in_coverage(self):
        """正常返回封套中的局部错误、截断和代理不能被搜索吞掉。"""
        transport = FakeTransport({'root': ['a', 'b']}, partial=True, proxy=True)
        result = discovery.search_settings(self.session, 'setting', expand=True, operate=transport)
        coverage = result['coverage']
        self.assertTrue({'fixture_descriptor_error', 'fixture_children_error'} <=
                        {item.get('reason') for item in coverage['errors']})
        self.assertTrue({'fixture_descriptor_budget', 'fixture_children_budget'} <=
                        {item.get('reason') for item in coverage['truncations']})
        self.assertEqual(len(coverage['unsupported']), 1)
        self.assertIsNone(coverage['unsupported'][0]['node_id'])
        self.assertFalse(coverage['whole_simulation_complete'])

    def test_cached_search_retains_errors_proxy_and_undescribed_nodes(self):
        """独立搜索已缓存观察时仍返回范围缺口，并区分未描述与未展开。"""
        transport = FakeTransport({'root': ['a', 'b', 'fresh']}, partial=True, proxy=True)
        root = discovery.browse_tree(self.session, operate=transport)
        children = {node['key']: node for node in root['children'] if node.get('node_id')}
        with patch('core.discovery.time.time', return_value=10):
            discovery.describe_node(self.session, children['b']['node_id'], operate=transport)
        with patch('core.discovery.time.time', return_value=20):
            discovery.browse_tree(self.session, children['a']['node_id'], operate=transport)
        calls = len(transport.calls)
        result = discovery.search_settings(self.session, 'setting', operate=transport)
        self.assertEqual(len(transport.calls), calls)
        coverage = result['coverage']
        self.assertEqual(coverage['undescribed_nodes'], 3)
        self.assertTrue({'fixture_descriptor_error', 'fixture_children_error'} <=
                        {item.get('reason') for item in coverage['errors']})
        self.assertTrue({'fixture_descriptor_budget', 'fixture_children_budget'} <=
                        {item.get('reason') for item in coverage['truncations']})
        property_error = next(item for item in coverage['errors'] if item['reason'] == 'fixture_descriptor_error')
        children_error = next(item for item in coverage['errors'] if item['reason'] == 'fixture_children_error')
        self.assertEqual(property_error['observed_at'], 10)
        self.assertEqual(children_error['observed_at'], 20)
        self.assertIsNone(coverage['unsupported'][0]['node_id'])

    def test_search_indexes_type_and_getter_program_identity(self):
        """属性类型和 getter 的声明标识可检索，显示名称不必包含程序名。"""
        prop = descriptor('setting', property_type='fixture.SpecialInput')
        prop['getter'] = {**prop['getter'], 'owner': 'fixture.ProgramOwner', 'name': 'getProgramIdentifier'}
        discovery.describe_node(self.session, operate=FakeTransport(properties=[prop]))
        for query, field in [('SpecialInput', 'property_type'), ('getProgramIdentifier', 'getter'),
                             ('ProgramOwner', 'getter')]:
            result = discovery.search_settings(self.session, query)
            self.assertEqual(len(result['matches']), 1)
            self.assertIn(field, {item['field'] for item in result['matches'][0]['matched_by']})

    def test_all_observation_preserves_default_scope_and_excludes_resource_branch(self):
        """all 刷新保留既有默认范围节点；资源及其后代不会混入默认搜索。"""
        transport = FakeTransport()
        discovery.describe_node(self.session, operate=transport)
        discovery.browse_tree(self.session, scope='all', operate=transport)
        self.assertTrue(discovery.search_settings(self.session, 'setting')['matches'])
        resource_class = 'star.material.MaterialDataBaseManager'
        root_path = [identity('root')]
        resource_path = root_path + [{**identity('database'), 'java_class': resource_class}]
        leaf_path = resource_path + [identity('material')]
        state = discovery._state(self.session)
        for path in [resource_path, leaf_path]:
            node = discovery._decorate({**path[-1], 'kind': 'object', 'path': path}, state)
            # 即便调用者直接以 simulation 描述了资源节点，实际类型仍决定排除。
            discovery._remember(self.session, state, node, scope='simulation')
            discovery._remember(self.session, state, node, scope='all')
        default = discovery.search_settings(self.session, 'setting')
        self.assertFalse({'database', 'material'} & {item['node']['key'] for item in default['matches']})
        all_nodes = discovery.search_settings(self.session, 'setting', scope='all')
        self.assertTrue({'database', 'material'} <= {item['node']['key'] for item in all_nodes['matches']})

    def test_private_key_is_atomic_owner_only_and_public_token_cannot_forge(self):
        """并发初始化得到同一私钥，公开 token 重签的引用必须拒绝。"""
        with ThreadPoolExecutor(max_workers=8) as pool:
            states = list(pool.map(lambda _: discovery._state(self.session), range(16)))
        self.assertEqual(len({s['_discovery_secret'] for s in states}), 1)
        self.assertEqual(stat.S_IMODE((Path(self.session) / '.discovery-reference-key').stat().st_mode), 0o600)
        self.assertNotIn('_discovery_secret', json.loads(self.state_path.read_text()))
        transport = FakeTransport()
        result = discovery.browse_tree(self.session, operate=transport)
        original = result['node']['node_id']
        discovery.describe_node(self.session, original, operate=transport)
        encoded = original.rsplit('.', 1)[0]
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        forged = encoded + '.' + hmac.new(b'public-fixture-token', raw, hashlib.sha256).hexdigest()
        count = len(transport.calls)
        with self.assertRaises(ValueError):
            discovery.describe_node(self.session, forged, operate=transport)
        self.assertEqual(len(transport.calls), count)

    def test_session_rotation_and_changed_page_fingerprint_invalidate_references(self):
        """会话世代变化拒绝旧引用，页面关系变化拒绝旧游标。"""
        transport = FakeTransport({'root': ['a']})
        def paged(*args, **kwargs):
            result = transport(*args, **kwargs)
            result['discovery']['next_offset'] = 1
            return result
        first = discovery.browse_tree(self.session, operate=paged)
        def changed(*args, **kwargs):
            result = transport(*args, **kwargs)
            result['discovery']['fingerprint'] = 'changed-relations'
            return result
        with self.assertRaises(ValueError):
            discovery.browse_tree(self.session, cursor=first['next_cursor'], operate=changed)
        state = json.loads(self.state_path.read_text())
        state['session_token'] = 'new-session-token'
        self.state_path.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            discovery.describe_node(self.session, first['node']['node_id'], operate=transport)

    def test_context_is_preserved_without_translation_changing_property_identity(self):
        """同 getter 的绑定差异保留为不同属性，显示翻译不改变语义身份。"""
        first = descriptor(attributes={'ReadOnly': False})
        second = descriptor(attributes={'ReadOnly': True})
        result = discovery.describe_node(self.session, operate=FakeTransport(properties=[first, second]))
        self.assertEqual(len(result['properties']), 2)
        self.assertNotEqual(result['properties'][0]['property_id'], result['properties'][1]['property_id'])
        translated = {**first, 'display_name': '显示名', 'description': '翻译说明'}
        self.assertEqual(property_id(first), property_id(translated))

    def test_browse_does_not_refresh_property_observation_time(self):
        """节点观察刷新后，旧属性候选仍报告原观察时刻与需要重新核验。"""
        transport = FakeTransport()
        with patch('core.discovery.time.time', return_value=10):
            discovery.describe_node(self.session, operate=transport)
        with patch('core.discovery.time.time', return_value=20):
            discovery.browse_tree(self.session, operate=transport)
        result = discovery.search_settings(self.session, 'setting')
        node = next(item for item in result['matches'] if item['property'] is None)
        prop = next(item for item in result['matches'] if item['property'] is not None)
        self.assertEqual(node['observed_at'], 20)
        self.assertEqual(prop['observed_at'], 10)
        self.assertTrue(prop['requires_revalidation'])
        self.assertEqual(prop['validity'], 'cached_may_be_stale')

    def test_one_compilation_failure_preserves_other_requested_properties(self):
        """一个声明无法编译时，保留另一属性的可执行计划并明确列出失败项。"""
        good, bad = descriptor('good'), descriptor('bad')
        transport = FakeTransport(properties=[good, bad])
        def compile_plan(session, node, properties, state, **kwargs):
            if any(p['name'] == 'bad' for p in properties):
                raise ValueError('Fixture missing declaration')
            return {'property_map': {p['property_id']: p for p in properties}}
        with patch('core.discovery.build_read_plan', side_effect=compile_plan):
            result = discovery.prepare_node_read(self.session, None,
                [property_id(good), property_id(bad)], operate=transport)
        self.assertEqual(len(result['prepared_plans']), 1)
        self.assertIn(property_id(good), result['prepared_plans'][0]['property_map'])
        self.assertEqual([e['property_id'] for e in result['compilation_errors']], [property_id(bad)])


def main():
    """返回机器可读的检查范围与结果，失败详情不会混入正常终端协议。"""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DiscoveryContracts)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {'scope': 'Core R6/R7/R8 controlled contract checks', 'real_star_coverage': False,
              'tests_run': result.testsRun, 'failures': len(result.failures),
              'errors': len(result.errors), 'successful': result.wasSuccessful(),
              'checks': ['cycles_and_duplicate_identity', 'partial_coverage_and_proxies',
                         'private_key_and_forgery', 'session_and_page_invalidation',
                         'descriptor_context', 'cache_observation_times', 'isolated_compilation_failure',
                         'cached_coverage_and_undescribed_nodes', 'type_and_getter_search',
                         'scope_preservation_and_resource_exclusion']}
    if not result.wasSuccessful():
        report['details'] = stream.getvalue()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
