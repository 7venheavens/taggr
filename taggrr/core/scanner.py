"""File scanning and multi-part detection system."""

import re
from difflib import SequenceMatcher
from pathlib import Path

from .models import PartInfo, VideoFile, VideoGroup


class PartDetector:
    """Detects and groups multi-part video files."""

    DEFAULT_PATTERNS = [
        (r"(?i)part[\s_]*(\d+)", "Part {n}"),
        (r"(?i)cd[\s_]*(\d+)", "CD{n}"),
        (r"(?i)disc[\s_]*(\d+)", "Disc {n}"),
        (r"(?i)-(\d+)(?=\.\w+$|$)", "Part {n}"),
        (r"(?i)_(\d+)(?=\.\w+$|$)", "Part {n}"),
        (r"(?i)\[(\d+)\]", "Part {n}"),
        (r"(?i)\((\d+)\)", "Part {n}"),
    ]

    def __init__(self, patterns: list[tuple[str, str]] | None = None):
        """Initialize with custom patterns or defaults."""
        self.patterns = patterns or self.DEFAULT_PATTERNS
        self.compiled_patterns = [
            (re.compile(pattern), format_str) for pattern, format_str in self.patterns
        ]

    def detect_parts(self, file_path: Path) -> list[PartInfo]:
        """Detect part information from filename."""
        parts = []
        filename = file_path.stem
        found_part_numbers = set()

        for pattern, format_str in self.compiled_patterns:
            matches = pattern.findall(filename)
            for match in matches:
                try:
                    part_num = int(match)

                    # Skip if we already found this part number
                    if part_num in found_part_numbers:
                        continue

                    found_part_numbers.add(part_num)
                    confidence = 0.9  # High confidence for explicit patterns

                    part_info = PartInfo(
                        part_number=part_num,
                        part_pattern=format_str.replace("{n}", str(part_num)),
                        confidence=confidence,
                        file_path=file_path,
                    )
                    parts.append(part_info)
                except ValueError:
                    continue

        return parts

    def group_related_files(
        self, video_files: list[VideoFile], similarity_threshold: float = 0.8
    ) -> list[VideoGroup]:
        """Group files that belong to the same multi-part series."""
        groups = []
        processed = set()

        for i, file1 in enumerate(video_files):
            if i in processed:
                continue

            group_files = [file1]
            processed.add(i)

            # Extract video ID from the first file to ensure we don't mix different videos
            file1_id = self._extract_video_id(file1.stem)

            # Find similar files that might be parts
            for j, file2 in enumerate(video_files[i + 1 :], i + 1):
                if j in processed:
                    continue

                # First check if they have the same video ID - if different IDs, never group
                file2_id = self._extract_video_id(file2.stem)
                if file1_id and file2_id and file1_id != file2_id:
                    continue  # Different video IDs, skip

                similarity = self._calculate_similarity(file1.stem, file2.stem)
                if similarity >= similarity_threshold:
                    # Check if both have part indicators or neither does
                    file1_has_parts = bool(file1.detected_parts)
                    file2_has_parts = bool(file2.detected_parts)

                    if file1_has_parts or file2_has_parts:
                        group_files.append(file2)
                        processed.add(j)

            # Create group
            if len(group_files) > 1 or any(f.detected_parts for f in group_files):
                group_name = self._generate_group_name(group_files)
                group = VideoGroup(
                    files=sorted(group_files, key=self._get_part_number),
                    group_name=group_name,
                    total_parts=len(group_files),
                    folder_path=group_files[0].file_path.parent,
                )
                groups.append(group)
            else:
                # Single file, create individual group
                group = VideoGroup(
                    files=group_files,
                    group_name=file1.stem,
                    total_parts=1,
                    folder_path=file1.file_path.parent,
                )
                groups.append(group)

        return groups

    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two filenames."""
        # Remove part indicators for comparison
        clean_name1 = self._remove_part_indicators(name1)
        clean_name2 = self._remove_part_indicators(name2)

        return SequenceMatcher(None, clean_name1.lower(), clean_name2.lower()).ratio()

    def _remove_part_indicators(self, filename: str) -> str:
        """Remove part indicators from filename for similarity comparison."""
        result = filename
        for pattern, _ in self.compiled_patterns:
            result = pattern.sub("", result)
        return result.strip()

    def _generate_group_name(self, files: list[VideoFile]) -> str:
        """Generate a group name from similar files."""
        if not files:
            return ""

        # Use the longest common substring approach
        names = [self._remove_part_indicators(f.stem) for f in files]
        base_name = names[0]

        for name in names[1:]:
            base_name = self._longest_common_substring(base_name, name)

        return base_name.strip()

    def _longest_common_substring(self, s1: str, s2: str) -> str:
        """Find longest common substring."""
        matcher = SequenceMatcher(None, s1, s2)
        match = matcher.find_longest_match()
        return s1[match.a : match.a + match.size]

    def _get_part_number(self, video_file: VideoFile) -> int:
        """Get part number for sorting, default to 1 if no parts detected."""
        if video_file.detected_parts:
            return video_file.detected_parts[0].part_number
        return 1

    def _extract_video_id(self, filename: str) -> str | None:
        """Extract video ID from filename to prevent grouping different videos."""
        # FC2-PPV patterns
        fc2_patterns = [
            r"FC2-PPV-(\d{6,8})",
            r"fc2-ppv-(\d{6,8})",
            r"FC2PPV-(\d{6,8})",
            r"ppv-(\d{6,8})",
        ]

        for pattern in fc2_patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return f"FC2-PPV-{match.group(1)}"

        # DMM/JAV patterns
        dmm_patterns = [
            r"([A-Z]{2,5}-\d{3,4})",
            r"([A-Z]{3,5}\d{3,4})",
            r"(\d{6}_\d{3})",
        ]

        for pattern in dmm_patterns:
            match = re.search(pattern, filename)
            if match:
                return match.group(1)

        return None


class VideoScanner:
    """Scans directories for video files and creates VideoFile objects."""

    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".mpg",
        ".mpeg",
    }

    def __init__(self, part_detector: PartDetector | None = None):
        """Initialize scanner with optional custom part detector."""
        self.part_detector = part_detector or PartDetector()

    def scan_directory(
        self, directory: Path, recursive: bool = True
    ) -> list[VideoFile]:
        """Scan directory for video files."""
        video_files = []

        pattern = "**/*" if recursive else "*"
        for file_path in directory.glob(pattern):
            if self._is_video_file(file_path):
                video_file = self._create_video_file(file_path)
                video_files.append(video_file)

        return video_files

    def scan_multiple_directories(self, directories: list[Path]) -> list[VideoFile]:
        """Scan multiple directories for video files."""
        all_files = []
        for directory in directories:
            files = self.scan_directory(directory)
            all_files.extend(files)
        return all_files

    def group_videos(
        self, video_files: list[VideoFile], similarity_threshold: float = 0.8
    ) -> list[VideoGroup]:
        """Group video files by similarity and part detection."""
        return self.part_detector.group_related_files(video_files, similarity_threshold)

    def _is_video_file(self, file_path: Path) -> bool:
        """Check if file is a video file based on extension."""
        return file_path.is_file() and file_path.suffix.lower() in self.VIDEO_EXTENSIONS

    def _create_video_file(self, file_path: Path) -> VideoFile:
        """Create VideoFile object from file path."""
        folder_name = file_path.parent.name
        file_name = file_path.name
        detected_parts = self.part_detector.detect_parts(file_path)

        # Get file size
        try:
            file_size = file_path.stat().st_size
        except OSError:
            file_size = None

        return VideoFile(
            file_path=file_path,
            folder_name=folder_name,
            file_name=file_name,
            detected_parts=detected_parts,
            source_hints=[],  # Will be populated by source detector
            file_size=file_size,
        )
