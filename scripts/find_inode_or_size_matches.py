#!/usr/bin/env python3
"""
Find files under a directory that match a reference file by inode and/or size.

Usage:
    python scripts/find_inode_or_size_matches.py /path/to/file /path/to/search_root
    python scripts/find_inode_or_size_matches.py /path/to/file /path/to/search_root --size-only
    python scripts/find_inode_or_size_matches.py /path/to/file /path/to/search_root --inode-only
"""

from __future__ import annotations

import argparse
from pathlib import Path


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def find_matches(
    reference_file: Path,
    search_dir: Path,
    check_inode: bool,
    check_size: bool,
) -> list[tuple[Path, bool, bool]]:
    ref_stat = reference_file.stat()
    ref_inode = ref_stat.st_ino
    ref_size = ref_stat.st_size

    matches: list[tuple[Path, bool, bool]] = []
    for candidate in search_dir.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            st = candidate.stat()
        except OSError:
            continue

        inode_match = check_inode and st.st_ino == ref_inode
        size_match = check_size and st.st_size == ref_size
        if inode_match or size_match:
            matches.append((candidate, inode_match, size_match))

    return matches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find files matching a reference file by inode and/or file size."
    )
    parser.add_argument("reference_file", type=Path, help="Reference file path")
    parser.add_argument("search_dir", type=Path, help="Directory to scan recursively")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--inode-only",
        action="store_true",
        help="Only report inode matches",
    )
    group.add_argument(
        "--size-only",
        action="store_true",
        help="Only report file-size matches",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    reference_file: Path = args.reference_file
    search_dir: Path = args.search_dir

    if not reference_file.is_file():
        print(f"Error: reference file not found or not a file: {reference_file}")
        return 1
    if not search_dir.is_dir():
        print(f"Error: search directory not found or not a directory: {search_dir}")
        return 1

    check_inode = not args.size_only
    check_size = not args.inode_only

    ref_stat = reference_file.stat()
    print(f"Reference: {reference_file}")
    print(f"Inode:     {ref_stat.st_ino}")
    print(f"Size:      {format_size(ref_stat.st_size)} ({ref_stat.st_size} bytes)")
    print(f"Search:    {search_dir}")
    print()

    matches = find_matches(reference_file, search_dir, check_inode, check_size)
    if not matches:
        print("No matches found.")
        return 0

    # Stable ordering for predictable output
    matches.sort(key=lambda m: str(m[0]))

    print(f"Found {len(matches)} match(es):")
    for path, inode_match, size_match in matches:
        flags = []
        if inode_match:
            flags.append("inode")
        if size_match:
            flags.append("size")
        print(f"  - {path}  [{'+'.join(flags)}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
