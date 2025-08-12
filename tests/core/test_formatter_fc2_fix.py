"""Test FC2 short naming fix for Windows path compatibility."""

from taggrr.config.settings import TaggerrConfig
from taggrr.core.formatter import PlexFormatter
from taggrr.core.models import ConfidenceBreakdown, MatchResult, SourceType


class TestFC2ShortNaming:
    """Test FC2 short naming feature for Windows compatibility."""

    def test_fc2_folder_uses_short_name(self):
        """Test FC2 videos get short folder names instead of long Japanese titles."""
        config = TaggerrConfig()
        formatter = PlexFormatter(config)

        # Create FC2 match result with long Japanese title
        match_result = MatchResult(
            video_metadata={
                "title": "Very Long Japanese Title That Would Cause Windows Path Issues テストタイトル",
                "year": 2024,
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Long Title",
            video_id="4734497",
        )

        folder_name = formatter.format_folder_name(match_result)

        # Should use short FC2 code instead of long title
        assert folder_name == "FC2-PPV-4734497 (2024)"
        assert "Very Long Japanese Title" not in folder_name
        assert len(folder_name) < 50  # Windows-friendly length

    def test_fc2_file_uses_short_name(self):
        """Test FC2 files get short names instead of long Japanese titles."""
        config = TaggerrConfig()
        formatter = PlexFormatter(config)

        match_result = MatchResult(
            video_metadata={
                "title": "Another Very Long Japanese Title テストタイトル２",
                "year": 2023,
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Long Title",
            video_id="1234567",
        )

        file_name = formatter.format_file_name(match_result, None, ".mp4")

        # Should use short FC2 code
        assert file_name == "FC2-PPV-1234567 (2023).mp4"
        assert "Another Very Long Japanese Title" not in file_name
        assert len(file_name) < 60  # Reasonable file name length

    def test_fc2_multipart_files_use_short_names(self):
        """Test FC2 multi-part files use short names."""
        config = TaggerrConfig()
        formatter = PlexFormatter(config)

        match_result = MatchResult(
            video_metadata={
                "title": "Long Multi-Part Japanese Title テストシリーズ",
                "year": 2024,
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Long Title",
            video_id="9999999",
        )

        file_name = formatter.format_file_name(match_result, "Part 1", ".mkv")

        # Should use short FC2 code with part info
        assert file_name == "FC2-PPV-9999999 (2024) - Part 1.mkv"
        assert "Long Multi-Part Japanese Title" not in file_name

    def test_fc2_without_year_uses_short_name(self):
        """Test FC2 videos without year still use short names."""
        config = TaggerrConfig()
        formatter = PlexFormatter(config)

        match_result = MatchResult(
            video_metadata={
                "title": "Long Title Without Year 年なしタイトル",
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Long Title",
            video_id="5555555",
        )

        folder_name = formatter.format_folder_name(match_result)

        # Should still use short FC2 code even without year
        assert folder_name == "FC2-PPV-5555555"
        assert "Long Title Without Year" not in folder_name

    def test_non_fc2_videos_keep_original_titles(self):
        """Test non-FC2 videos keep their original titles."""
        config = TaggerrConfig()
        formatter = PlexFormatter(config)

        # DMM video should keep original title
        dmm_result = MatchResult(
            video_metadata={"title": "DMM Movie Title", "year": 2024},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.DMM,
            suggested_output_name="DMM Movie Title",
            video_id="MIDE-123",
        )

        folder_name = formatter.format_folder_name(dmm_result)

        # Should keep original title for non-FC2
        assert folder_name == "DMM Movie Title (2024)"
        assert "DMM Movie Title" in folder_name

    def test_fc2_with_non_numeric_id_keeps_title(self):
        """Test FC2 with non-numeric video_id keeps original title."""
        config = TaggerrConfig()
        formatter = PlexFormatter(config)

        match_result = MatchResult(
            video_metadata={"title": "FC2 With Non-Numeric ID", "year": 2024},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="FC2 With Non-Numeric ID",
            video_id="not-numeric",  # Non-numeric ID
        )

        folder_name = formatter.format_folder_name(match_result)

        # Should keep original title if video_id is not numeric
        assert folder_name == "FC2 With Non-Numeric ID (2024)"
        assert "FC2-PPV-" not in folder_name
