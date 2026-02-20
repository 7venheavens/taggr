"""Tests for find_duplicates.py CLI script."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

# find_duplicates.py lives in scripts/, not in the package
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from find_duplicates import fix_duplicates, format_size, main  # noqa: E402
from taggrr.core.duplicate_detector import DuplicateSet  # noqa: E402
from taggrr.core.models import SourceType, VideoFile  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _vf(path: Path, size: int = 1000) -> VideoFile:
    """Create a VideoFile pointing at the given path."""
    return VideoFile(
        file_path=path,
        folder_name=path.parent.name,
        file_name=path.name,
        file_size=size,
    )


def _make_set(
    source_file: VideoFile,
    copy_files: list[VideoFile] | None = None,
    hardlink_files: list[VideoFile] | None = None,
    video_id: str = "TEST123",
) -> DuplicateSet:
    """Build a DuplicateSet from a source file plus copy/hardlink files."""
    copy_files = copy_files or []
    hardlink_files = hardlink_files or []

    files_by_dir: dict[Path, list[VideoFile]] = {
        source_file.file_path.parent: [source_file]
    }
    for f in copy_files + hardlink_files:
        files_by_dir.setdefault(f.file_path.parent, []).append(f)

    return DuplicateSet(
        match_type="name",
        video_id=video_id,
        confidence=0.9,
        source_type=SourceType.DMM,
        file_size=None,
        file_hash=None,
        files_by_dir=files_by_dir,
        source_file=source_file,
        hardlink_pairs=[(source_file, f) for f in hardlink_files],
        copy_pairs=[(source_file, f) for f in copy_files],
        wasted_space=sum(f.file_size or 0 for f in copy_files),
    )


# ---------------------------------------------------------------------------
# format_size
# ---------------------------------------------------------------------------


class TestFormatSize:
    def test_bytes(self):
        assert format_size(100) == "100.0 B"
        assert format_size(1023) == "1023.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self):
        assert format_size(1024**3) == "1.0 GB"


# ---------------------------------------------------------------------------
# fix_duplicates
# ---------------------------------------------------------------------------


class TestFixDuplicates:
    """Tests for the fix_duplicates function."""

    def test_hardlink_only_set_produces_no_work(self, temp_dir, capsys):
        """A set with only hardlinks is already optimal; nothing to fix."""
        src = temp_dir / "src" / "test.mp4"
        tgt = temp_dir / "tgt" / "test.mp4"
        src.parent.mkdir()
        tgt.parent.mkdir()
        src.write_bytes(b"video")
        os.link(src, tgt)

        dup_set = _make_set(_vf(src, 5), hardlink_files=[_vf(tgt, 5)])
        files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=True)

        assert files_fixed == 0
        assert space_freed == 0
        assert "No fixable" in capsys.readouterr().out

    def test_auto_confirm_replaces_copy_with_hardlink(self, temp_dir):
        """auto_confirm=True replaces a copy in the target with a hardlink."""
        src_path = temp_dir / "src" / "ABC-123.mp4"
        tgt_path = temp_dir / "tgt" / "ABC-123.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes(b"x" * 2000)
        tgt_path.write_bytes(b"x" * 2000)

        dup_set = _make_set(_vf(src_path, 2000), copy_files=[_vf(tgt_path, 2000)])
        files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=True)

        assert files_fixed == 1
        assert space_freed == 2000
        assert src_path.exists() and tgt_path.exists()
        assert src_path.samefile(tgt_path)

    def test_interactive_confirm_replaces_copy(self, temp_dir):
        """User confirming the interactive prompt causes the hardlink to be created."""
        src_path = temp_dir / "src" / "DEF-456.mp4"
        tgt_path = temp_dir / "tgt" / "DEF-456.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes(b"y" * 1500)
        tgt_path.write_bytes(b"y" * 1500)

        dup_set = _make_set(_vf(src_path, 1500), copy_files=[_vf(tgt_path, 1500)])
        with patch("find_duplicates.click.confirm", return_value=True):
            files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=False)

        assert files_fixed == 1
        assert src_path.samefile(tgt_path)

    def test_interactive_reject_leaves_files_unchanged(self, temp_dir):
        """User rejecting the prompt leaves both files untouched."""
        src_path = temp_dir / "src" / "GHI-789.mp4"
        tgt_path = temp_dir / "tgt" / "GHI-789.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes(b"z" * 1000)
        tgt_path.write_bytes(b"z" * 1000)
        original_ino = tgt_path.stat().st_ino

        dup_set = _make_set(_vf(src_path, 1000), copy_files=[_vf(tgt_path, 1000)])
        with patch("find_duplicates.click.confirm", return_value=False):
            files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=False)

        assert files_fixed == 0
        assert space_freed == 0
        assert tgt_path.stat().st_ino == original_ino

    def test_size_mismatch_skipped(self, temp_dir, capsys):
        """Files with different sizes are always skipped for safety."""
        src_path = temp_dir / "src" / "SIZE-001.mp4"
        tgt_path = temp_dir / "tgt" / "SIZE-001.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes(b"x" * 1000)
        tgt_path.write_bytes(b"x" * 2000)  # different size

        dup_set = _make_set(_vf(src_path, 1000), copy_files=[_vf(tgt_path, 2000)])
        files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=True)

        assert files_fixed == 0
        assert "mismatch" in capsys.readouterr().out.lower()

    def test_quick_hash_mismatch_skipped(self, temp_dir, capsys):
        """Same-size files with different content are skipped by quick-hash check."""
        src_path = temp_dir / "src" / "HASH-001.mp4"
        tgt_path = temp_dir / "tgt" / "HASH-001.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes((b"A" * 1024) + (b"B" * 1024))
        tgt_path.write_bytes((b"A" * 1024) + (b"C" * 1024))
        original_ino = tgt_path.stat().st_ino

        dup_set = _make_set(_vf(src_path, 2048), copy_files=[_vf(tgt_path, 2048)])
        files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=True)

        assert files_fixed == 0
        assert space_freed == 0
        assert "quick-hash mismatch" in capsys.readouterr().out.lower()
        assert tgt_path.stat().st_ino == original_ino

    def test_multiple_copies_all_hardlinked(self, temp_dir):
        """All copy pairs in a set are processed and hardlinked."""
        src_path = temp_dir / "src" / "ABC-999.mp4"
        tgt1_path = temp_dir / "tgt1" / "ABC-999.mp4"
        tgt2_path = temp_dir / "tgt2" / "ABC-999.mp4"
        for p in (src_path, tgt1_path, tgt2_path):
            p.parent.mkdir(parents=True)
            p.write_bytes(b"x" * 1000)

        dup_set = _make_set(
            _vf(src_path, 1000),
            copy_files=[_vf(tgt1_path, 1000), _vf(tgt2_path, 1000)],
        )
        files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=True)

        assert files_fixed == 2
        assert space_freed == 2000
        assert src_path.samefile(tgt1_path)
        assert src_path.samefile(tgt2_path)

    def test_error_during_unlink_handled_gracefully(self, temp_dir, capsys):
        """An OS error during unlink is caught and reported; fix count stays 0."""
        src_path = temp_dir / "src" / "ERR-001.mp4"
        tgt_path = temp_dir / "tgt" / "ERR-001.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes(b"content")
        tgt_path.write_bytes(b"content")

        dup_set = _make_set(_vf(src_path, 7), copy_files=[_vf(tgt_path, 7)])
        original_unlink = Path.unlink

        def fail_tgt_unlink(self, *args, **kwargs):
            if self == tgt_path:
                raise PermissionError("Permission denied")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", fail_tgt_unlink):
            files_fixed, space_freed = fix_duplicates([dup_set], auto_confirm=True)

        assert files_fixed == 0
        assert "Error" in capsys.readouterr().out

    def test_returns_two_tuple(self, temp_dir):
        """fix_duplicates returns (files_fixed, space_freed) — not a three-tuple."""
        src_path = temp_dir / "src" / "XYZ-001.mp4"
        tgt_path = temp_dir / "tgt" / "XYZ-001.mp4"
        src_path.parent.mkdir()
        tgt_path.parent.mkdir()
        src_path.write_bytes(b"data")
        tgt_path.write_bytes(b"data")

        dup_set = _make_set(_vf(src_path, 4), copy_files=[_vf(tgt_path, 4)])
        result = fix_duplicates([dup_set], auto_confirm=True)

        assert len(result) == 2


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    """End-to-end tests via Click's test runner."""

    def test_help_shows_key_options(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Find duplicate videos" in result.output
        assert "--fix" in result.output
        assert "--confirm" in result.output
        assert "--content-match" in result.output

    def test_confirm_without_fix_is_error(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        result = CliRunner().invoke(main, [str(source), str(target), "--confirm"])
        assert "--confirm can only be used with --fix" in result.output

    def test_show_flags_incompatible_with_fix(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        result = CliRunner().invoke(
            main, [str(source), str(target), "--fix", "--show-copies-only"]
        )
        assert "cannot be used with --fix" in result.output

    def test_display_mode_shows_summary(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-200.mp4").write_bytes(b"content")
        (target / "ABC-200.mp4").write_bytes(b"content")

        result = CliRunner().invoke(main, [str(source), str(target)])
        assert result.exit_code == 0
        assert "Video Duplicate Detection" in result.output
        assert "SUMMARY" in result.output
        assert "FIX MODE" not in result.output

    def test_fix_with_autoconfirm_creates_hardlink(self, temp_dir):
        """--fix --confirm replaces the target copy with a hardlink to source."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        src_file = source / "TEST-100.mp4"
        tgt_file = target / "TEST-100.mp4"
        src_file.write_bytes(b"test content")
        tgt_file.write_bytes(b"test content")

        result = CliRunner().invoke(
            main, [str(source), str(target), "--fix", "--confirm"]
        )
        assert "FIX SUMMARY" in result.output
        assert src_file.samefile(tgt_file)

    def test_fix_aborted_when_user_declines_global_prompt(self, temp_dir):
        """Without --confirm, declining the global prompt aborts the fix."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        src_file = source / "ABC-300.mp4"
        tgt_file = target / "ABC-300.mp4"
        src_file.write_bytes(b"video")
        tgt_file.write_bytes(b"video")
        original_ino = tgt_file.stat().st_ino

        # Simulate user typing "n" at the global confirmation prompt
        result = CliRunner().invoke(
            main, [str(source), str(target), "--fix"], input="n\n"
        )
        assert "Aborted" in result.output
        assert tgt_file.stat().st_ino == original_ino

    def test_multi_target_cli(self, temp_dir):
        """Multiple target directories are accepted and shown in the summary."""
        source = temp_dir / "source"
        target1 = temp_dir / "target1"
        target2 = temp_dir / "target2"
        for d in (source, target1, target2):
            d.mkdir()
        (source / "ABC-300.mp4").write_bytes(b"v")
        (target1 / "ABC-300.mp4").write_bytes(b"v")
        (target2 / "ABC-300.mp4").write_bytes(b"v")

        result = CliRunner().invoke(
            main, [str(source), str(target1), str(target2)]
        )
        assert result.exit_code == 0
        assert "SUMMARY" in result.output
        assert "Duplicate Set" in result.output

    def test_content_match_flag_accepted(self, temp_dir):
        """--content-match flag is accepted without error."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        result = CliRunner().invoke(
            main, [str(source), str(target), "--content-match"]
        )
        assert result.exit_code == 0
        assert "Content match:   yes" in result.output

    def test_json_export(self, temp_dir):
        """--output-json writes a valid JSON file with the expected structure."""
        import json

        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"content")
        (target / "ABC-123.mp4").write_bytes(b"content")

        out_file = temp_dir / "report.json"
        CliRunner().invoke(
            main, [str(source), str(target), f"--output-json={out_file}"]
        )

        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "duplicate_sets" in data
        assert len(data["duplicate_sets"]) == 1
        entry = data["duplicate_sets"][0]
        assert "video_id" in entry
        assert "match_type" in entry
        assert "hardlink_pairs" in entry
        assert "copy_pairs" in entry
        assert "files_by_dir" in entry
        assert "source_file" in entry
