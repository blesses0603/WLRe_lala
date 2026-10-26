"""盤點工具不得執行來源，並正確保留相依與未確認動態匯入。"""
import unittest

from tools.rebuild_inventory import analyze, cycles


class InventoryTests(unittest.TestCase):
    def test_relative_imports_resources_and_unknown_dynamic_import(self):
        row = analyze('wlre/example/controller.py', '''
from . import model
from ..core import state
import importlib
importlib.import_module(name)
__import__('wlre.paths')
resource = 'smallmaps.zip'
raise RuntimeError('must never execute')
class Controller:
    def start(self): pass
''')
        self.assertIn('wlre.example.model', row['imports'])
        self.assertIn('wlre.core.state', row['imports'])
        self.assertEqual([i['module'] for i in row['dynamic_imports']], ['UNKNOWN', 'wlre.paths'])
        self.assertEqual(row['resource_references'], ['smallmaps.zip'])
        self.assertEqual(row['symbols'][0]['methods'], ['start'])

    def test_package_relative_import_and_dependency_cycles(self):
        row = analyze('wlre/example/__init__.py', 'from .controller import Controller')
        self.assertIn('wlre.example.controller', row['imports'])
        graph = {'a': {'b'}, 'b': {'a', 'c'}, 'c': set(), 'd': {'d'}}
        self.assertEqual(cycles(graph), [['a', 'b'], ['d']])

    def test_syntax_errors_cannot_be_reported_as_complete(self):
        with self.assertRaises(SyntaxError):
            analyze('wlre/broken.py', 'def broken(')
