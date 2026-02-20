"""Duplicate video file detection across multiple folders."""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from taggrr.core.analyzer import IDExtractor
from taggrr.core.models import SourceType, VideoFile
from taggrr.core.scanner import VideoScanner


@dataclass
class DuplicateSet:
    """Group of duplicate video files across one or more directories."""

    match_type: str  # "name", "content", or "name+content"

    # Name match fields (None for content-only sets)
    video_id: str | None
    confidence: float | None
    source_type: SourceType | None

    # Content match fields (None for name-only sets)
    file_size: int | None
    file_hash: str | None  # SHA256; populated when content_match is used

    # Files grouped by their resolved parent directory
    files_by_dir: dict[Path, list[VideoFile]]

    # The canonical source file (from the source dir); None if source has no file here
    source_file: VideoFile | None

    # Hardlink/copy analysis: (source_file, other_file) pairs
    hardlink_pairs: list[tuple[VideoFile, VideoFile]] = field(default_factory=list)
    copy_pairs: list[tuple[VideoFile, VideoFile]] = field(default_factory=list)

    wasted_space: int = 0  # Sum of copy file sizes (non-source copies only)

    @property
    def all_files(self) -> list[VideoFile]:
        """Flat list of all files across all directories."""
        return [f for files in self.files_by_dir.values() for f in files]

    @property
    def has_hardlinks(self) -> bool:
        return len(self.hardlink_pairs) > 0

    @property
    def has_copies(self) -> bool:
        return len(self.copy_pairs) > 0

    @property
    def status(self) -> str:
        """Return 'HARDLINK', 'COPY', 'MIXED', or 'NO_SOURCE'."""
        if self.source_file is None:
            return "NO_SOURCE"
        if self.has_hardlinks and not self.has_copies:
            return "HARDLINK"
        if self.has_copies and not self.has_hardlinks:
            return "COPY"
        return "MIXED"


def are_hardlinks(path1: Path, path2: Path) -> bool:
    """
    Check if two paths point to the same underlying file (hardlinks).

    Uses Path.samefile() which is cross-platform: on Windows it uses the
    Win32 file-ID API (GetFileInformationByHandle), on POSIX it compares
    st_dev + st_ino.

    Args:
        path1: First file path
        path2: Second file path

    Returns:
        True if both paths refer to the same file
    """
    try:
        return path1.samefile(path2)
    except OSError:
        return False


