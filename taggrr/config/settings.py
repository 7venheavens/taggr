"""Configuration management for Taggerr."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class PatternConfig(BaseModel):
    """Configuration for a regex pattern."""
    regex: str
    format: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str | None = None


class SourcePatternConfig(BaseModel):
    """Source detection patterns for a specific source."""
    folder: list[str] = Field(default_factory=list)
    file: list[str] = Field(default_factory=list)
    confidence_boost: float = Field(default=0.1, ge=0.0, le=1.0)


class NameAnalysisConfig(BaseModel):
    """Name analysis configuration."""
    folder_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    file_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    context_boost: float = Field(default=0.1, ge=0.0, le=1.0)


class ConfidenceThresholdsConfig(BaseModel):
    """Confidence threshold settings."""
    auto_process: float = Field(default=85.0, ge=0.0, le=100.0)
    manual_review: float = Field(default=40.0, ge=0.0, le=100.0)
    skip_threshold: float = Field(default=20.0, ge=0.0, le=100.0)


class PartDetectionConfig(BaseModel):
    """Multi-part detection configuration."""
    patterns: list[PatternConfig] = Field(default_factory=lambda: [
        PatternConfig(regex=r"(?i)part\s*(\d+)", format="Part {n}", confidence=0.9),
        PatternConfig(regex=r"(?i)cd\s*(\d+)", format="CD{n}", confidence=0.9),
        PatternConfig(regex=r"(?i)disc\s*(\d+)", format="Disc {n}", confidence=0.9),
        PatternConfig(regex=r"(?i)-(\d+)(?=\.\w+$)", format="Part {n}", confidence=0.8),
        PatternConfig(regex=r"(?i)_(\d+)(?=\.\w+$)", format="Part {n}", confidence=0.8),
        PatternConfig(regex=r"(?i)\[(\d+)\]", format="Part {n}", confidence=0.7),
        PatternConfig(regex=r"(?i)\((\d+)\)", format="Part {n}", confidence=0.7),
    ])
    max_parts: int = Field(default=10, ge=1, le=50)
    similarity_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class IDExtractionConfig(BaseModel):
    """ID extraction pattern configuration."""
    strong_patterns: list[PatternConfig] = Field(default_factory=lambda: [
        PatternConfig(regex=r"FC2-PPV-(\d{6,8})", format="FC2-PPV-{}", confidence=0.95, source="fc2"),
        PatternConfig(regex=r"fc2-ppv-(\d{6,8})", format="FC2-PPV-{}", confidence=0.95, source="fc2"),
        PatternConfig(regex=r"FC2PPV-(\d{6,8})", format="FC2-PPV-{}", confidence=0.90, source="fc2"),
        PatternConfig(regex=r"ppv-(\d{6,8})", format="FC2-PPV-{}", confidence=0.80, source="fc2"),
    ])
    medium_patterns: list[PatternConfig] = Field(default_factory=lambda: [
        PatternConfig(regex=r"([A-Z]{2,5}-\d{3,4})", format="{}", confidence=0.75, source="dmm"),
        PatternConfig(regex=r"([A-Z]{3,5}\d{3,4})", format="{}", confidence=0.65, source="dmm"),
        PatternConfig(regex=r"(\d{6}_\d{3})", format="{}", confidence=0.70, source="dmm"),
    ])
    weak_patterns: list[PatternConfig] = Field(default_factory=lambda: [
        PatternConfig(regex=r"(\d{6,8})", format="{}", confidence=0.40, source="generic"),
        PatternConfig(regex=r"([A-Z]+\d+)", format="{}", confidence=0.50, source="generic"),
    ])


class SourceDetectionConfig(BaseModel):
    """Source detection configuration."""
    global_preference: str | None = None
    patterns: dict[str, SourcePatternConfig] = Field(default_factory=lambda: {
        "fc2": SourcePatternConfig(
            folder=["*FC2*", "*fc2*", "*PPV*", "*ppv*"],
            file=["FC2-*", "fc2_*", "*ppv*", "*PPV*"],
            confidence_boost=0.2
        ),
        "dmm": SourcePatternConfig(
            folder=["*DMM*", "*R18*", "*dmm*", "*r18*"],
            file=["*-h.mp4", "*uncensored*", "*DMM*"],
            confidence_boost=0.15
        )
    })


class PlexOutputConfig(BaseModel):
    """Plex output configuration."""
    folder_format: str = "{title} ({year})"
    file_format: str = "{title} ({year}) - {part}"
    single_file_format: str = "{title} ({year})"
    create_nfo: bool = True
    download_assets: bool = True
    asset_types: list[str] = Field(default_factory=lambda: ["poster", "fanart"])


class APIConfig(BaseModel):
    """API configuration."""
    base_url: str = "http://localhost:8000"
    timeout: int = 30
    retries: int = 3
    retry_delay: float = 1.0


class MatchingConfig(BaseModel):
    """Matching configuration container."""
    name_analysis: NameAnalysisConfig = Field(default_factory=NameAnalysisConfig)
    confidence_thresholds: ConfidenceThresholdsConfig = Field(default_factory=ConfidenceThresholdsConfig)


class TaggerrConfig(BaseModel):
    """Main Taggerr configuration."""
    matching: MatchingConfig = Field(default_factory=MatchingConfig)

    source_detection: SourceDetectionConfig = Field(default_factory=SourceDetectionConfig)
    multi_part: PartDetectionConfig = Field(default_factory=PartDetectionConfig)
    id_extraction: IDExtractionConfig = Field(default_factory=IDExtractionConfig)
    plex_output: PlexOutputConfig = Field(default_factory=PlexOutputConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    # File processing
    processing_mode: str = Field(default="inplace", pattern="^(inplace|hardlink|copy)$")
    video_extensions: list[str] = Field(default_factory=lambda: [
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"
    ])

    # Logging
    log_level: str = "INFO"
    log_file: str | None = None


class ConfigManager:
    """Manages configuration loading and saving."""

    DEFAULT_CONFIG_NAME = "taggerr.yaml"

    def __init__(self, config_path: Path | None = None):
        """Initialize config manager."""
        self.config_path = config_path or self._get_default_config_path()
        self._config: TaggerrConfig | None = None

    def load(self) -> TaggerrConfig:
        """Load configuration from file or create default."""
        if self.config_path.exists():
            try:
                with open(self.config_path, encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    self._config = TaggerrConfig(**data)
            except Exception as e:
                print(f"Error loading config from {self.config_path}: {e}")
                print("Using default configuration")
                self._config = TaggerrConfig()
        else:
            print(f"Config file not found at {self.config_path}")
            print("Creating default configuration")
            self._config = TaggerrConfig()
            self.save()

        return self._config

    def save(self, config: TaggerrConfig | None = None) -> None:
        """Save configuration to file."""
        config_to_save = config or self._config
        if config_to_save is None:
            raise ValueError("No configuration to save")

        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict and save as YAML
        data = config_to_save.model_dump()
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)

        print(f"Configuration saved to {self.config_path}")

    def get_config(self) -> TaggerrConfig:
        """Get current configuration, loading if necessary."""
        if self._config is None:
            self.load()
        return self._config

    def update_config(self, **kwargs) -> None:
        """Update configuration values."""
        if self._config is None:
            self.load()

        # Update fields
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)

        self.save()

    def _get_default_config_path(self) -> Path:
        """Get default configuration file path."""
        # Look for config in current directory first, then user config dir
        current_dir = Path.cwd() / self.DEFAULT_CONFIG_NAME
        if current_dir.exists():
            return current_dir

        # User config directory
        config_dir = Path.home() / ".config" / "taggerr"
        return config_dir / self.DEFAULT_CONFIG_NAME

    def create_sample_config(self, output_path: Path | None = None) -> None:
        """Create a sample configuration file with comments."""
        output_path = output_path or (Path.cwd() / "taggerr_sample.yaml")

        sample_config = TaggerrConfig()

        # Add comments to the YAML
        sample_yaml = """# Taggerr Configuration File
