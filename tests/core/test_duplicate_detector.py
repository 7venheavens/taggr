"""Tests for duplicate video file detection."""

import os

from taggrr.core.duplicate_detector import (
    DuplicateDetector,
    _group_files_by_inode,
    are_hardlinks,
    compute_hash,
    get_unmatched_files,
)
from taggrr.core.models import SourceType, VideoFile


class TestHardlinkDetection:
    """Test hardlink detection utility."""

    def test_hardlinks_detected(self, temp_dir):
        """Hardlinked files are identified as the same underlying file."""
        original = temp_dir / "file1.mp4"
        original.write_bytes(b"video content")
        hardlink = temp_dir / "file2.mp4"
        os.link(original, hardlink)

        assert are_hardlinks(original, hardlink)

    def test_copies_not_detected_as_hardlinks(self, temp_dir):
        """True copies (separate inodes) are not identified as hardlinks."""
        file1 = temp_dir / "file1.mp4"
        file2 = temp_dir / "file2.mp4"
        file1.write_bytes(b"video content")
        file2.write_bytes(b"video content")

        assert not are_hardlinks(file1, file2)

    def test_missing_file_returns_false(self, temp_dir):
        """Missing files are handled gracefully and return False."""
        existing = temp_dir / "exists.mp4"
        missing = temp_dir / "missing.mp4"
        existing.write_bytes(b"content")

        assert not are_hardlinks(existing, missing)
        assert not are_hardlinks(missing, existing)


class TestComputeHash:
    """Test SHA256 hash computation."""

    def test_identical_content_same_hash(self, temp_dir):
        content = b"video data"
        f1, f2 = temp_dir / "a.mp4", temp_dir / "b.mp4"
        f1.write_bytes(content)
        f2.write_bytes(content)
        assert compute_hash(f1) == compute_hash(f2)

    def test_different_content_different_hash(self, temp_dir):
        f1, f2 = temp_dir / "a.mp4", temp_dir / "b.mp4"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert compute_hash(f1) != compute_hash(f2)

    def test_result_is_valid_hex_string(self, temp_dir):
        f = temp_dir / "file.mp4"
        f.write_bytes(b"some data")
        h = compute_hash(f)
        assert len(h) == 64
        int(h, 16)  # raises ValueError if not valid hex


