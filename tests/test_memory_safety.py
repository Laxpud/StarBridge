"""验证记忆写前拦截与不回显边界；所有凭据样例均为无效合成值。

只使用临时存储和假的认证格式，不访问真实凭据、外部引用、网络或 STAR。
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from starbridge.core import memory
from starbridge.core.memory_safety import (
    MemorySensitiveDataError, ensure_safe_memory_data, sensitive_data_rejection,
)
from starbridge.core.service import Service


FAKE_VALUE = 'not-a-real-credential-starbridge-7291046'
FAKE_PROVIDER_TOKEN = 'sk-proj-' + 'A1b2' * 10
FAKE_PRIVATE_KEY = '-----BEGIN PRIVATE KEY-----\n' + 'M' * 64 + '\n-----END PRIVATE KEY-----'


def clean_entry(memory_id='safe-method'):
    return {'memory_id': memory_id, 'problem': 'Read current export settings',
            'applicability': 'STAR 2602 current objects', 'approach': 'Read and compare update settings',
            'certainty': 'single_observation'}


def recipe(parameters=None, code='result.put("ok", true);'):
    return {'code': code, 'imports': [], 'parameters': parameters or {}}


def parameter(**changes):
    value = {'type': 'string', 'description': 'Supply at runtime; do not persist authentication values', 'required': True}
    value.update(changes)
    return value


class MemorySafetyTests(unittest.TestCase):
    """从公开 Core 写入接口检查拒绝、兼容性及持久化前后的实际文件状态。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='starbridge-memory-safety-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        self.project = self.root / 'project'
        self.project.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(memory, 'runtime_root', return_value=self.runtime).start()
        patch.object(Service, '_operate', side_effect=AssertionError('STAR must not be called')).start()

    def assert_safe_error(self, error, *values):
        text = str(error) + repr(error) + json.dumps(vars(error))
        for value in values:
            self.assertNotIn(value, text)
        self.assertTrue(error.field_path)
        self.assertLessEqual(len(error.field_path), 32)

    def snapshot(self):
        if not self.runtime.exists():
            return {}
        return {str(path.relative_to(self.runtime)): path.read_bytes()
                for path in self.runtime.rglob('*') if path.is_file()}

    def test_common_authentication_formats_are_rejected_before_lock_or_files(self):
        texts = [
            FAKE_PRIVATE_KEY,
            '-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-256-CBC,00\n' + 'M' * 64,
            FAKE_PROVIDER_TOKEN,
            json.dumps(json.dumps({'api_key': FAKE_VALUE})),
            'Authorization: Bearer ' + FAKE_VALUE,
            'Proxy-Authorization: Basic bm90LWEtdmFsaWQtdXNlcjpub3QtYS1wYXNzd29yZA==',
            'Cookie: sid=' + FAKE_VALUE + '; theme=dark',
            'Set-Cookie: __Host-session=' + FAKE_VALUE + '; Secure; HttpOnly',
            'https://reader:' + FAKE_VALUE + '@service.invalid/read',
            'https://reader:' + FAKE_VALUE + '@[invalid/read',
            'https://[invalid/read?access_token=' + FAKE_VALUE,
            'https://storage.invalid/file?X-Amz-Signature=' + FAKE_VALUE,
            'https://storage.invalid/file?sig=' + FAKE_VALUE,
            'https://service.invalid/read?api%5Fkey=' + FAKE_VALUE,
            'https://service.invalid/#access_token=' + FAKE_VALUE,
            'API_KEY=' + FAKE_VALUE,
            '{"client_secret": "' + FAKE_VALUE + '"}',
            'String password = "' + FAKE_VALUE + '";',
        ]
        for index, text in enumerate(texts):
            with self.subTest(index=index):
                entry = clean_entry()
                entry['approach'] = text
                with patch.object(memory, '_write_scope', side_effect=AssertionError('No write lock expected')):
                    with self.assertRaises(MemorySensitiveDataError) as captured:
                        memory.record_memory(entry)
                self.assert_safe_error(captured.exception, FAKE_VALUE, FAKE_PROVIDER_TOKEN, FAKE_PRIVATE_KEY)
                self.assertFalse(self.runtime.exists())

    def test_entire_payload_including_code_and_evidence_is_checked(self):
        entries = []
        for field in ('problem', 'applicability', 'approach', 'title'):
            value = clean_entry()
            value[field] = FAKE_PROVIDER_TOKEN
            entries.append(value)
        value = clean_entry()
        value['tags'] = ['export', FAKE_PROVIDER_TOKEN]
        entries.append(value)
        for field in ('code', 'declarations', 'scope'):
            value = clean_entry()
            value['recipe'] = recipe()
            value['recipe'][field] = FAKE_PROVIDER_TOKEN
            entries.append(value)
        for field in ('summary', 'limitations'):
            value = clean_entry()
            value['evidence'] = {'summary': 'An existing observation', field: FAKE_PROVIDER_TOKEN}
            entries.append(value)
        value = clean_entry()
        value['evidence'] = {'summary': 'An existing observation',
                             'references': ['https://example.invalid/result?access_token=' + FAKE_VALUE]}
        entries.append(value)
        for index, value in enumerate(entries):
            with self.subTest(index=index), self.assertRaises(MemorySensitiveDataError):
                memory.record_memory(value)
        self.assertFalse(self.runtime.exists())

    def test_named_credential_defaults_and_nested_values_are_rejected(self):
        defaults = [FAKE_VALUE, 7291046, [FAKE_VALUE], {'nested': [FAKE_VALUE]}]
        for name in ('api_key', 'clientSecret', 'password', 'private_key'):
            for value in defaults:
                with self.subTest(name=name, kind=type(value).__name__):
                    entry = clean_entry()
                    entry['recipe'] = recipe({name: parameter(default=value)})
                    with self.assertRaises(MemorySensitiveDataError) as captured:
                        memory.record_memory(entry)
                    self.assertIn('default', captured.exception.field_path)
                    self.assert_safe_error(captured.exception, FAKE_VALUE)
        self.assertFalse(self.runtime.exists())

    def test_structured_auth_headers_and_cookies_are_rejected(self):
        values = [{'Authorization': 'Bearer ' + FAKE_VALUE}, {'Authorization': FAKE_VALUE}, {'Authorization': 7291046},
                  {'Proxy-Authorization': 'Token ' + FAKE_VALUE}, {'Cookie': 'sessionid=' + FAKE_VALUE}]
        for value in values:
            entry = clean_entry()
            entry['recipe'] = recipe({'headers': parameter(type='object', default=value)})
            with self.subTest(kind=list(value)[0]), self.assertRaises(MemorySensitiveDataError):
                memory.record_memory(entry)
        self.assertFalse(self.runtime.exists())

    def test_parameter_definitions_and_explicit_placeholders_remain_valid(self):
        variants = [None, '<API_KEY>', '<PRIVATE_KEY>', '<CLIENT_SECRET>', '<ACCESS_TOKEN>',
                    '{API_KEY}', '${STARBRIDGE_TEST_KEY}', '{{STARBRIDGE_TEST_KEY}}',
                    '%STARBRIDGE_TEST_KEY%', 'REDACTED', '***']
        for index, value in enumerate(variants):
            entry = clean_entry(f'placeholder-{index}')
            contract = parameter()
            if value is not None:
                contract['default'] = value
            entry['recipe'] = recipe({'api_key': contract},
                'String apiKey = System.getenv("STARBRIDGE_TEST_KEY");\n'
                'String password = currentPassword;\n'
                'result.put("Authorization", "Bearer " + apiKey);')
            entry['evidence'] = {'summary': 'Runtime credential sources are parameters, not stored values',
                                 'references': ['https://example.invalid/?access_token=${TOKEN}']}
            self.assertEqual(memory.record_memory(entry)['revision'], 1)

    def test_normal_identifiers_versions_paths_and_public_api_names_are_not_secrets(self):
        identifier = '19fb6cd0daff427299fed00cfcca4a96'
        entry = clean_entry(identifier)
        entry['approach'] = 'Use getApiKey() only as a public API name; read STAR 2602 without storing a key.'
        entry['evidence'] = {'summary': 'A technical observation',
                             'references': ['~/.starbridge/sessions/' + identifier + '/requests/read/result.json',
                                            'https://docs.invalid/api?request_id=' + identifier]}
        receipt = memory.record_memory(entry)
        self.assertEqual(receipt['memory_id'], identifier)
        self.assertEqual(memory.record_memory(clean_entry('sk-common-parameter-checks'))['revision'], 1)
        ensure_safe_memory_data({'token': identifier, 'session_id': identifier, 'object_id': identifier,
                                 'path': '/opt/Siemens/STAR-CCM+', 'cookie': 'theme=dark'})

    def test_redacted_key_markers_without_key_material_are_allowed(self):
        entry = clean_entry()
        entry['approach'] = 'Never store -----BEGIN PRIVATE KEY----- blocks; use a runtime provider.'
        entry['recipe'] = recipe({'password': parameter(default='<PASSWORD>')})
        memory.record_memory(entry)

    def test_url_placeholders_and_blank_auth_fields_are_allowed(self):
        ensure_safe_memory_data({'Authorization': 'Bearer <TOKEN>', 'password': '', 'client_secret': None,
                                 'reference': 'https://reader:${PASSWORD}@service.invalid/?sig=<TOKEN>',
                                 'Cookie': 'sessionid=<TOKEN>'})

    def test_custom_key_names_are_not_echoed_in_exception_or_response(self):
        key = 'customer-private-field-' + FAKE_VALUE
        with self.assertRaises(MemorySensitiveDataError) as captured:
            ensure_safe_memory_data({'entry': {'recipe': {'parameters': {key: parameter(default=FAKE_PROVIDER_TOKEN)}}}})
        self.assert_safe_error(captured.exception, key, FAKE_VALUE, FAKE_PROVIDER_TOKEN)
        payload = sensitive_data_rejection(captured.exception)
        self.assertNotIn(key, json.dumps(payload))
        self.assertNotIn(FAKE_PROVIDER_TOKEN, json.dumps(payload))
        self.assertFalse(payload['recovery']['automatic_retry'])

    def test_credential_in_dictionary_key_is_rejected_without_echo(self):
        with self.assertRaises(MemorySensitiveDataError) as captured:
            memory.record_memory(dict(clean_entry(), **{FAKE_PROVIDER_TOKEN: 'ignored'}))
        self.assert_safe_error(captured.exception, FAKE_PROVIDER_TOKEN)
        self.assertTrue(any(str(part).startswith('<key:') for part in captured.exception.field_path))
        self.assertFalse(self.runtime.exists())

    def test_shared_container_is_rechecked_in_credential_context(self):
        shared = parameter(default=FAKE_VALUE)
        entry = clean_entry()
        entry['recipe'] = recipe({'ordinary_value': shared, 'password': shared})
        with patch.object(memory, '_write_scope', side_effect=AssertionError('No write lock expected')):
            with self.assertRaises(MemorySensitiveDataError):
                memory.record_memory(entry)
        self.assertFalse(self.runtime.exists())

    def test_deep_and_cyclic_input_cannot_expand_sensitive_diagnostics(self):
        value = FAKE_PROVIDER_TOKEN
        for index in range(1200):
            value = {'private-customer-name': value}
        with self.assertRaises(MemorySensitiveDataError) as captured:
            ensure_safe_memory_data(value)
        self.assert_safe_error(captured.exception, FAKE_PROVIDER_TOKEN, 'private-customer-name')
        cycle = []
        cycle.append(cycle)
        ensure_safe_memory_data(cycle)
        with self.assertRaises(ValueError):
            memory.record_memory(dict(clean_entry(), exceptions=cycle))

    def test_escaped_code_literal_is_checked_without_executing_it(self):
        entry = clean_entry()
        entry['recipe'] = recipe(code='String configuration = ' +
                                json.dumps(json.dumps({'password': FAKE_VALUE})) + ';')
        with self.assertRaises(MemorySensitiveDataError) as captured:
            memory.record_memory(entry)
        self.assertEqual(captured.exception.field_path, ['entry', 'recipe', 'code'])
        self.assertFalse(self.runtime.exists())

    def test_unreviewably_large_auth_url_query_is_not_silently_accepted(self):
        url = 'https://service.invalid/read?' + '&'.join(f'p{index}=value' for index in range(1025))
        with self.assertRaises(MemorySensitiveDataError) as captured:
            ensure_safe_memory_data({'references': [url]})
        self.assertEqual(captured.exception.category, 'unreviewable_url')
        self.assertNotIn(url, str(captured.exception))

    def test_exception_category_cannot_be_used_to_echo_arbitrary_content(self):
        error = MemorySensitiveDataError(FAKE_VALUE, [FAKE_PROVIDER_TOKEN])
        self.assert_safe_error(error, FAKE_VALUE, FAKE_PROVIDER_TOKEN)
        self.assertEqual(error.category, 'sensitive_data')

    def test_guard_never_opens_files_or_network_references(self):
        with patch('builtins.open', side_effect=AssertionError('No file access expected')):
            ensure_safe_memory_data({'references': ['outputs/missing.json', '~/.starbridge/missing.json',
                                                    'https://service.invalid/not-downloaded']})
        self.assertFalse(self.runtime.exists())

    def test_rejected_update_preserves_knowledge_evidence_and_revision(self):
        memory.record_memory(clean_entry())
        before = self.snapshot()
        with self.assertRaises(MemorySensitiveDataError):
            memory.update_memory('safe-method', 1, {'approach': 'Bearer ' + FAKE_VALUE,
                                                   'evidence': {'summary': 'A new observation'}})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(memory.get_memory('safe-method')['revision'], 1)

    def test_rejected_evidence_update_does_not_leave_orphan(self):
        memory.record_memory(clean_entry())
        before = self.snapshot()
        with self.assertRaises(MemorySensitiveDataError):
            memory.update_memory('safe-method', 1, {'evidence': {'summary': FAKE_PROVIDER_TOKEN}})
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.runtime / 'memory/evidence').exists())

    def test_merged_knowledge_is_checked_before_any_new_evidence_is_written(self):
        memory.record_memory(clean_entry())
        path = self.runtime / 'memory/safe-method.json'
        raw = json.loads(path.read_text())
        raw['approach'] = FAKE_PROVIDER_TOKEN
        path.write_text(json.dumps(raw), encoding='utf-8')
        with self.assertRaises(MemorySensitiveDataError) as captured:
            memory.update_memory('safe-method', 1, {'title': 'New title', 'evidence': {'summary': 'New observation'}})
        self.assertEqual(captured.exception.field_path[0], 'stored_knowledge')
        self.assertEqual(json.loads(path.read_text())['revision'], 1)
        self.assertFalse((self.runtime / 'memory/evidence').exists())

    def test_removing_old_sensitive_optional_field_is_allowed(self):
        memory.record_memory(clean_entry())
        path = self.runtime / 'memory/safe-method.json'
        raw = json.loads(path.read_text())
        raw['exceptions'] = [FAKE_PROVIDER_TOKEN]
        path.write_text(json.dumps(raw), encoding='utf-8')
        receipt = memory.update_memory('safe-method', 1, {'exceptions': None})
        self.assertEqual(receipt['revision'], 2)
        self.assertNotIn('exceptions', memory.get_memory('safe-method'))

    def test_migration_cannot_copy_sensitive_legacy_record_to_archive(self):
        root = self.runtime / 'memory'
        root.mkdir(parents=True)
        raw = dict(clean_entry('legacy-method'), schema_version=1, revision=4,
                   created_at='2026-11-05T00:00:00+08:00', updated_at='2026-11-05T00:00:00+08:00',
                   observed_effect='Observed once', source=FAKE_PROVIDER_TOKEN,
                   evidence=['Existing reference'], evidence_scope='One version')
        path = root / 'legacy-method.json'
        path.write_text(json.dumps(raw), encoding='utf-8')
        changes = clean_entry()
        changes.pop('memory_id')
        with self.assertRaises(MemorySensitiveDataError) as captured:
            memory.update_memory('legacy-method', 4, changes)
        self.assertEqual(captured.exception.field_path[:2], ['legacy_archive', 'source'])
        self.assertEqual(json.loads(path.read_text()), raw)
        self.assertFalse((root / 'legacy').exists())
        self.assertFalse((root / 'evidence').exists())

    def test_does_not_scan_unrelated_records_or_existing_evidence(self):
        memory.record_memory(clean_entry())
        path = self.runtime / 'memory/unrelated.json'
        path.write_text(FAKE_PROVIDER_TOKEN, encoding='utf-8')
        with patch.object(memory, '_get_evidence', side_effect=AssertionError('No evidence read expected')):
            receipt = memory.update_memory('safe-method', 1, {'title': 'Safe update'})
        self.assertEqual(receipt['revision'], 2)
        self.assertEqual(path.read_text(), FAKE_PROVIDER_TOKEN)

    def test_service_rejects_without_echoing_values_or_logging_them(self):
        value = clean_entry()
        value['approach'] = FAKE_PROVIDER_TOKEN
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = Service().call('record_memory', {'entry': value})
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['error']['type'], 'MemorySensitiveDataError')
        for text in (json.dumps(result), output.getvalue(), errors.getvalue()):
            self.assertNotIn(FAKE_PROVIDER_TOKEN, text)
        self.assertFalse(self.runtime.exists())

    def test_service_format_and_unexpected_errors_omit_input_and_underlying_text(self):
        unknown = 'private-customer-field-' + FAKE_VALUE
        invalid = dict(clean_entry(), **{unknown: 'not a valid knowledge field'})
        result = Service().call('record_memory', {'entry': invalid})
        self.assertEqual(result['status'], 'rejected')
        self.assertNotIn(unknown, json.dumps(result))
        for error in (RuntimeError(FAKE_VALUE), memory.MemoryCorruptionError(FAKE_VALUE),
                      memory.MemoryPersistenceError(FAKE_VALUE, may_have_committed=True)):
            with patch.object(memory, 'record_memory', side_effect=error):
                result = Service().call('record_memory', {'entry': clean_entry()})
            self.assertNotIn(FAKE_VALUE, json.dumps(result))
            self.assertFalse(result['recovery']['automatic_retry'])
        self.assertEqual(result['status'], 'uncertain')

    def test_no_bypass_flag_is_accepted(self):
        result = Service().call('record_memory', {'entry': clean_entry(), 'allow_sensitive': True})
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(self.runtime.exists())

    def test_cli_uses_same_rejection_and_does_not_write_or_echo(self):
        request = self.root / 'request.json'
        entry = clean_entry()
        entry['evidence'] = {'summary': FAKE_PROVIDER_TOKEN}
        request.write_text(json.dumps({'entry': entry}), encoding='utf-8')
        env = dict(os.environ, STARBRIDGE_HOME=str(self.runtime))
        result = subprocess.run([sys.executable, str(ROOT / 'starbridge.py'), 'record_memory',
                                 '--arguments', str(request)], env=env, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['error']['type'], 'MemorySensitiveDataError')
        self.assertNotIn(FAKE_PROVIDER_TOKEN, result.stdout + result.stderr)
        self.assertFalse(self.runtime.exists())

    def test_cli_request_parse_error_omits_sensitive_filename(self):
        request = self.root / (FAKE_PROVIDER_TOKEN + '.json')
        result = subprocess.run([sys.executable, str(ROOT / 'starbridge.py'), 'record_memory',
                                 '--arguments', str(request)], env=dict(os.environ, STARBRIDGE_HOME=str(self.runtime)),
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(FAKE_PROVIDER_TOKEN, result.stdout + result.stderr)
        self.assertFalse(self.runtime.exists())


if __name__ == '__main__':
    unittest.main()
