"""Duplicate video file detection across folders."""

from dataclasses import dataclass, field
from pathlib import Path

from taggrr.core.analyzer import IDExtractor
from taggrr.core.models import SourceType, VideoFile
from taggrr.core.scanner import VideoScanner


@dataclass
class DuplicateGroup:
    """Group of duplicate video files across two folders."""

    video_id: str  # Extracted ID (e.g., "FC2-PPV-1234567", "ABC-123")
    confidence: float  # ID extraction confidence (0.0-1.0)
    source_type: SourceType  # FC2, DMM, or GENERIC

    # Files grouped by folder
    folder_a_files: list[VideoFile]  # One or more matches in Folder A
    folder_b_file: VideoFile  # Single match in Folder B (per requirement)

    # Hardlink analysis results
    hardlink_pairs: list[tuple[VideoFile, VideoFile]] = field(
        default_factory=list
    )  # (A, B) pairs that are hardlinked
    copy_pairs: list[tuple[VideoFile, VideoFile]] = field(
        default_factory=list
    )  # (A, B) pairs that are true copies

    # Space calculations
    total_size: int = 0  # Total bytes across all files
    wasted_space: int = 0  # Bytes wasted by true copies (excludes hardlinks)

    @property
    def has_hardlinks(self) -> bool:
        """Check if any files are hardlinked."""
        return len(self.hardlink_pairs) > 0

    @property
    def has_copies(self) -> bool:
        """Check if any files are true duplicates."""
        return len(self.copy_pairs) > 0

    @property
    def status(self) -> str:
        """Return 'HARDLINK', 'COPY', or 'MIXED'."""
        if self.has_hardlinks and not self.has_copies:
            return "HARDLINK"
        elif self.has_copies and not self.has_hardlinks:
            return "COPY"
        else:
            return "MIXED"


def are_hardlinks(path1: Path, path2: Path) -> bool:
    """
    Check if two paths are hardlinks to the same inode.

    Uses st_dev (device) and st_ino (inode) comparison.
    Works reliably on Linux + NFS environments.

    Args:
        path1: First file path
        path2: Second file path

    Returns:
        True if both paths point to same inode on same device
    """
    try:
        stat1 = path1.stat()
        stat2 = path2.stat()

        # Must match both device AND inode
        # NFS preserves inode numbers within same filesystem
        return stat1.st_dev == stat2.st_dev and stat1.st_ino == stat2.st_ino
    except (OSError, FileNotFoundError):
        # Handle NFS stale handles or missing files
        return False


class DuplicateDetector:
    """Detects duplicate video files across two folders using ID extraction."""

    def __init__(self) -> None:
        """Initialize detector with scanner and ID extractor."""
        self.scanner = VideoScanner()
        self.id_extractor = IDExtractor()

    def scan_folders(
        self, folder_a: Path, folder_b: Path, min_confidence: float = 0.5
    ) -> list[DuplicateGroup]:
        """
        Scan two folders and identify duplicate videos by ID matching.

        Args:
            folder_a: Original video folder
            folder_b: Reorganized video folder
            min_confidence: Minimum ID extraction confidence (default: 0.5)

        Returns:
            List of DuplicateGroup objects with hardlink analysis
        """
        # 1. Scan both folders
        files_a = self.scanner.scan_directory(folder_a)
        files_b = self.scanner.scan_directory(folder_b)

        # 2. Extract IDs from all files
        id_map_a = self._build_id_map(files_a, min_confidence)
        id_map_b = self._build_id_map(files_b, min_confidence)

        # 3. Find common IDs
        common_ids = set(id_map_a.keys()) & set(id_map_b.keys())

        # 4. Create duplicate groups
        groups = []
        for video_id in common_ids:
            group = self._create_group(
                video_id,
                id_map_a[video_id],  # List of files from A
                id_map_b[video_id],  # Files from B
            )
            groups.append(group)

        return groups

    def _build_id_map(
        self, files: list[VideoFile], min_confidence: float
    ) -> dict[str, list[VideoFile]]:
        """
        Build mapping of video_id -> list of VideoFile objects.

        Args:
            files: List of video files to process
            min_confidence: Minimum confidence threshold

        Returns:
            Dictionary mapping normalized video IDs to file lists
        """
        id_map: dict[str, list[VideoFile]] = {}

        for video_file in files:
            # Extract IDs from both filename and folder name
            text = f"{video_file.folder_name} {video_file.file_name}"
            ids = self.id_extractor.extract_ids(text)

            # Use highest confidence match above threshold
            if ids:
                video_id, source_type, confidence = ids[0]  # Best match
                if confidence >= min_confidence:
                    # Normalize ID for comparison
                    normalized_id = self._normalize_id(video_id, source_type)

                    if normalized_id not in id_map:
                        id_map[normalized_id] = []
                    id_map[normalized_id].append(video_file)

        return id_map

    def _normalize_id(self, video_id: str, source_type: SourceType) -> str:
        """
        Normalize video ID for consistent matching.

        Args:
            video_id: Raw video ID
            source_type: Type of source (FC2, DMM, etc.)

        Returns:
            Normalized ID string
        """
        # Uppercase for consistency
        normalized = video_id.upper()

        # Remove separators for FC2 (FC2-PPV-123456 -> FC2PPV123456)
        if source_type == SourceType.FC2:
            normalized = normalized.replace("-", "").replace("_", "")

        return normalized

    def _create_group(
        self,
        video_id: str,
        files_a: list[VideoFile],
        files_b: list[VideoFile],
    ) -> DuplicateGroup:
        """
        Create a DuplicateGroup with hardlink analysis.

        Args:
            video_id: Normalized video ID
            files_a: Files from folder A
            files_b: Files from folder B

        Returns:
            DuplicateGroup with complete analysis
        """
        # Per requirement: max 1 file in Folder B
        folder_b_file = files_b[0]

        # Analyze each Folder A file against Folder B file
        hardlink_pairs = []
        copy_pairs = []

        for file_a in files_a:
            if are_hardlinks(file_a.file_path, folder_b_file.file_path):
                hardlink_pairs.append((file_a, folder_b_file))
            else:
                copy_pairs.append((file_a, folder_b_file))

        # Calculate space usage
        total_size = sum(f.file_size or 0 for f in files_a)
        wasted_space = sum(f[0].file_size or 0 for f in copy_pairs)

        # Get confidence and source from first file in A
        first_file_text = f"{files_a[0].folder_name} {files_a[0].file_name}"
        ids = self.id_extractor.extract_ids(first_file_text)
        confidence = ids[0][2] if ids else 0.0
        source_type = ids[0][1] if ids else SourceType.GENERIC

        return DuplicateGroup(
            video_id=video_id,
            confidence=confidence,
            source_type=source_type,
            folder_a_files=files_a,
            folder_b_file=folder_b_file,
            hardlink_pairs=hardlink_pairs,
            copy_pairs=copy_pairs,
            total_size=total_size,
            wasted_space=wasted_space,
        )


def get_unmatched_files(
    folder_files: list[VideoFile], matched_files: set[Path]
) -> list[VideoFile]:
    """
    Return files that weren't matched in duplicate detection.

    Args:
        folder_files: All files from a folder
        matched_files: Set of paths that were matched

    Returns:
        List of unmatched VideoFile objects
    """
    return [f for f in folder_files if f.file_path not in matched_files]