class TestIdNormalization:
    """Normalization is consistent across all source types."""

    def test_fc2_case_insensitive(self, temp_dir):
        """fc2-ppv-1234567 and FC2-PPV-1234567 match."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "fc2-ppv-1234567.mp4").write_bytes(b"video")
        (target / "FC2-PPV-1234567.mp4").write_bytes(b"copy")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 1

    def test_dmm_dashes_stripped(self, temp_dir):
        """MIDE-123 and mide-123 match (dashes stripped for all types)."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "MIDE-123.mp4").write_bytes(b"video")
        (target / "mide-123.mkv").write_bytes(b"copy")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 1
        assert sets[0].source_type == SourceType.DMM

    def test_underscores_stripped(self, temp_dir):
        """MIDE_123 and MIDE-123 normalise to the same ID and match."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "MIDE-123.mp4").write_bytes(b"video")
        (target / "MIDE_123.mp4").write_bytes(b"copy")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 1
        assert sets[0].source_type == SourceType.DMM


class TestDuplicateDetector:
    """Core duplicate detection behaviour."""

    def test_fc2_pattern_matching(self, temp_dir):
        """FC2-PPV files detected by ID across directories."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "fc2-ppv-1234567.mp4").write_bytes(b"video")
        (target / "FC2-PPV-1234567.mp4").write_bytes(b"copy")

        sets = DuplicateDetector().scan_multiple(source, [target])

        assert len(sets) == 1
        assert sets[0].source_type == SourceType.FC2
        assert sets[0].confidence >= 0.80
        assert sets[0].match_type == "name"

    def test_multiple_targets(self, temp_dir):
        """A single source file duplicated across two targets produces one set."""
        source = temp_dir / "source"
        target1 = temp_dir / "target1"
        target2 = temp_dir / "target2"
        for d in (source, target1, target2):
            d.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"video")
        (target1 / "ABC-123.mp4").write_bytes(b"copy 1")
        (target2 / "ABC-123.mp4").write_bytes(b"copy 2")

        sets = DuplicateDetector().scan_multiple(source, [target1, target2])

        assert len(sets) == 1
        s = sets[0]
        assert len(s.files_by_dir) == 3
        assert s.source_file is not None
        assert s.source_file.file_path.parent.resolve() == source.resolve()
        assert len(s.copy_pairs) == 2

    def test_source_only_file_not_reported(self, temp_dir):
        """Files that exist only in the source dir are not reported."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"video A")
        (source / "XYZ-999.mp4").write_bytes(b"video B")  # source-only
        (target / "ABC-123.mp4").write_bytes(b"copy A")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 1

    def test_no_matches_returns_empty(self, temp_dir):
        """Non-matching files produce no duplicate sets."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"video")
        (target / "XYZ-999.mp4").write_bytes(b"video")

        assert DuplicateDetector().scan_multiple(source, [target]) == []

    def test_empty_directories(self, temp_dir):
        """Empty directories produce no results."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        assert DuplicateDetector().scan_multiple(source, [target]) == []

    def test_hardlink_detected_as_hardlink(self, temp_dir):
        """A hardlinked target file is classified as HARDLINK."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        src_file = source / "fc2-ppv-111111.mp4"
        src_file.write_bytes(b"x" * 1000)
        os.link(src_file, target / "FC2-PPV-111111.mp4")

        sets = DuplicateDetector().scan_multiple(source, [target])

        assert len(sets) == 1
        s = sets[0]
        assert s.status == "HARDLINK"
        assert len(s.hardlink_pairs) == 1
        assert len(s.copy_pairs) == 0
        assert s.wasted_space == 0

    def test_copy_status_and_wasted_space(self, temp_dir):
        """A true copy is COPY status; wasted_space = copy file size."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-456.mp4").write_bytes(b"x" * 1500)
        (target / "abc-456.mp4").write_bytes(b"x" * 1500)

        sets = DuplicateDetector().scan_multiple(source, [target])

        assert len(sets) == 1
        s = sets[0]
        assert s.status == "COPY"
        # wasted_space is the target (copy) file size, not the source size
        assert s.wasted_space == 1500

    def test_mixed_hardlink_and_copy(self, temp_dir):
        """When source has multiple target copies, some HL and some copy → MIXED."""
        source = temp_dir / "source"
        target1 = temp_dir / "target1"
        target2 = temp_dir / "target2"
        for d in (source, target1, target2):
            d.mkdir()

        src_file = source / "ABC-789.mp4"
        src_file.write_bytes(b"x" * 2000)
        os.link(src_file, target1 / "ABC-789.mp4")         # hardlink
        (target2 / "ABC-789.mp4").write_bytes(b"x" * 2000)  # true copy

        sets = DuplicateDetector().scan_multiple(source, [target1, target2])

        assert len(sets) == 1
        s = sets[0]
        assert s.status == "MIXED"
        assert len(s.hardlink_pairs) == 1
        assert len(s.copy_pairs) == 1
        assert s.wasted_space == 2000  # only the copy wastes space

    def test_confidence_threshold_filtering(self, temp_dir):
        """Low-confidence matches are filtered by min_confidence."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        # Generic 8-digit pattern has low confidence (~0.40)
        (source / "12345678.mp4").write_bytes(b"video")
        (target / "12345678.mkv").write_bytes(b"video")

        detector = DuplicateDetector()
        assert len(detector.scan_multiple(source, [target], min_confidence=0.7)) == 0
        assert len(detector.scan_multiple(source, [target], min_confidence=0.3)) == 1

    def test_output_sorted_deterministically(self, temp_dir):
        """Sets are returned in a consistent, sorted order."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        for name in ("ZZZ-999.mp4", "AAA-001.mp4", "MMM-500.mp4"):
            (source / name).write_bytes(b"video")
            (target / name).write_bytes(b"copy")

        sets = DuplicateDetector().scan_multiple(source, [target])
        ids = [s.video_id for s in sets]
        assert ids == sorted(ids)

    def test_source_file_points_to_source_dir(self, temp_dir):
        """The source_file in each set points to the file in the source directory."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"video")
        (target / "ABC-123.mp4").write_bytes(b"copy")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert sets[0].source_file is not None
        assert sets[0].source_file.file_path.parent.resolve() == source.resolve()


