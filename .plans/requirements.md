
● Taggerr - Revised Requirements & Development Plan

  Core Requirements (Updated)

  1. Multi-Level Name Analysis

  - Dual Analysis: Extract identification data from both folder names AND file names
  - Smart Prioritization: Algorithm determines which source (folder vs file) provides better match
  - Configurable Weighting: User can adjust folder vs filename importance
  - Context Awareness: Use folder context to improve file matching accuracy

  2. Multi-Part Video Handling (Plex-Optimized)

  - Automatic Part Detection: Identify split videos using common patterns
  - Grouped Output: Always output to single folder for Plex compatibility
  - Plex Naming Convention: Use Plex-recognized part naming
  - Shared Metadata: Single set of assets (poster, fanart) per grouped movie

  3. Source Override & Detection

  - Global Source Preference: CLI flag to prefer specific sources
  - Per-Match Override: Manual source selection during review
  - Pattern-Based Detection: Configurable regex for auto-source detection
  - Confidence Boosting: Higher confidence for detected source patterns

  Technical Architecture (Revised)

  Enhanced File Analysis

  class VideoFile:
      file_path: str
      folder_name: str
      file_name: str
      detected_parts: List[PartInfo]
      source_hints: List[str]

  class PartInfo:
      part_number: int
      part_pattern: str  # "Part 1", "CD1", "Disc 2", etc.
      confidence: float

  class MatchResult:
      video_metadata: dict
      confidence_breakdown: {
          'folder_name_match': float,
          'file_name_match': float,
          'source_match': float,
          'overall_confidence': float
      }
      source: str
      suggested_output_name: str

  Multi-Part Processing Pipeline

  1. Scan & Group: Find all files, detect and group parts
  2. Match Groups: Match each group against API metadata
  3. Generate Structure: Create Plex-compatible folder structure
  4. Asset Download: Download shared metadata assets
  5. File Organization: Copy/move files with proper naming

  Plex-Compatible Output Strategy

  /output
    /Movie Title (Year)              # Single folder per movie
      Movie Title (Year) - Part 1.mkv    # Plex auto-detects parts
      Movie Title (Year) - Part 2.mkv    # Groups as single movie
      poster.jpg                          # Shared poster
      fanart.jpg                          # Shared background
      movie.nfo                           # Optional metadata file

  Configuration Schema (Updated)

  matching:
    name_analysis:
      folder_weight: 0.6      # How much to weight folder name matches
      file_weight: 0.4        # How much to weight filename matches
      context_boost: 0.1      # Boost when folder provides context

    confidence_thresholds:
      auto_process: 85
      manual_review: 40
      skip_threshold: 20

  source_detection:
    global_preference: null   # Override: "fc2", "dmm", etc.
    patterns:
      fc2:
        folder: ["*FC2*", "*fc2*", "*PPV*"]
        file: ["FC2-*", "fc2_*", "*ppv*"]
        confidence_boost: 0.2
      dmm:
        folder: ["*DMM*", "*R18*"]
        file: ["*-h.mp4", "*uncensored*"]
        confidence_boost: 0.15

  multi_part:
    detection_patterns:
      - regex: "(?i)part\s*(\d+)"
        output_format: "Part {n}"
      - regex: "(?i)cd\s*(\d+)"
        output_format: "CD{n}"
      - regex: "(?i)disc\s*(\d+)"
        output_format: "Disc {n}"
      - regex: "(?i)-(\d+)(?=\.\w+$)"
        output_format: "Part {n}"

    grouping:
      max_parts: 10
      similarity_threshold: 0.8    # How similar names must be to group

  plex_output:
    folder_format: "{title} ({year})"
    file_format: "{title} ({year}) - {part}"
    create_nfo: true
    download_assets: true

  Example Workflows

  Complex Input Structure

  /input
    /FC2-PPV-4734151 Premium HD
      video_part1.mp4
      video_part2.mp4
    /[DMM] Random Folder Name
      actual_movie_title_cd1.mkv
      actual_movie_title_cd2.mkv
    /cryptic_folder
      FC2-4567890-part1.mp4

  Processing Logic

  1. Group Detection: Find part relationships
  2. Name Analysis:
    - Group 1: Folder name "FC2-PPV-4734151 Premium HD" + file hints
    - Group 2: File names "actual_movie_title" + folder hint "[DMM]"
    - Group 3: File names "FC2-4567890" override folder
  3. API Matching: Search using best available names + source hints
  4. Plex Output: Generate grouped folders

  CLI Examples

  # Standard processing with smart name analysis
  taggerr /input /output

  # Prefer folder names for matching
  taggerr --folder-priority 0.8 /input /output

  # Force FC2 source preference  
  taggerr --source-preference fc2 /input /output

  # Review mode for manual overrides
  taggerr --review-mode /input /output

  # Custom configuration
  taggerr --config custom.yaml /input /output

  Review Interface

  Processing: /input/Mystery Folder/cryptic_file_pt1.mp4
  Detected: 2-part video series

  Group Analysis:
    Folder: "Mystery Folder" (low confidence)
    Files: "cryptic_file_pt1.mp4", "cryptic_file_pt2.mp4"

  Best Matches:
  1. [FC2] Amazing Video Title (confidence: 78%)
     - Folder match: 20% | File match: 85% | Source: FC2 detected

  2. [DMM] Different Video Title (confidence: 65%)
     - Folder match: 40% | File match: 70% | Source: Generic

  Actions: [1] Accept | [2] Select #2 | [s] Set source | [m] Manual | [skip]

  This revised strategy prioritizes Plex compatibility while handling the complexity of real-world file naming       
  scenarios through intelligent multi-level analysis and flexible source detect