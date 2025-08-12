"""Test name analysis functionality."""

import pytest
from pathlib import Path

from taggrr.core.analyzer_config import ConfigurableNameAnalyzer, ConfigurableIDExtractor, ConfigurableSourceDetector
from taggrr.core.models import VideoFile, SourceType, SourceHint


class TestConfigurableIDExtractor:
    """Test ID extraction functionality."""
    
    def test_extract_fc2_ids(self, test_config):
        """Test FC2 ID extraction."""
        extractor = ConfigurableIDExtractor(test_config)
        
        test_cases = [
            "FC2-PPV-1234567",
            "fc2-ppv-7654321", 
            "FC2PPV-9999999",
            "ppv-1111111"
        ]
        
        for test_text in test_cases:
            ids = extractor.extract_ids(test_text)
            assert len(ids) >= 1
            
            # Should extract some form of FC2 ID
            fc2_ids = [id_tuple for id_tuple in ids if id_tuple[1] == SourceType.FC2]
            assert len(fc2_ids) >= 1
            
            # Should have high confidence for explicit FC2 patterns
            if "FC2-PPV-" in test_text.upper():
                assert fc2_ids[0][2] >= 0.90
    
    def test_extract_dmm_ids(self, test_config):
        """Test DMM ID extraction."""
        extractor = ConfigurableIDExtractor(test_config)
        
        test_cases = [
            "MIDE-123",
            "SSNI-456", 
            "ABP789",
            "123456_001"
        ]
        
        for test_text in test_cases:
            ids = extractor.extract_ids(test_text)
            assert len(ids) >= 1
            
            # Should extract the ID
            extracted_id = ids[0][0]
            assert extracted_id in test_text or test_text in extracted_id
    
    def test_extract_no_ids(self, test_config):
        """Test text with no recognizable IDs."""
        extractor = ConfigurableIDExtractor(test_config)
        
        test_cases = [
            "just_a_movie_title",
            "no-numbers-here",
            "random text"
        ]
        
        for test_text in test_cases:
            ids = extractor.extract_ids(test_text)
            # Might find weak patterns, but should be low confidence
            if ids:
                assert ids[0][2] <= 0.6


class TestConfigurableSourceDetector:
    """Test source detection functionality."""
    
    def test_detect_fc2_sources(self, test_config):
        """Test FC2 source detection."""
        detector = ConfigurableSourceDetector(test_config)
        
        test_cases = [
            ("[FC2] Video Title", "folder:[FC2]"),
            ("FC2-PPV-1234567.mp4", "file:FC2-*"),
            ("some ppv video", "file:*ppv*"),
            ("folder with fc2 content", "folder:*fc2*")
        ]
        
        for test_text, expected_pattern_type in test_cases:
            hints = detector.detect_sources(test_text)
            
            fc2_hints = [h for h in hints if h.source_type == SourceType.FC2]
            assert len(fc2_hints) >= 1
            
            # Should have positive confidence boost
            assert fc2_hints[0].confidence_boost > 0
    
    def test_detect_dmm_sources(self, test_config):
        """Test DMM source detection."""
        detector = ConfigurableSourceDetector(test_config)
        
        test_cases = [
            "[DMM] Movie Title",
            "[R18] Another Title",
            "movie-h.mp4",
            "uncensored version"
        ]
        
        for test_text in test_cases:
            hints = detector.detect_sources(test_text)
            
            dmm_hints = [h for h in hints if h.source_type == SourceType.DMM]
            assert len(dmm_hints) >= 1
            assert dmm_hints[0].confidence_boost > 0
    
    def test_detect_multiple_sources(self, test_config):
        """Test detection of multiple source hints."""
        detector = ConfigurableSourceDetector(test_config)
        
        # Text with both FC2 and DMM indicators
        test_text = "[DMM] FC2-PPV-1234567"
        hints = detector.detect_sources(test_text)
        
        source_types = {h.source_type for h in hints}
        assert SourceType.FC2 in source_types
        assert SourceType.DMM in source_types


