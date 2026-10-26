"""對指定 Git 快照進行唯讀 AST 盤點，不匯入或執行受分析程式。"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import subprocess
from collections import Counter
from pathlib import Path


def module_name(path):
    parts = Path(path).with_suffix('').parts
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def analyze(path, source):
    tree = ast.parse(source, filename=path)
    module = module_name(path)
    package = module if Path(path).name == '__init__.py' else module.rpartition('.')[0]
    imports, dynamic, resources, symbols = set(), [], set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = '.' * node.level + (node.module or '')
            resolved = importlib.util.resolve_name(name, package) if node.level else name
            imports.add(resolved)
            imports.update(resolved + '.' + alias.name for alias in node.names if alias.name != '*')
        elif isinstance(node, ast.Call):
            func = node.func
            if ((isinstance(func, ast.Name) and func.id == '__import__') or
                    (isinstance(func, ast.Attribute) and func.attr == 'import_module')):
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    dynamic.append({'line': node.lineno, 'module': arg.value})
                else:
                    dynamic.append({'line': node.lineno, 'module': 'UNKNOWN'})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if (len(value) < 180 and '\n' not in value and
                    value.endswith(('.zip', '.json', '.json.gz', '.bytes', '.bundle', '.png', '.ico'))):
                resources.add(value)
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            row = {'name': node.name, 'line': node.lineno, 'kind': type(node).__name__}
            if isinstance(node, ast.ClassDef):
                row['methods'] = [child.name for child in node.body if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef))]
            symbols.append(row)
    return {'path': path, 'module': module, 'lines': len(source.splitlines()),
            'sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'imports': sorted(imports), 'dynamic_imports': dynamic,
            'resource_references': sorted(resources), 'symbols': symbols}


def cycles(graph):
    """Tarjan 強連通分量；函式內延遲匯入仍列為待審查相依，非執行期斷言。"""
    indexes, low, stack, active, found = {}, {}, [], set(), []

    def visit(node):
        indexes[node] = low[node] = len(indexes)
        stack.append(node)
        active.add(node)
        for target in sorted(graph.get(node, ())):
            if target not in indexes:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in active:
                low[node] = min(low[node], indexes[target])
        if low[node] == indexes[node]:
            component = []
            while True:
                item = stack.pop()
                active.remove(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1 or node in graph.get(node, ()):
                found.append(sorted(component))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return sorted(found)


def inventory(root, ref):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root)

    commit = git('rev-parse', '--verify', ref + '^{commit}').decode().strip()
    paths = git('ls-tree', '-r', '--name-only', '-z', commit).decode().split('\0')
    python_paths = sorted(p for p in paths if p.endswith('.py'))
    files = [analyze(path, git('show', commit + ':' + path).decode('utf-8-sig'))
             for path in python_paths]
    known = {row['module'] for row in files}
    graph = {}
    for row in files:
        dependencies = set()
        for imported in row['imports']:
            while imported and imported not in known:
                imported = imported.rpartition('.')[0]
            if imported and imported != row['module']:
                dependencies.add(imported)
        row['dependencies'] = sorted(dependencies)
        graph[row['module']] = dependencies
    tests = [row for row in files if row['path'].startswith('tests/')]
    for row in files:
        row['direct_test_importers'] = [test['path'] for test in tests
                                        if row['module'] in test['dependencies']]
    counts = Counter(row['path'].split('/')[0] for row in files)
    return {'schema': 1, 'source_commit': commit, 'python_files': len(files),
            'counts': dict(sorted(counts.items())),
            'lines': sum(row['lines'] for row in files),
            'static_dependency_cycles': cycles(graph), 'files': files,
            'limitations': ['AST 含延遲匯入，循環須人工判讀；非執行期追蹤',
                            '直接測試匯入非完整覆蓋率；動態載入另外列出',
                            '資源字串僅作候選引用，不代表來源驗證通過']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='origin/main')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = inventory(Path(__file__).resolve().parents[1], args.ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('source_commit', 'python_files', 'counts', 'lines')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
