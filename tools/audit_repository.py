"""Offline, read-only repository hygiene checks (no network or game login).

Usage: python -m tools.audit_repository
Checks local Markdown links and exact duplicate *nonempty* tracked blobs.
Zero-byte package __init__.py files are intentionally shared by Git.
"""
from collections import defaultdict
import argparse
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?(?:\\[[^\\]]*\\])\\(([^)]+)\\)")
VERSION = re.compile(r"^__version__\\s*=\\s*(['\\\"])([^'\\\"]+)\\1", re.MULTILINE)


def markdown_files(root=ROOT):
    """Only tracked project prose; do not traverse build venvs or generated output."""
    return [root / "README.md", root / "版本歷史.md", *sorted((root / "docs").rglob("*.md"))]


def invalid_links(root=ROOT):
    root = root.resolve()
    broken = []
    examined = 0
    for document in markdown_files(root):
        if not document.is_file():
            broken.append(f"{document.relative_to(root)}: missing document")
            continue
        content = document.read_text(encoding="utf-8")
        for match in LINK.finditer(content):
            target = match.group(1).strip().split(None, 1)[0].strip("<>")
            if not target or target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            # Local links may refer to another document's fragment.
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if not clean:
                continue
            examined += 1
            path = (document.parent / clean).resolve()
            if not path.is_relative_to(root) or not path.exists():
                broken.append(f"{document.relative_to(root)}: {target}")
    return examined, broken


def duplicate_tracked_blobs(root=ROOT):
    """Do not hash large archives again: the Git index already has blob IDs."""
    if not shutil.which("git") or not (root / ".git").exists():
        return None
    result = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root,
                            capture_output=True, check=True)
    by_sha = defaultdict(list)
    for entry in result.stdout.split(b"\\0"):
        if not entry:
            continue
        info, filename = entry.split(b"\\t", 1)
        parts = info.split(b" ")
        if len(parts) != 3 or parts[2] != b"0":
            continue
        by_sha[parts[1].decode("ascii")].append(filename.decode("utf-8"))
    duplicates = []
    for sha, paths in by_sha.items():
        if len(paths) <= 1:
            continue
        size = subprocess.run(["git", "cat-file", "-s", sha], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
        if int(size) > 0:
            duplicates.append(sorted(paths))
    return sorted(duplicates)


def application_version(root=ROOT):
    text = (root / "wlre" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION.search(text)
    if not match:
        raise ValueError("wlre/__init__.py lacks a literal __version__")
    return match.group(2)


def audit(root=ROOT):
    checked, broken = invalid_links(root)
    duplicates = duplicate_tracked_blobs(root)
    version = application_version(root)
    return {
        "application_version": version,
        "markdown_files": len(markdown_files(root)),
        "local_links_checked": checked,
        "broken_local_links": broken,
        "nonempty_duplicate_blobs": duplicates,
        "git_index_available": duplicates is not None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="WLRe:LaLa offline repository audit")
    parser.add_argument("--strict-git", action="store_true", help="require Git index for duplicate checks")
    args = parser.parse_args(argv)
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result["broken_local_links"] or result["nonempty_duplicate_blobs"]
                    or (args.strict_git and not result["git_index_available"])))


if __name__ == "__main__":
    raise SystemExit(main())