class TestConfigurableNameAnalyzer:
    """Test the complete name analysis engine."""
    
    def test_analyze_fc2_video(self, test_config, temp_dir):
        """Test analysis of FC2 video file."""
        analyzer = ConfigurableNameAnalyzer(test_config)
        
        # Create test file
        folder_path = temp_dir / "FC2-PPV-1234567 Premium"
        folder_path.mkdir()
        file_path = folder_path / "FC2-PPV-1234567.mp4"
        file_path.touch()
        
        video_file = VideoFile(
            file_path=file_path,
            folder_name="FC2-PPV-1234567 Premium",
            file_name="FC2-PPV-1234567.mp4",
            detected_parts=[],
            source_hints=[]
        )
        
        result = analyzer.analyze(video_file)
        
        assert result.primary_id == "FC2-PPV-1234567"
        assert len(result.source_hints) >= 1
        assert any(h.source_type == SourceType.FC2 for h in result.source_hints)
        assert result.confidence_scores["combined"] > 0.5
    
    def test_analyze_dmm_video(self, test_config, temp_dir):
        """Test analysis of DMM video file.""" 
        analyzer = ConfigurableNameAnalyzer(test_config)
        
        folder_path = temp_dir / "[DMM] Random Folder"
        folder_path.mkdir()
        file_path = folder_path / "MIDE-123.mp4"
        file_path.touch()
        
        video_file = VideoFile(
            file_path=file_path,
            folder_name="[DMM] Random Folder",
            file_name="MIDE-123.mp4",
            detected_parts=[],
            source_hints=[]
        )
        
        result = analyzer.analyze(video_file)
        
        assert result.primary_id == "MIDE-123"
        assert len(result.source_hints) >= 1
        assert any(h.source_type == SourceType.DMM for h in result.source_hints)
    
    def test_analyze_conflicting_sources(self, test_config, temp_dir):
        """Test analysis when folder and filename suggest different sources."""
        analyzer = ConfigurableNameAnalyzer(test_config)
        
        folder_path = temp_dir / "[DMM] Folder"
        folder_path.mkdir()
        file_path = folder_path / "FC2-PPV-1234567.mp4"
        file_path.touch()
        
        video_file = VideoFile(
            file_path=file_path,
            folder_name="[DMM] Folder",
            file_name="FC2-PPV-1234567.mp4", 
            detected_parts=[],
            source_hints=[]
        )
        
        result = analyzer.analyze(video_file)
        
        # Should still extract the ID
        assert result.primary_id == "FC2-PPV-1234567"
        
        # Should detect both source types
        source_types = {h.source_type for h in result.source_hints}
        assert SourceType.FC2 in source_types
        assert SourceType.DMM in source_types
        
        # Filename should win due to stronger ID pattern
        assert result.extraction_source == "filename"
    
    def test_folder_vs_filename_weighting(self, test_config, temp_dir):
        """Test configurable folder vs filename weighting."""
        # Test with folder preference
        test_config.matching.name_analysis.folder_weight = 0.8
        test_config.matching.name_analysis.file_weight = 0.2
        
        analyzer = ConfigurableNameAnalyzer(test_config)
        
        folder_path = temp_dir / "CLEAR-ID-123 Folder"
        folder_path.mkdir()
        file_path = folder_path / "cryptic_filename.mp4"
        file_path.touch()
        
        video_file = VideoFile(
            file_path=file_path,
            folder_name="CLEAR-ID-123 Folder",
            file_name="cryptic_filename.mp4",
            detected_parts=[],
            source_hints=[]
        )
        
        result = analyzer.analyze(video_file)
        
        # Should prefer folder-based extraction due to weighting
        assert result.confidence_scores["folder"] > result.confidence_scores["filename"]
    
    def test_year_extraction(self, test_config, temp_dir):
        """Test year extraction from folder/filename."""
        analyzer = ConfigurableNameAnalyzer(test_config)
        
        folder_path = temp_dir / "Movie Title (2024)"
        folder_path.mkdir()
        file_path = folder_path / "movie.mp4"
        file_path.touch()
        
        video_file = VideoFile(
            file_path=file_path,
            folder_name="Movie Title (2024)",
            file_name="movie.mp4",
            detected_parts=[],
            source_hints=[]
        )
        
        result = analyzer.analyze(video_file)
        
        assert result.year == 2024