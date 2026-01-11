"""Tests for duplicate video file detection."""

import os

from taggrr.core.duplicate_detector import (
    DuplicateDetector,
    are_hardlinks,
    get_unmatched_files,
)
from taggrr.core.models import SourceType, VideoFile


class TestHardlinkDetection:
    """Test hardlink detection utility."""

    def test_hardlinks_detected(self, temp_dir):
        """Test that hardlinks are correctly identified."""
        # Create original file
        original = temp_dir / "file1.mp4"
        original.write_bytes(b"video content")

        # Create hardlink
        hardlink = temp_dir / "file2.mp4"
        os.link(original, hardlink)

        # Verify detection
        assert are_hardlinks(original, hardlink)
        assert original.stat().st_ino == hardlink.stat().st_ino

    def test_copies_not_detected_as_hardlinks(self, temp_dir):
        """Test that true copies are not identified as hardlinks."""
        file1 = temp_dir / "file1.mp4"
        file2 = temp_dir / "file2.mp4"

        file1.write_bytes(b"video content")
        file2.write_bytes(b"video content")  # Same content, different file

        assert not are_hardlinks(file1, file2)
        assert file1.stat().st_ino != file2.stat().st_ino

    def test_missing_file_handling(self, temp_dir):
        """Test graceful handling of missing files."""
        existing = temp_dir / "exists.mp4"
        missing = temp_dir / "missing.mp4"
        existing.write_bytes(b"content")

        assert not are_hardlinks(existing, missing)
        assert not are_hardlinks(missing, existing)


