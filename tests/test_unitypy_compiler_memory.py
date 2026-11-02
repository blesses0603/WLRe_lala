"""The C1002 workaround must retain classes instead of excluding the decoder."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from tools.build import build_nuitka

ROOT = Path(__file__).resolve().parents[1]


class UnityPyCompilerMemoryTests(unittest.TestCase):
    def test_only_generated_module_uses_bytecode_and_other_modules_keep_default(self):
        # Normal source tests need no Nuitka install. Model its documented base
        # interface; real build invocations also load this plugin through Nuitka.
        base = ModuleType('nuitka.plugins.PluginBase')
        base.NuitkaPluginBase = type('NuitkaPluginBase', (), {})
        spec = importlib.util.spec_from_file_location(
            'wlre_compiler_plugin_test', ROOT / 'tools/build/unitypy_nuitka_plugin.py')
        plugin_module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'nuitka.plugins.PluginBase': base}):
            spec.loader.exec_module(plugin_module)
        plugin = plugin_module.UnityPyGeneratedBytecodePlugin()
        self.assertEqual(plugin.decideCompilation('UnityPy.classes.generated'), 'bytecode')
        for name in ('UnityPy', 'UnityPy.classes', 'UnityPy.classes.ClassIDTypeToClassMap',
                     'UnityPy.classes.generated_extra', 'lz4.block', 'wlre'):
            with self.subTest(name=name):
                self.assertIsNone(plugin.decideCompilation(name))

    def test_standalone_and_onefile_keep_decoder_and_load_memory_workaround(self):
        for mode in ('standalone', 'onefile'):
            with self.subTest(mode=mode):
                command = build_nuitka.make_command('python', mode=mode, compiler='msvc')
                plugins = [x.split('=', 1)[1] for x in command if x.startswith('--user-plugin=')]
                self.assertEqual(plugins, [str(ROOT / 'tools/build/unitypy_nuitka_plugin.py')])
                self.assertTrue(Path(plugins[0]).is_file())
                self.assertIn('--include-package=UnityPy', command)
                self.assertIn('--include-package-data=UnityPy', command)
                self.assertFalse(any('nofollow-import-to=UnityPy' in x for x in command))


if __name__ == '__main__':
    unittest.main()
