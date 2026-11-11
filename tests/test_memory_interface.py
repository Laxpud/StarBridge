"""检查共享 Core、MCP 路由与发布契约，不启动协议进程或 STAR 客户端。"""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jsonschema import Draft202012Validator
from mcp.server.mcpserver.exceptions import ToolError
from starbridge.core import memory
from starbridge.core.interface_contract import SERVER_INSTRUCTIONS, usage_contract
from starbridge.core.interface_exposure import expand, method_entry
from starbridge.core.service import METHODS, Service
from starbridge.interfaces import mcp_server


SECRET = 'CASE_EVIDENCE_MUST_NOT_ENTER_KNOWLEDGE'


def entry():
    return {'memory_id': 'interface-method', 'problem': 'Read export configuration',
            'applicability': 'Current STAR objects', 'approach': 'Read the selected update object',
            'certainty': 'single_observation', 'evidence': {'summary': SECRET, 'kind': 'execution'}}


def decoded(result):
    return json.loads(''.join(part.text for part in result.content if hasattr(part, 'text')))


class MemoryInterfaceTests(unittest.IsolatedAsyncioTestCase):
    """以真实 SDK 注册表核对 schema 和调用，但把所有记忆存储隔离到临时目录。"""

    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='starbridge-memory-interface-')
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(memory, 'runtime_root', return_value=Path(self.temporary.name) / 'runtime').start()
        patch.object(Service, '_operate', side_effect=AssertionError('STAR must not be called')).start()
        self.catalog = await mcp_server.method_catalog()

    async def test_registered_methods_schemas_and_read_partition_agree(self):
        self.assertEqual(set(self.catalog), set(METHODS))
        self.assertEqual(method_entry('get_memory_evidence'), 'query')
        for method, contract in self.catalog.items():
            with self.subTest(method=method):
                Draft202012Validator.check_schema(contract['input_schema'])
        self.assertEqual(self.catalog['search_memory']['input_schema']['properties']['limit']['default'], 5)

    async def test_memory_capability_is_bounded_and_includes_explicit_reader(self):
        result = expand(self.catalog, capabilities=['memory'])
        self.assertIsNone(result['next_offset'])
        self.assertEqual({item['method'] for item in result['methods']},
                         {'search_memory', 'get_memory', 'get_memory_evidence', 'record_memory', 'update_memory'})
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 32768)

    async def test_mcp_write_get_search_and_explicit_evidence(self):
        written = await mcp_server.invoke_method('execute', 'record_memory', {'entry': entry()})
        self.assertFalse(written.is_error)
        self.assertNotIn(SECRET, str(decoded(written)))
        normal = await mcp_server.invoke_method('query', 'get_memory', {'memory_id': 'interface-method'})
        self.assertFalse(normal.is_error)
        self.assertNotIn(SECRET, str(decoded(normal)))
        found = await mcp_server.invoke_method('query', 'search_memory', {'query': 'export'})
        self.assertFalse(found.is_error)
        self.assertNotIn(SECRET, str(decoded(found)))
        explicit = await mcp_server.invoke_method('query', 'get_memory_evidence', {'memory_id': 'interface-method'})
        self.assertFalse(explicit.is_error)
        self.assertEqual(decoded(explicit)['result']['records'][0]['summary'], SECRET)

    async def test_unknown_legacy_fields_are_rejected_before_business_call(self):
        invalid = entry()
        invalid['observed_effect'] = SECRET
        with patch.object(mcp_server.service, 'call', wraps=mcp_server.service.call) as business:
            result = await mcp_server.invoke_method('execute', 'record_memory', {'entry': invalid})
            self.assertTrue(result.is_error)
            business.assert_not_called()

    async def test_query_cannot_write_and_evidence_reader_cannot_run_on_execute(self):
        result = await mcp_server.invoke_method('query', 'record_memory', {'entry': entry()})
        self.assertTrue(result.is_error)
        result = await mcp_server.invoke_method('execute', 'get_memory_evidence', {'memory_id': 'interface-method'})
        self.assertTrue(result.is_error)
        self.assertEqual(memory.search_memory('export')['total_matches'], 0)

    async def test_sdk_preserves_strict_integer_validation(self):
        # JSON Schema 可接受 1.0；实际 SDK 的 StrictInt 必须继续拒绝它。
        with patch.object(mcp_server.service, 'call', wraps=mcp_server.service.call) as business:
            with self.assertRaisesRegex(ToolError, 'valid integer'):
                await mcp_server.invoke_method('query', 'search_memory', {'query': '', 'limit': 1.0})
            business.assert_not_called()

    async def test_evidence_schema_does_not_require_detailed_case_fields(self):
        schema = self.catalog['record_memory']['input_schema']
        minimal = entry()
        minimal['evidence'] = {'summary': 'One concise existing observation'}
        Draft202012Validator(schema).validate({'entry': minimal})
        minimal.pop('evidence')
        Draft202012Validator(schema).validate({'entry': minimal})
        self.assertEqual(set(schema['properties']['entry']['required']),
                         {'problem', 'applicability', 'approach', 'certainty'})

    async def test_get_memory_evidence_rejects_unreferenced_and_unsafe_ids(self):
        memory.record_memory(entry())
        for identifier in ('../outside', 'not-referenced'):
            result = await mcp_server.invoke_method('query', 'get_memory_evidence',
                {'memory_id': 'interface-method', 'evidence_id': identifier})
            self.assertTrue(result.is_error)

    async def test_service_recipe_provenance_does_not_read_or_return_case_evidence(self):
        method = entry()
        method['recipe'] = {'code': 'result.put("name", parameters.get("name"));', 'imports': [],
                            'effect': 'read', 'scope': 'Read the current parameter',
                            'parameters': {'name': {'type': 'string', 'description': 'Current parameter', 'required': True}}}
        memory.record_memory(method)
        service = Service()
        result = {'execution': {'status': 'completed', 'steps': [{'id': 'recipe', 'status': 'completed', 'result': {}}]}}
        with patch.object(service, '_execute_bound_macro', return_value=result) as execute:
            with patch.object(memory, '_get_evidence', side_effect=AssertionError('Evidence should not be read')):
                value = service.execute_recipe('current-session', 'current-request', 'memory:interface-method',
                                               parameters={'name': 'current'}, expected_revision=1)
        execute.assert_called_once()
        self.assertNotIn(SECRET, json.dumps(value))
        self.assertNotIn('evidence_scope', value['recipe'])
        self.assertEqual(value['recipe']['certainty'], 'single_observation')

    async def test_runtime_contract_matches_new_storage_behavior(self):
        contract = usage_contract()['working_memory']
        self.assertEqual(contract['schema_version'], 2)
        self.assertEqual(set(contract['required_entry_fields']),
                         {'problem', 'applicability', 'approach', 'certainty'})
        self.assertIn('get_memory_evidence', contract['methods'])
        self.assertNotIn('observed_effect', contract['required_entry_fields'])

    async def test_guidance_allows_direct_macros_and_keeps_case_read_optional(self):
        self.assertIn('自身知识', SERVER_INSTRUCTIONS)
        self.assertIn('不把查文档或先执行失败设为前置', SERVER_INSTRUCTIONS)
        self.assertIn('普通记忆搜索和读取不含案例证据', SERVER_INSTRUCTIONS)
        self.assertIn('复用不要求先读案例', SERVER_INSTRUCTIONS)
        self.assertNotIn('任务开始时按已有背景用 search_memory', SERVER_INSTRUCTIONS)
        self.assertNotIn('选中后用 read_api', self.catalog['search_api']['description'])
        self.assertIn('无需先查询索引', self.catalog['read_api']['input_schema']['properties']['java_class']['description'])


if __name__ == '__main__':
    unittest.main()
