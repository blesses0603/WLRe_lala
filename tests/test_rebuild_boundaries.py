"""新核心相依契約：純標準庫、無平台／GUI 引用、沒有靜態循環。"""
import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

from tools.rebuild_inventory import analyze, cycles

ROOT = Path(__file__).resolve().parents[1]
CORE_PATHS = ('wlre/core/application', 'wlre/core/events')


class CoreBoundariesTests(unittest.TestCase):
    def test_new_core_imports_only_itself_and_standard_library(self):
        paths = [ROOT / 'wlre/core/primitives.py']
        for directory in CORE_PATHS:
            paths.extend((ROOT / directory).rglob('*.py'))
        records = [analyze(str(path.relative_to(ROOT)), path.read_text(encoding='utf-8'))
                   for path in paths]
        known = {record['module'] for record in records}
        graph = {}
        for record in records:
            dependencies = set()
            self.assertEqual(record['dynamic_imports'], [], record['path'])
            for name in record['imports']:
                if name.split('.')[0] == 'wlre':
                    target = name
                    while target not in known and '.' in target:
                        target = target.rpartition('.')[0]
                    self.assertIn(target, known, (record['path'], name))
                    if target != record['module']:
                        dependencies.add(target)
                else:
                    self.assertIn(name.split('.')[0], sys.stdlib_module_names, (record['path'], name))
                    self.assertNotIn(name.split('.')[0], ('tkinter', 'ctypes', 'winreg'))
            # 不允許用 __import__ 或 eval 規避靜態相依規則。
            tree = ast.parse((ROOT / record['path']).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ('eval', 'exec', '__import__'))
            graph[record['module']] = dependencies
        self.assertEqual(cycles(graph), [])

    def test_import_does_not_initialize_desktop_or_legacy_game_services(self):
        code = '''
import json, sys
from wlre.core.application import Application
app = Application()
app.initialize(); app.start(); app.stop()
print(json.dumps(sorted(name for name in sys.modules if name.split('.')[0] in
    ('tkinter', 'PIL', 'UnityPy', 'ctypes') or name.startswith(('wlre.ui', 'wlre.services', 'wlre.network')))))
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), [])
