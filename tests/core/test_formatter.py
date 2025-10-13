"""Test Plex-compatible formatting functionality."""

from pathlib import Path

from taggrr.core.formatter import NFOGenerator, OutputPlanner, PlexFormatter
from taggrr.core.models import (
    ConfidenceBreakdown,
    MatchResult,
    SourceType,
    VideoFile,
    VideoGroup,
)


class TestPlexFormatter:
    """Test Plex formatting functionality."""

    def test_format_folder_name(self, test_config, sample_match_result):
        """Test folder name formatting."""
        formatter = PlexFormatter(test_config)

        folder_name = formatter.format_folder_name(sample_match_result)

        assert folder_name == "Test Movie Title (2024)"

    def test_format_folder_name_no_year(self, test_config):
        """Test folder name formatting without year."""
        formatter = PlexFormatter(test_config)

        match_result = MatchResult(
            video_metadata={"title": "Movie Without Year"},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.GENERIC,
            suggested_output_name="Movie Without Year",
            video_id="test",
        )

        folder_name = formatter.format_folder_name(match_result)
        assert folder_name == "Movie Without Year"

    def test_format_file_name_single(self, test_config, sample_match_result):
        """Test single file name formatting."""
        formatter = PlexFormatter(test_config)

        file_name = formatter.format_file_name(sample_match_result, None, ".mp4")

        assert file_name == "Test Movie Title (2024).mp4"

    def test_format_file_name_multipart(self, test_config, sample_match_result):
        """Test multi-part file name formatting."""
        formatter = PlexFormatter(test_config)

        file_name = formatter.format_file_name(sample_match_result, "Part 1", ".mkv")

        assert file_name == "Test Movie Title (2024) - Part 1.mkv"

    def test_sanitize_invalid_characters(self, test_config):
        """Test sanitization of invalid characters."""
        formatter = PlexFormatter(test_config)

        test_cases = [
            ("Movie<>Title", "Movie__Title"),
            ("Title:With|Invalid?Chars", "Title_With_Invalid_Chars"),
            ('Title"With/Quotes\\', "Title_With_Quotes_"),
            ("   Leading/Trailing Spaces   ", "Leading_Trailing Spaces"),
            ("Title.", "Title"),  # Trailing dot removal
        ]

        for input_name, expected in test_cases:
            result = formatter._sanitize_name(input_name)
            assert result == expected

    def test_sanitize_reserved_names(self, test_config):
        """Test handling of Windows reserved names."""
        formatter = PlexFormatter(test_config)

        reserved_names = ["CON", "PRN", "AUX", "NUL"]

        for name in reserved_names:
            result = formatter._sanitize_name(name)
            assert result.startswith("_")
            assert name in result

    def test_sanitize_long_names(self, test_config):
        """Test handling of very long names."""
        formatter = PlexFormatter(test_config)

        long_name = "A" * 300
        result = formatter._sanitize_name(long_name)

        assert len(result) <= 200
        assert result == "A" * 200


