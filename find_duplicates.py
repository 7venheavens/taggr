#!/usr/bin/env python3
"""
Find duplicate video files across two directories.

This script compares video files from two folders by extracting video IDs
(e.g., FC2-PPV-123456, MIDE-123) and detecting whether files are hardlinked
or true copies wasting disk space.

Usage:
    python find_duplicates.py <folder_a> <folder_b> [OPTIONS]

Examples:
    # Basic comparison
    python find_duplicates.py /media/original /media/organized

    # Show only space-wasting copies
    python find_duplicates.py /media/original /media/organized --show-copies-only

    # Export results to JSON
    python find_duplicates.py /media/original /media/organized --output-json report.json

    # Adjust confidence threshold
    python find_duplicates.py /media/original /media/organized --min-confidence 0.75

    # Fix duplicates by removing copies from Folder B/destination (interactive)
    python find_duplicates.py /media/original /media/organized --fix

    # Fix duplicates with auto-confirmation
    python find_duplicates.py /media/original /media/organized --fix --confirm

Options:
    --min-confidence FLOAT     Minimum ID extraction confidence (0.0-1.0) [default: 0.5]
    --show-hardlinks-only      Show only hardlinked files
    --show-copies-only         Show only true copy files (wasting space)
    --output-json PATH         Export results to JSON file
    --fix                      Remove duplicate copies from Folder B/destination
    --confirm                  Auto-confirm all deletions (use with --fix)

Output:
    The script displays duplicate groups with:
    - Video ID extracted from filename/folder
    - Hardlink status (✓ HARDLINK, ❌ COPY, or MIXED)
    - File paths and sizes
    - Total space wasted by true copies

Understanding Results:
    - HARDLINK: Files share same inode, no space wasted
    - COPY: Files are separate copies, wasting disk space
    - MIXED: Some files hardlinked, some copied

Environment:
    Designed for Linux + NFS environments where inode detection is reliable.
"""

import json
from pathlib import Path

import click

from taggrr.core.duplicate_detector import DuplicateDetector, DuplicateGroup


def format_size(bytes_count: int) -> str:
    """Format bytes as human-readable size."""
    size = float(bytes_count)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def display_groups(groups: list[DuplicateGroup]) -> None:
    """Display duplicate groups with formatting."""
    if not groups:
        click.echo("No duplicate groups found.")
        return

    for idx, group in enumerate(groups, 1):
        click.echo()
        click.echo("=" * 60)
        click.echo(f"Duplicate Group #{idx}: {group.video_id}")
        click.echo("=" * 60)

        # Status line
        status_symbol = "✓" if group.status == "HARDLINK" else "❌"
        status_text = group.status
        wasted = format_size(group.wasted_space)

        if group.wasted_space > 0:
            click.echo(f"Status: {status_symbol} {status_text} (wasting {wasted})")
        else:
            click.echo(f"Status: {status_symbol} {status_text} (no space wasted)")

        click.echo(f"Confidence: {group.confidence:.0%} ({group.source_type.value})")
        click.echo()

        # Folder A files
        click.echo("Folder A:")
        for file_a in group.folder_a_files:
            size = format_size(file_a.file_size or 0)
            click.echo(f"  • {file_a.file_path} ({size})")

        # Folder B file
        click.echo()
        click.echo("Folder B:")
        size = format_size(group.folder_b_file.file_size or 0)
        click.echo(f"  • {group.folder_b_file.file_path} ({size})")


