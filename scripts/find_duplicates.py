#!/usr/bin/env python3
"""
Find duplicate video files across a source directory and one or more target directories.

This script compares video files by extracting video IDs from filenames/folders
(e.g., FC2-PPV-123456, MIDE-123) and optionally by SHA256 hash. It detects
whether files are hardlinked (same inode/file-ID) or true copies wasting disk
space. When fixing duplicates the source directory is always kept; non-source
copies are replaced with hardlinks to the source file.

Usage:
    python find_duplicates.py <source> <target1> [<target2> ...] [OPTIONS]

Examples:
    # Basic comparison (name matching only)
    python find_duplicates.py /media/original /media/organized

    # Compare against multiple target directories
    python find_duplicates.py /media/original /media/lib1 /media/lib2

    # Also match by size + SHA256 hash (finds ID-less duplicates too)
    python find_duplicates.py /media/original /media/organized --content-match

    # Show only space-wasting copies
    python find_duplicates.py /media/original /media/organized --show-copies-only

    # Export results to JSON
    python find_duplicates.py /media/original /media/organized --output-json report.json

    # Fix duplicates by replacing copies with hardlinks (interactive)
    python find_duplicates.py /media/original /media/organized --fix

    # Fix with auto-confirmation
    python find_duplicates.py /media/original /media/organized --fix --confirm

Options:
    --min-confidence FLOAT  Minimum ID extraction confidence (0.0-1.0) [default: 0.5]
    --content-match         Also match by file size + SHA256 hash
    --show-hardlinks-only   Show only hardlinked files
    --show-copies-only      Show only true copy files (wasting space)
    --output-json PATH      Export results to JSON file
    --fix                   Replace copies in targets with hardlinks to source
    --confirm               Auto-confirm all operations (use with --fix)

Understanding Results:
    - HARDLINK:   Files share the same underlying data, no space wasted
    - COPY:       Files are separate copies, wasting disk space
    - MIXED:      Some pairs hardlinked, some copied
    - NO_SOURCE:  No file from source dir in this set; cannot auto-fix

Match Types:
    - [NAME]:         Matched by video ID extracted from filename/folder
    - [CONTENT]:      Matched by file size + SHA256 hash only
    - [NAME+CONTENT]: Matched by both name and content (highest confidence)
"""

import json
from pathlib import Path

import click

from taggrr.core.duplicate_detector import DuplicateDetector, DuplicateSet


def format_size(bytes_count: int) -> str:
    """Format bytes as human-readable size."""
    size = float(bytes_count)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _match_badge(match_type: str) -> str:
    badges = {
        "name": "[NAME]",
        "content": "[CONTENT]",
        "name+content": "[NAME+CONTENT]",
    }
    return badges.get(match_type, f"[{match_type.upper()}]")


def display_groups(groups: list[DuplicateSet], source_dir: Path) -> None:
    """Display duplicate sets with formatting."""
    if not groups:
        click.echo("No duplicate sets found.")
        return

    source_dir_r = source_dir.resolve()

    for idx, group in enumerate(groups, 1):
        click.echo()
        click.echo("=" * 60)

        if group.video_id:
            header = f"Duplicate Set #{idx}: {group.video_id}"
        else:
            header = f"Duplicate Set #{idx}: <content match>"
        click.echo(header)
        click.echo("=" * 60)

        # Status + match type
        status_symbol = "✓" if group.status == "HARDLINK" else "❌"
        wasted = format_size(group.wasted_space)
        badge = _match_badge(group.match_type)

        if group.wasted_space > 0:
            click.echo(
                f"Status: {status_symbol} {group.status}  {badge}  (wasting {wasted})"
            )
        else:
            click.echo(
                f"Status: {status_symbol} {group.status}  {badge}  (no space wasted)"
            )

        if group.confidence is not None:
            click.echo(f"Confidence: {group.confidence:.0%}")
        if group.file_hash:
            click.echo(f"Hash: {group.file_hash[:16]}...")

        click.echo()

        # Files per directory, sorted so source is first
        dirs = sorted(
            group.files_by_dir.keys(), key=lambda d: (d != source_dir_r, str(d))
        )
        for d in dirs:
            label = "Source" if d == source_dir_r else "Target"
            click.echo(f"{label}: {d}")
            for f in group.files_by_dir[d]:
                size = format_size(f.file_size or 0)
                is_source = (
                    group.source_file is not None
                    and f.file_path == group.source_file.file_path
                )
                star = " ★" if is_source else ""

                # Annotate hardlink/copy status per file
                pair_status = ""
                if group.source_file and not is_source:
                    in_hl = any(
                        f.file_path == b.file_path for _, b in group.hardlink_pairs
                    )
                    in_cp = any(
                        f.file_path == b.file_path for _, b in group.copy_pairs
                    )
                    if in_hl:
                        pair_status = "  [hardlink]"
                    elif in_cp:
                        pair_status = "  [copy]"

                click.echo(f"  • {f.file_path} ({size}){star}{pair_status}")


