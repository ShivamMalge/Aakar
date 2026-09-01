"""Prove the API key is not in anything that leaves this machine. ``python -m aakar.evals.keyscan``

Structural reasoning about why a credential *cannot* leak is worth having, and is not the
same as looking. This looks — for the literal value, in every place a commit, a push or a
shared artefact could carry it.

**It never prints the key.** Every match is reported by file and offset only, and the value
is redacted out of any excerpt. A leak-detector that prints the leak is not a detector.

Five checks, each answering a different question:

1. ``.env`` is ignored *by a rule git can name*, not merely absent from `git status`.
2. No **commit** in the repository's whole history contains it.
3. No **cassette** contains it — the one that matters, because recording actually happened.
4. No **working-tree file** contains it, cassettes aside: evidence, logs, notes.
5. The generic key-shaped scan still passes, catching a *different* key someone else added.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

#: Shapes worth flagging even when they are not *our* key: someone else's, or a second one
#: added later. Check 5 is the only one that can catch a credential this module was never
#: told about.
KEY_SHAPES = (
    re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(rb"sk-[A-Za-z0-9]{32,}"),
    re.compile(rb"ghp_[A-Za-z0-9]{36}"),
)

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".next",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "out",
}

#: Never scanned for the literal value, because it is where the value legitimately lives.
ALLOWED_TO_HOLD_IT = {".env"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def read_key(root: Path) -> str:
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("AAKAR_API_KEY"):
            return line.split("=", 1)[1].split("  #")[0].strip().strip('"').strip("'")
    raise SystemExit("no AAKAR_API_KEY in .env; nothing to scan for")


def walk(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in ALLOWED_TO_HOLD_IT:
            continue
        yield path


def _git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def check_gitignored(root: Path, out: TextIO) -> bool:
    rule = _git(root, "check-ignore", "-v", ".env").strip()
    if rule:
        print(f"  1. .env ignored by {rule.split(chr(9))[0]}", file=out)
        return True
    print("  1. FAIL - .env is NOT ignored by any rule", file=out)
    return False


def check_history(root: Path, key: str, out: TextIO) -> bool:
    """Search every commit, not just HEAD. A key removed in a later commit is still pushed."""
    commits = _git(root, "rev-list", "--all").split()
    found = _git(root, "grep", "-l", "-F", key, *commits) if commits else ""
    if found.strip():
        print(f"  2. FAIL - the key appears in {len(found.splitlines())} tracked blob(s)", file=out)
        return False
    print(f"  2. absent from all {len(commits)} commits", file=out)
    return True


def _scan(paths: Iterator[Path], key: bytes, root: Path) -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    for path in paths:
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        offset = blob.find(key)
        if offset >= 0:
            hits.append((path.relative_to(root), offset))
    return hits


def check_cassettes(root: Path, key: str, out: TextIO) -> bool:
    """The check that matters once recording has actually happened."""
    cassettes = list((root / "services" / "api" / "tests" / "cassettes").rglob("*.json"))
    hits = _scan(iter(cassettes), key.encode(), root)
    if hits:
        for path, offset in hits:
            print(f"  3. FAIL - {path} at byte {offset}", file=out)
        return False
    print(f"  3. absent from all {len(cassettes)} cassette files", file=out)
    return True


def check_working_tree(root: Path, key: str, out: TextIO) -> bool:
    hits = _scan(walk(root), key.encode(), root)
    if hits:
        for path, offset in hits:
            print(f"  4. FAIL - {path} at byte {offset}", file=out)
        return False
    print("  4. absent from every working-tree file (.env excepted)", file=out)
    return True


def check_key_shapes(root: Path, out: TextIO) -> bool:
    """Catches a credential this module was never told about — someone else's, or a second
    one added later. The only check that does not depend on knowing the value."""
    offenders: list[str] = []
    for path in walk(root):
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        for shape in KEY_SHAPES:
            if shape.search(blob):
                offenders.append(str(path.relative_to(root)))
                break
    if offenders:
        for name in offenders:
            print(f"  5. FAIL - key-shaped string in {name}", file=out)
        return False
    print("  5. no key-shaped string anywhere in the working tree", file=out)
    return True


def main(out: TextIO = sys.stdout) -> int:
    root = repo_root()
    key = read_key(root)
    print("API key exposure scan", file=out)
    print("=" * 21, file=out)
    print(f"  scanning for a {len(key)}-character value (never printed)", file=out)
    results = [
        check_gitignored(root, out),
        check_history(root, key, out),
        check_cassettes(root, key, out),
        check_working_tree(root, key, out),
        check_key_shapes(root, out),
    ]
    print(file=out)
    print("ALL CLEAR" if all(results) else "EXPOSURE FOUND - do not push", file=out)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
