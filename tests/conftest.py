"""Pytest configuration and fixtures."""

import shutil
import tempfile
from pathlib import Path

import pytest

from taggrr.config.settings import TaggerrConfig
from taggrr.core.models import (
    ConfidenceBreakdown,
    MatchResult,
    SourceType,
    VideoFile,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def test_config():
    """Create a test configuration."""
    return TaggerrConfig()


@pytest.fixture
def sample_video_files(temp_dir):
    """Create sample video files for testing."""
    files = []

    # Single file
    single_file = temp_dir / "single_movie.mp4"
    single_file.touch()
    files.append(single_file)

    # Multi-part files
    part1 = temp_dir / "multi_part_1.mkv"
    part2 = temp_dir / "multi_part_2.mkv"
    part1.touch()
    part2.touch()
    files.extend([part1, part2])

    # FC2 files
    fc2_dir = temp_dir / "FC2-PPV-1234567"
    fc2_dir.mkdir()
    fc2_file = fc2_dir / "FC2-PPV-1234567.mp4"
    fc2_file.touch()
    files.append(fc2_file)

    # DMM files
    dmm_dir = temp_dir / "[DMM] MIDE-123"
    dmm_dir.mkdir()
    dmm_file = dmm_dir / "MIDE-123_high.mp4"
    dmm_file.touch()
    files.append(dmm_file)

    return files


@pytest.fixture
def sample_video_file(temp_dir):
    """Create a single VideoFile object for testing."""
    file_path = temp_dir / "test_folder" / "FC2-PPV-1234567.mp4"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    return VideoFile(
        file_path=file_path,
        folder_name="test_folder",
        file_name="FC2-PPV-1234567.mp4",
        detected_parts=[],
        source_hints=[],
        file_size=1024
    )


@pytest.fixture
def sample_match_result():
    """Create a sample MatchResult for testing."""
    return MatchResult(
        video_metadata={
            "title": "Test Movie Title",
            "year": 2024,
            "id": "FC2-PPV-1234567",
            "description": "A test movie description",
            "poster_url": "https://example.com/poster.jpg",
            "fanart_url": "https://example.com/fanart.jpg"
        },
        confidence_breakdown=ConfidenceBreakdown(
            folder_name_match=0.8,
            file_name_match=0.9,
            source_match=0.85,
            overall_confidence=0.87
        ),
        source=SourceType.FC2,
        suggested_output_name="Test Movie Title (2024)",
        video_id="FC2-PPV-1234567"
    )