# Edit this file to customize Taggerr's behavior

# Matching configuration
matching:
  name_analysis:
    folder_weight: 0.6      # How much to weight folder name matches (0.0-1.0)
    file_weight: 0.4        # How much to weight filename matches (0.0-1.0)
    context_boost: 0.1      # Boost when folder provides context (0.0-1.0)
  
  confidence_thresholds:
    auto_process: 85.0      # Auto-process files above this confidence
    manual_review: 40.0     # Show review prompt between this and auto_process
    skip_threshold: 20.0    # Skip files below this threshold

# Source detection patterns
source_detection:
  global_preference: null   # Override: "fc2", "dmm", etc.
  patterns:
    fc2:
      folder: ["*FC2*", "*fc2*", "*PPV*", "*ppv*"]
      file: ["FC2-*", "fc2_*", "*ppv*", "*PPV*"]
      confidence_boost: 0.2
    dmm:
      folder: ["*DMM*", "*R18*", "*dmm*", "*r18*"]
      file: ["*-h.mp4", "*uncensored*", "*DMM*"]
      confidence_boost: 0.15

# Multi-part video detection
multi_part:
  patterns:
    - regex: "(?i)part\\s*(\\d+)"
      format: "Part {n}"
      confidence: 0.9
    - regex: "(?i)cd\\s*(\\d+)"
      format: "CD{n}"
      confidence: 0.9
    - regex: "(?i)disc\\s*(\\d+)"
      format: "Disc {n}"
      confidence: 0.9
  max_parts: 10
  similarity_threshold: 0.8

# ID extraction patterns
id_extraction:
  strong_patterns:
    - regex: "FC2-PPV-(\\d{6,8})"
      format: "FC2-PPV-{}"
      confidence: 0.95
      source: "fc2"
  medium_patterns:
    - regex: "([A-Z]{2,5}-\\d{3,4})"
      format: "{}"
      confidence: 0.75
      source: "dmm"
  weak_patterns:
    - regex: "(\\d{6,8})"
      format: "{}"
      confidence: 0.40
      source: "generic"

# Plex output settings
plex_output:
  folder_format: "{title} ({year})"
  file_format: "{title} ({year}) - {part}"
  single_file_format: "{title} ({year})"
  create_nfo: true
  download_assets: true
  asset_types: ["poster", "fanart"]

# API settings
api:
  base_url: "http://localhost:8000"
  timeout: 30
  retries: 3
  retry_delay: 1.0

# Supported video file extensions
video_extensions:
  - ".mp4"
  - ".mkv" 
  - ".avi"
  - ".mov"
  - ".wmv"
  - ".flv"
  - ".webm"
  - ".m4v"
  - ".mpg"
  - ".mpeg"

# Logging
log_level: "INFO"
log_file: null  # Set to file path for file logging
"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(sample_yaml)

        print(f"Sample configuration created at {output_path}")


# Global config instance
config_manager = ConfigManager()


def get_config() -> TaggerrConfig:
    """Get the global configuration instance."""
    return config_manager.get_config()


def load_config(config_path: Path | None = None) -> TaggerrConfig:
    """Load configuration from specific path."""
    if config_path:
        manager = ConfigManager(config_path)
        return manager.load()
    return config_manager.load()