class TestContentMatching:
    """Content-based (size + SHA256) duplicate detection."""

    def test_content_match_finds_identical_unnamed_files(self, temp_dir):
        """Files with the same content but no ID match are found via --content-match."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        content = b"identical video without a recognizable ID pattern" * 10
        (source / "randomfile.mp4").write_bytes(content)
        (target / "differentname.mp4").write_bytes(content)

        sets = DuplicateDetector().scan_multiple(
            source, [target], content_match=True
        )
        content_sets = [s for s in sets if s.match_type in ("content", "name+content")]
        assert len(content_sets) >= 1

    def test_content_match_ignores_different_content(self, temp_dir):
        """Files with different content are not grouped as content duplicates."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "unique1.mp4").write_bytes(b"content A" * 100)
        (target / "unique2.mp4").write_bytes(b"content B" * 100)

        sets = DuplicateDetector().scan_multiple(
            source, [target], content_match=True
        )
        content_sets = [s for s in sets if s.match_type == "content"]
        assert len(content_sets) == 0

    def test_name_and_content_match_annotated(self, temp_dir):
        """When name-matched files also have identical content, match_type = name+content."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        content = b"x" * 5000
        (source / "ABC-123.mp4").write_bytes(content)
        (target / "ABC-123.mp4").write_bytes(content)

        sets = DuplicateDetector().scan_multiple(
            source, [target], content_match=True
        )
        assert len(sets) == 1
        assert sets[0].match_type == "name+content"
        assert sets[0].file_hash is not None
        assert sets[0].file_size == 5000

    def test_name_match_with_different_content_stays_name(self, temp_dir):
        """Name-matched files with different content stay as name-only match."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"content version 1")
        (target / "ABC-123.mp4").write_bytes(b"content version 2 different")

        sets = DuplicateDetector().scan_multiple(
            source, [target], content_match=True
        )
        assert len(sets) == 1
        assert sets[0].match_type == "name"
        assert sets[0].file_hash is None

    def test_content_match_disabled_by_default(self, temp_dir):
        """Without content_match=True, identical unnamed files are not found."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        content = b"video without any recognizable ID " * 100
        (source / "noname1.mp4").write_bytes(content)
        (target / "noname2.mp4").write_bytes(content)

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 0

    def test_content_only_set_with_no_source_is_no_source(self, temp_dir):
        """Content duplicates found only in target dirs have NO_SOURCE status."""
        source = temp_dir / "source"
        target1 = temp_dir / "target1"
        target2 = temp_dir / "target2"
        for d in (source, target1, target2):
            d.mkdir()

        content = b"identical content no id" * 50
        (target1 / "copy_a.mp4").write_bytes(content)
        (target2 / "copy_b.mp4").write_bytes(content)
        # source dir is empty

        sets = DuplicateDetector().scan_multiple(
            source, [target1, target2], content_match=True
        )
        no_source = [s for s in sets if s.status == "NO_SOURCE"]
        assert len(no_source) >= 1


class TestPartAwareMatching:
    """Part-aware duplicate grouping by filename suffixes."""

    def test_numeric_parts_match_pt_variants(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        for part in (1, 2, 3, 4):
            (source / f"vrkm-646-{part}.mp4").write_bytes(f"src-{part}".encode())
            (target / f"VRKM-646-pt{part}.mp4").write_bytes(f"tgt-{part}".encode())

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 4
        assert all(s.video_id and "VRKM646" in s.video_id for s in sets)

    def test_letter_suffix_parts_supported(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        (source / "ABC-123-A.mp4").write_bytes(b"a-src")
        (target / "ABC-123_A.mp4").write_bytes(b"a-tgt")
        (source / "ABC-123-B.mp4").write_bytes(b"b-src")
        (target / "ABC-123_B.mp4").write_bytes(b"b-tgt")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 2
        ids = sorted(s.video_id for s in sets)
        assert ids == ["ABC123 [A]", "ABC123 [B]"]

    def test_option_suffix_supported(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        (source / "ABC-123-option.mp4").write_bytes(b"src")
        (target / "ABC-123_option.mp4").write_bytes(b"tgt")

        sets = DuplicateDetector().scan_multiple(source, [target])
        assert len(sets) == 1
        assert sets[0].video_id == "ABC123 [OPTION]"

    def test_folder_id_does_not_pull_unrelated_file(self, temp_dir):
        source = temp_dir / "source" / "VRKM-646"
        target = temp_dir / "target"
        source.mkdir(parents=True)
        target.mkdir()

        (source / "promo clip.mp4").write_bytes(b"noise")
        (target / "VRKM-646-pt1.mp4").write_bytes(b"video")

        sets = DuplicateDetector().scan_multiple(source.parent, [target])
        assert len(sets) == 0


class TestUncenProviderIds:
    """Provider-specific ID extraction for uncensored sources."""

    def test_1pon_ids_are_grouped_by_date_id(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        (source / "[BT]102116_410-1pon-1080p.mp4").write_bytes(b"a")
        (source / "[BT]100616_399-1pon-1080p.mp4").write_bytes(b"b")
        (target / "102116_410-1pon-1080p.mp4").write_bytes(b"c")
        (target / "100616_399-1pon-1080p.mp4").write_bytes(b"d")

        sets = DuplicateDetector().scan_multiple(source, [target], min_confidence=0.5)
        ids = sorted(s.video_id for s in sets)
        assert ids == ["100616399", "102116410"]

    def test_caribpr_ids_prefer_date_id_not_quality_token(self, temp_dir):
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()

        (source / "[BT]121616_005-caribpr-1080p.mp4").write_bytes(b"a")
        (source / "[BT]123016_005-caribpr-1080p.mp4").write_bytes(b"b")
        (target / "121616_005-caribpr-1080p.mp4").write_bytes(b"c")
        (target / "123016_005-caribpr-1080p.mp4").write_bytes(b"d")

        sets = DuplicateDetector().scan_multiple(source, [target], min_confidence=0.5)
        ids = sorted(s.video_id for s in sets)
        assert ids == ["121616005", "123016005"]
        assert all("RIBPR1080" not in (s.video_id or "") for s in sets)


class TestInodeChains:
    """Inode chain grouping within a duplicate set."""

    def test_single_copy_has_two_chains(self, temp_dir):
        """One source + one copy produces source chain and one copy chain."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        (source / "ABC-123.mp4").write_bytes(b"x" * 1000)
        (target / "ABC-123.mp4").write_bytes(b"x" * 1000)

        sets = DuplicateDetector().scan_multiple(source, [target])
        s = sets[0]

        assert len(s.inode_chains) == 2
        # Chain 0 contains the source file
        src_paths = {f.file_path for f in s.inode_chains[0]}
        assert s.source_file.file_path in src_paths
        # Chain 1 is the copy
        assert len(s.inode_chains[1]) == 1

    def test_hardlinked_target_is_in_source_chain(self, temp_dir):
        """A target file hardlinked to source appears in chain 0, no copy chains."""
        source = temp_dir / "source"
        target = temp_dir / "target"
        source.mkdir()
        target.mkdir()
        src_file = source / "fc2-ppv-111111.mp4"
        src_file.write_bytes(b"x" * 1000)
        os.link(src_file, target / "FC2-PPV-111111.mp4")

        sets = DuplicateDetector().scan_multiple(source, [target])
        s = sets[0]

        assert len(s.inode_chains) == 1
        assert len(s.inode_chains[0]) == 2  # source + hardlink
        assert s.wasted_space == 0

    def test_two_copy_chains_wasted_space_counted_once_each(self, temp_dir):
        """
        When a copy chain has two hardlinked paths (C↔D), wasted_space counts
        that inode once — not once per path.

        Layout (all files named the same so part-token matching is consistent):
          source/fc2-ppv-111111.mp4  inode A  (source)
          t1/fc2-ppv-111111.mp4      inode A  (hardlinked to source → source chain)
          t2/fc2-ppv-111111.mp4      inode C  (independent copy → copy chain, path 1)
          t3/fc2-ppv-111111.mp4      inode C  (hardlinked to t2 → copy chain, path 2)
        """
        source = temp_dir / "source"
        t1 = temp_dir / "t1"
        t2 = temp_dir / "t2"
        t3 = temp_dir / "t3"
        for d in (source, t1, t2, t3):
            d.mkdir()

        FILE_SIZE = 2000
        src_file = source / "fc2-ppv-111111.mp4"
        src_file.write_bytes(b"x" * FILE_SIZE)
        os.link(src_file, t1 / "fc2-ppv-111111.mp4")

        copy_file = t2 / "fc2-ppv-111111.mp4"
        copy_file.write_bytes(b"y" * FILE_SIZE)
        os.link(copy_file, t3 / "fc2-ppv-111111.mp4")

        sets = DuplicateDetector().scan_multiple(source, [t1, t2, t3])
        assert len(sets) == 1
        s = sets[0]

        # Two inode chains: [src + t1 hardlink] and [t2 + t3 hardlink]
        assert len(s.inode_chains) == 2
        src_chain_paths = {f.file_path for f in s.inode_chains[0]}
        assert src_file in src_chain_paths
        assert (t1 / "fc2-ppv-111111.mp4") in src_chain_paths

        copy_chain_paths = {f.file_path for f in s.inode_chains[1]}
        assert copy_file in copy_chain_paths
        assert (t3 / "fc2-ppv-111111.mp4") in copy_chain_paths

        # Copy chain has two paths sharing one inode → count wasted space once
        assert s.wasted_space == FILE_SIZE
        assert s.status == "MIXED"

    def test_multiple_independent_copy_chains(self, temp_dir):
        """Multiple unrelated copy chains each contribute one size to wasted_space."""
        source = temp_dir / "source"
        t1 = temp_dir / "t1"
        t2 = temp_dir / "t2"
        for d in (source, t1, t2):
            d.mkdir()

        FILE_SIZE = 3000
        src_file = source / "MIDE-500.mp4"
        src_file.write_bytes(b"s" * FILE_SIZE)

        copy_a = t1 / "MIDE-500.mp4"
        copy_a.write_bytes(b"a" * FILE_SIZE)
        copy_b = t2 / "MIDE-500.mp4"
        copy_b.write_bytes(b"b" * FILE_SIZE)
        # copy_a and copy_b are different inodes (different content written)

        sets = DuplicateDetector().scan_multiple(source, [t1, t2])
        s = sets[0]

        # 3 chains: source, copy_a, copy_b
        assert len(s.inode_chains) == 3
        assert s.wasted_space == FILE_SIZE * 2

    def test_group_files_by_inode_groups_hardlinks(self, temp_dir):
        """_group_files_by_inode puts hardlinked paths in the same group."""
        from taggrr.core.scanner import VideoScanner

        f1 = temp_dir / "a.mp4"
        f1.write_bytes(b"data")
        f2 = temp_dir / "b.mp4"
        os.link(f1, f2)
        f3 = temp_dir / "c.mp4"
        f3.write_bytes(b"other")

        scanner = VideoScanner()
        files = scanner.scan_directory(temp_dir)
        groups = _group_files_by_inode(files)

        assert len(groups) == 2
        sizes = sorted(len(g) for g in groups)
        assert sizes == [1, 2]


class TestUnmatchedFiles:
    """Utility for retrieving files not included in any duplicate set."""

    def test_get_unmatched_files(self, temp_dir):
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

        matched = {temp_dir / "file1.mp4", temp_dir / "file3.mp4"}
        unmatched = get_unmatched_files([file1, file2, file3], matched)

        assert len(unmatched) == 1
        assert unmatched[0].file_path == temp_dir / "file2.mp4"
