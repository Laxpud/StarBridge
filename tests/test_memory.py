"""检查知识/证据隔离、修订和迁移；全部文件只写入临时目录，不调用 STAR。"""

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

# 仓库根的兼容脚本也叫 starbridge.py；测试明确导入 src 中的实际包。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starbridge.core import memory
from starbridge.core.service import Service


CASE_MARKER = 'PRIVATE_CASE_OBSERVATION_275_VALUES'


def knowledge(memory_id='export-directory', **overrides):
    """测试知识没有历史对象名、路径或结果数值。"""
    entry = {'memory_id': memory_id, 'title': 'Read and update export directory',
             'problem': 'Read export settings', 'applicability': 'Current update objects in STAR 2602',
             'approach': 'Read the directory, compare the expected path, then update and read back.',
             'certainty': 'single_observation', 'tags': ['export', 'directory']}
    entry.update(overrides)
    return entry


def evidence(**overrides):
    entry = {'summary': CASE_MARKER, 'kind': 'execution',
             'references': ['/private/case/request/result.json'],
             'limitations': 'No export was triggered in the observed case.'}
    entry.update(overrides)
    return entry


class MemoryTests(unittest.TestCase):
    """每项测试隔离用户运行根，避免碰到开发者的真实共享记忆。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='starbridge-memory-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.runtime = self.base / 'runtime'
        self.project = self.base / 'project'
        self.project.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(memory, 'runtime_root', return_value=self.runtime).start()
        # 即便未来改动误接到了会话路径，也应立即失败而非连接实际 STAR。
        patch.object(Service, '_operate', side_effect=AssertionError('STAR must not be called')).start()

    def create(self, memory_id='export-directory', **overrides):
        return memory.record_memory(knowledge(memory_id, **overrides))

    def make_legacy(self, memory_id='legacy-export'):
        """模拟升级前的混合记录，包含必须隔离的案例正文。"""
        record = knowledge(memory_id)
        record.update(schema_version=1, revision=4, created_at='2026-11-05T00:00:00+08:00',
                      updated_at='2026-11-05T00:00:00+08:00', observed_effect=CASE_MARKER,
                      source=CASE_MARKER, evidence=[CASE_MARKER], evidence_scope=CASE_MARKER)
        root = self.runtime / 'memory'
        root.mkdir(parents=True, exist_ok=True)
        path = root / f'{memory_id}.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        return path, record

    def test_builtin_reads_do_not_create_directories(self):
        found = memory.search_memory('单位 表达式')
        item = memory.get_memory('starccm-unit-expression')
        self.assertEqual(found['returned'], 1)
        self.assertEqual(item['schema_version'], 2)
        self.assertNotIn('source', item)
        self.assertNotIn('evidence', item)
        self.assertFalse(self.runtime.exists())
        proof = memory.get_memory_evidence(item['memory_id'])
        self.assertEqual(proof['records'][0]['kind'], 'user_rule')
        self.assertFalse(self.runtime.exists())

    def test_write_get_and_search_do_not_return_case_content(self):
        receipt = self.create(evidence=evidence())
        item = memory.get_memory(receipt['memory_id'])
        found = memory.search_memory('export directory')
        for value in (receipt, item, found):
            self.assertNotIn(CASE_MARKER, json.dumps(value))
            self.assertNotIn('/private/case/', json.dumps(value))
        self.assertEqual(set(receipt), {'memory_id', 'revision', 'schema_version', 'storage_scope', 'evidence_added'})
        self.assertEqual(len(item['evidence_ids']), 1)
        self.assertNotIn('observed_effect', found['candidates'][0]['summary'])
        self.assertNotIn('evidence_scope', found['candidates'][0]['summary'])
        root_record = json.loads((self.runtime / 'memory/export-directory.json').read_text())
        self.assertNotIn(CASE_MARKER, json.dumps(root_record))
        proof = memory.get_memory_evidence(item['memory_id'])
        self.assertEqual(proof['records'][0]['summary'], CASE_MARKER)

    def test_evidence_is_optional(self):
        receipt = self.create()
        self.assertFalse(receipt['evidence_added'])
        self.assertEqual(memory.get_memory('export-directory')['evidence_ids'], [])
        self.assertEqual(memory.get_memory_evidence('export-directory')['records'], [])
        self.assertFalse((self.runtime / 'memory/evidence').exists())

    def test_case_fields_and_evidence_ids_do_not_match_queries(self):
        self.create(evidence=evidence())
        identifier = memory.get_memory('export-directory')['evidence_ids'][0]
        for query in (CASE_MARKER, '/private/case/', identifier, '275_VALUES'):
            self.assertEqual(memory.search_memory(query)['total_matches'], 0, query)
        before = memory.search_memory('', limit=200)
        after = memory.search_memory('', context=CASE_MARKER, limit=200)
        self.assertEqual([(item['memory_id'], item['match']['score']) for item in before['candidates']],
                         [(item['memory_id'], item['match']['score']) for item in after['candidates']])

    def test_normal_reads_never_open_evidence(self):
        self.create(evidence=evidence())
        with patch.object(memory, '_get_evidence', side_effect=AssertionError('Evidence read was not requested')):
            self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
            self.assertEqual(memory.search_memory('export')['returned'], 1)

    def test_all_whitespace_keywords_must_match_knowledge(self):
        self.create('exports-only', approach='Read exports without touching the solver.', tags=[])
        self.create('solver-only', title='Solver status', problem='Read iterations',
                    approach='Read solver status.', tags=[])
        found = memory.search_memory('exports solver')
        self.assertEqual([item['memory_id'] for item in found['candidates']], ['exports-only'])
        self.assertEqual(memory.search_memory('exports nonexistent')['returned'], 0)

    def test_default_short_page_and_explicit_browse(self):
        for index in range(8):
            self.create(f'method-{index}')
        result = memory.search_memory('export')
        self.assertEqual(result['limit'], 5)
        self.assertEqual(result['returned'], 5)
        self.assertEqual(result['next_offset'], 5)
        self.assertEqual(memory.search_memory('', limit=200)['total_matches'], 9)

    def test_search_byte_budget_and_pagination_preserve_candidates(self):
        for index in range(45):
            self.create(f'bounded-{index:02d}', title='知识' * 80, problem='export ' + '问题' * 200,
                        approach='做法' * 300, applicability='条件' * 150)
        offset, seen = 0, []
        while True:
            result = memory.search_memory('export', limit=200, offset=offset)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 32768)
            self.assertEqual(result['budget']['serialized_bytes'], len(json.dumps(result, ensure_ascii=False).encode('utf-8')))
            seen.extend(item['memory_id'] for item in result['candidates'])
            if result['next_offset'] is None:
                break
            self.assertGreater(result['next_offset'], offset)
            offset = result['next_offset']
        self.assertEqual(len(seen), 45)
        self.assertEqual(len(set(seen)), 45)

    def test_update_preserves_prior_evidence_without_echoing_it(self):
        self.create(evidence=evidence())
        first = memory.get_memory('export-directory')
        receipt = memory.update_memory('export-directory', 1,
                                      {'approach': 'Read only the requested update objects.',
                                       'evidence': evidence(summary='Another concise observation')})
        self.assertEqual(receipt['revision'], 2)
        self.assertNotIn('Another concise observation', json.dumps(receipt))
        second = memory.get_memory('export-directory')
        self.assertEqual(second['evidence_ids'][0], first['evidence_ids'][0])
        self.assertEqual(len(second['evidence_ids']), 2)
        self.assertEqual(memory.get_memory_evidence('export-directory')['total'], 2)

    def test_evidence_only_update_does_not_rewrite_method(self):
        self.create()
        before = memory.get_memory('export-directory')
        memory.update_memory('export-directory', 1, {'evidence': evidence()})
        after = memory.get_memory('export-directory')
        for field in ('problem', 'applicability', 'approach', 'certainty', 'created_at'):
            self.assertEqual(before[field], after[field])

    def test_revision_conflict_does_not_append_evidence(self):
        self.create(evidence=evidence())
        with self.assertRaises(memory.MemoryConflictError):
            memory.update_memory('export-directory', 2, {'evidence': evidence()})
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
        self.assertEqual(memory.get_memory_evidence('export-directory')['total'], 1)

    def test_duplicate_create_is_rejected(self):
        self.create()
        with self.assertRaises(memory.MemoryConflictError):
            self.create(evidence=evidence())
        self.assertFalse((self.runtime / 'memory/evidence').exists())

    def test_invalid_evidence_is_rejected_before_writing(self):
        invalid = [None, [], {}, {'summary': ''}, {'summary': 'x', 'case_data': [1, 2]},
                   evidence(summary='超长' * 3000), evidence(references=['x'] * 9),
                   evidence(kind='unknown'), evidence(kind=[])]
        for item in invalid:
            with self.subTest(item=str(item)[:80]), self.assertRaises(ValueError):
                self.create(evidence=item)
        self.assertFalse(self.runtime.exists())

    def test_legacy_case_fields_cannot_be_written_as_knowledge(self):
        for field in ('observed_effect', 'source', 'evidence_scope', 'references', 'evidence_ids'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.create(**{field: CASE_MARKER})
        self.assertFalse(self.runtime.exists())

    def test_recipe_is_retained_without_evidence(self):
        recipe = {'code': 'result.put("name", parameters.get("name"));', 'imports': [],
                  'parameters': {'name': {'type': 'string', 'description': 'Current name', 'required': True}}}
        self.create(recipe=recipe, evidence=evidence())
        item = memory.get_memory('export-directory')
        self.assertEqual(item['recipe'], recipe)
        self.assertNotIn(CASE_MARKER, json.dumps(item))
        bad = deepcopy(recipe)
        bad['parameters']['target'] = {'type': 'object_reference', 'description': 'Current object',
                                       'required': True, 'default': {'object_id': 'old-object'}}
        with self.assertRaises(ValueError):
            self.create('bad-default', recipe=bad)

    def test_optional_knowledge_fields_can_be_deleted(self):
        self.create(exceptions=['Requires current objects'])
        memory.update_memory('export-directory', 1, {'title': None, 'exceptions': None})
        item = memory.get_memory('export-directory')
        self.assertNotIn('title', item)
        self.assertNotIn('exceptions', item)
        with self.assertRaises(ValueError):
            memory.update_memory('export-directory', 2, {'approach': None})

    def test_project_overlay_retains_inherited_evidence(self):
        self.create(evidence=evidence())
        receipt = memory.update_memory('export-directory', 1, {'approach': 'Project-specific method conditions'},
                                       project_dir=str(self.project))
        self.assertEqual(receipt['storage_scope'], 'project')
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
        item = memory.get_memory('export-directory', str(self.project))
        self.assertEqual(item['revision'], 2)
        proof = memory.get_memory_evidence('export-directory', str(self.project))
        self.assertEqual(proof['records'][0]['summary'], CASE_MARKER)

    def test_explicit_shared_project_directory_is_unchanged(self):
        receipt = memory.record_memory(knowledge(), str(self.project))
        self.assertEqual(receipt['storage_scope'], 'project')
        self.assertTrue((self.project / '.starbridge/memory/export-directory.json').exists())
        self.assertEqual(memory.search_memory('export')['total_matches'], 0)
        self.assertEqual(memory.search_memory('export', project_dir=str(self.project))['total_matches'], 1)

    def test_legacy_reads_fail_without_exposing_case_body(self):
        self.make_legacy()
        for operation in (lambda: memory.get_memory('legacy-export'), lambda: memory.search_memory('export')):
            with self.assertRaises(memory.MemoryMigrationRequiredError) as captured:
                operation()
            self.assertNotIn(CASE_MARKER, str(captured.exception))
            self.assertEqual(captured.exception.records, [{'memory_id': 'legacy-export', 'revision': 4}])
        result = Service().call('search_memory', {'query': 'export'})
        self.assertEqual(result['status'], 'rejected')
        self.assertNotIn(CASE_MARKER, json.dumps(result))
        self.assertEqual(result['recovery']['next_tool'], 'starbridge.update_memory')

    def test_legacy_migration_preserves_archive_and_only_curated_knowledge(self):
        path, original = self.make_legacy()
        changes = knowledge()
        changes.pop('memory_id')
        changes['evidence'] = evidence(summary='One existing execution supports this method')
        receipt = memory.update_memory('legacy-export', 4, changes)
        self.assertEqual(receipt['revision'], 5)
        archive = path.parent / 'legacy/legacy-export-r4.json'
        self.assertEqual(json.loads(archive.read_text()), original)
        self.assertNotIn(CASE_MARKER, json.dumps(memory.get_memory('legacy-export')))
        self.assertEqual(memory.search_memory('export')['total_matches'], 1)
        self.assertEqual(memory.get_memory_evidence('legacy-export')['total'], 1)

    def test_partial_legacy_migration_does_not_change_original(self):
        path, original = self.make_legacy()
        with self.assertRaises(memory.MemoryMigrationRequiredError):
            memory.update_memory('legacy-export', 4, {'approach': 'Still needs full curation'})
        self.assertEqual(json.loads(path.read_text()), original)
        self.assertFalse((path.parent / 'legacy').exists())

    def test_project_knowledge_can_override_user_legacy_record(self):
        self.make_legacy()
        changes = knowledge()
        changes.pop('memory_id')
        memory.update_memory('legacy-export', 4, changes, str(self.project))
        self.assertEqual(memory.search_memory('export', project_dir=str(self.project))['total_matches'], 1)
        with self.assertRaises(memory.MemoryMigrationRequiredError):
            memory.get_memory('legacy-export')

    def test_missing_or_corrupt_evidence_does_not_block_knowledge(self):
        self.create(evidence=evidence())
        identifier = memory.get_memory('export-directory')['evidence_ids'][0]
        path = self.runtime / f'memory/evidence/export-directory/{identifier}.json'
        path.write_text('{broken', encoding='utf-8')
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
        self.assertEqual(memory.search_memory('export')['returned'], 1)
        with self.assertRaises(memory.MemoryCorruptionError):
            memory.get_memory_evidence('export-directory')
        path.unlink()
        with self.assertRaises(memory.MemoryNotFoundError):
            memory.get_memory_evidence('export-directory')

    def test_only_referenced_evidence_can_be_requested(self):
        self.create(evidence=evidence())
        with self.assertRaises(memory.MemoryNotFoundError):
            memory.get_memory_evidence('export-directory', evidence_id='unreferenced-id')
        identifier = memory.get_memory('export-directory')['evidence_ids'][0]
        proof = memory.get_memory_evidence('export-directory', evidence_id=identifier)
        self.assertEqual(proof['records'][0]['evidence_id'], identifier)

    def test_evidence_pagination_has_byte_budget(self):
        self.create()
        for revision in range(1, 15):
            memory.update_memory('export-directory', revision,
                                 {'evidence': evidence(summary=f'Case {revision}: ' + '观察' * 450)})
        offset, seen = 0, []
        while True:
            page = memory.get_memory_evidence('export-directory', offset=offset, limit=200)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode('utf-8')), 32768)
            seen.extend(item['evidence_id'] for item in page['records'])
            if page['next_offset'] is None:
                break
            self.assertGreater(page['next_offset'], offset)
            offset = page['next_offset']
        self.assertEqual(len(set(seen)), 14)

    def test_invalid_inputs_cannot_escape_or_trigger_writes(self):
        for identifier in ('../escape', '/absolute', '', 'a/b'):
            with self.assertRaises(ValueError):
                memory.get_memory(identifier)
        for kwargs in ({'limit': True}, {'offset': -1}, {'offset': True}, {'limit': 201}):
            with self.assertRaises(ValueError):
                memory.search_memory('', **kwargs)
        with self.assertRaises(ValueError):
            self.create(tags=[float('nan')])
        self.assertFalse(self.runtime.exists())

    def test_null_evidence_is_not_an_implicit_delete(self):
        self.create(evidence=evidence())
        with self.assertRaises(ValueError):
            memory.update_memory('export-directory', 1, {'approach': 'Changed', 'evidence': None})
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
        self.assertEqual(memory.get_memory_evidence('export-directory')['total'], 1)

    @unittest.skipIf(os.name == 'nt', 'Symlink creation may require Windows privileges')
    def test_evidence_subdirectory_cannot_redirect_writes(self):
        self.create()
        outside = self.base / 'unrelated'
        outside.mkdir()
        (self.runtime / 'memory/evidence').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(memory.MemoryCorruptionError):
            memory.update_memory('export-directory', 1, {'evidence': evidence()})
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
        self.assertEqual(memory.search_memory('export')['returned'], 1)

    def test_evidence_owner_mismatch_is_explicit_corruption(self):
        self.create(evidence=evidence())
        identifier = memory.get_memory('export-directory')['evidence_ids'][0]
        path = self.runtime / f'memory/evidence/export-directory/{identifier}.json'
        record = json.loads(path.read_text())
        record['memory_id'] = 'another-method'
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(memory.MemoryCorruptionError):
            memory.get_memory_evidence('export-directory')
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)

    def test_corrupt_knowledge_is_not_treated_as_no_match(self):
        root = self.runtime / 'memory'
        root.mkdir(parents=True)
        (root / 'broken.json').write_text('{"memory_id":"a","memory_id":"b"}', encoding='utf-8')
        with self.assertRaises(memory.MemoryCorruptionError):
            memory.search_memory('export')

    @unittest.skipIf(os.name == 'nt', 'Uses POSIX process locks')
    def test_busy_store_does_not_write_record(self):
        with memory._lock(self.runtime / 'memory'):
            with self.assertRaises(memory.MemoryBusyError):
                self.create()
        self.assertFalse((self.runtime / 'memory/export-directory.json').exists())

    def test_failed_knowledge_commit_keeps_old_revision_and_hides_orphan(self):
        self.create()
        original = memory._persist

        def fail_knowledge(root, record, **kwargs):
            if record.get('schema_version') == 2:
                raise memory.MemoryPersistenceError('Injected knowledge commit failure')
            return original(root, record, **kwargs)

        with patch.object(memory, '_persist', side_effect=fail_knowledge):
            with self.assertRaises(memory.MemoryPersistenceError):
                memory.update_memory('export-directory', 1, {'evidence': evidence()})
        self.assertEqual(memory.get_memory('export-directory')['revision'], 1)
        self.assertEqual(memory.get_memory('export-directory')['evidence_ids'], [])
        self.assertEqual(memory.get_memory_evidence('export-directory')['total'], 0)
        self.assertEqual(memory.search_memory(CASE_MARKER)['returned'], 0)

    @unittest.skipIf(os.name == 'nt', 'Directory fsync is POSIX-specific')
    def test_post_replace_failure_reports_uncertain_commit(self):
        self.create()
        original = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('Injected directory fsync failure')
            return original(fd)

        with patch.object(memory.os, 'fsync', side_effect=fail_directory):
            with self.assertRaises(memory.MemoryPersistenceError) as captured:
                memory.update_memory('export-directory', 1, {'approach': 'Updated knowledge'})
        self.assertTrue(captured.exception.may_have_committed)
        self.assertEqual(memory.get_memory('export-directory')['revision'], 2)


if __name__ == '__main__':
    unittest.main()
