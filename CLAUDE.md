# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Taggrr is a video file organization tool with multi-level name analysis designed for Plex compatibility. It automatically processes video files by extracting IDs from filenames and folder names, matching them against metadata APIs, and organizing them with proper Plex-compatible folder structures.

## Development Commands

**Dependencies:**
```bash
# Install dependencies (uses uv package manager)
uv sync

# Install with dev dependencies
uv sync --group dev
```

**Linting and Type Checking:**
```bash
# Run Ruff linter
ruff check .

# Run Ruff formatter
ruff format .

# Run MyPy type checker
mypy taggrr/
```

**Testing:**
```bash
# Run pytest (use uv run to ensure proper environment)
uv run pytest

# Run with coverage
uv run pytest --cov=taggrr

# Run specific test file
uv run pytest tests/core/test_analyzer.py

# Run single test
uv run pytest tests/core/test_analyzer.py::TestNameAnalyzer::test_fc2_id_extraction
```

**Running the Application:**
```bash
# Run via CLI entry point
taggerr /path/to/input /path/to/output

# Run with dry-run mode
taggerr /path/to/input /path/to/output --dry-run

# Run with custom config
taggerr /path/to/input /path/to/output --config custom_config.yaml

# Run directly with Python
python main.py
```

## Architecture Overview

**Core Processing Pipeline:**
1. **Scanner** (`core/scanner.py`) - Discovers video files and groups multi-part series
2. **Analyzer** (`core/analyzer.py`) - Extracts IDs and source hints from names using pattern matching
3. **API Client** (`api/scraperr_client.py`) - Fetches metadata from external APIs
4. **Formatter** (`core/formatter.py`) - Generates Plex-compatible folder/file names
5. **Processor** (`core/processor.py`) - Orchestrates the complete workflow

**Key Components:**
- **Models** (`core/models.py`) - Core data structures (VideoFile, VideoGroup, MatchResult, ProcessingResult)
- **Configuration** (`config/settings.py`) - Pydantic-based config management with YAML support
- **CLI** (`cli/__init__.py`) - Click-based command-line interface

**Pattern Detection System:**
The analyzer uses a multi-tier confidence system for ID extraction:
- **Strong patterns**: FC2-PPV-\d{6,8} (95% confidence)
- **Medium patterns**: [A-Z]{2,5}-\d{3,4} (75% confidence) 
- **Weak patterns**: Generic \d{6,8} (40% confidence)

Source hints boost confidence when folder/filename context matches patterns (FC2, DMM, etc.)

**Multi-part Detection:**
Automatically groups related files using patterns like "Part 1", "CD1", "Disc 2", etc. with configurable similarity thresholds.

## Configuration

Default config file: `taggerr.yaml` in project root or `~/.config/taggerr/taggerr.yaml`

Key configuration sections:
- `matching.name_analysis` - Weights for folder vs filename matching
- `matching.confidence_thresholds` - Auto-process/review/skip thresholds
- `source_detection` - Pattern matching for FC2, DMM sources
- `id_extraction` - Regex patterns for video ID extraction
- `plex_output` - Output naming formats and asset download settings

## Test Structure

Tests are organized by module:
- `tests/core/` - Core functionality tests (analyzer, formatter, scanner)
- `tests/api/` - API client tests
- `tests/config/` - Configuration tests
- `conftest.py` - Shared test fixtures

The test suite includes real video file examples in `test_videos/` for integration testing.

## Development Planning

**Important**: Always check and update the development todos file at `.plans/development-todos.md` when working on this project. This file tracks the current implementation status and prioritized tasks.

When starting work:
1. Review `.plans/development-todos.md` to understand current progress
2. Update todo items as you complete tasks  
3. Mark completed items and add new discovered tasks
4. Use the TodoWrite tool to track your current session progress

The development plan prioritizes: CLI interface → scanner → analyzer → API client → formatter → testing.