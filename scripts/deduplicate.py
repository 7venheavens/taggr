#!/usr/bin/env python3
"""
Hardlink Duplicates Script

Compares two directories (source and dest), matches files by filesize + partial
hash (first 1 MB), and identifies files that are duplicates but not hardlinks.
By default runs in dry-run mode; pass --execute to actually replace copies with
hardlinks.

Usage:
    python hardlink_duplicates.py <source_dir> <dest_dir> [--execute]

Arguments:
    source_dir: Source directory to scan
    dest_dir:   Destination directory to scan
    --execute:  Actually replace duplicate dest files with hardlinks (default: dry-run)
"""

import argparse
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path

MIN_FILE_SIZE = 100 * 1024 * 1024  # 100 MB floor
PARTIAL_HASH_SIZE = 1 * 1024 * 1024  # 1 MB for quick identity check


class FileInfo:
    """Information about a file for comparison."""

    def __init__(self, path: Path, origin: str):
        self.path = path
        self.origin = origin  # "source" or "dest"
        stat = path.stat()
        self.size = stat.st_size
        self.inode = stat.st_ino
        self.dev = stat.st_dev
        self._partial_hash: str | None = None

    def partial_hash(self) -> str:
        """Compute MD5 of the first PARTIAL_HASH_SIZE bytes (lazy, cached)."""
        if self._partial_hash is None:
            h = hashlib.md5()
            with open(self.path, "rb") as f:
                h.update(f.read(PARTIAL_HASH_SIZE))
            self._partial_hash = h.hexdigest()
        return self._partial_hash

    def is_hardlink_to(self, other: "FileInfo") -> bool:
        return self.dev == other.dev and self.inode == other.inode

    def __repr__(self) -> str:
        return f"FileInfo({self.path}, size={self.size}, inode={self.inode}, origin={self.origin})"


def scan_directories(dirs: list[tuple[Path, str]]) -> dict[int, list[FileInfo]]:
    """
    Scan multiple directories into a single size-keyed dict.

    Args:
        dirs: List of (directory, origin_label) pairs

    Returns:
        Dict mapping file size to list of FileInfo objects (only files >= MIN_FILE_SIZE)
    """
    files_by_size: dict[int, list[FileInfo]] = defaultdict(list)

    for directory, origin in dirs:
        print(f"Scanning [{origin}] {directory}...")
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                filepath = Path(root) / filename
                try:
                    if not filepath.is_file():
                        continue
                    fi = FileInfo(filepath, origin)
                    if fi.size < MIN_FILE_SIZE:
                        continue
                    files_by_size[fi.size].append(fi)
                except (OSError, PermissionError) as e:
                    print(f"Warning: Cannot access {filepath}: {e}", file=sys.stderr)

    return files_by_size


def find_duplicate_groups(
    files_by_size: dict[int, list[FileInfo]],
) -> list[list[FileInfo]]:
    """
    Find groups of files that share size + partial hash but are not all hardlinked.

    Returns:
        List of duplicate groups; each group contains >= 2 FileInfo objects
        that are confirmed duplicates and at least one pair is not yet hardlinked.
    """
    duplicate_groups: list[list[FileInfo]] = []

    candidate_sizes = {
        size: files for size, files in files_by_size.items() if len(files) >= 2
    }
    n = len(candidate_sizes)
    print(f"\nFound {n} size bucket(s) with 2+ files — computing partial hashes...")

    for size, files in sorted(candidate_sizes.items()):
        by_hash: dict[str, list[FileInfo]] = defaultdict(list)
        for fi in files:
            try:
                by_hash[fi.partial_hash()].append(fi)
            except (OSError, PermissionError) as e:
                print(f"Warning: Cannot hash {fi.path}: {e}", file=sys.stderr)

        for phash, group in by_hash.items():
            if len(group) < 2:
                continue
            # Skip if every file is already hardlinked to group[0]
            if all(group[0].is_hardlink_to(f) for f in group[1:]):
                continue
            duplicate_groups.append(group)

    return duplicate_groups


