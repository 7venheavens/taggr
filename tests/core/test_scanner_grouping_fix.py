"""Test cases for the video grouping fix to prevent incorrect ID mixing."""

import unittest
from pathlib import Path
from taggrr.core.scanner import PartDetector, VideoScanner
from taggrr.core.models import VideoFile


class TestVideoGroupingFix(unittest.TestCase):
    """Test that videos with different IDs are not incorrectly grouped."""

    def setUp(self):
        """Set up test fixtures."""
        self.part_detector = PartDetector()
        self.video_scanner = VideoScanner()

    def test_extract_video_id_fc2_ppv(self):
        """Test FC2-PPV ID extraction from various filename formats."""
        test_cases = [
            ("hhd800.com@FC2-PPV-4734631_1", "FC2-PPV-4734631"),
            ("hhd800.com@FC2-PPV-4734766", "FC2-PPV-4734766"),
            ("fc2-ppv-1234567", "FC2-PPV-1234567"),
            ("FC2PPV-9876543", "FC2-PPV-9876543"),
            ("ppv-555666", "FC2-PPV-555666"),
            ("T66Y.COM@FC2-PPV-4485258", "FC2-PPV-4485258"),
        ]

        for filename, expected_id in test_cases:
            actual_id = self.part_detector._extract_video_id(filename)
            self.assertEqual(
                actual_id,
                expected_id,
                f"Failed for {filename}: expected {expected_id}, got {actual_id}",
            )

    def test_extract_video_id_dmm_patterns(self):
        """Test DMM/JAV ID extraction from filename formats."""
        test_cases = [
            ("SSIS-123", "SSIS-123"),
            ("MIDV456", "MIDV456"),
            ("123456_789", "123456_789"),
            ("random_filename_without_id", None),
        ]

        for filename, expected_id in test_cases:
            actual_id = self.part_detector._extract_video_id(filename)
            self.assertEqual(
                actual_id,
                expected_id,
                f"Failed for {filename}: expected {expected_id}, got {actual_id}",
            )

    def test_different_fc2_ids_not_grouped(self):
        """Test that FC2 videos with different IDs are not grouped together."""
        # Create mock video files with different FC2 IDs but similar names
        mock_files = [
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734631_1.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734631_1.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734631_2.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734631_2.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734766.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734766.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
        ]

        # Detect parts for each file
        for video_file in mock_files:
            video_file.detected_parts = self.video_scanner.part_detector.detect_parts(
                video_file.file_path
            )

        # Group the files
        groups = self.video_scanner.group_videos(mock_files)

        # Should create 2 separate groups, not 1
        self.assertEqual(len(groups), 2, f"Expected 2 groups, got {len(groups)}")

        # Find the groups
        group_4734631 = None
        group_4734766 = None

        for group in groups:
            if "4734631" in group.group_name or any(
                "4734631" in f.file_name for f in group.files
            ):
                group_4734631 = group
            elif "4734766" in group.group_name or any(
                "4734766" in f.file_name for f in group.files
            ):
                group_4734766 = group

        # Verify both groups exist
        self.assertIsNotNone(group_4734631, "Group for FC2-PPV-4734631 not found")
        self.assertIsNotNone(group_4734766, "Group for FC2-PPV-4734766 not found")

        # Verify group 4734631 has 2 files (the multi-part files)
        self.assertEqual(
            len(group_4734631.files),
            2,
            f"FC2-PPV-4734631 group should have 2 files, got {len(group_4734631.files)}",
        )

        # Verify group 4734766 has 1 file
        self.assertEqual(
            len(group_4734766.files),
            1,
            f"FC2-PPV-4734766 group should have 1 file, got {len(group_4734766.files)}",
        )

        # Verify no cross-contamination
        for file in group_4734631.files:
            self.assertIn(
                "4734631",
                file.file_name,
                f"Wrong file in 4734631 group: {file.file_name}",
            )

        for file in group_4734766.files:
            self.assertIn(
                "4734766",
                file.file_name,
                f"Wrong file in 4734766 group: {file.file_name}",
            )

    def test_same_id_multi_parts_grouped(self):
        """Test that multi-part files with same ID are correctly grouped."""
        mock_files = [
            VideoFile(
                file_path=Path("test/FC2-PPV-1234567_part1.mp4"),
                folder_name="test",
                file_name="FC2-PPV-1234567_part1.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/FC2-PPV-1234567_part2.mp4"),
                folder_name="test",
                file_name="FC2-PPV-1234567_part2.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
        ]

        # Detect parts for each file
        for video_file in mock_files:
            video_file.detected_parts = self.video_scanner.part_detector.detect_parts(
                video_file.file_path
            )

        # Group the files
        groups = self.video_scanner.group_videos(mock_files)

        # Should create 1 group with 2 files
        self.assertEqual(len(groups), 1, f"Expected 1 group, got {len(groups)}")
        self.assertEqual(
            len(groups[0].files),
            2,
            f"Expected 2 files in group, got {len(groups[0].files)}",
        )

    def test_fc2_mini_dataset_scenario(self):
        """Test the exact scenario from the FC2 mini dataset."""
        mock_files = [
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734631_1.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734631_1.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734631_2.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734631_2.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734631_3.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734631_3.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734631_4.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734631_4.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/hhd800.com@FC2-PPV-4734766.mp4"),
                folder_name="test",
                file_name="hhd800.com@FC2-PPV-4734766.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
            VideoFile(
                file_path=Path("test/T66Y.COM@FC2-PPV-4485258.mp4"),
                folder_name="test",
                file_name="T66Y.COM@FC2-PPV-4485258.mp4",
                detected_parts=[],
                source_hints=[],
                file_size=1000000,
            ),
        ]

        # Detect parts for each file
        for video_file in mock_files:
            video_file.detected_parts = self.video_scanner.part_detector.detect_parts(
                video_file.file_path
            )

        # Group the files
        groups = self.video_scanner.group_videos(mock_files)

        # Should create 3 separate groups:
        # 1. FC2-PPV-4734631 (4 files)
        # 2. FC2-PPV-4734766 (1 file)
        # 3. FC2-PPV-4485258 (1 file)
        self.assertEqual(len(groups), 3, f"Expected 3 groups, got {len(groups)}")

        # Find each group and verify file counts
        group_counts = {}
        for group in groups:
            for file in group.files:
                if "4734631" in file.file_name:
                    group_counts["4734631"] = group_counts.get("4734631", 0) + 1
                elif "4734766" in file.file_name:
                    group_counts["4734766"] = group_counts.get("4734766", 0) + 1
                elif "4485258" in file.file_name:
                    group_counts["4485258"] = group_counts.get("4485258", 0) + 1

        # Verify correct grouping
        self.assertEqual(
            group_counts.get("4734631", 0),
            4,
            f"FC2-PPV-4734631 should have 4 files, got {group_counts.get('4734631', 0)}",
        )
        self.assertEqual(
            group_counts.get("4734766", 0),
            1,
            f"FC2-PPV-4734766 should have 1 file, got {group_counts.get('4734766', 0)}",
        )
        self.assertEqual(
            group_counts.get("4485258", 0),
            1,
            f"FC2-PPV-4485258 should have 1 file, got {group_counts.get('4485258', 0)}",
        )


if __name__ == "__main__":
    unittest.main()
