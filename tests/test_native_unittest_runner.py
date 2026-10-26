"""隔離子程序驗證原生 CI runner 的 spawn、失敗傳遞與逾時。"""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class NativeUnittestRunnerTests(unittest.TestCase):
    def run_fixture(self, body, *, timeout=10):
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, 'test_fixture.py').write_text(textwrap.dedent(body), encoding='utf-8')
            return subprocess.run(
                [sys.executable, '-m', 'tools.run_native_unittest', '--start-directory', temporary,
                 '--timeout', str(timeout)], check=False, capture_output=True, text=True,
                encoding='utf-8', timeout=30)

    def test_spawn_child_reimports_real_main_file(self):
        result = self.run_fixture('''
            import multiprocessing
            import unittest
            def notify(event):
                event.set()
            class Fixture(unittest.TestCase):
                def test_spawn(self):
                    context = multiprocessing.get_context('spawn')
                    event = context.Event()
                    child = context.Process(target=notify, args=(event,))
                    child.start()
                    try:
                        self.assertTrue(event.wait(8))
                        child.join(8)
                        self.assertEqual(child.exitcode, 0)
                    finally:
                        if child.is_alive():
                            child.terminate()
                            child.join()
        ''', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ran 1 test', result.stderr)

    def test_failed_assertion_is_not_converted_to_success(self):
        result = self.run_fixture('''
            import unittest
            class Fixture(unittest.TestCase):
                def test_failure(self):
                    self.fail('fixture_failure')
        ''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('fixture_failure', result.stderr)

    def test_blocked_class_setup_emits_stack_and_exits_nonzero(self):
        result = self.run_fixture('''
            import time
            import unittest
            class Fixture(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    time.sleep(10)
                def test_unreached(self):
                    pass
        ''', timeout=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Timeout', result.stderr)
        self.assertIn('setUpClass', result.stderr)
