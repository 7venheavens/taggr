"""Command-line interface."""

import asyncio
from pathlib import Path
from typing import Optional

import click

from ..config.settings import load_config
from ..core.analyzer import NameAnalyzer
from ..core.processor import VideoProcessor
from ..core.scanner import VideoScanner


@click.command()
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory (defaults to input directory for in-place organization)",
)
@click.option("--link", is_flag=True, help="Create hardlinks instead of moving files")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Custom configuration file",
)
@click.option(
    "--folder-priority",
    type=float,
    metavar="0.0-1.0",
    help="Weight for folder name matching (0.0-1.0)",
)
@click.option(
    "--source-preference",
    type=click.Choice(["fc2", "dmm"]),
    help="Prefer specific video source",
)
@click.option(
    "--review-mode", is_flag=True, help="Enable manual review for all matches"
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without making changes"
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(
    input_path: Path,
    output_dir: Path | None,
    link: bool,
    config: Path | None,
    folder_priority: float | None,
    source_preference: str | None,
    review_mode: bool,
    dry_run: bool,
    verbose: bool,
):
    """Process video files with intelligent name analysis for Plex compatibility.

    INPUT_PATH: Directory containing video files to process

    By default, files will be organized in-place within the input directory.
    Use --output-dir to specify a different output location.
    """
    try:
        # Load configuration
        settings = load_config(config)

        # Set output directory (default to input directory for in-place organization)
        output_path = output_dir if output_dir else input_path

        # Set processing mode based on CLI flags
        from ..core.models import ProcessingMode

        if link:
            processing_mode = ProcessingMode.HARDLINK
        else:
            processing_mode = ProcessingMode.INPLACE

        # Apply CLI overrides
        if folder_priority is not None:
            if not 0.0 <= folder_priority <= 1.0:
                click.echo(
                    "Error: folder-priority must be between 0.0 and 1.0", err=True
                )
                return
            settings.matching.name_analysis.folder_weight = folder_priority
            settings.matching.name_analysis.file_weight = 1.0 - folder_priority
            click.echo(f"Setting folder priority to {folder_priority}")

        if source_preference:
            settings.source_detection.global_preference = source_preference
            click.echo(f"Setting source preference to {source_preference}")

        # Configure logging
        import logging

        if verbose:
            settings.log_level = "DEBUG"
            logging.basicConfig(level=logging.DEBUG)
            click.echo("Verbose logging enabled")
        else:
            logging.basicConfig(level=logging.INFO)

        if dry_run:
            click.echo("DRY RUN MODE - No changes will be made")

        click.echo(f"Scanning: {input_path}")
        click.echo(f"Output: {output_path}")

        # Initialize components
        scanner = VideoScanner()
        analyzer = NameAnalyzer(
            folder_weight=settings.matching.name_analysis.folder_weight,
            file_weight=settings.matching.name_analysis.file_weight,
            context_boost=settings.matching.name_analysis.context_boost,
        )

        # Process files
        video_files = scanner.scan_directory(input_path)
        video_groups = scanner.group_videos(video_files)
        click.echo(
            f"Found {len(video_files)} video file(s) in {len(video_groups)} group(s)"
        )

        # Run the complete processing pipeline
        processor = VideoProcessor(settings, processing_mode=processing_mode)

        if not dry_run:
            click.echo(f"\nProcessing {len(video_groups)} group(s)...")
            if processing_mode == ProcessingMode.HARDLINK:
                click.echo("Using hardlinks to avoid copying large files")
            elif output_dir:
                click.echo(f"Moving files to: {output_path}")
            else:
                click.echo("Organizing files in-place")
        else:
            click.echo(
                f"\nDRY RUN: Planning processing for {len(video_groups)} group(s)..."
            )

        # Run async processing
        results = asyncio.run(
            processor.process_groups(video_groups, output_path, dry_run)
        )

        # Display results
        click.echo(f"\n{'=' * 60}")
        click.echo("PROCESSING RESULTS")
        click.echo(f"{'=' * 60}")

        for result in results:
            status_icon = {
                "success": "[SUCCESS]",
                "failed": "[FAILED]",
                "skipped": "[SKIPPED]",
                "review_needed": "[REVIEW]",
            }.get(result.status, "[UNKNOWN]")

            click.echo(f"\n{status_icon} {result.original_path.name}")

            if result.match_result:
                title = result.match_result.video_metadata.get("title", "Unknown")
                # Handle Unicode titles safely for console output
                try:
                    title_display = title
                except UnicodeEncodeError:
                    title_display = title.encode("ascii", "replace").decode("ascii")

                confidence = result.match_result.confidence_breakdown.overall_confidence
                try:
                    click.echo(f"    Title: {title_display}")
                except UnicodeEncodeError:
                    click.echo(f"    Title: [Unicode title - {len(title)} chars]")
                click.echo(f"    Confidence: {confidence:.2f}")
                if result.match_result.video_id:
                    click.echo(f"    ID: {result.match_result.video_id}")

            if result.output_path:
                try:
                    click.echo(f"    Output: {result.output_path}")
                except UnicodeEncodeError:
                    click.echo(
                        f"    Output: {str(result.output_path).encode('ascii', 'replace').decode('ascii')}"
                    )

            if result.assets_downloaded:
                click.echo(f"    Assets: {', '.join(result.assets_downloaded)}")

            if result.error_message:
                click.echo(f"    Error: {result.error_message}")

        # Display summary
        summary = processor.get_processing_summary(results)
        click.echo(f"\n{'=' * 60}")
        click.echo("SUMMARY")
        click.echo(f"{'=' * 60}")
        click.echo(f"Total groups processed: {summary['total_groups']}")
        click.echo(
            f"Successful: {summary['successful']} ({summary['success_rate']:.1f}%)"
        )
        click.echo(f"Failed: {summary['failed']}")
        click.echo(f"Skipped (low confidence): {summary['skipped']}")
        click.echo(f"Review needed: {summary['review_needed']}")
        if summary["total_assets"] > 0:
            click.echo(f"Assets downloaded: {summary['total_assets']}")

        if not dry_run and summary["successful"] > 0:
            click.echo(
                f"\n*** Successfully organized {summary['successful']} video group(s) to {output_path}"
            )
        elif dry_run:
            click.echo("\n*** Run without --dry-run to execute the processing plan")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    main()
