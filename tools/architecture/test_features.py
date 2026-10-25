"""Module CI entry point; the full three-platform workflow remains mandatory."""
import argparse
import json
from pathlib import Path
import sys
import unittest

from tools.architecture.inventory import ROOT, config, owner, scan


def selected_tests(features, document=None, spec=None):
    spec = spec or config()
    document = document or scan()
    if any(name not in spec['features'] for name in features):
        raise ValueError('Unknown feature')
    selected = {'test_feature_architecture'}
    shared = [prefix for name in features for prefix in spec['features'][name].get('shared', [])]
    modules = [row for row in document['python_files'] if row['path'].startswith('wlre/')]
    affected = {row['module'] for row in modules if owner(row['module'], spec) in features
                or any(row['module'].startswith(prefix) for prefix in shared)}
    # Include consumers transitively: a guild change exercised through State,
    # or a panel exercised through App, must not disappear from module CI.
    while True:
        consumers = {row['module'] for row in modules
                     if any(dependency == module or dependency.startswith(module + '.')
                            for dependency in row['imports'] for module in affected)}
        if consumers <= affected: break
        affected.update(consumers)
    for row in document['python_files']:
        if not row['path'].startswith('tests/test_'): continue
        if (any(owner(dependency, spec) in features for dependency in row['imports'])
                or any(dependency.startswith(prefix) for dependency in row['imports'] for prefix in shared)
                or any(dependency == module or dependency.startswith(module + '.')
                       for dependency in row['imports'] for module in affected)):
            selected.add(Path(row['path']).stem)
    return sorted(selected)


def main():
    parser = argparse.ArgumentParser(description='執行功能回歸；共享層／最終驗收請使用 all')
    parser.add_argument('--feature', action='append', choices=['all', *config()['features']], required=True)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if 'all' in args.feature:
        names = sorted(path.stem for path in (ROOT / 'tests').glob('test_*.py'))
    else:
        names = selected_tests(args.feature)
    print(json.dumps({'features': args.feature, 'test_modules': names}, ensure_ascii=False), flush=True)
    if args.list: return
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun == 0: raise SystemExit('No tests executed')
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__': main()
