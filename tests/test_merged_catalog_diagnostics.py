"""Diagnostics cover merged daily, guild and Ark parsers without changing verdicts."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from wlre.services.parser_diagnostics import diagnostic_session
from wlre.services.world import ark_catalog, daily_task_catalog, guild_catalog
import test_daily_task_runtime
from test_guild_actions import raw_catalogs as guild_sources
from test_star_ark import raw_catalogs as ark_sources


def parser_cases():
    guild = guild_sources()
    ark = ark_sources()
    return (
        (daily_task_catalog.parse_rewards, test_daily_task_runtime.DailyCatalogTests().reward_raw()),
        (guild_catalog.parse_sell, guild['UISellData_C']),
        (guild_catalog.parse_formulas, guild['FormulaData_C']),
        (guild_catalog.parse_organization, guild['OrganizationFunctionData_C']),
        (ark_catalog.parse_stars, ark['ArkStarData_C']),
        (ark_catalog.parse_agents, ark['ArkAgentData_C']),
        (ark_catalog.parse_fights, ark['ArkFightData_C']),
    )


class MergedCatalogDiagnosticsTests(unittest.TestCase):
    def test_successful_parsers_record_counts_and_preserve_results(self):
        for parser, raw in parser_cases():
            with self.subTest(parser=parser.__name__), tempfile.TemporaryDirectory() as root:
                expected = parser.__wrapped__(raw)
                with diagnostic_session(root):
                    self.assertEqual(parser(raw), expected)
                report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
                event, = report['parsers']
                self.assertEqual(event['parser'], parser.__module__ + '.' + parser.__name__)
                self.assertEqual(event['status'], 'passed')
                self.assertEqual(event['record_count'], len(expected))
                self.assertEqual(event['inputs']['raw'],
                                 dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
                self.assertFalse(report['assets_ready'])
                self.assertFalse(report['can_send_packets'])

    def test_bad_sources_keep_exception_and_success_baseline(self):
        for parser, raw in parser_cases():
            with self.subTest(parser=parser.__name__), tempfile.TemporaryDirectory() as root:
                with diagnostic_session(root):
                    parser(raw)
                directory = Path(root) / 'parser_diagnostics'
                baseline = (directory / 'last_success.json').read_bytes()
                for malformed in (raw[:-2], raw + b'!'):
                    with self.subTest(size=len(malformed)):
                        with self.assertRaises(ValueError) as original:
                            parser.__wrapped__(malformed)
                        with diagnostic_session(root):
                            with self.assertRaises(type(original.exception)) as caught:
                                parser(malformed)
                        self.assertEqual(str(caught.exception), str(original.exception))
                        self.assertEqual((directory / 'last_success.json').read_bytes(), baseline)
                        report_text = (directory / 'latest.json').read_text()
                        report = json.loads(report_text)
                        event, = report['parsers']
                        self.assertEqual(event['status'], 'failed')
                        self.assertEqual(event['error_type'], type(original.exception).__name__)
                        self.assertEqual(event['inputs']['raw']['size'], len(malformed))
                        self.assertIn('offset', event['location'])
                        self.assertNotIn('message', event)
                        self.assertNotIn('traceback', event)
                        self.assertNotIn(malformed.hex(), report_text)
                        self.assertNotIn(root, report_text)

    def test_both_ark_fight_layouts_emit_one_success_despite_internal_probes(self):
        for tail in (False, True):
            raw = ark_sources(tail)['ArkFightData_C']
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as root:
                with diagnostic_session(root):
                    rows = ark_catalog.parse_fights(raw)
                self.assertEqual('opaque_flag' in rows[1], tail)
                report = json.loads((Path(root) / 'parser_diagnostics/latest.json').read_text())
                event, = report['parsers']
                self.assertEqual(event['status'], 'passed')
                self.assertEqual(event['record_count'], 1)


if __name__ == '__main__':
    unittest.main()
