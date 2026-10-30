#!/usr/bin/env python3
"""在已打开的 Base 验收副本验证 R1—R5、R7—R10 的公开发现接口。

本脚本只读取；会话生命周期由调用者显式管理。名称是验收算例的已知
上下文，不是产品过滤规则。R6 重建及动态范围 fixture 另用隔离副本验收。
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.service import Service
from bridge.runner.modifier import content_snapshot, snapshot_diff
from bridge.runner.file_bridge import digest


def main():
    """保存每次真实响应并检查行为；失败立即停止，不重复调用或修改会话状态。"""
    parser = argparse.ArgumentParser(description='Validate runtime discovery on the Base acceptance session.')
    parser.add_argument('--session-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    session = str(args.session_dir.resolve())
    service, checks = Service(), []

    def call(label, method, expected='ok', **values):
        """保留状态封套作为证据；只按明确预期接受拒绝。"""
        result = service.call(method, {'session_dir': session, **values})
        (output / (label + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(label, result['status'], flush=True)
        assert result['status'] == expected, result
        return result.get('result', result)

    def check(name, condition):
        """每条断言对应规划验收边界，不把成功请求数当作覆盖率。"""
        assert condition, name
        checks.append(name)

    def child(parent, label, record):
        page = call(record, 'browse_tree', node_id=parent['node_id'])
        return next(item for item in page['children'] if item['label'] == label)

    state = service.session_status(session)
    source_hash = digest(Path(state['input']))
    before = call('snapshot-before', 'inspect_session')['snapshot']
    root = call('root', 'browse_tree')
    check('R1_root_one_level', root['node']['children_state'] == 'complete' and bool(root['children']))
    solver = next(item for item in root['children'] if item['label'] == 'Solvers')
    unsteady = child(solver, 'Implicit Unsteady', 'solvers')
    description = call('unsteady-description', 'describe_node', node_id=unsteady['node_id'])
    by_name = {item['name']: item for item in description['properties']}
    ids = [by_name[name]['property_id'] for name in ('TimeStep', 'TimeDiscretizationOption')]
    values = call('unsteady-values', 'read_node_properties', node_id=unsteady['node_id'], property_ids=ids)
    check('R1_R2_automatic_plan', values['inspection_complete'] and values['properties'][ids[0]]['status'] == 'ok')
    check('R3_quantity_identity_and_units', 'unit' in values['properties'][ids[0]]['value'] and
          values['properties'][ids[0]]['relation']['status'] == 'ok')
    enumeration = values['properties'][ids[1]]['value']
    check('R5_enum_options', bool(enumeration['allowed']) and enumeration['selected'] in enumeration['allowed'])
    check('R9_generated_writes_disabled', all(not item['write_enabled'] for item in description['properties']))

    interfaces = next(item for item in root['children'] if item['label'] == 'Interfaces')
    desc = call('interfaces-description', 'describe_node', node_id=interfaces['node_id'])
    by_name = {item['name']: item for item in desc['properties']}
    hidden, supported = by_name['DebugObjFiles'], by_name['BoundaryInterfaceCaching']
    check('R4_hidden_metadata', hidden['hidden'] and hidden['read_support'] == 'unsupported')
    partial = call('mixed-read', 'read_node_properties', node_id=interfaces['node_id'],
                   property_ids=[supported['property_id'], hidden['property_id']])
    check('R8_partial_read', not partial['inspection_complete'] and
          partial['properties'][supported['property_id']]['status'] == 'ok' and
          partial['properties'][hidden['property_id']]['status'] == 'unsupported')

    plots = next(item for item in root['children'] if item['label'] == 'Plots')
    residuals = child(plots, 'Residuals', 'plots')
    desc = call('plot-description', 'describe_node', node_id=residuals['node_id'])
    height = next(p for p in desc['properties'] if p['name'] == 'ExportHeight')
    check('R5_static_range_metadata', 'StarBeanBounded.Range' in height['attributes'])
    # Style Defaults 是非 CSO 提供器的实际来源，路径来自公开子项或显式重定位。
    locator = plots['locator'] + [{'name': 'Style Defaults', 'java_class': 'star.common.PlotStyleDefaults'}]
    styles = call('styles', 'relocate_node', locator=locator)['node']
    proxies = call('style-proxies', 'browse_tree', node_id=styles['node_id'])
    check('R4_proxy_explicit', any(n['kind'] == 'proxy' and n['node_id'] is None and
                                 n['children_state'] == 'unsupported' for n in proxies['children']))

    page1 = call('page1', 'browse_tree', limit=2)
    page2 = call('page2', 'browse_tree', cursor=page1['next_cursor'], limit=2)
    check('R8_pagination', not ({n['node_id'] for n in page1['children']} & {n['node_id'] for n in page2['children']}))
    call('wrong-cursor', 'browse_tree', expected='rejected', node_id=solver['node_id'], cursor=page1['next_cursor'])
    limited = call('node-budget', 'browse_tree', max_nodes=1)
    check('R8_budget_not_empty', limited['state'] == 'partial' and limited['total_count'] is None and bool(limited['truncations']))
    empty_node = next(n for n in root['children'] if n['label'] == 'Derived Parts')
    empty = call('empty-node', 'browse_tree', node_id=empty_node['node_id'])
    check('R8_empty_distinct', empty['state'] == 'complete' and empty['total_count'] == 0)
    call('invalid-reference', 'describe_node', expected='rejected', node_id=unsteady['node_id'] + 'invalid')

    for query, label in [('时间步长', 'search-cn'), ('time step', 'search-en'), ('URF', 'search-urf')]:
        found = call(label, 'search_settings', query=query)
        if label != 'search-urf':
            check('R7_' + label, any((item.get('property') or {}).get('name') == 'TimeStep' for item in found['matches']))
        check(label + '_coverage', found['coverage']['whole_simulation_complete'] is False)
    expanded = call('search-budget', 'search_settings', query='not-a-real-setting', expand=True, max_nodes=2, max_depth=1)
    check('R7_budgeted_expansion', bool(expanded['coverage']['truncations']) and not expanded['coverage']['whole_simulation_complete'])
    after = call('snapshot-after', 'inspect_session')['snapshot']
    check('R9_snapshot_unchanged', not snapshot_diff(content_snapshot(before), content_snapshot(after)))
    check('R9_source_unchanged', digest(Path(state['input'])) == source_hash == state['input_sha256'])
    unsupported = service.get_capabilities('2510')
    check('R10_exact_version_capability', not unsupported['runtime_discovery']['supported'])
    (output / 'report.json').write_text(json.dumps({'checks': checks, 'target': state['catalog_target'],
        'source_sha256': source_hash, 'automatic_write_attempts': 0,
        'scope': 'Base fixture, selected runtime branches; not whole-simulation coverage'}, indent=2) + '\n')
    print('Passed', len(checks), 'checks', flush=True)


if __name__ == '__main__':
    main()
