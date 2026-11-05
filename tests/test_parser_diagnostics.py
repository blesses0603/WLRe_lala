"""Regression: update diagnostics must never change a parser's verdict."""
import ast
import importlib
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from wlre.services.parser_diagnostics import (
    DiagnosticRun, diagnostic_session, diagnosed, checkpoint,
)
from wlre.services.world.itemdata_v1 import parse_itemdata, ItemDataDecodeError
from wlre.services.world.resource_parser_audit import audit_sources
from test_itemdata_v1 import sample


class ParserDiagnosticsTests(unittest.TestCase):

    def test_1296_versioned_parse_preserves_rows_and_diagnostic_success(self):
        raw = struct.pack('<I', 2) + sample(10) + b'\x00\xff' + sample(11) + b'\x12\x34'
        with tempfile.TemporaryDirectory() as root:
            with patch('wlre.services.world.itemdata_v1.ITEMDATA_1296_SHA256',
                       hashlib.sha256(raw).hexdigest()):
                with diagnostic_session(root):
                    rows = parse_itemdata(raw, package_version='1296_2026_11_04_13_34_19_13')
            self.assertEqual(rows[10]['unknown_tail_1296_hex'], '00ff')
            self.assertEqual(rows[11]['unknown_tail_1296_hex'], '1234')
            report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
            event, = report['parsers']
            self.assertEqual(event['status'], 'passed')
            self.assertEqual(event['record_count'], 2)
            self.assertEqual(event['inputs']['raw']['sha256'], hashlib.sha256(raw).hexdigest())

    def test_1296_truncated_tail_retains_exact_diagnostic_location(self):
        raw = struct.pack('<I', 2) + sample(10) + b'\x00\xff' + sample(11) + b'\x12'
        # Select the synthetic layout so this exercises the reader, not the digest gate.
        with patch('wlre.services.world.itemdata_v1.ITEMDATA_1296_SHA256',
                   hashlib.sha256(raw).hexdigest()):
            with self.assertRaises(ItemDataDecodeError) as caught:
                parse_itemdata(raw, package_version='1296_2026_11_04_13_34_19_13')
        detail = caught.exception.parser_diagnostic
        self.assertEqual(detail['location']['record'], 2)
        self.assertEqual(detail['location']['field'], 'unknown_tail_1296')
        self.assertEqual(detail['location']['offset'], len(raw) - 1)
        self.assertEqual(detail['location']['requested_bytes'], 2)
        self.assertEqual(detail['location']['available_bytes'], 1)

    def test_explicit_legacy_version_keeps_original_record_layout(self):
        raw = struct.pack('<I', 1) + sample()
        rows = parse_itemdata(raw, package_version='1286_2026_10_29_13_42_37_94')
        self.assertEqual(rows, parse_itemdata(raw))
        self.assertNotIn('unknown_tail_1296_hex', rows[39852])

    def test_changed_item_record_fails_with_exact_row_and_offset(self):
        record = sample()
        raw = struct.pack('<I', 2) + record + b'\0\0' + sample(iid=39853)
        with self.assertRaises(ItemDataDecodeError) as caught:
            parse_itemdata(raw)
        detail = caught.exception.parser_diagnostic
        self.assertEqual(detail['location']['record'], 2)
        self.assertEqual(detail['location']['offset'], 4 + len(record))
        self.assertEqual(detail['location']['field'], 'name_length')
        self.assertEqual(detail['location']['actual'], 0)
        self.assertEqual(detail['location']['constraint'], 'nonempty_even_utf16_length')
        self.assertEqual(detail['inputs']['raw']['size'], len(raw))
        self.assertEqual(str(caught.exception), 'Invalid ItemData Unicode byte length')

    def test_failed_update_preserves_previous_success_and_has_no_payload(self):
        with tempfile.TemporaryDirectory() as root:
            good = struct.pack('<I', 1) + sample(name='SECRET_ITEM_NAME')
            with diagnostic_session(root):
                parse_itemdata(good)
            baseline = Path(root) / 'parser_diagnostics' / 'last_success.json'
            before = json.loads(baseline.read_text())
            with diagnostic_session(root):
                try:
                    parse_itemdata(good[:-1])
                except ItemDataDecodeError:
                    pass
            self.assertEqual(before, json.loads(baseline.read_text()))
            report_text = (baseline.parent / 'latest.json').read_text()
            report = json.loads(report_text)
            self.assertNotIn('SECRET_ITEM_NAME', report_text)
            self.assertNotIn(good.hex(), report_text)
            self.assertNotIn(root, report_text)
            self.assertEqual(report['parsers'][0]['comparison'], 'source_changed')
            self.assertIs(report['can_send_packets'], False)
            self.assertIs(report['assets_ready'], False)

    def test_one_bad_table_does_not_hide_other_parser_results(self):
        with tempfile.TemporaryDirectory() as root:
            with diagnostic_session(root):
                result = audit_sources({
                    'ItemData_C': b'bad',
                    'TextData_C': struct.pack('<IIH', 1, 10, 2) + '字'.encode('utf-16le'),
                    'TalkData_C': b'bad',
                })
            self.assertEqual(result['items'], 'failed')
            self.assertEqual(result['talks'], 'failed')
            self.assertEqual(result['texts'], 'passed')
            self.assertEqual(result['daily_tasks'], 'not_available')
            report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
            self.assertEqual(report['coverage'], result)
            self.assertEqual(sum(r['status'] == 'failed' for r in report['parsers']), 2)

    def test_known_smith_layouts_are_selected_without_relaxing_unknown_layout(self):
        from wlre.services.world.smith_candidate import parse_smith_records
        row = struct.pack('<H', 30000) + bytes(31)
        with tempfile.TemporaryDirectory() as root:
            with diagnostic_session(root):
                parse_smith_records(struct.pack('<I', 1) + row)
                parse_smith_records(struct.pack('<IH', 1, 1) + row)
                with self.assertRaises(ValueError):
                    parse_smith_records(struct.pack('<I', 1) + row + b'\0')
            report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
            successes = [r for r in report['parsers'] if r['status'] == 'passed']
            self.assertEqual({r['selected_schema'] for r in successes}, {'smith-33-v1', 'smith-35-v1'})

    def test_known_layout_change_is_compared_with_prior_success(self):
        from wlre.services.world.smith_candidate import parse_smith_records
        row = struct.pack('<H', 30000) + bytes(31)
        with tempfile.TemporaryDirectory() as root:
            with diagnostic_session(root):
                parse_smith_records(struct.pack('<I', 1) + row)
            with diagnostic_session(root):
                parse_smith_records(struct.pack('<IH', 1, 1) + row)
            report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
            event = report['parsers'][0]
            self.assertTrue(event['schema_changed'])
            self.assertEqual(event['size_delta']['data'], 2)
            self.assertEqual(event['record_count_delta'], 0)

    def test_cli_never_reports_missing_or_empty_coverage_as_success(self):
        from contextlib import redirect_stdout
        import io
        from tools.diagnose_parsers import main
        with tempfile.TemporaryDirectory() as root:
            with diagnostic_session(root):
                audit_sources({})
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--root', root]), 2)

    def test_bounded_report_retains_earlier_failure_and_marks_dropped_events(self):
        with tempfile.TemporaryDirectory() as root:
            run = DiagnosticRun(root)
            run.record({'parser': 'failed', 'status': 'failed', 'inputs': {}})
            for i in range(256):
                run.record({'parser': 'passed' + str(i), 'status': 'passed', 'inputs': {}})
            self.assertEqual(len(run.events), 128)
            self.assertTrue(any(r['status'] == 'failed' for r in run.events.values()))
            self.assertEqual(run.dropped_events, 129)

    def test_nested_and_swallowed_failures_and_isolated_sessions(self):
        @diagnosed('test-child-v1')
        def child(raw):
            checkpoint(offset=7, field='header')
            raise ValueError('secret remote response')
        @diagnosed('test-parent-v1')
        def parent(raw):
            try:
                child(raw)
            except ValueError:
                return {'status': 'layout_unrecognized'}
        with tempfile.TemporaryDirectory() as root:
            with diagnostic_session(root):
                with diagnostic_session(root):
                    parent(b'private source')
            report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
            self.assertTrue(all(r['status'] == 'failed' for r in report['parsers']))
            self.assertEqual(len(report['parsers']), 2)
            self.assertNotIn('secret', json.dumps(report))
            with diagnostic_session(root):
                pass
            self.assertEqual(json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())['parsers'], [])

    def test_read_only_output_and_corrupt_baseline_do_not_change_parser(self):
        good = struct.pack('<I', 1) + sample()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'parser_diagnostics'
            directory.mkdir()
            (directory / 'last_success.json').write_text('{"parsers":{"secret":{"inputs":"sensitive"}}}')
            with diagnostic_session(root):
                self.assertEqual(len(parse_itemdata(good)), 1)
            self.assertNotIn('sensitive', (directory / 'latest.json').read_text())
            with patch.object(DiagnosticRun, 'save', side_effect=OSError('read only')):
                with diagnostic_session(root):
                    self.assertEqual(len(parse_itemdata(good)), 1)
                    with self.assertRaises(ItemDataDecodeError):
                        parse_itemdata(good[:-1])

    def test_every_public_official_parser_is_instrumented(self):
        modules = (
            'wlre.services.official_version', 'wlre.services.official_lua_index',
            'wlre.services.instance_catalog', 'wlre.services.expedition.data',
            'wlre.services.world.itemdata_v1', 'wlre.services.world.eve_v115',
            'wlre.services.world.doors_1275', 'wlre.services.world.npc_talk',
            'wlre.services.world.daily_task_1275', 'wlre.services.world.preview_1275',
            'wlre.services.world.smith_candidate', 'wlre.services.world.portal_links_1275',
            'wlre.services.world.portal_schema', 'wlre.services.world.catalog_adapters',
            'wlre.services.world.catalog_source_extractor', 'wlre.services.world.unity_textasset',
            'wlre.services.world.dynamic_bundle_runtime', 'tools.resources.lala_manifest_full_index',
        )
        count = 0
        for name in modules:
            module = importlib.import_module(name)
            tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name.startswith(('parse_', 'derive_', 'extract_', 'inspect_', 'recognize_')):
                    fn = getattr(module, node.name)
                    self.assertTrue(hasattr(fn, 'parser_schema'), name + '.' + node.name)
                    count += 1
        self.assertGreaterEqual(count, 30)

    def test_new_binary_resource_parser_cannot_silently_skip_diagnostics(self):
        root = Path(__file__).resolve().parents[1]
        paths = [*(root / 'wlre/services').rglob('*.py'),
                 *(root / 'tools/resources').glob('*.py')]
        for path in paths:
            for node in ast.parse(path.read_text(encoding='utf-8')).body:
                if not isinstance(node, ast.FunctionDef) or not node.name.startswith(('parse_', 'derive_', 'extract_', 'inspect_')):
                    continue
                args = [a.arg for a in node.args.args + node.args.kwonlyargs]
                if not any(a in args for a in ('raw', 'data', 'body', 'text_data', 'tasks_data', 'npc_data')):
                    continue
                registered = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                                 and d.func.id == 'diagnosed' for d in node.decorator_list)
                self.assertTrue(registered, str(path.relative_to(root)) + ':' + node.name)


if __name__ == '__main__':
    unittest.main()