class TestNFOGenerator:
    """Test NFO file generation."""

    def test_generate_movie_nfo(self, test_config, sample_match_result):
        """Test basic NFO generation."""
        generator = NFOGenerator(test_config)

        nfo_content = generator.generate_movie_nfo(sample_match_result)

        assert nfo_content is not None
        assert "<?xml" in nfo_content
        assert "<movie>" in nfo_content
        assert "<title>Test Movie Title</title>" in nfo_content
        assert "<year>2024</year>" in nfo_content
        assert "</movie>" in nfo_content

    def test_generate_nfo_disabled(self, test_config, sample_match_result):
        """Test NFO generation when disabled."""
        test_config.plex_output.create_nfo = False
        generator = NFOGenerator(test_config)

        nfo_content = generator.generate_movie_nfo(sample_match_result)

        assert nfo_content is None

    def test_nfo_with_optional_fields(self, test_config):
        """Test NFO with all optional fields."""
        match_result = MatchResult(
            video_metadata={
                "title": "Complete Movie",
                "year": 2024,
                "description": "A movie with all metadata",  # Should be ignored
                "director": "Test Director",
                "duration": 7200,  # 2 hours in seconds
                "genres": ["Action", "Drama"],
                "rating": 8.5,
                "studio": "Test Studio",
                "id": "test-123",
                "creator": "Test Creator",
                "tags": ["tag1", "tag2", ""],  # Empty tag should be filtered out
                "thumbnail_url": "http://example.com/thumb.jpg",
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.GENERIC,
            suggested_output_name="Complete Movie (2024)",
            video_id="test-123",
        )

        generator = NFOGenerator(test_config)
        nfo_content = generator.generate_movie_nfo(match_result)

        # Verify expected fields are present
        assert "<director>Test Director</director>" in nfo_content
        assert "<runtime>120</runtime>" in nfo_content  # Converted to minutes
        assert "<genre>Action</genre>" in nfo_content
        assert "<genre>Drama</genre>" in nfo_content
        assert "<rating>8.5</rating>" in nfo_content
        assert "<studio>Test Studio</studio>" in nfo_content
        assert "<tag>tag1</tag>" in nfo_content
        assert "<tag>tag2</tag>" in nfo_content

        # Verify description/plot is NOT present
        assert "<plot>" not in nfo_content
        assert "A movie with all metadata" not in nfo_content

    def test_creator_as_director_fallback(self, test_config):
        """Test that creator is used as director when director field is not present."""
        match_result = MatchResult(
            video_metadata={
                "title": "FC2 Video",
                "creator": "天使の戯れ",
                "actors": [],
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="FC2 Video",
            video_id="4773622",
        )

        generator = NFOGenerator(test_config)
        nfo_content = generator.generate_movie_nfo(match_result)

        # Creator should be mapped to director when director is not present
        assert "<director>天使の戯れ</director>" in nfo_content
        # Should not be mapped to actor
        assert "<actor>" not in nfo_content

    def test_actors_array_processing(self, test_config):
        """Test that actors array is properly processed into actor tags."""
        match_result = MatchResult(
            video_metadata={
                "title": "Video with Actors",
                "creator": "Studio Name",
                "actors": [
                    {
                        "id": 1,
                        "name": "Actor One",
                        "image_url": None,
                        "created_at": "",
                        "updated_at": "",
                    },
                    {
                        "id": 2,
                        "name": "Actor Two",
                        "image_url": None,
                        "created_at": "",
                        "updated_at": "",
                    },
                ],
            },
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Video with Actors",
            video_id="test-123",
        )

        generator = NFOGenerator(test_config)
        nfo_content = generator.generate_movie_nfo(match_result)

        # Actors should be properly added
        assert "<name>Actor One</name>" in nfo_content
        assert "<name>Actor Two</name>" in nfo_content
        # Creator should be director, not actor
        assert "<director>Studio Name</director>" in nfo_content

    def test_escape_xml_characters(self, test_config):
        """Test XML character escaping."""
        generator = NFOGenerator(test_config)

        test_cases = [
            ("Title & Subtitle", "Title &amp; Subtitle"),
            ("Title <with> tags", "Title &lt;with&gt; tags"),
            ('Title "with quotes"', "Title &quot;with quotes&quot;"),
            ("Title 'with apostrophes'", "Title &#39;with apostrophes&#39;"),
        ]

        for input_text, expected in test_cases:
            result = generator._escape_xml(input_text)
            assert result == expected


class TestOutputPlanner:
    """Test output planning functionality."""

    def test_plan_single_file_output(self, test_config, sample_match_result, temp_dir):
        """Test planning output for single file."""
        planner = OutputPlanner(test_config)

        # Create single file group
        video_file = VideoFile(
            file_path=temp_dir / "source.mp4",
            folder_name="source_folder",
            file_name="source.mp4",
            detected_parts=[],
            source_hints=[],
        )

        video_group = VideoGroup(
            files=[video_file], group_name="source", total_parts=1, folder_path=temp_dir
        )

        output_dir = temp_dir / "output"
        plan = planner.plan_output(video_group, sample_match_result, output_dir)

        assert plan["folder_name"] == "Test Movie Title (2024)"
        assert plan["total_files"] == 1

        # Check file mapping
        source_path = str(video_file.file_path)
        assert source_path in plan["structure"]

        target_info = plan["structure"][source_path]
        assert "Test Movie Title (2024).mp4" in str(target_info["target_path"])

    def test_plan_multipart_output(self, test_config, sample_match_result, temp_dir):
        """Test planning output for multi-part files."""
        planner = OutputPlanner(test_config)

        # Create multi-part group
        video_files = []
        for i in range(1, 3):
            file_path = temp_dir / f"source_part_{i}.mkv"
            file_path.touch()

            from taggrr.core.models import PartInfo

            part_info = PartInfo(
                part_number=i,
                part_pattern=f"Part {i}",
                confidence=0.9,
                file_path=file_path,
            )

            video_file = VideoFile(
                file_path=file_path,
                folder_name="source_folder",
                file_name=f"source_part_{i}.mkv",
                detected_parts=[part_info],
                source_hints=[],
            )
            video_files.append(video_file)

        video_group = VideoGroup(
            files=video_files,
            group_name="source series",
            total_parts=2,
            folder_path=temp_dir,
        )

        output_dir = temp_dir / "output"
        plan = planner.plan_output(video_group, sample_match_result, output_dir)

        assert plan["total_files"] == 2

        # Check that both parts are planned
        structure = plan["structure"]
        file_paths = [k for k in structure.keys() if not k.startswith("_")]
        assert len(file_paths) == 2

        # Check naming
        for file_path in file_paths:
            target_path = str(structure[file_path]["target_path"])
            assert "Test Movie Title (2024) - Part" in target_path

    def test_plan_with_assets(self, test_config, sample_match_result, temp_dir):
        """Test planning with asset downloads."""
        planner = OutputPlanner(test_config)

        video_file = VideoFile(
            file_path=temp_dir / "source.mp4",
            folder_name="source_folder",
            file_name="source.mp4",
            detected_parts=[],
            source_hints=[],
        )

        video_group = VideoGroup(
            files=[video_file], group_name="source", total_parts=1, folder_path=temp_dir
        )

        # Update match result with API response for assets
        sample_match_result.api_response = sample_match_result.video_metadata

        output_dir = temp_dir / "output"
        plan = planner.plan_output(video_group, sample_match_result, output_dir)

        # Should plan asset downloads
        assert "_poster" in plan["structure"]
        assert "_fanart" in plan["structure"]

        poster_info = plan["structure"]["_poster"]
        assert poster_info["action"] == "download"
        assert "folder.jpg" in str(
            poster_info["target_path"]
        )  # Poster is saved as folder.jpg for Plex

    def test_validate_output_plan(self, test_config, temp_dir):
        """Test output plan validation."""
        planner = OutputPlanner(test_config)

        # Valid plan
        valid_plan = {
            "output_folder": temp_dir / "valid_folder",
            "structure": {
                "file1": {"target_path": temp_dir / "output" / "file1.mp4"},
                "file2": {"target_path": temp_dir / "output" / "file2.mp4"},
            },
            "folder_name": "Valid Folder Name",
            "total_files": 2,
        }

        is_valid, issues = planner.validate_output_plan(valid_plan)
        assert is_valid
        assert len(issues) == 0

        # Invalid plan with long path
        invalid_plan = {
            "output_folder": Path("A" * 300),
            "structure": {},
            "folder_name": "Valid Name",
            "total_files": 0,
        }

        is_valid, issues = planner.validate_output_plan(invalid_plan)
        assert not is_valid
        assert len(issues) > 0

    def test_get_plan_summary(self, test_config):
        """Test plan summary generation."""
        planner = OutputPlanner(test_config)

        plan = {
            "folder_name": "Test Movie (2024)",
            "total_files": 2,
            "structure": {
                "file1": {"action": "copy"},
                "file2": {"action": "copy"},
                "_nfo": {"action": "create"},
                "_poster": {"action": "download"},
            },
        }

        summary = planner.get_plan_summary(plan)

        assert "Test Movie (2024)" in summary
        assert "Files to process: 2" in summary
        assert "Files to copy: 2" in summary
        assert "NFO files to create: 1" in summary
        assert "Assets to download: 1" in summary
