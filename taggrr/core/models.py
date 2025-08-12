"""Core data models for video file processing."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ProcessingMode(Enum):
    """File processing modes."""

    INPLACE = "inplace"
    HARDLINK = "hardlink"


class SourceType(Enum):
    """Video source types."""

    FC2 = "fc2"
    DMM = "dmm"
    GENERIC = "generic"


@dataclass
class PartInfo:
    """Information about a video part."""

    part_number: int
    part_pattern: str  # "Part 1", "CD1", "Disc 2", etc.
    confidence: float
    file_path: Path


@dataclass
class SourceHint:
    """Source detection hint."""

    source_type: SourceType
    pattern_matched: str
    confidence_boost: float


@dataclass
class VideoFile:
    """Represents a video file with analysis metadata."""

    file_path: Path
    folder_name: str
    file_name: str
    detected_parts: list[PartInfo] = field(default_factory=list)
    source_hints: list[SourceHint] = field(default_factory=list)
    file_size: int | None = None

    @property
    def stem(self) -> str:
        """File name without extension."""
        return self.file_path.stem

    @property
    def is_multipart(self) -> bool:
        """Check if this file is part of a multi-part series."""
        return len(self.detected_parts) > 0


@dataclass
class VideoGroup:
    """Group of related video files (e.g., multi-part series)."""

    files: list[VideoFile]
    group_name: str
    total_parts: int
    folder_path: Path

    @property
    def primary_file(self) -> VideoFile:
        """Get the primary file for metadata lookup."""
        return min(
            self.files,
            key=lambda f: f.detected_parts[0].part_number if f.detected_parts else 0,
        )


@dataclass
class ConfidenceBreakdown:
    """Detailed confidence scoring."""

    folder_name_match: float
    file_name_match: float
    source_match: float
    overall_confidence: float


@dataclass
class MatchResult:
    """Result of matching a video against metadata APIs."""

    video_metadata: dict
    confidence_breakdown: ConfidenceBreakdown
    source: SourceType
    suggested_output_name: str
    video_id: str | None = None
    api_response: dict | None = None


@dataclass
class ProcessingResult:
    """Result of processing a video file or group."""

    original_path: Path
    output_path: Path | None
    match_result: MatchResult | None
    status: str  # "success", "skipped", "failed", "review_needed"
    error_message: str | None = None
    assets_downloaded: list[str] = field(default_factory=list)


@dataclass
class PlexMetadata:
    """Plex-compatible metadata structure."""

    title: str
    year: int | None
    poster_url: str | None = None
    fanart_url: str | None = None
    plot: str | None = None
    genre: list[str] | None = None
    director: str | None = None
    duration: int | None = None
