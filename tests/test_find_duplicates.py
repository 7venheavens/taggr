"""Tests for find_duplicates.py CLI script."""

import os
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from find_duplicates import fix_duplicates, format_size, main
from taggrr.core.duplicate_detector import DuplicateGroup
from taggrr.core.models import SourceType, VideoFile


class TestFormatSize:
    """Test human-readable size formatting."""

    def test_bytes(self):
        """Test byte formatting."""
        assert format_size(100) == "100.0 B"
        assert format_size(1023) == "1023.0 B"

    def test_kilobytes(self):
        """Test kilobyte formatting."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        """Test megabyte formatting."""
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(1024 * 1024 * 2.5) == "2.5 MB"

    def test_gigabytes(self):
        """Test gigabyte formatting."""
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert format_size(1024 * 1024 * 1024 * 10.3) == "10.3 GB"


class TestFixDuplicates:
    """Test fix_duplicates function."""

    def test_no_copies_found(self, capsys):
        """Test handling when no duplicate copies exist."""
        # Create groups with only hardlinks (no copies)
        folder_a = Path("/fake/folder_a")
        folder_b = Path("/fake/folder_b")

        file_a = VideoFile(
            file_path=folder_a / "test.mp4",
            folder_name="folder_a",
            file_name="test.mp4",
            file_size=1000,
        )
        file_b = VideoFile(
            file_path=folder_b / "test.mp4",
            folder_name="folder_b",
            file_name="test.mp4",
            file_size=1000,
        )

        # Group with only hardlinks (no copy_pairs)
        group = DuplicateGroup(
            video_id="TEST-123",
            confidence=0.9,
            source_type=SourceType.DMM,
            folder_a_files=[file_a],
            folder_b_file=file_b,
            hardlink_pairs=[(file_a, file_b)],
            copy_pairs=[],
            total_size=1000,
            wasted_space=0,
        )

        files_fixed, space_freed, hardlinks_created = fix_duplicates(
            [group], auto_confirm=False
        )

        assert files_fixed == 0
        assert space_freed == 0
        assert hardlinks_created == 0

        captured = capsys.readouterr()
        assert "No duplicate copies found to fix" in captured.out

    def test_auto_confirm_replaces_with_hardlink(self, temp_dir):
        """Test that auto-confirm mode replaces copies with hardlinks."""
        # Create real files for testing
        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        # Create copy files (not hardlinked)
        file_a_path = folder_a / "ABC-123.mp4"
        file_b_path = folder_b / "ABC-123.mp4"
        file_a_path.write_bytes(b"x" * 2000)
        file_b_path.write_bytes(b"x" * 2000)

        file_a = VideoFile(
            file_path=file_a_path,
            folder_name="folder_a",
            file_name="ABC-123.mp4",
            file_size=2000,
        )
        file_b = VideoFile(
            file_path=file_b_path,
            folder_name="folder_b",
            file_name="ABC-123.mp4",
            file_size=2000,
        )

        # Create group with copy pairs
        group = DuplicateGroup(
            video_id="ABC123",
            confidence=0.8,
            source_type=SourceType.DMM,
            folder_a_files=[file_a],
            folder_b_file=file_b,
            hardlink_pairs=[],
            copy_pairs=[(file_a, file_b)],
            total_size=2000,
            wasted_space=2000,
        )

        # Before fix, both files exist and are NOT hardlinked
        assert file_a_path.exists()
        assert file_b_path.exists()
        assert file_a_path.stat().st_ino != file_b_path.stat().st_ino

        # Run fix with auto-confirm
        files_fixed, space_freed, hardlinks_created = fix_duplicates(
            [group], auto_confirm=True
        )

        # Check results
        assert files_fixed == 1
        assert space_freed == 2000
        assert hardlinks_created == 1

        # Both files should exist and now be hardlinked
        assert file_a_path.exists()
        assert file_b_path.exists()
        assert file_a_path.stat().st_ino == file_b_path.stat().st_ino

    def test_interactive_mode_with_confirmation(self, temp_dir):
        """Test interactive mode when user confirms replacement."""
        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        file_a_path = folder_a / "TEST-456.mp4"
        file_b_path = folder_b / "TEST-456.mp4"
        file_a_path.write_bytes(b"y" * 1500)
        file_b_path.write_bytes(b"y" * 1500)

        file_a = VideoFile(
            file_path=file_a_path,
            folder_name="folder_a",
            file_name="TEST-456.mp4",
            file_size=1500,
        )
        file_b = VideoFile(
            file_path=file_b_path,
            folder_name="folder_b",
            file_name="TEST-456.mp4",
            file_size=1500,
        )

        group = DuplicateGroup(
            video_id="TEST456",
            confidence=0.85,
            source_type=SourceType.GENERIC,
            folder_a_files=[file_a],
            folder_b_file=file_b,
            hardlink_pairs=[],
            copy_pairs=[(file_a, file_b)],
            total_size=1500,
            wasted_space=1500,
        )

        # Mock click.confirm to return True (user confirms)
        with patch("find_duplicates.click.confirm", return_value=True):
            files_fixed, space_freed, hardlinks_created = fix_duplicates(
                [group], auto_confirm=False
            )

        assert files_fixed == 1
        assert space_freed == 1500
        assert hardlinks_created == 1
        assert file_a_path.exists()
        assert file_b_path.exists()
        assert file_a_path.stat().st_ino == file_b_path.stat().st_ino

    def test_interactive_mode_with_rejection(self, temp_dir):
        """Test interactive mode when user rejects replacement."""
        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        file_a_path = folder_a / "KEEP-789.mp4"
        file_b_path = folder_b / "KEEP-789.mp4"
        file_a_path.write_bytes(b"z" * 1000)
        file_b_path.write_bytes(b"z" * 1000)

        file_a = VideoFile(
            file_path=file_a_path,
            folder_name="folder_a",
            file_name="KEEP-789.mp4",
            file_size=1000,
        )
        file_b = VideoFile(
            file_path=file_b_path,
            folder_name="folder_b",
            file_name="KEEP-789.mp4",
            file_size=1000,
        )

        group = DuplicateGroup(
            video_id="KEEP789",
            confidence=0.75,
            source_type=SourceType.DMM,
            folder_a_files=[file_a],
            folder_b_file=file_b,
            hardlink_pairs=[],
            copy_pairs=[(file_a, file_b)],
            total_size=1000,
            wasted_space=1000,
        )

        # Store original inodes
        orig_ino_a = file_a_path.stat().st_ino
        orig_ino_b = file_b_path.stat().st_ino

        # Mock click.confirm to return False (user rejects)
        with patch("find_duplicates.click.confirm", return_value=False):
            files_fixed, space_freed, hardlinks_created = fix_duplicates(
                [group], auto_confirm=False
            )

        # Nothing should be changed
        assert files_fixed == 0
        assert space_freed == 0
        assert hardlinks_created == 0
        assert file_a_path.exists()
        assert file_b_path.exists()
        # Inodes should be unchanged (still not hardlinked)
        assert file_a_path.stat().st_ino == orig_ino_a
        assert file_b_path.stat().st_ino == orig_ino_b

    def test_multiple_groups_mixed_decisions(self, temp_dir):
        """Test processing multiple groups with mixed user decisions."""
        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        # Create two groups
        files_to_create = [
            ("GROUP1-111.mp4", "GROUP1111", 1000),
            ("GROUP2-222.mp4", "GROUP2222", 2000),
        ]

        groups = []
        for filename, video_id, size in files_to_create:
            file_a_path = folder_a / filename
            file_b_path = folder_b / filename
            file_a_path.write_bytes(b"x" * size)
            file_b_path.write_bytes(b"x" * size)

            file_a = VideoFile(
                file_path=file_a_path,
                folder_name="folder_a",
                file_name=filename,
                file_size=size,
            )
            file_b = VideoFile(
                file_path=file_b_path,
                folder_name="folder_b",
                file_name=filename,
                file_size=size,
            )

            group = DuplicateGroup(
                video_id=video_id,
                confidence=0.8,
                source_type=SourceType.DMM,
                folder_a_files=[file_a],
                folder_b_file=file_b,
                hardlink_pairs=[],
                copy_pairs=[(file_a, file_b)],
                total_size=size,
                wasted_space=size,
            )
            groups.append(group)

        # Mock user confirming first, rejecting second
        with patch("find_duplicates.click.confirm", side_effect=[True, False]):
            files_fixed, space_freed, hardlinks_created = fix_duplicates(
                groups, auto_confirm=False
            )

        assert files_fixed == 1
        assert space_freed == 1000
        assert hardlinks_created == 1

        # First group's files should now be hardlinked
        file1_a = folder_a / "GROUP1-111.mp4"
        file1_b = folder_b / "GROUP1-111.mp4"
        assert file1_a.exists()
        assert file1_b.exists()
        assert file1_a.stat().st_ino == file1_b.stat().st_ino

        # Second group's files should still be separate copies
        file2_a = folder_a / "GROUP2-222.mp4"
        file2_b = folder_b / "GROUP2-222.mp4"
        assert file2_a.exists()
        assert file2_b.exists()
        assert file2_a.stat().st_ino != file2_b.stat().st_ino

    def test_error_handling(self, temp_dir, capsys):
        """Test handling of errors during hardlink creation."""
        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        file_a_path = folder_a / "ERROR-999.mp4"
        file_b_path = folder_b / "ERROR-999.mp4"
        file_a_path.write_bytes(b"content")
        file_b_path.write_bytes(b"content")

        file_a = VideoFile(
            file_path=file_a_path,
            folder_name="folder_a",
            file_name="ERROR-999.mp4",
            file_size=500,
        )
        file_b = VideoFile(
            file_path=file_b_path,
            folder_name="folder_b",
            file_name="ERROR-999.mp4",
            file_size=500,
        )

        group = DuplicateGroup(
            video_id="ERROR999",
            confidence=0.9,
            source_type=SourceType.GENERIC,
            folder_a_files=[file_a],
            folder_b_file=file_b,
            hardlink_pairs=[],
            copy_pairs=[(file_a, file_b)],
            total_size=500,
            wasted_space=500,
        )

        # Mock unlink to raise an exception
        original_unlink = Path.unlink

        def mock_unlink(self, *args, **kwargs):
            if self == file_b_path:
                raise PermissionError("Permission denied")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", mock_unlink):
            files_fixed, space_freed, hardlinks_created = fix_duplicates(
                [group], auto_confirm=True
            )

        # Should handle error gracefully
        assert files_fixed == 0
        assert space_freed == 0
        assert hardlinks_created == 0

        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_skips_hardlink_groups(self, temp_dir, capsys):
        """Test that hardlink-only groups are skipped."""
        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        # Create hardlinked files
        original = folder_b / "FC2-PPV-555555.mp4"
        original.write_bytes(b"hardlink content")
        hardlink = folder_a / "fc2-ppv-555555.mp4"
        os.link(original, hardlink)

        file_a = VideoFile(
            file_path=hardlink,
            folder_name="folder_a",
            file_name="fc2-ppv-555555.mp4",
            file_size=1000,
        )
        file_b = VideoFile(
            file_path=original,
            folder_name="folder_b",
            file_name="FC2-PPV-555555.mp4",
            file_size=1000,
        )

        # Group with hardlinks only
        hardlink_group = DuplicateGroup(
            video_id="555555",
            confidence=0.95,
            source_type=SourceType.FC2,
            folder_a_files=[file_a],
            folder_b_file=file_b,
            hardlink_pairs=[(file_a, file_b)],
            copy_pairs=[],
            total_size=1000,
            wasted_space=0,
        )

        files_fixed, space_freed, hardlinks_created = fix_duplicates(
            [hardlink_group], auto_confirm=True
        )

        # No files should be changed
        assert files_fixed == 0
        assert space_freed == 0
        assert hardlinks_created == 0
        assert original.exists()
        assert hardlink.exists()

        # When there are only hardlink groups and no copy groups,
        # the message says "No duplicate copies found"
        captured = capsys.readouterr()
        assert "No duplicate copies found to fix" in captured.out


class TestCLIIntegration:
    """Test CLI command integration."""

    def test_help_message(self):
        """Test that help message displays correctly."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "Find duplicate videos" in result.output
        assert "--fix" in result.output
        assert "--confirm" in result.output

    def test_confirm_requires_fix(self, temp_dir):
        """Test that --confirm can only be used with --fix."""
        runner = CliRunner()

        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        result = runner.invoke(
            main, [str(folder_a), str(folder_b), "--confirm"]
        )

        assert "Error: --confirm can only be used with --fix" in result.output

    def test_fix_mode_displays_correctly(self, temp_dir):
        """Test that fix mode displays proper header."""
        runner = CliRunner()

        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        # Create a duplicate copy
        file_a = folder_a / "TEST-100.mp4"
        file_b = folder_b / "TEST-100.mp4"
        file_a.write_bytes(b"test content")
        file_b.write_bytes(b"test content")

        result = runner.invoke(
            main, [str(folder_a), str(folder_b), "--fix", "--confirm"]
        )

        assert "FIX MODE (auto-confirm)" in result.output
        assert "FIX SUMMARY" in result.output

    def test_display_mode_without_fix(self, temp_dir):
        """Test normal display mode without fix flag."""
        runner = CliRunner()

        folder_a = temp_dir / "folder_a"
        folder_b = temp_dir / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        # Create a duplicate
        file_a = folder_a / "ABC-200.mp4"
        file_b = folder_b / "ABC-200.mp4"
        file_a.write_bytes(b"content")
        file_b.write_bytes(b"content")

        result = runner.invoke(main, [str(folder_a), str(folder_b)])

        assert result.exit_code == 0
        assert "Video Duplicate Detection" in result.output
        assert "SUMMARY" in result.output
        # Should not be in fix mode
        assert "FIX MODE" not in result.output
