"""Exercise the actual workflow preflight with a local fake GitHub CLI."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Preflight runs on Linux bash')
class ReleasePreflightTests(unittest.TestCase):
    def run_preflight(self, tag, tag_result='0', release_result='1'):
        workflow = (ROOT / '.github/workflows/release-windows.yml').read_text(encoding='utf8')
        step = workflow.split('      - name: Check tag format, existence and previous release\n', 1)[1]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1].split('\n  build:', 1)[0])
        fake_gh = '''gh() {
          printf '%s\\n' "$*" >> "$GH_CALLS"
          if [[ "$2" == */git/ref/tags/* ]]; then return "$TAG_RESULT"; fi
          return "$RELEASE_RESULT"
        }
'''
        with tempfile.TemporaryDirectory(prefix='release test ') as directory:
            output = Path(directory) / 'output'
            calls = Path(directory) / 'calls'
            env = dict(os.environ, REQUESTED_TAG=tag, TAG_RESULT=tag_result,
                       RELEASE_RESULT=release_result, GITHUB_REPOSITORY='fixture/repo',
                       GITHUB_OUTPUT=str(output), GH_CALLS=str(calls))
            result = subprocess.run(['bash', '-e', '-c', fake_gh + script], env=env,
                                    text=True, capture_output=True, timeout=10)
            return result, output.read_text() if output.exists() else '', calls.read_text() if calls.exists() else ''

    def test_existing_unreleased_tag_is_forwarded(self):
        result, output, calls = self.run_preflight('v1.2.3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'tag=v1.2.3\n')
        self.assertEqual(len(calls.splitlines()), 2)

    def test_wrong_format_fails_before_any_remote_request(self):
        for tag in ('Ver.0.4.20', '0.4.20', 'main', 'v1.2.3/other'):
            result, output, calls = self.run_preflight(tag)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('vX.Y.Z', result.stdout)
            self.assertEqual((output, calls), ('', ''))

    def test_missing_tag_reports_problem_without_starting_build(self):
        result, output, calls = self.run_preflight('v1.2.3', tag_result='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not exist', result.stdout)
        self.assertEqual(output, '')
        self.assertEqual(len(calls.splitlines()), 1)

    def test_published_tag_is_not_rebuilt(self):
        result, output, _ = self.run_preflight('v1.2.3', release_result='0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stdout)
        self.assertEqual(output, '')
