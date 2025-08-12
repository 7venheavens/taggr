"""Test video file scanning functionality."""

from taggrr.core.models import VideoFile
from taggrr.core.scanner import PartDetector, VideoScanner


class TestPartDetector:
    """Test part detection functionality."""

    def test_detect_parts_basic_patterns(self, temp_dir):
        """Test basic part detection patterns."""
        detector = PartDetector()

        test_cases = [
            ("movie_part_1.mp4", "Part 1"),
            ("video_cd1.mkv", "CD1"),
            ("film_disc_2.avi", "Disc 2"),
            ("show-1.mp4", "Part 1"),
            ("series_2.mkv", "Part 2"),
        ]

        for filename, expected_pattern in test_cases:
            file_path = temp_dir / filename
            file_path.touch()

            parts = detector.detect_parts(file_path)
            assert len(parts) == 1
            assert parts[0].part_pattern == expected_pattern
            assert parts[0].confidence >= 0.7

    def test_detect_no_parts(self, temp_dir):
        """Test files without part indicators."""
        detector = PartDetector()

        file_path = temp_dir / "single_movie.mp4"
        file_path.touch()

        parts = detector.detect_parts(file_path)
        assert len(parts) == 0

    def test_group_related_files(self, temp_dir):
        """Test grouping of related multi-part files."""
        detector = PartDetector()

        # Create related files
        files = []
        for i in range(1, 4):
            file_path = temp_dir / f"movie_part_{i}.mp4"
            file_path.touch()

            parts = detector.detect_parts(file_path)
            video_file = VideoFile(
                file_path=file_path,
                folder_name=temp_dir.name,
                file_name=file_path.name,
                detected_parts=parts,
                source_hints=[],
            )
            files.append(video_file)

        # Group the files
        groups = detector.group_related_files(files)

        assert len(groups) == 1
        group = groups[0]
        assert group.total_parts == 3
        assert len(group.files) == 3


class TestVideoScanner:
    """Test video file scanning."""

    def test_scan_directory_basic(self, sample_video_files, temp_dir):
        """Test basic directory scanning."""
        scanner = VideoScanner()

        video_files = scanner.scan_directory(temp_dir)

        # Should find all video files
        assert len(video_files) >= 4

        # Check file extensions
        extensions = {vf.file_path.suffix for vf in video_files}
        assert ".mp4" in extensions
        assert ".mkv" in extensions

    def test_scan_directory_recursive(self, sample_video_files, temp_dir):
        """Test recursive directory scanning."""
        scanner = VideoScanner()

        # Scan recursively
        video_files = scanner.scan_directory(temp_dir, recursive=True)

        # Should find files in subdirectories
        folder_names = {vf.folder_name for vf in video_files}
        assert "FC2-PPV-1234567" in folder_names
        assert "[DMM] MIDE-123" in folder_names

    def test_scan_directory_non_recursive(self, sample_video_files, temp_dir):
        """Test non-recursive directory scanning."""
        scanner = VideoScanner()

        # Scan non-recursively
        video_files = scanner.scan_directory(temp_dir, recursive=False)

        # Should only find files in root directory
        root_files = [vf for vf in video_files if vf.file_path.parent == temp_dir]
        assert len(root_files) >= 2  # single_movie.mp4 and multi_part files

    def test_video_file_creation(self, temp_dir):
        """Test VideoFile object creation."""
        scanner = VideoScanner()

        # Create a test file
        test_file = temp_dir / "FC2-PPV-1234567_part1.mp4"
        test_file.write_bytes(b"fake video content")

        video_files = scanner.scan_directory(temp_dir)

        assert len(video_files) == 1
        vf = video_files[0]

        assert vf.file_path == test_file
        assert vf.folder_name == temp_dir.name
        assert vf.file_name == "FC2-PPV-1234567_part1.mp4"
        assert vf.file_size == len(b"fake video content")
        assert len(vf.detected_parts) >= 1  # Should detect "part1"

    def test_group_videos(self, temp_dir):
        """Test video grouping functionality."""
        scanner = VideoScanner()

        # Create multi-part series
        for i in range(1, 3):
            file_path = temp_dir / f"series_part_{i}.mp4"
            file_path.touch()

        # Create single file
        single_file = temp_dir / "single_movie.mkv"
        single_file.touch()

        video_files = scanner.scan_directory(temp_dir)
        groups = scanner.group_videos(video_files)

        # Should create appropriate groups
        multi_part_groups = [g for g in groups if g.total_parts > 1]
        single_file_groups = [g for g in groups if g.total_parts == 1]

        assert len(multi_part_groups) >= 1
        assert len(single_file_groups) >= 1

    def test_is_video_file(self, temp_dir):
        """Test video file detection."""
        scanner = VideoScanner()

        # Video files
        video_extensions = [".mp4", ".mkv", ".avi", ".mov"]
        for ext in video_extensions:
            file_path = temp_dir / f"video{ext}"
            file_path.touch()
            assert scanner._is_video_file(file_path)

        # Non-video files
        non_video_extensions = [".txt", ".jpg", ".nfo", ".srt"]
        for ext in non_video_extensions:
            file_path = temp_dir / f"file{ext}"
            file_path.touch()
            assert not scanner._is_video_file(file_path)

        # Directory should not be considered a video file
        dir_path = temp_dir / "not_a_file"
        dir_path.mkdir()
        assert not scanner._is_video_file(dir_path)
