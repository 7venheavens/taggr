"""Configuration-aware name analysis engine."""

import re
from dataclasses import dataclass

from ..config.settings import PatternConfig, TaggerrConfig
from .models import SourceHint, SourceType, VideoFile


@dataclass
class AnalysisResult:
    """Result of name analysis."""

    primary_id: str | None
    alternative_ids: list[str]
    year: int | None
    source_hints: list[SourceHint]
    confidence_scores: dict[str, float]
    extraction_source: str  # "folder", "filename", or "combined"
    raw_folder: str
    raw_filename: str


class ConfigurableIDExtractor:
    """Extracts video IDs using configurable patterns."""

    def __init__(self, config: TaggerrConfig):
        """Initialize with configuration."""
        self.config = config
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns from configuration."""
        self.strong_patterns = self._compile_pattern_list(
            self.config.id_extraction.strong_patterns
        )
        self.medium_patterns = self._compile_pattern_list(
            self.config.id_extraction.medium_patterns
        )
        self.weak_patterns = self._compile_pattern_list(
            self.config.id_extraction.weak_patterns
        )

    def _compile_pattern_list(self, patterns: list[PatternConfig]) -> list[tuple]:
        """Compile a list of pattern configurations."""
        compiled = []
        for pattern_config in patterns:
            try:
                regex = re.compile(pattern_config.regex, re.IGNORECASE)
                source_type = self._get_source_type(pattern_config.source)
                compiled.append(
                    (
                        regex,
                        pattern_config.format,
                        source_type,
                        pattern_config.confidence,
                    )
                )
            except re.error as e:
                print(f"Invalid regex pattern '{pattern_config.regex}': {e}")
                continue
        return compiled

    def _get_source_type(self, source_str: str | None) -> SourceType:
        """Convert source string to SourceType enum."""
        if not source_str:
            return SourceType.GENERIC

        source_map = {
            "fc2": SourceType.FC2,
            "dmm": SourceType.DMM,
            "generic": SourceType.GENERIC,
        }
        return source_map.get(source_str.lower(), SourceType.GENERIC)

    def extract_ids(self, text: str) -> list[tuple[str, SourceType, float]]:
        """Extract all possible IDs from text with confidence scores."""
        ids = []

        # Try strong patterns first
        for pattern, format_str, source, confidence in self.strong_patterns:
            matches = pattern.findall(text)
            for match in matches:
                formatted_id = format_str.format(match)
                ids.append((formatted_id, source, confidence))

        # If no strong matches, try medium patterns
        if not ids:
            for pattern, format_str, source, confidence in self.medium_patterns:
                matches = pattern.findall(text)
                for match in matches:
                    formatted_id = format_str.format(match)
                    ids.append((formatted_id, source, confidence))

        # If still no matches, try weak patterns
        if not ids:
            for pattern, format_str, source, confidence in self.weak_patterns:
                matches = pattern.findall(text)
                for match in matches:
                    formatted_id = format_str.format(match)
                    ids.append((formatted_id, source, confidence))

        # Remove duplicates while preserving order
        seen = set()
        unique_ids = []
        for id_tuple in ids:
            if id_tuple[0] not in seen:
                seen.add(id_tuple[0])
                unique_ids.append(id_tuple)

        return unique_ids


class ConfigurableSourceDetector:
    """Detects source hints using configurable patterns."""

    def __init__(self, config: TaggerrConfig):
        """Initialize with configuration."""
        self.config = config
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile source detection patterns from configuration."""
        self.compiled_patterns = {}

        for source_name, source_config in self.config.source_detection.patterns.items():
            source_type = self._get_source_type(source_name)
            patterns = []

            # Compile folder patterns
            for pattern_str in source_config.folder:
                try:
                    # Convert glob pattern to regex
                    regex_pattern = pattern_str.replace("*", ".*")
                    regex = re.compile(regex_pattern, re.IGNORECASE)
                    patterns.append(
                        (regex, f"folder:{pattern_str}", source_config.confidence_boost)
                    )
                except re.error as e:
                    print(f"Invalid folder pattern '{pattern_str}': {e}")
                    continue

            # Compile file patterns
            for pattern_str in source_config.file:
                try:
                    # Convert glob pattern to regex
                    regex_pattern = pattern_str.replace("*", ".*")
                    regex = re.compile(regex_pattern, re.IGNORECASE)
                    patterns.append(
                        (regex, f"file:{pattern_str}", source_config.confidence_boost)
                    )
                except re.error as e:
                    print(f"Invalid file pattern '{pattern_str}': {e}")
                    continue

            self.compiled_patterns[source_type] = patterns

    def _get_source_type(self, source_str: str) -> SourceType:
        """Convert source string to SourceType enum."""
        source_map = {
            "fc2": SourceType.FC2,
            "dmm": SourceType.DMM,
            "generic": SourceType.GENERIC,
        }
        return source_map.get(source_str.lower(), SourceType.GENERIC)

    def detect_sources(self, text: str) -> list[SourceHint]:
        """Detect source hints from text."""
        hints = []

        for source_type, patterns in self.compiled_patterns.items():
            for pattern, matched_text, boost in patterns:
                if pattern.search(text):
                    hint = SourceHint(
                        source_type=source_type,
                        pattern_matched=matched_text,
                        confidence_boost=boost,
                    )
                    hints.append(hint)

        return hints


class YearExtractor:
    """Extracts year information from text."""

    YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

    def extract_year(self, text: str) -> int | None:
        """Extract year from text."""
        matches = self.YEAR_PATTERN.findall(text)
        if matches:
            # Return the first valid year found
            for year_str in matches:
                year = int(year_str)
                if 2000 <= year <= 2030:  # Reasonable range
                    return year
        return None


