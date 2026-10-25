"""Reviewable feature moves with exact compatibility modules.

Default operation is a dry run. All collisions and rewritten Python syntax are
checked before applying a plan. Git remains the rollback/audit mechanism; this
tool never resets a checkout, rewrites tests or removes user/resource files.
"""
import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path

from tools.architecture.inventory import ROOT, module_name


class MigrationError(ValueError):
    pass


@dataclass(frozen=True)
class Move:
    old_module: str
    new_module: str
    old_path: Path
    new_path: Path
    text: str
    package: bool


def _source(root, module):
    base = root.joinpath(*module.split('.'))
    choices = [path for path in (base.with_suffix('.py'), base / '__init__.py') if path.is_file()]
    if len(choices) != 1:
        raise MigrationError(f'Expected a unique Python source for {module}')
    return choices[0]


def _target(root, module, package=False):
    base = root.joinpath(*module.split('.'))
    return base / '__init__.py' if package else base.with_suffix('.py')


def _mapping_file(root):
    path = root / 'architecture/compatibility.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('modules'), dict):
        raise MigrationError('Unsupported compatibility map')
    return dict(data['modules'])


def _is_compatibility(text):
    doc = ast.get_docstring(ast.parse(text)) or ''
    return doc.startswith('Compatibility import for ')


def _remap(module, mapping):
    choices = [old for old in mapping if module == old or module.startswith(old + '.')]
    if not choices:
        return module
    old = max(choices, key=len)
    return mapping[old] + module[len(old):]


def _absolute_from(node, module, package):
    if not node.level:
        return node.module or ''
    base = module if package else module.rpartition('.')[0]
    parts = base.split('.')
    keep = len(parts) - node.level + 1
    if keep <= 0:
        raise MigrationError(f'Relative import escapes package: {module}')
    return '.'.join(parts[:keep] + ([node.module] if node.module else []))


def _position(lines, offsets, lineno, column):
    # AST columns are UTF-8 byte offsets, while slicing uses Python characters.
    return offsets[lineno - 1] + len(lines[lineno - 1].encode('utf8')[:column].decode('utf8'))


def rewrite_imports(text, module, package, mapping, relative_module=None):
    """Resolve parent imports and relative imports without changing APIs/tests."""
    if _is_compatibility(text):
        return text
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    replacements = []
    for node in ast.walk(tree):
        statements = None
        if isinstance(node, ast.Import):
            values = []
            changed = False
            for item in node.names:
                new = _remap(item.name, mapping)
                if new != item.name and item.asname is None and '.' in item.name:
                    # A bare dotted import also binds a namespace used in code.
                    # Do not silently change that binding with an import-only edit.
                    raise MigrationError(f'Bare dotted import requires a reviewed edit: {module}: {item.name}')
                changed = changed or new != item.name
                values.append(new + (' as ' + item.asname if item.asname else ''))
            if changed:
                statements = ['import ' + ', '.join(values)]
        elif isinstance(node, ast.ImportFrom):
            old_base = _absolute_from(node, relative_module or module, package)
            new_base = _remap(old_base, mapping)
            groups = {}
            changed = new_base != old_base or bool(node.level and relative_module and relative_module != module)
            for item in node.names:
                full = old_base + '.' + item.name
                # Exact module keys distinguish importing a child module from
                # importing a class/function exposed by the parent package.
                if full in mapping:
                    new_full = mapping[full]
                    target_base, _, target_name = new_full.rpartition('.')
                    alias = item.asname or (item.name if target_name != item.name else None)
                    changed = True
                else:
                    target_base, target_name, alias = new_base, item.name, item.asname
                groups.setdefault(target_base, []).append(target_name + (' as ' + alias if alias else ''))
            if changed:
                statements = ['from ' + base + ' import ' + ', '.join(names) for base, names in groups.items()]
        if statements is None:
            continue
        indent = lines[node.lineno - 1][:node.col_offset]
        start = _position(lines, offsets, node.lineno, node.col_offset)
        end = _position(lines, offsets, node.end_lineno, node.end_col_offset)
        replacement = '; '.join(statements) if indent.strip() else ('\n' + indent).join(statements)
        replacements.append((start, end, replacement))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    compile(text, module, 'exec')
    return text


