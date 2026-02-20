"""Name analysis engine for extracting video IDs and source hints."""

import re
from dataclasses import dataclass

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


class IDExtractor:
    """Extracts video IDs from text using pattern matching."""

    # Strong ID patterns with high confidence
    STRONG_PATTERNS = [
        (
            r"FC2-PPV-(\d{6,8})",
            "{}",
            SourceType.FC2,
            0.95,
        ),  # Extract just the number for FC2 API
        (r"fc2-ppv-(\d{6,8})", "{}", SourceType.FC2, 0.95),
        (r"FC2PPV-(\d{6,8})", "{}", SourceType.FC2, 0.90),
        (r"ppv-(\d{6,8})", "{}", SourceType.FC2, 0.80),
        # 1Pondo / 1pon date IDs (e.g. 102116_410, 100915_3257)
        (r"(?:1pondo|1pon)[-_\s]*(\d{6}_\d{3,4})", "{}", SourceType.GENERIC, 0.92),
        (r"(\d{6}_\d{3,4})[-_\s]*(?:1pondo|1pon)", "{}", SourceType.GENERIC, 0.92),
        # Caribbean / CaribbeanPR / Carrib variants (e.g. 121616_005, 21418_003)
        (
            r"(?:carib(?:bean)?(?:pr)?|carrib(?:ean)?(?:pr)?)[-_\s]*(\d{5,6}_\d{3,4})",
            "{}",
            SourceType.GENERIC,
            0.90,
        ),
        (
            r"(\d{5,6}_\d{3,4})[-_\s]*(?:carib(?:bean)?(?:pr)?|carrib(?:ean)?(?:pr)?)",
            "{}",
            SourceType.GENERIC,
            0.90,
        ),
    ]

    # Medium confidence patterns
    MEDIUM_PATTERNS = [
        (r"([A-Z]{2,5}-\d{3,4})", "{}", SourceType.DMM, 0.75),  # MIDE-123, SSNI-456
        (r"([A-Z]{2,5}_\d{3,4})", "{}", SourceType.DMM, 0.75),  # MIDE_123, SSNI_456
        (r"([A-Z]{3,5}\d{3,4})", "{}", SourceType.DMM, 0.65),  # MIDE123
        (r"(\d{6}_\d{3,4})", "{}", SourceType.DMM, 0.70),  # 123456_001 / 123456_1234
    ]

    # Weak patterns - need source hints
    WEAK_PATTERNS = [
        (r"(\d{6,8})", "{}", SourceType.GENERIC, 0.40),  # Plain numbers
        (r"([A-Z]+\d+)", "{}", SourceType.GENERIC, 0.50),  # ABC123
    ]

    def __init__(self):
        """Initialize with compiled patterns."""
        self.strong_patterns = [
            (re.compile(p, re.IGNORECASE), f, s, c)
            for p, f, s, c in self.STRONG_PATTERNS
        ]
        self.medium_patterns = [
            (re.compile(p, re.IGNORECASE), f, s, c)
            for p, f, s, c in self.MEDIUM_PATTERNS
        ]
        self.weak_patterns = [
            (re.compile(p, re.IGNORECASE), f, s, c) for p, f, s, c in self.WEAK_PATTERNS
        ]

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


class SourceDetector:
    """Detects source hints from folder and filenames."""

    SOURCE_PATTERNS = {
        SourceType.FC2: [
            (r"\[FC2\]", "[FC2]", 0.25),
            (r"\(FC2\)", "(FC2)", 0.25),
            (r"FC2[-_\s]", "FC2", 0.20),
            (r"PPV[-_\s]", "PPV", 0.15),
            (r"fc2", "fc2", 0.10),
            (r"ppv", "ppv", 0.10),
        ],
        SourceType.DMM: [
            (r"\[DMM\]", "[DMM]", 0.25),
            (r"\[R18\]", "[R18]", 0.25),
            (r"\(DMM\)", "(DMM)", 0.20),
            (r"DMM[-_\s]", "DMM", 0.15),
            (r"R18[-_\s]", "R18", 0.15),
            (r"uncensored", "uncensored", 0.10),
            (r"-h\.mp4$", "-h.mp4", 0.15),
        ],
    }

    def __init__(self):
        """Initialize with compiled patterns."""
        self.compiled_patterns = {}
        for source_type, patterns in self.SOURCE_PATTERNS.items():
            self.compiled_patterns[source_type] = [
                (re.compile(pattern, re.IGNORECASE), matched_text, boost)
                for pattern, matched_text, boost in patterns
            ]

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


class NameAnalyzer:
    """Main name analysis engine."""

    def __init__(
        self,
        folder_weight: float = 0.6,
        file_weight: float = 0.4,
        context_boost: float = 0.1,
    ):
        """Initialize analyzer with configurable weights."""
        self.folder_weight = folder_weight
        self.file_weight = file_weight
        self.context_boost = context_boost

        self.id_extractor = IDExtractor()
        self.source_detector = SourceDetector()
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
