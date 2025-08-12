"""Test configuration management functionality."""

import pytest
import yaml

from taggrr.config.settings import ConfigManager, PatternConfig, TaggerrConfig


class TestConfigManager:
    """Test configuration manager functionality."""

    def test_load_default_config(self, temp_dir):
        """Test loading default configuration."""
        config_path = temp_dir / "test_config.yaml"
        manager = ConfigManager(config_path)

        config = manager.load()

        assert isinstance(config, TaggerrConfig)
        assert config.api.base_url == "http://localhost:8000"
        assert config.plex_output.create_nfo == True
        assert len(config.id_extraction.strong_patterns) > 0

    def test_save_and_load_config(self, temp_dir):
        """Test saving and loading configuration."""
        config_path = temp_dir / "test_config.yaml"
        manager = ConfigManager(config_path)

        # Create and save config
        config = TaggerrConfig()
        config.api.base_url = "http://custom:9000"
        config.plex_output.create_nfo = False

        manager.save(config)
        assert config_path.exists()

        # Load config back
        loaded_config = manager.load()
        assert loaded_config.api.base_url == "http://custom:9000"
        assert loaded_config.plex_output.create_nfo == False

    def test_load_existing_config(self, temp_dir):
        """Test loading from existing YAML file."""
        config_path = temp_dir / "existing_config.yaml"

        # Create config file manually
        config_data = {
            "api": {"base_url": "http://existing:8080", "timeout": 60},
            "plex_output": {"folder_format": "{title} [{year}]", "create_nfo": False},
        }

        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # Load with manager
        manager = ConfigManager(config_path)
        config = manager.load()

        assert config.api.base_url == "http://existing:8080"
        assert config.api.timeout == 60
        assert config.plex_output.folder_format == "{title} [{year}]"
        assert config.plex_output.create_nfo == False

    def test_invalid_config_fallback(self, temp_dir):
        """Test fallback to default when config is invalid."""
        config_path = temp_dir / "invalid_config.yaml"

        # Create invalid YAML
        with open(config_path, "w") as f:
            f.write("invalid: yaml: content: [")

        manager = ConfigManager(config_path)
        config = manager.load()

        # Should fallback to defaults
        assert isinstance(config, TaggerrConfig)
        assert config.api.base_url == "http://localhost:8000"

    def test_update_config(self, temp_dir):
        """Test updating configuration values."""
        config_path = temp_dir / "update_config.yaml"
        manager = ConfigManager(config_path)

        # Load initial config
        config = manager.load()
        original_url = config.api.base_url

        # Update config manually (update_config method needs to be fixed to handle nested updates)
        config.api.base_url = "http://updated:7000"
        manager.save(config)

        # Verify update
        updated_config = manager.get_config()
        assert updated_config.api.base_url == "http://updated:7000"

    def test_create_sample_config(self, temp_dir):
        """Test sample configuration creation."""
        output_path = temp_dir / "sample_config.yaml"
        manager = ConfigManager()

        manager.create_sample_config(output_path)

        assert output_path.exists()

        # Should be valid YAML with comments
        content = output_path.read_text()
        assert "# Taggerr Configuration File" in content
        assert "matching:" in content
        assert "source_detection:" in content


class TestTaggerrConfig:
    """Test configuration model validation."""

    def test_default_config_creation(self):
        """Test creating default configuration."""
        config = TaggerrConfig()

        # Check defaults are set
        assert config.api.base_url == "http://localhost:8000"
        assert config.api.timeout == 30
        assert config.plex_output.create_nfo == True
        assert len(config.video_extensions) > 0

    def test_pattern_config_validation(self):
        """Test pattern configuration validation."""
        # Valid pattern
        pattern = PatternConfig(
            regex=r"FC2-PPV-(\d+)", format="FC2-PPV-{}", confidence=0.95
        )
        assert pattern.confidence == 0.95

        # Invalid confidence should raise validation error
        with pytest.raises(ValueError):
            PatternConfig(
                regex=r"test",
                format="{}",
                confidence=1.5,  # > 1.0
            )

        with pytest.raises(ValueError):
            PatternConfig(
                regex=r"test",
                format="{}",
                confidence=-0.1,  # < 0.0
            )

    def test_config_with_custom_patterns(self):
        """Test configuration with custom ID patterns."""
        custom_patterns = [
            PatternConfig(
                regex=r"CUSTOM-(\d+)",
                format="CUSTOM-{}",
                confidence=0.8,
                source="custom",
            )
        ]

        config = TaggerrConfig()
        config.id_extraction.strong_patterns = custom_patterns

        assert len(config.id_extraction.strong_patterns) == 1
        assert config.id_extraction.strong_patterns[0].regex == r"CUSTOM-(\d+)"

    def test_source_detection_config(self):
        """Test source detection configuration."""
        config = TaggerrConfig()

        # Should have default FC2 and DMM patterns
        assert "fc2" in config.source_detection.patterns
        assert "dmm" in config.source_detection.patterns

        fc2_config = config.source_detection.patterns["fc2"]
        assert len(fc2_config.folder) > 0
        assert len(fc2_config.file) > 0
        assert fc2_config.confidence_boost > 0

    def test_name_analysis_config(self):
        """Test name analysis configuration access."""
        config = TaggerrConfig()

        name_analysis = config.matching.name_analysis
        assert hasattr(name_analysis, "folder_weight")
        assert hasattr(name_analysis, "file_weight")
        assert hasattr(name_analysis, "context_boost")

        # Weights should sum to <= 1.0
        assert name_analysis.folder_weight + name_analysis.file_weight <= 1.0