def compatibility_source(move, mapping):
    descendants = sorted((old, new) for old, new in mapping.items()
                         if old.startswith(move.old_module + '.')) if move.package else []
    has_main = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'main'
                   for node in ast.parse(move.text).body)
    lines = [f'"""Compatibility import for {move.old_module}; implementation: {move.new_module}."""',
             'from wlre.compat import alias_module as _alias_module', '']
    if has_main:
        lines += ["if __name__ == '__main__':",
                  f'    from {move.new_module} import main as _main',
                  '    raise SystemExit(_main())', 'else:']
        prefix = '    '
    else:
        prefix = ''
    lines += [prefix + f'_alias_module(__name__, {move.new_module!r}, descendants={descendants!r})', '']
    return '\n'.join(lines)


def plan(root, features):
    root = Path(root).resolve()
    spec = json.loads((root / 'architecture/features.json').read_text(encoding='utf8'))
    mapping = _mapping_file(root)
    moves = []
    selected = []
    for name in dict.fromkeys(features):
        feature = spec['features'].get(name)
        if feature is None:
            raise MigrationError('Unknown feature: ' + name)
        selected.append(name)
        for old_module, new_module in feature['moves'].items():
            if old_module in mapping:
                if mapping[old_module] != new_module:
                    raise MigrationError('Conflicting prior compatibility target: ' + old_module)
                _source(root, new_module)
                continue
            source = _source(root, old_module)
            package = source.name == '__init__.py'
            files = sorted(source.parent.rglob('*.py')) if package else [source]
            for old_path in files:
                if '__pycache__' in old_path.parts:
                    continue
                child_package = old_path.name == '__init__.py'
                old = module_name(old_path.relative_to(root))
                new = new_module + old[len(old_module):]
                target = _target(root, new, child_package)
                if target.exists():
                    raise MigrationError('Target already exists: ' + str(target.relative_to(root)))
                if old in mapping or any(row.new_path == target for row in moves):
                    raise MigrationError('Overlapping move: ' + old)
                text = old_path.read_text(encoding='utf8')
                if _is_compatibility(text):
                    raise MigrationError('Source is already a compatibility entry: ' + old)
                moves.append(Move(old, new, old_path, target, text, child_package))
                mapping[old] = new
    old_paths = {move.old_path for move in moves}
    outputs = {}
    for move in moves:
        outputs[move.new_path] = rewrite_imports(move.text, move.new_module, move.package, mapping,
                                                relative_module=move.old_module)
        outputs[move.old_path] = compatibility_source(move, mapping)
    for path in sorted((root / 'wlre').rglob('*.py')):
        if '__pycache__' in path.parts or path in old_paths:
            continue
        original = path.read_text(encoding='utf8')
        rewritten = rewrite_imports(original, module_name(path.relative_to(root)), path.name == '__init__.py', mapping)
        if rewritten != original:
            outputs[path] = rewritten
    # Parents are explicit normal packages. Distinct docstrings avoid duplicate
    # nonempty Git blobs and identify their ownership in source inventories.
    for path in list(outputs):
        if path not in {move.new_path for move in moves}:
            continue
        parent = path.parent
        while parent != root / 'wlre' and root / 'wlre' in parent.parents:
            init = parent / '__init__.py'
            if not init.exists() and init not in outputs:
                name = module_name(init.relative_to(root))
                outputs[init] = f'"""Feature package {name}."""\n'
            parent = parent.parent
    for path, text in outputs.items():
        compile(text, str(path), 'exec')
    return {'root': root, 'spec': spec, 'features': selected, 'moves': moves,
            'mapping': mapping, 'outputs': outputs}


def apply(planned, mark_implemented=False):
    root = planned['root']
    for path, text in planned['outputs'].items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf8')
    registry = root / 'architecture/compatibility.json'
    registry.write_text(json.dumps({'schema_version': 1,
                                   'modules': dict(sorted(planned['mapping'].items()))}, indent=2) + '\n', encoding='utf8')
    for name in planned['features']:
        planned['spec']['features'][name]['status'] = 'implemented' if mark_implemented else 'migrated'
    (root / 'architecture/features.json').write_text(
        json.dumps(planned['spec'], ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description='規劃或套用功能搬遷，保留原模組相容入口')
    parser.add_argument('--feature', action='append', required=True)
    parser.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--mark-implemented', action='store_true')
    args = parser.parse_args()
    planned = plan(args.root, args.feature)
    summary = {'features': planned['features'], 'moved_modules': len(planned['moves']),
               'rewritten_files': len(planned['outputs']), 'applied': args.apply}
    if args.apply:
        apply(planned, args.mark_implemented)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__': main()
