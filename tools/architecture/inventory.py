"""Read every Python source; inventory feature owners and static dependencies.

Imports, literal patch points and resource references are static evidence;
runtime-computed resource names are explicitly not a deletion authorization.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def config(root=ROOT):
    return json.loads((root / 'architecture/features.json').read_text(encoding='utf8'))


def module_name(path):
    parts = list(path.with_suffix('').parts)
    if parts[-1] == '__init__': parts.pop()
    return '.'.join(parts)


def owner(module, spec):
    for name in spec['features']:
        if module.startswith('wlre.features.' + name + '.') or module == 'wlre.features.' + name:
            return name
    choices = [(len(prefix), name) for name, feature in spec['features'].items()
               for prefix in feature['moves'] if module == prefix or module.startswith(prefix + '.')]
    return max(choices)[1] if choices else 'shared'


def imports(tree, module, package=False):
    found = set()
    base = module if package else module.rpartition('.')[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ''
            if node.level:
                parts = base.split('.')
                prefix = '.'.join(parts[:len(parts) - node.level + 1] + ([prefix] if prefix else []))
            found.add(prefix)
            found.update(prefix + '.' + alias.name for alias in node.names if alias.name != '*')
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Include mock.patch and deferred import strings as dependencies.
            found.update(re.findall(r'\bwlre(?:\.[A-Za-z_][A-Za-z_0-9]*)+', node.value))
    return sorted(value for value in found if value)


def scan(root=ROOT):
    spec = config(root)
    resource_files = sorted(p.relative_to(root / 'wlre/resources').as_posix()
                            for p in (root / 'wlre/resources').rglob('*') if p.is_file())
    records = []
    for base in ('wlre', 'tests', 'tools'):
        for path in sorted((root / base).rglob('*.py')):
            if '__pycache__' in path.parts: continue
            text = path.read_text(encoding='utf8')
            tree = ast.parse(text, filename=str(path))
            relative = path.relative_to(root)
            module = module_name(relative)
            literals = {node.value for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            resources = sorted(name for name in resource_files
                               if name in literals or Path(name).name in literals)
            records.append({'path': relative.as_posix(), 'module': module, 'owner': owner(module, spec),
                            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'lines': len(text.splitlines()),
                            'imports': imports(tree, module, path.name == '__init__.py'),
                            'resources': resources,
                            'definitions': [node.name for node in tree.body
                                            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))],
                            'compatibility_entry': 'Compatibility import' in ast.get_docstring(tree) if ast.get_docstring(tree) else False})
    consumers = {name: [row['module'] for row in records if name in row['resources']] for name in resource_files}
    return {'schema_version': 1, 'baseline': spec['baseline'], 'python_files': records,
            'resources': [{'path': name, 'consumers': consumers[name],
                           'migration': 'retain_pending_equivalence_and_all_consumer_migration',
                           'deletion_authorized': False} for name in resource_files],
            'static_analysis_limit': 'Computed imports/resource names and live E2E require separate review.'}


def write_report(root=ROOT):
    document = scan(root)
    target = root / 'architecture/inventory.json'
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    spec = config(root)
    lines = ['# 全功能模組盤點與執行順序', '',
             '基準：最新 main `14af2ff`、PR #57 `cb9e9a77`；版本維持 v0.6.1。',
             '本報告由 `python -m tools.architecture.inventory` 讀取所有 Python 原始碼與測試產生。',
             '完整 import、定義、資源引用與來源 SHA 見 [inventory.json](../architecture/inventory.json)。', '',
             '| 階段 | 功能 | 原始碼歸屬數 | 來源遷移規則 |', '| --- | --- | ---: | --- |']
    for name, feature in sorted(spec['features'].items(), key=lambda pair: pair[1]['phase']):
        count = sum(row['owner'] == name for row in document['python_files'])
        lines.append(f"| {feature['phase']} | {feature['title']} (`{name}`) | {count} | 優先官方 Runtime；未證等價保留舊檔 |")
    lines += ['', '共享層保留 network、State／事件、排程、資源驗證與下載、路徑與原子儲存、',
              'UI 主執行緒／主視窗組裝、共用圖片快取及多功能安全規則。', '',
              '## 完整 Python 模組歸屬', '', '| 路徑 | 歸屬 | 直接依賴數 | 資源引用數 |',
              '| --- | --- | ---: | ---: |']
    for row in document['python_files']:
        lines.append(f"| `{row['path']}` | {row['owner']} | {len(row['imports'])} | {len(row['resources'])} |")
    lines += ['', '## 驗收與資源移除界線', '',
              '- 每個功能經舊入口／新入口相容測試與對應模組回歸；共享邊界變更執行完整回歸。',
              '- 官方來源延續現有 `.version`／`.bytes`／`.hash`、Bundle MD5／CRC、固定 SHA 與 Runtime；不新增手動 ZIP 前置要求。',
              '- 所有現存資源本輪先保留。靜態零引用不能證明所有消費者已遷移，也不能代替地圖／導航等價與乾淨安裝驗收。',
              '- GitHub 三平台 CI、正式服 E2E、原生 EXE 打包分別記錄；未執行者不標示通過。',
              '- PR #57 尚未合併：開發分支以其 head 為依賴，PR 先以該分支為 base，合併後再調整 main；保留 cb9e9a77。', '']
    (root / 'docs/FEATURE_INVENTORY.md').write_text('\n'.join(lines), encoding='utf8')
    return document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        saved = json.loads((ROOT / 'architecture/inventory.json').read_text(encoding='utf8'))
        if scan() != saved: raise SystemExit('Feature inventory is stale; run tools.architecture.inventory')
    else:
        result = write_report()
        print(json.dumps({'python_files': len(result['python_files']), 'resources': len(result['resources'])}))


if __name__ == '__main__': main()
