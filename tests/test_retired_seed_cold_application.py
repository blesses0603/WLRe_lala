"""Real App entry in a fresh source/data copy, no retired seed or game network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RetiredSeedColdApplicationTests(unittest.TestCase):
    def test_real_offline_cold_entry_without_navigation_seed(self):
        import tkinter as tk
        try:root=tk.Tk()
        except tk.TclError as error:self.skipTest(str(error))
        root.update();root.destroy()
        from tools.isolated_navigation_trial import prepare
        source=Path(__file__).resolve().parents[1]
        self.assertFalse((source/'wlre/resources/resource_catalog_seed.sqlite3').exists())
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);snapshot=base/'snapshot';snapshot.mkdir()
            # The UI cold-entry check does not consume a catalog snapshot or fake Runtime.
            for name in ('current-identity.json','current-stages.json'):
                (snapshot/name).write_text('{}')
            workspace=base/'isolated';prepare(workspace,snapshot)
            self.assertFalse((workspace/'source/wlre/resources/resource_catalog_seed.sqlite3').exists())
            result=subprocess.run([sys.executable,'-B','-m','tools.check_isolated_application',
                '--workspace',str(workspace),'--platform','desktop'],cwd=source,
                env={**os.environ,'WLRE_DISABLE_AUTO_CATALOG':'1'},capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout[-5000:]+result.stderr[-5000:])
            report=json.loads((workspace/'cold-start.json').read_text())
            self.assertFalse(report['seed_present'])
            self.assertEqual(report['legacy_navigation_reads'],0)
            self.assertFalse(report['actual_game_login'])
            self.assertFalse(report['can_send_packets'])
            self.assertTrue(report['observations']['dashboard_mapped'])
            self.assertTrue(report['observations']['startup_checks_completed'])
            self.assertFalse(report['observations']['official_login_verified'])
            self.assertTrue(report['observations']['preview_safe_stop'])