def compute_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """
    Calculate SHA256 hash of a file.

    Args:
        file_path: Path to the file
        chunk_size: Read chunk size in bytes

    Returns:
        Hexadecimal SHA256 digest string
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


class DuplicateDetector:
    """Detects duplicate video files across a source dir and multiple target dirs."""

    _PART_PATTERNS = [
        re.compile(r"(?i)(?:pt|part|cd|disc)[\s._-]*([0-9]+|[a-d])(?:\b|$)"),
        re.compile(r"(?i)[-_]([0-9]+|[a-d])$"),
        re.compile(r"(?i)(?<=\d)([a-d])$"),
    ]
    _OPTION_PATTERN = re.compile(r"(?i)(?:^|[-_\s])option$")

    def __init__(self) -> None:
        self.scanner = VideoScanner()
        self.id_extractor = IDExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_multiple(
        self,
        source_dir: Path,
        target_dirs: list[Path],
        min_confidence: float = 0.5,
        content_match: bool = False,
        min_file_size_bytes: int = 0,
    ) -> list[DuplicateSet]:
        """
        Scan source + target directories and build duplicate sets.

        A duplicate set groups files that share the same normalized video ID
        (name match) and/or the same SHA256 hash (content match). Each set
        carries a source_file pointer to the canonical copy in source_dir
        (or None if source has no representative in that set).

        Args:
            source_dir: The authoritative directory (files here are kept on fix).
            target_dirs: One or more directories to compare against.
            min_confidence: Minimum ID extraction confidence for name matching.
            content_match: If True, also match files by size + SHA256 hash.
            min_file_size_bytes: Ignore files smaller than this size.

        Returns:
            Sorted list of DuplicateSet objects.
        """
        all_dirs = [source_dir] + list(target_dirs)

        # 1. Scan all directories
        files_by_dir: dict[Path, list[VideoFile]] = {
            d.resolve(): self.scanner.scan_directory(d) for d in all_dirs
        }
        if min_file_size_bytes > 0:
            files_by_dir = {
                d: [
                    f
                    for f in files
                    if f.file_size is not None and f.file_size >= min_file_size_bytes
                ]
                for d, files in files_by_dir.items()
            }
        source_dir_r = source_dir.resolve()

        # 2. Build id_maps per directory
        # id_map: (normalized_id, part_token) -> list of entries
        id_maps: dict[
            Path, dict[tuple[str, str | None], list[tuple[VideoFile, float, SourceType]]]
        ] = {
            d: self._build_id_map(files, min_confidence)
            for d, files in files_by_dir.items()
        }

        # Track which files have been placed into a name-based set
        matched_paths: set[Path] = set()

        # 3. Find IDs present in source AND at least one target
        source_id_map = id_maps[source_dir_r]
        name_sets: list[DuplicateSet] = []

        for match_key, source_entries in source_id_map.items():
            video_id, part_token = match_key
            # Collect matching entries from every dir that has this ID
            dir_entries: dict[Path, list[tuple[VideoFile, float, SourceType]]] = {
                source_dir_r: source_entries
            }
            for d in [d.resolve() for d in target_dirs]:
                if match_key in id_maps[d]:
                    dir_entries[d] = id_maps[d][match_key]

            if len(dir_entries) < 2:
                # ID only in source; not a duplicate
                continue

            # Gather VideoFile objects per dir
            set_files_by_dir: dict[Path, list[VideoFile]] = {
                d: [e[0] for e in entries] for d, entries in dir_entries.items()
            }
            confidence = source_entries[0][1]
            src_type = source_entries[0][2]
            source_file = source_entries[0][0]

            # Track matched paths
            for files in set_files_by_dir.values():
                for f in files:
                    matched_paths.add(f.file_path)

            dup_set = self._build_set(
                match_type="name",
                video_id=(
                    f"{video_id} [{part_token}]"
                    if part_token is not None
                    else video_id
                ),
                confidence=confidence,
                source_type=src_type,
                file_size=None,
                file_hash=None,
                files_by_dir=set_files_by_dir,
                source_file=source_file,
                source_dir=source_dir_r,
            )
            name_sets.append(dup_set)

        # 4. Optionally annotate name sets with content confirmation
        #    and find content-only duplicates
        content_sets: list[DuplicateSet] = []

        if content_match:
            # Annotate name sets: check if files also match by size + hash
            for dup_set in name_sets:
                if dup_set.source_file is None:
                    continue
                source_size = dup_set.source_file.file_size
                # Check all non-source files against source size
                all_same_size = all(
                    f.file_size == source_size
                    for files in dup_set.files_by_dir.values()
                    for f in files
                    if f.file_path != dup_set.source_file.file_path
                )
                if all_same_size and source_size is not None:
                    source_hash = compute_hash(dup_set.source_file.file_path)
                    all_same_hash = all(
                        compute_hash(f.file_path) == source_hash
                        for files in dup_set.files_by_dir.values()
                        for f in files
                        if f.file_path != dup_set.source_file.file_path
                    )
                    if all_same_hash:
                        dup_set.match_type = "name+content"
                        dup_set.file_size = source_size
                        dup_set.file_hash = source_hash

            # Find content-only duplicates from unmatched files
            unmatched: list[VideoFile] = [
                f
                for files in files_by_dir.values()
                for f in files
                if f.file_path not in matched_paths
            ]
            content_sets = self._find_content_duplicates(
                unmatched, files_by_dir, source_dir_r
            )

        all_sets = name_sets + content_sets

        # 5. Sort: name/name+content by video_id, content-only by file_size
        all_sets.sort(
            key=lambda s: (
                s.match_type == "content",  # name matches first
                s.video_id or "",
                s.file_size or 0,
            )
        )
        return all_sets

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_id_map(
        self,
        files: list[VideoFile],
        min_confidence: float,
    ) -> dict[tuple[str, str | None], list[tuple[VideoFile, float, SourceType]]]:
        """
        Build (normalized_id, part_token) -> entries map.

        Only the best match above min_confidence is used per file.
        """
        id_map: dict[
            tuple[str, str | None], list[tuple[VideoFile, float, SourceType]]
        ] = {}
        for video_file in files:
            # Use filename-only extraction for duplicate matching.
            # Folder-derived IDs can incorrectly pull in unrelated sidecar files.
            ids = self.id_extractor.extract_ids(video_file.file_name)
            if not ids:
                continue
            video_id, src_type, confidence = ids[0]
            if confidence < min_confidence:
                continue
            normalized = self._normalize_id(video_id)
            part_token = self._extract_part_token(video_file.file_name)
            id_map.setdefault((normalized, part_token), []).append(
                (video_file, confidence, src_type)
            )
        return id_map

    def _extract_part_token(self, file_name: str) -> str | None:
        """Extract normalized part token from filename."""
        stem = Path(file_name).stem

        if self._OPTION_PATTERN.search(stem):
            return "OPTION"

        for pattern in self._PART_PATTERNS:
            match = pattern.search(stem)
            if not match:
                continue
            token = match.group(1).upper()
            if token.isdigit():
                return str(int(token))
            return token

        return None

    def _normalize_id(self, video_id: str) -> str:
        """Normalize video ID for consistent cross-source matching.

        Strips dashes and underscores and uppercases for all source types,
        so MIDE-123 == MIDE123 == mide_123.
        """
        return video_id.upper().replace("-", "").replace("_", "")

    def _build_set(
        self,
        *,
        match_type: str,
        video_id: str | None,
        confidence: float | None,
        source_type: SourceType | None,
        file_size: int | None,
        file_hash: str | None,
        files_by_dir: dict[Path, list[VideoFile]],
        source_file: VideoFile | None,
        source_dir: Path | None,
    ) -> DuplicateSet:
        """Create a DuplicateSet and populate hardlink/copy pairs."""
        hardlink_pairs: list[tuple[VideoFile, VideoFile]] = []
        copy_pairs: list[tuple[VideoFile, VideoFile]] = []

        if source_file is not None:
            for group_dir, files in files_by_dir.items():
                if source_dir is not None and group_dir == source_dir:
                    continue
                for f in files:
                    if f.file_path == source_file.file_path:
                        continue
                    if are_hardlinks(source_file.file_path, f.file_path):
                        hardlink_pairs.append((source_file, f))
                    else:
                        copy_pairs.append((source_file, f))

        # Wasted space = sum of non-source copy file sizes (the files we'd delete)
        wasted_space = sum(f[1].file_size or 0 for f in copy_pairs)

        return DuplicateSet(
            match_type=match_type,
            video_id=video_id,
            confidence=confidence,
            source_type=source_type,
            file_size=file_size,
            file_hash=file_hash,
            files_by_dir=files_by_dir,
            source_file=source_file,
            hardlink_pairs=hardlink_pairs,
            copy_pairs=copy_pairs,
            wasted_space=wasted_space,
        )

    def _find_content_duplicates(
        self,
        files: list[VideoFile],
        files_by_dir: dict[Path, list[VideoFile]],
        source_dir: Path,
    ) -> list[DuplicateSet]:
        """
        Group unmatched files by size then hash to find content duplicates.

        Only creates a DuplicateSet if files from at least 2 different dirs
        share the same hash.
        """
        # Build a reverse map: file_path -> dir
        path_to_dir: dict[Path, Path] = {}
        for d, dir_files in files_by_dir.items():
            for f in dir_files:
                path_to_dir[f.file_path] = d

        # Group by size
        by_size: dict[int, list[VideoFile]] = {}
        for f in files:
            if f.file_size is not None:
                by_size.setdefault(f.file_size, []).append(f)

        sets: list[DuplicateSet] = []
        for size, size_group in by_size.items():
            if len(size_group) < 2:
                continue
            # Check that at least 2 different dirs are represented
            dirs_in_group = {path_to_dir.get(f.file_path) for f in size_group}
            if len(dirs_in_group) < 2:
                continue

            # Hash all files in this size group
            hash_groups: dict[str, list[VideoFile]] = {}
            for f in size_group:
                try:
                    h = compute_hash(f.file_path)
                    hash_groups.setdefault(h, []).append(f)
                except OSError:
                    pass

            for file_hash, hash_group in hash_groups.items():
                if len(hash_group) < 2:
                    continue
                # Need at least 2 dirs
                dirs_here = {path_to_dir.get(f.file_path) for f in hash_group}
                if len(dirs_here) < 2:
                    continue

                # Build files_by_dir for this set
                set_files_by_dir: dict[Path, list[VideoFile]] = {}
                for f in hash_group:
                    d = path_to_dir[f.file_path]
                    set_files_by_dir.setdefault(d, []).append(f)

                source_file = (
                    set_files_by_dir[source_dir][0]
                    if source_dir in set_files_by_dir
                    else None
                )

                dup_set = self._build_set(
                    match_type="content",
                    video_id=None,
                    confidence=None,
                    source_type=None,
                    file_size=size,
                    file_hash=file_hash,
                    files_by_dir=set_files_by_dir,
                    source_file=source_file,
                    source_dir=source_dir,
                )
                sets.append(dup_set)

        return sets


def get_unmatched_files(
    folder_files: list[VideoFile], matched_files: set[Path]
) -> list[VideoFile]:
    """Return files that weren't matched in duplicate detection."""
    return [f for f in folder_files if f.file_path not in matched_files]
