"""Exercise actual PyJNIUS overload/varargs and JCE AES, isolated from the UI JVM."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = shutil.which('javac') or str(Path(os.environ.get('JAVA_HOME', '/missing')) / 'bin/javac')


@unittest.skipUnless(importlib.util.find_spec('jnius') and Path(JAVA).is_file(),
                     'Requires PyJNIUS and JDK; Android Keystore provider is tested in emulator')
class AndroidVaultJNI(unittest.TestCase):
    def test_real_varargs_overloads_and_full_byte_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([JAVA, '-d', directory, str(ROOT / 'tests/fixtures/VaultBuilder.java')],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run([sys.executable, str(ROOT / 'tests/fixtures/android_vault_bridge.py'),
                                     str(ROOT), directory], cwd=ROOT, text=True,
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-4000:])
            self.assertIn('roundtrip passed', result.stdout)
