#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Scotty Wimberley
"""Add SPDX license and copyright headers to every .py file in a project.

Usage:
    python3 tools/add_spdx_headers.py "Your Name <you@example.com>"   # dry run
    python3 tools/add_spdx_headers.py "Your Name <you@example.com>" --apply

Safe to run repeatedly: files that already carry an SPDX tag are skipped.
A shebang line (#!...) and/or a coding line (# -*- coding ...) stay at the
top, with the header inserted just after them.
"""
import argparse
import datetime
import pathlib
import re
import sys

SKIP_DIRS = {".git", ".venv", "venv", "env", "build", "dist",
             "__pycache__", ".pytest_cache", ".mypy_cache", ".tox"}
CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=]")


def header(owner: str, year: int) -> list[str]:
    return [
        "# SPDX-License-Identifier: GPL-3.0-or-later\n",
        f"# Copyright (C) {year} {owner}\n",
    ]


def process(path: pathlib.Path, owner: str, year: int, apply: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if "SPDX-License-Identifier" in text[:2000]:
        return "skip"
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    if len(lines) > insert_at and CODING_RE.match(lines[insert_at]):
        insert_at += 1
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    new = lines[:insert_at] + header(owner, year) + lines[insert_at:]
    if apply:
        path.write_text("".join(new), encoding="utf-8")
    return "add"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("owner", help='copyright holder, e.g. "Jane Doe <jane@example.com>"')
    ap.add_argument("--root", default=".", help="project root (default: current dir)")
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--apply", action="store_true",
                    help="actually modify files (default is a dry run)")
    args = ap.parse_args()

    root = pathlib.Path(args.root).resolve()
    added = skipped = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        result = process(path, args.owner, args.year, args.apply)
        rel = path.relative_to(root)
        if result == "add":
            added += 1
            print(f"{'added  ' if args.apply else 'would add'}  {rel}")
        else:
            skipped += 1
            print(f"skipped    {rel} (already has SPDX tag)")

    print(f"\n{added} file(s) {'updated' if args.apply else 'to update'}, "
          f"{skipped} already tagged.")
    if not args.apply and added:
        print("Dry run only. Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