def display_summary(
    groups: list[DuplicateSet],
    source_dir: Path,
    target_dirs: list[Path],
) -> None:
    """Display summary statistics."""
    click.echo()
    click.echo("=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)
    click.echo(f"Source:  {source_dir}")
    for d in target_dirs:
        click.echo(f"Target:  {d}")
    click.echo()

    total = len(groups)
    by_status = {
        s: sum(1 for g in groups if g.status == s)
        for s in ("HARDLINK", "COPY", "MIXED", "NO_SOURCE")
    }
    by_match = {
        m: sum(1 for g in groups if g.match_type == m)
        for m in ("name", "content", "name+content")
    }
    total_wasted = sum(g.wasted_space for g in groups)

    click.echo(f"Total duplicate sets: {total}")
    click.echo(f"  Hardlinks:  {by_status['HARDLINK']} (no space wasted)")
    click.echo(f"  Copies:     {by_status['COPY']} (wasting space)")
    click.echo(f"  Mixed:      {by_status['MIXED']}")
    if by_status["NO_SOURCE"]:
        click.echo(f"  No source:  {by_status['NO_SOURCE']} (cannot auto-fix)")
    click.echo()
    click.echo(
        f"Match types:  name={by_match['name']}"
        f"  content={by_match['content']}"
        f"  both={by_match['name+content']}"
    )
    click.echo()
    click.echo(f"Total space wasted by copies: {format_size(total_wasted)}")


def export_json(
    groups: list[DuplicateSet],
    output_path: Path,
    source_dir: Path,
    target_dirs: list[Path],
) -> None:
    """Export results to JSON file."""
    data = {
        "source_dir": str(source_dir),
        "target_dirs": [str(d) for d in target_dirs],
        "duplicate_sets": [
            {
                "video_id": g.video_id,
                "match_type": g.match_type,
                "confidence": g.confidence,
                "source_type": g.source_type.value if g.source_type else None,
                "file_size": g.file_size,
                "file_hash": g.file_hash,
                "status": g.status,
                "source_file": str(g.source_file.file_path) if g.source_file else None,
                "files_by_dir": {
                    str(d): [str(f.file_path) for f in files]
                    for d, files in g.files_by_dir.items()
                },
                "hardlink_pairs": [
                    [str(a.file_path), str(b.file_path)] for a, b in g.hardlink_pairs
                ],
                "copy_pairs": [
                    [str(a.file_path), str(b.file_path)] for a, b in g.copy_pairs
                ],
                "wasted_space_bytes": g.wasted_space,
            }
            for g in groups
        ],
    }
    output_path.write_text(json.dumps(data, indent=2))
    click.echo(f"\nResults exported to: {output_path}")


def fix_duplicates(
    groups: list[DuplicateSet],
    auto_confirm: bool = False,
) -> tuple[int, int]:
    """
    Replace non-source copies with hardlinks to the source file.

    For each duplicate set that has true copies (not hardlinked), the source
    file is kept intact and every non-source copy is:
      1. Size-verified against the source
      2. Deleted
      3. Replaced with a hardlink to the source

    Args:
        groups: List of duplicate sets to process.
        auto_confirm: If True, skip per-group confirmation prompts.

    Returns:
        Tuple of (files_fixed, space_freed_bytes).
    """
    files_fixed = 0
    space_freed = 0

    copy_groups = [g for g in groups if g.has_copies and g.source_file is not None]
    skipped_no_source = sum(1 for g in groups if g.status == "NO_SOURCE")

    if not copy_groups:
        click.echo("\nNo fixable duplicate copies found.")
        if skipped_no_source:
            click.echo(
                click.style(
                    f"  ({skipped_no_source} sets skipped: no source file present)",
                    fg="yellow",
                )
            )
        return (0, 0)

    click.echo()
    click.echo("=" * 60)
    click.echo("FIX MODE: Replace copies with hardlinks to source")
    click.echo("=" * 60)
    already_ok = len([g for g in groups if g.has_hardlinks and not g.has_copies])
    click.echo(
        f"Found {len(copy_groups)} sets with copies to fix "
        f"(skipping {already_ok} already-hardlinked)"
    )
    if skipped_no_source:
        click.echo(
            click.style(
                f"Skipping {skipped_no_source} sets with no source file",
                fg="yellow",
            )
        )

    for idx, group in enumerate(copy_groups, 1):
        source_file = group.source_file
        assert source_file is not None  # guaranteed by filter above

        click.echo()
        label = group.video_id or "<content match>"
        click.echo(f"Group {idx}/{len(copy_groups)}: {label}")
        click.echo(f"  Source: {source_file.file_path}")
        click.echo(f"  Potential savings: {format_size(group.wasted_space)}")
        click.echo()

        for _src, copy_file in group.copy_pairs:
            copy_path = copy_file.file_path
            copy_size = copy_file.file_size or 0

            # Size check
            try:
                actual_src_size = source_file.file_path.stat().st_size
                actual_copy_size = copy_path.stat().st_size
                if actual_src_size != actual_copy_size:
                    click.echo(
                        click.style(
                            f"  ⚠ Size mismatch, skipping: {copy_path}",
                            fg="red",
                            bold=True,
                        )
                    )
                    click.echo(f"    Source: {format_size(actual_src_size)}, "
                               f"Copy: {format_size(actual_copy_size)}")
                    continue
            except OSError as e:
                click.echo(click.style(f"  ✗ Cannot stat file: {e}", fg="red"))
                continue

            click.echo(f"  Will replace: {copy_path} ({format_size(copy_size)})")
            click.echo(f"    → hardlink to: {source_file.file_path}")

            if auto_confirm:
                click.echo("  [Auto-confirmed]")
                confirmed = True
            else:
                confirmed = click.confirm("  Replace with hardlink?", default=False)

            if confirmed:
                try:
                    copy_path.unlink()
                    copy_path.hardlink_to(source_file.file_path)
                    files_fixed += 1
                    space_freed += copy_size
                    click.echo(click.style("  ✓ Done", fg="green"))
                except OSError as e:
                    click.echo(click.style(f"  ✗ Error: {e}", fg="red"))
            else:
                click.echo(click.style("  Skipped", fg="yellow"))

    return (files_fixed, space_freed)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.argument(
    "targets", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--min-confidence",
    default=0.5,
    type=float,
    help="Minimum ID extraction confidence (0.0-1.0)",
)
@click.option(
    "--content-match",
    is_flag=True,
    help="Also match by file size + SHA256 hash",
)
@click.option(
    "--show-hardlinks-only", is_flag=True, help="Show only hardlinked sets"
)
@click.option(
    "--show-copies-only",
    is_flag=True,
    help="Show only sets with true copies (wasting space)",
)
@click.option(
    "--output-json", type=click.Path(path_type=Path), help="Export results to JSON file"
)
@click.option(
    "--fix",
    is_flag=True,
    help="Replace copies in targets with hardlinks to source",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Auto-confirm all operations (use with --fix)",
)
def main(
    source: Path,
    targets: tuple[Path, ...],
    min_confidence: float,
    content_match: bool,
    show_hardlinks_only: bool,
    show_copies_only: bool,
    output_json: Path | None,
    fix: bool,
    confirm: bool,
) -> None:
    """Find duplicate videos between SOURCE and one or more TARGET directories."""
    target_dirs = list(targets)

    # Validate option combinations
    if confirm and not fix:
        click.echo("Error: --confirm can only be used with --fix")
        return
    if fix and (show_hardlinks_only or show_copies_only):
        click.echo(
            "Error: --show-hardlinks-only/--show-copies-only cannot be used with --fix"
        )
        return

    # Header
    click.echo("=" * 60)
    click.echo("Video Duplicate Detection")
    click.echo("=" * 60)
    click.echo(f"Source:          {source}")
    for d in target_dirs:
        click.echo(f"Target:          {d}")
    click.echo(f"Min confidence:  {min_confidence}")
    click.echo(f"Content match:   {'yes' if content_match else 'no'}")
    if fix:
        mode = "FIX (auto-confirm)" if confirm else "FIX (interactive)"
        click.echo(f"Mode:            {mode}")
    click.echo()

    # Scan
    detector = DuplicateDetector()
    click.echo("Scanning directories...")
    groups = detector.scan_multiple(
        source,
        target_dirs,
        min_confidence=min_confidence,
        content_match=content_match,
    )

    # Always show groups and summary first (even in fix mode).
    # Pure-HARDLINK sets are hidden by default (already optimal, not actionable).
    # The summary always reflects all sets so counts are complete.
    if show_hardlinks_only:
        display_groups([g for g in groups if g.has_hardlinks], source)
    elif show_copies_only:
        display_groups([g for g in groups if g.has_copies], source)
    else:
        actionable = [g for g in groups if g.status != "HARDLINK"]
        display_groups(actionable, source)
        hidden = len(groups) - len(actionable)
        if hidden:
            click.echo(
                f"({hidden} hardlinked set(s) not shown — already optimal;"
                " use --show-hardlinks-only to view them)"
            )

    display_summary(groups, source, target_dirs)

    # Export JSON if requested
    if output_json:
        export_json(groups, output_json, source, target_dirs)

    # Fix mode
    if fix:
        if not confirm:
            click.echo()
            if not click.confirm("Proceed with fixing the above sets?", default=False):
                click.echo("Aborted.")
                return

        files_fixed, space_freed = fix_duplicates(groups, auto_confirm=confirm)

        click.echo()
        click.echo("=" * 60)
        click.echo("FIX SUMMARY")
        click.echo("=" * 60)
        click.echo(f"Files fixed:  {files_fixed}")
        click.echo(f"Space freed:  {format_size(space_freed)}")


if __name__ == "__main__":
    main()