def pick_canonical(group: list[FileInfo]) -> FileInfo:
    """
    Choose the canonical file to keep.  Prefer source-origin; break ties by
    shortest absolute path (a rough proxy for "less nested = more authoritative").
    """
    source_files = [f for f in group if f.origin == "source"]
    candidates = source_files if source_files else group
    return min(candidates, key=lambda f: len(str(f.path)))


def replace_with_hardlink(source: FileInfo, dest: FileInfo) -> bool:
    """
    Replace dest file with a hardlink to source file (atomic via temp file).

    Returns True on success, False on error.
    Raises OSError if files are on different filesystems.
    """
    if source.dev != dest.dev:
        raise OSError(
            f"Cannot create hardlink across different filesystems: "
            f"{source.path} (dev={source.dev}) -> {dest.path} (dev={dest.dev})"
        )

    temp_path = dest.path.with_suffix(dest.path.suffix + ".hardlink_tmp")
    try:
        os.link(source.path, temp_path)
        temp_path.replace(dest.path)
        return True
    except OSError as e:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"Error creating hardlink: {e}", file=sys.stderr)
        return False


def format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Identify duplicate files (size + 1 MB hash) and optionally replace "
            "dest copies with hardlinks. Default: dry-run."
        )
    )
    parser.add_argument("source_dir", type=Path, help="Source directory")
    parser.add_argument("dest_dir", type=Path, help="Destination directory")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually replace duplicate files with hardlinks (default: dry-run)",
    )
    args = parser.parse_args()

    for label, d in [("source_dir", args.source_dir), ("dest_dir", args.dest_dir)]:
        if not d.is_dir():
            print(f"Error: {label} does not exist: {d}", file=sys.stderr)
            sys.exit(1)

    if not args.execute:
        print("** DRY-RUN mode — pass --execute to apply changes **\n")

    print("=" * 80)
    files_by_size = scan_directories(
        [
            (args.source_dir, "source"),
            (args.dest_dir, "dest"),
        ]
    )

    print("=" * 80)
    duplicate_groups = find_duplicate_groups(files_by_size)

    if not duplicate_groups:
        print("\nNo duplicate non-hardlinked files found.")
        return

    # Display findings
    print("=" * 80)
    print(f"\nFound {len(duplicate_groups)} duplicate group(s):\n")

    total_replaceable = 0
    for group in duplicate_groups:
        canonical = pick_canonical(group)
        phash = canonical.partial_hash()
        prefix = phash[:16]
        size_str = format_size(canonical.size)
        print(f"[DUPLICATE GROUP] {size_str} | hash prefix: {prefix}...")
        for fi in group:
            tag = "[SOURCE]" if fi.origin == "source" else "[DEST]  "
            marker = " <- canonical" if fi is canonical else " <- will be replaced"
            if fi.is_hardlink_to(canonical):
                marker = " <- already hardlinked"
            print(f"  {tag} {fi.path}  (inode {fi.inode}){marker}")
            if fi is not canonical and not fi.is_hardlink_to(canonical):
                total_replaceable += fi.size
        print()

    print(f"Total space recoverable: {format_size(total_replaceable)}")
    print("=" * 80)

    if not args.execute:
        print("\nDry-run complete. Pass --execute to apply hardlinks.")
        return

    # Perform replacements
    print("\nReplacing files with hardlinks...")
    success_count = 0
    failed_count = 0
    space_saved = 0

    for group in duplicate_groups:
        canonical = pick_canonical(group)
        for fi in group:
            if fi is canonical or fi.is_hardlink_to(canonical):
                continue
            print(f"  {fi.path.name} ...", end=" ")
            try:
                if replace_with_hardlink(canonical, fi):
                    print("OK")
                    success_count += 1
                    space_saved += fi.size
                else:
                    print("FAILED")
                    failed_count += 1
            except OSError as e:
                print(f"ERROR: {e}")
                failed_count += 1

    print("=" * 80)
    print("\nCompleted:")
    print(f"  Successfully hardlinked: {success_count}")
    print(f"  Failed:                  {failed_count}")
    if space_saved:
        print(f"  Space reclaimed:         {format_size(space_saved)}")


if __name__ == "__main__":
    main()
