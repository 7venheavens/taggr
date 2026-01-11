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

Options:
    --min-confidence FLOAT     Minimum ID extraction confidence (0.0-1.0) [default: 0.5]
    --show-hardlinks-only      Show only hardlinked files
    --show-copies-only         Show only true copy files (wasting space)
    --output-json PATH         Export results to JSON file

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
def main(
    folder_a: Path,
    folder_b: Path,
    min_confidence: float,
    show_hardlinks_only: bool,
    show_copies_only: bool,
    output_json: Path | None,
) -> None:
    """Find duplicate videos between FOLDER_A and FOLDER_B."""
    # Display header
    click.echo("=" * 60)
    click.echo("Video Duplicate Detection")
    click.echo("=" * 60)
    click.echo(f"Folder A: {folder_a}")
    click.echo(f"Folder B: {folder_b}")
    click.echo(f"Min Confidence: {min_confidence}")
    click.echo()

    # Scan and detect duplicates
    detector = DuplicateDetector()
    click.echo("Scanning folders...")
    groups = detector.scan_folders(folder_a, folder_b, min_confidence)

    # Apply filters
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