class ConfigurableNameAnalyzer:
    """Configuration-aware name analysis engine."""

    def __init__(self, config: TaggerrConfig):
        """Initialize analyzer with configuration."""
        self.config = config

        # Get analysis settings from Pydantic model
        name_config = config.matching.name_analysis
        self.folder_weight = name_config.folder_weight
        self.file_weight = name_config.file_weight
        self.context_boost = name_config.context_boost

        self.id_extractor = ConfigurableIDExtractor(config)
        self.source_detector = ConfigurableSourceDetector(config)
        self.year_extractor = YearExtractor()

    def analyze(self, video_file: VideoFile) -> AnalysisResult:
        """Analyze video file for IDs and metadata."""
        folder_name = video_file.folder_name
        file_name = video_file.stem  # Without extension

        # Extract IDs from both sources
        folder_ids = self.id_extractor.extract_ids(folder_name)
        file_ids = self.id_extractor.extract_ids(file_name)

        # Extract source hints
        folder_sources = self.source_detector.detect_sources(folder_name)
        file_sources = self.source_detector.detect_sources(file_name)
        all_sources = folder_sources + file_sources

        # Extract year
        folder_year = self.year_extractor.extract_year(folder_name)
        file_year = self.year_extractor.extract_year(file_name)
        year = file_year or folder_year  # Prefer filename year

        # Calculate confidence scores
        folder_confidence = self._calculate_confidence(folder_ids, folder_sources)
        file_confidence = self._calculate_confidence(file_ids, file_sources)

        # Apply context boost if sources agree
        if self._sources_agree(folder_sources, file_sources):
            folder_confidence += self.context_boost
            file_confidence += self.context_boost

        # Apply global source preference if configured
        if self.config.source_detection.global_preference:
            folder_confidence, file_confidence = self._apply_global_preference(
                folder_ids, file_ids, folder_confidence, file_confidence
            )

        # Determine best source and primary ID
        primary_id, extraction_source, alternative_ids = self._select_primary_id(
            folder_ids, file_ids, folder_confidence, file_confidence
        )

        # Calculate final confidence
        combined_confidence = (
            folder_confidence * self.folder_weight + file_confidence * self.file_weight
        )

        confidence_scores = {
            "folder": folder_confidence,
            "filename": file_confidence,
            "combined": combined_confidence,
        }

        return AnalysisResult(
            primary_id=primary_id,
            alternative_ids=alternative_ids,
            year=year,
            source_hints=all_sources,
            confidence_scores=confidence_scores,
            extraction_source=extraction_source,
            raw_folder=folder_name,
            raw_filename=file_name,
        )

    def _calculate_confidence(
        self, ids: list[tuple[str, SourceType, float]], sources: list[SourceHint]
    ) -> float:
        """Calculate confidence score for a set of IDs and sources."""
        if not ids:
            return 0.0

        # Base confidence from best ID
        base_confidence = max(conf for _, _, conf in ids)

        # Boost from source hints
        source_boost = sum(hint.confidence_boost for hint in sources)

        return min(1.0, base_confidence + source_boost)

    def _sources_agree(
        self, folder_sources: list[SourceHint], file_sources: list[SourceHint]
    ) -> bool:
        """Check if folder and file sources agree."""
        if not folder_sources or not file_sources:
            return False

        folder_types = {hint.source_type for hint in folder_sources}
        file_types = {hint.source_type for hint in file_sources}

        return bool(folder_types & file_types)  # Any overlap

    def _apply_global_preference(
        self,
        folder_ids: list[tuple],
        file_ids: list[tuple],
        folder_conf: float,
        file_conf: float,
    ) -> tuple[float, float]:
        """Apply global source preference boost."""
        pref = self.config.source_detection.global_preference.lower()
        pref_source = self._get_source_type(pref)

        boost = 0.2  # Global preference boost

        # Boost folder confidence if it contains preferred source
        if any(source == pref_source for _, source, _ in folder_ids):
            folder_conf += boost

        # Boost file confidence if it contains preferred source
        if any(source == pref_source for _, source, _ in file_ids):
            file_conf += boost

        return folder_conf, file_conf

    def _get_source_type(self, source_str: str) -> SourceType:
        """Convert source string to SourceType enum."""
        source_map = {
            "fc2": SourceType.FC2,
            "dmm": SourceType.DMM,
            "generic": SourceType.GENERIC,
        }
        return source_map.get(source_str, SourceType.GENERIC)

    def _select_primary_id(
        self,
        folder_ids: list[tuple[str, SourceType, float]],
        file_ids: list[tuple[str, SourceType, float]],
        folder_conf: float,
        file_conf: float,
    ) -> tuple[str | None, str, list[str]]:
        """Select primary ID based on confidence and weights."""
        all_ids = []

        # Weight the confidences and create combined list
        for id_str, source, conf in folder_ids:
            weighted_conf = conf + (folder_conf * self.folder_weight)
            all_ids.append((id_str, weighted_conf, "folder"))

        for id_str, source, conf in file_ids:
            weighted_conf = conf + (file_conf * self.file_weight)
            all_ids.append((id_str, weighted_conf, "filename"))

        if not all_ids:
            return None, "none", []

        # Sort by confidence and select best
        all_ids.sort(key=lambda x: x[1], reverse=True)

        primary_id = all_ids[0][0]
        extraction_source = all_ids[0][2]

        # Alternative IDs are the rest, deduplicated
        seen = {primary_id}
        alternative_ids = []
        for id_str, _, _ in all_ids[1:]:
            if id_str not in seen:
                seen.add(id_str)
                alternative_ids.append(id_str)

        return primary_id, extraction_source, alternative_ids