def display_summary(
    groups: list[DuplicateGroup], folder_a: Path, folder_b: Path
) -> None:
    """Display summary statistics."""
    click.echo()
    click.echo("=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)

    total_groups = len(groups)
    hardlink_groups = sum(1 for g in groups if g.status == "HARDLINK")
    copy_groups = sum(1 for g in groups if g.status == "COPY")
    mixed_groups = sum(1 for g in groups if g.status == "MIXED")
    total_wasted = sum(g.wasted_space for g in groups)

    click.echo(f"Total duplicate groups: {total_groups}")
    click.echo(f"  - Hardlinks: {hardlink_groups} (no space wasted)")
    click.echo(f"  - True copies: {copy_groups} (wasting space)")
    click.echo(f"  - Mixed: {mixed_groups}")
    click.echo()
    click.echo(f"Total space wasted by copies: {format_size(total_wasted)}")


def export_json(groups: list[DuplicateGroup], output_path: Path) -> None:
    """Export results to JSON file."""
    data = {
        "duplicate_groups": [
            {
                "video_id": g.video_id,
                "confidence": g.confidence,
                "source_type": g.source_type.value,
                "status": g.status,
                "folder_a_files": [str(f.file_path) for f in g.folder_a_files],
                "folder_b_file": str(g.folder_b_file.file_path),
                "wasted_space_bytes": g.wasted_space,
            }
            for g in groups
        ]
    }

    output_path.write_text(json.dumps(data, indent=2))
    click.echo(f"\nResults exported to: {output_path}")


def fix_duplicates(
    groups: list[DuplicateGroup], auto_confirm: bool = False
) -> tuple[int, int]:
    """
    Remove duplicate copies from Folder B (keeps hardlinks).

    Only deletes files from Folder B that are true copies (not hardlinked)
    of files in Folder A. Hardlinked files are preserved as they don't
    waste space.

    Args:
        groups: List of duplicate groups to process
        auto_confirm: If True, skip confirmation prompts

    Returns:
        Tuple of (files_deleted, space_freed_bytes)
    """
    files_deleted = 0
    space_freed = 0

    # Filter to only groups with true copies
    copy_groups = [g for g in groups if g.has_copies]

    if not copy_groups:
        click.echo("\nNo duplicate copies found to fix.")
        return (0, 0)

    click.echo()
    click.echo("=" * 60)
    click.echo("FIX MODE: Remove duplicate copies from Folder B")
    click.echo("=" * 60)
    hardlink_only_count = len(
        [g for g in groups if g.has_hardlinks and not g.has_copies]
    )
    click.echo(
        f"Found {len(copy_groups)} groups with true copies "
        f"(skipping {hardlink_only_count} hardlink groups)"
    )
    click.echo()

    for idx, group in enumerate(copy_groups, 1):
        # Only process if there are copy pairs (not hardlinked)
        if not group.copy_pairs:
            continue

        click.echo(f"\nGroup {idx}/{len(copy_groups)}: {group.video_id}")
        click.echo(f"Status: {group.status}")
        click.echo(f"Potential space savings: {format_size(group.wasted_space)}")
        click.echo()

        # Show what will be deleted (folder B file if it's a copy)
        folder_b_path = group.folder_b_file.file_path
        folder_b_size = group.folder_b_file.file_size or 0

        click.echo("Will DELETE from Folder B:")
        click.echo(f"  • {folder_b_path} ({format_size(folder_b_size)})")
        click.echo()
        click.echo("Will KEEP in Folder A:")
        for file_a in group.folder_a_files:
            click.echo(f"  • {file_a.file_path}")

        # Confirm deletion
        if auto_confirm:
            click.echo("\n[Auto-confirmed]")
            confirmed = True
        else:
            click.echo()
            confirmed = click.confirm(
                "Delete this file from Folder B?", default=False
            )

        if confirmed:
            try:
                folder_b_path.unlink()
                files_deleted += 1
                space_freed += folder_b_size
                click.echo(
                    click.style("✓ Deleted successfully", fg="green")
                )
            except Exception as e:
                click.echo(
                    click.style(f"✗ Error deleting: {e}", fg="red")
                )
        else:
            click.echo(click.style("Skipped", fg="yellow"))

    return (files_deleted, space_freed)


@click.command()
@click.argument("folder_a", type=click.Path(exists=True, path_type=Path))
@click.argument("folder_b", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--min-confidence",
    default=0.5,
    type=float,
    help="Minimum ID extraction confidence (0.0-1.0)",
)
@click.option(
    "--show-hardlinks-only", is_flag=True, help="Show only hardlinked files"
)
@click.option(
    "--show-copies-only",
    is_flag=True,
    help="Show only true copy files (wasting space)",
)
@click.option(
    "--output-json", type=click.Path(path_type=Path), help="Export results to JSON file"
)
@click.option(
    "--fix",
    is_flag=True,
    help="Remove duplicate copies from Folder B/destination",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Auto-confirm all deletions (use with --fix)",
)
def main(
    folder_a: Path,
    folder_b: Path,
    min_confidence: float,
    show_hardlinks_only: bool,
    show_copies_only: bool,
    output_json: Path | None,
    fix: bool,
    confirm: bool,
) -> None:
    """Find duplicate videos between FOLDER_A and FOLDER_B."""
    # Validate options
    if confirm and not fix:
        click.echo("Error: --confirm can only be used with --fix")
        return

    # Display header
    click.echo("=" * 60)
    click.echo("Video Duplicate Detection")
    click.echo("=" * 60)
    click.echo(f"Folder A (source): {folder_a}")
    click.echo(f"Folder B (destination): {folder_b}")
    click.echo(f"Min Confidence: {min_confidence}")
    if fix:
        mode = "FIX MODE (auto-confirm)" if confirm else "FIX MODE (interactive)"
        click.echo(f"Mode: {mode}")
    click.echo()

    # Scan and detect duplicates
    detector = DuplicateDetector()
    click.echo("Scanning folders...")
    groups = detector.scan_folders(folder_a, folder_b, min_confidence)

    # If in fix mode, process immediately
    if fix:
        files_deleted, space_freed = fix_duplicates(groups, auto_confirm=confirm)

        # Display final summary
        click.echo()
        click.echo("=" * 60)
        click.echo("FIX SUMMARY")
        click.echo("=" * 60)
        click.echo(f"Files deleted: {files_deleted}")
        click.echo(f"Space freed: {format_size(space_freed)}")
        return

    # Apply filters for display mode
    if show_hardlinks_only:
        groups = [g for g in groups if g.has_hardlinks]
    elif show_copies_only:
        groups = [g for g in groups if g.has_copies]

    # Display results
    display_groups(groups)
    display_summary(groups, folder_a, folder_b)

    # Export if requested
    if output_json:
        export_json(groups, output_json)


if __name__ == "__main__":
    main()