class TestDuplicateDetector:
    """Test duplicate detection logic."""

    def test_fc2_pattern_matching(self, temp_dir):
        """Test FC2-PPV pattern detection across folders."""
        # Create folder A with FC2 file
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        file_a = folder_a / "fc2-ppv-1234567.mp4"
        file_a.write_bytes(b"video")

        # Create folder B with matching FC2 file
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()
        file_b = folder_b / "FC2-PPV-1234567.mp4"
        file_b.write_bytes(b"video")

        # Detect duplicates
        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        # IDExtractor returns just the number for FC2 patterns
        assert groups[0].video_id == "1234567"
        assert groups[0].source_type == SourceType.FC2
        assert groups[0].confidence >= 0.80

    def test_dmm_pattern_matching(self, temp_dir):
        """Test DMM (ABC-123) pattern detection."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        file_a = folder_a / "MIDE-123.mp4"
        file_a.write_bytes(b"video")

        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()
        file_b = folder_b / "mide-123.mkv"  # Case insensitive
        file_b.write_bytes(b"video")

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        assert "MIDE-123" in groups[0].video_id.upper()
        assert groups[0].source_type == SourceType.DMM

    def test_multiple_folder_a_files(self, temp_dir):
        """Test multiple files in Folder A matching one in Folder B."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()

        # Create 3 files with same ID in Folder A
        for i in range(3):
            file = folder_a / f"ABC-123_copy{i}.mp4"
            file.write_bytes(b"video" * 100)

        # Create single file in Folder B
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()
        file_b = folder_b / "ABC-123.mp4"
        file_b.write_bytes(b"video" * 100)

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        assert len(groups[0].folder_a_files) == 3
        assert groups[0].folder_b_file.file_name == "ABC-123.mp4"

    def test_hardlink_vs_copy_classification(self, temp_dir):
        """Test correct classification of hardlinks vs copies."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()

        # Create original in Folder B
        original = folder_b / "FC2-PPV-111111.mp4"
        original.write_bytes(b"x" * 1000)

        # Create hardlink in Folder A
        hardlink = folder_a / "fc2-ppv-111111.mp4"
        os.link(original, hardlink)

        # Create true copy in Folder A
        copy_file = folder_a / "fc2-ppv-111111_copy.mp4"
        copy_file.write_bytes(b"x" * 1000)

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        group = groups[0]
        assert len(group.folder_a_files) == 2
        assert len(group.hardlink_pairs) == 1
        assert len(group.copy_pairs) == 1
        assert group.status == "MIXED"
        assert group.wasted_space == 1000  # Only copy wastes space

    def test_no_matches_empty_result(self, temp_dir):
        """Test that non-matching folders return empty results."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        (folder_a / "ABC-123.mp4").write_bytes(b"video")

        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()
        (folder_b / "XYZ-999.mp4").write_bytes(b"video")

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 0

    def test_confidence_threshold_filtering(self, temp_dir):
        """Test that low confidence matches are filtered out."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        # File with weak pattern (generic numbers only)
        (folder_a / "12345678.mp4").write_bytes(b"video")

        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()
        (folder_b / "12345678.mkv").write_bytes(b"video")

        detector = DuplicateDetector()

        # With high threshold, should find nothing
        groups = detector.scan_folders(folder_a, folder_b, min_confidence=0.7)
        assert len(groups) == 0

        # With low threshold, should find match
        groups = detector.scan_folders(folder_a, folder_b, min_confidence=0.3)
        assert len(groups) == 1

    def test_space_calculation(self, temp_dir):
        """Test accurate space wasted calculation."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()

        # Create files with known sizes
        file_b = folder_b / "ABC-123.mp4"
        file_b.write_bytes(b"x" * 2000)  # 2000 bytes

        file_a = folder_a / "abc-123.mp4"
        file_a.write_bytes(b"x" * 2000)  # True copy

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        assert groups[0].wasted_space == 2000
        assert groups[0].total_size == 2000

    def test_empty_folders(self, temp_dir):
        """Test handling of empty folders."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 0

    def test_hardlink_only_status(self, temp_dir):
        """Test HARDLINK status when all files are hardlinked."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()

        # Create original in Folder B
        original = folder_b / "FC2-PPV-222222.mp4"
        original.write_bytes(b"x" * 1500)

        # Create hardlink in Folder A
        hardlink = folder_a / "fc2-ppv-222222.mp4"
        os.link(original, hardlink)

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        assert groups[0].status == "HARDLINK"
        assert groups[0].wasted_space == 0

    def test_copy_only_status(self, temp_dir):
        """Test COPY status when all files are true copies."""
        folder_a = temp_dir / "folder_a"
        folder_a.mkdir()
        folder_b = temp_dir / "folder_b"
        folder_b.mkdir()

        # Create files with same ID but different inodes
        file_b = folder_b / "ABC-456.mp4"
        file_b.write_bytes(b"x" * 1500)

        file_a = folder_a / "abc-456.mp4"
        file_a.write_bytes(b"x" * 1500)

        detector = DuplicateDetector()
        groups = detector.scan_folders(folder_a, folder_b)

        assert len(groups) == 1
        assert groups[0].status == "COPY"
        assert groups[0].wasted_space == 1500


class TestUnmatchedFiles:
    """Test unmatched file detection."""

    def test_get_unmatched_files(self, temp_dir):
        """Test identifying files that weren't matched."""
        # Create some video files
        file1 = VideoFile(
            file_path=temp_dir / "file1.mp4",
            folder_name="test",
            file_name="file1.mp4",
            file_size=1000,
        )
        file2 = VideoFile(
            file_path=temp_dir / "file2.mp4",
            folder_name="test",
            file_name="file2.mp4",
            file_size=2000,
        )
        file3 = VideoFile(
            file_path=temp_dir / "file3.mp4",
            folder_name="test",
            file_name="file3.mp4",
            file_size=3000,
        )

        all_files = [file1, file2, file3]
        matched = {temp_dir / "file1.mp4", temp_dir / "file3.mp4"}

        unmatched = get_unmatched_files(all_files, matched)

        assert len(unmatched) == 1
        assert unmatched[0].file_path == temp_dir / "file2.mp4"
