"""Plex-compatible output formatting and file organization."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

from .models import VideoGroup, MatchResult, ProcessingResult, ProcessingMode, PlexMetadata
from ..config.settings import TaggerrConfig


logger = logging.getLogger(__name__)


class PlexFormatter:
    """Formats file names and folder structures for Plex compatibility."""
    
    def __init__(self, config: TaggerrConfig):
        """Initialize formatter with configuration."""
        self.config = config
        self.plex_config = config.plex_output
        
        # Characters that need to be sanitized for file systems
        self.invalid_chars = re.compile(r'[<>:"/\\|?*]')
        self.invalid_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 
                            'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 
                            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 
                            'LPT7', 'LPT8', 'LPT9'}
    
    def format_folder_name(self, match_result: MatchResult) -> str:
        """Generate Plex-compatible folder name."""
        title = match_result.video_metadata.get('title', 'Unknown Title')
        year = match_result.video_metadata.get('year')
        
        # For FC2 content, use the video ID instead of long Japanese titles to avoid Windows path issues
        if (match_result.source.name == 'FC2' and match_result.video_id and 
            match_result.video_id.isdigit()):
            title = f"FC2-PPV-{match_result.video_id}"
        
        # Use configured format
        if year:
            folder_name = self.plex_config.folder_format.format(
                title=title, 
                year=year
            )
        else:
            # Fallback if no year available
            folder_name = title
        
        return self._sanitize_name(folder_name)
    
    def format_file_name(self, match_result: MatchResult, 
                        part_info: Optional[str] = None, 
                        file_extension: str = ".mp4") -> str:
        """Generate Plex-compatible file name."""
        title = match_result.video_metadata.get('title', 'Unknown Title')
        year = match_result.video_metadata.get('year')
        
        # For FC2 content, use the video ID instead of long Japanese titles to avoid Windows path issues
        if (match_result.source.name == 'FC2' and match_result.video_id and 
            match_result.video_id.isdigit()):
            title = f"FC2-PPV-{match_result.video_id}"
        
        if part_info:
            # Multi-part file
            if year:
                file_name = self.plex_config.file_format.format(
                    title=title,
                    year=year,
                    part=part_info
                )
            else:
                file_name = f"{title} - {part_info}"
        else:
            # Single file
            if year:
                file_name = self.plex_config.single_file_format.format(
                    title=title,
                    year=year
                )
            else:
                file_name = title
        
        sanitized_name = self._sanitize_name(file_name)
        return f"{sanitized_name}{file_extension}"
    
    def format_group_structure(self, video_group: VideoGroup, 
                             match_result: MatchResult) -> Dict[str, str]:
        """Generate complete folder structure for a video group."""
        folder_name = self.format_folder_name(match_result)
        
        structure = {}
        
        if video_group.total_parts == 1:
            # Single file
            original_file = video_group.files[0]
            file_extension = original_file.file_path.suffix
            file_name = self.format_file_name(match_result, None, file_extension)
            structure[str(original_file.file_path)] = f"{folder_name}/{file_name}"
        else:
            # Multi-part files
            for video_file in video_group.files:
                part_info = self._get_part_info(video_file)
                file_extension = video_file.file_path.suffix
                file_name = self.format_file_name(match_result, part_info, file_extension)
                structure[str(video_file.file_path)] = f"{folder_name}/{file_name}"
        
        return structure
    
    def _get_part_info(self, video_file) -> str:
        """Extract part information from video file."""
        if video_file.detected_parts:
            return video_file.detected_parts[0].part_pattern
        return "Part 1"  # Default fallback
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for file system compatibility."""
        # Remove/replace invalid characters
        sanitized = self.invalid_chars.sub('_', name)
        
        # Remove leading/trailing whitespace and dots
        sanitized = sanitized.strip(' .')
        
        # Handle reserved Windows names
        base_name = sanitized.split('.')[0].upper()
        if base_name in self.invalid_names:
            sanitized = f"_{sanitized}"
        
        # Ensure not empty
        if not sanitized:
            sanitized = "Unknown"
        
        # Limit length (most file systems support 255 chars)
        if len(sanitized) > 200:  # Leave room for extensions
            sanitized = sanitized[:200].rstrip()
        
        return sanitized


class NFOGenerator:
    """Generates NFO files for Plex metadata."""
    
    def __init__(self, config: TaggerrConfig):
        """Initialize NFO generator with configuration."""
        self.config = config
    
    def generate_movie_nfo(self, match_result: MatchResult) -> Optional[str]:
        """Generate movie NFO content."""
        if not self.config.plex_output.create_nfo:
            return None
        
        metadata = match_result.video_metadata
        
        nfo_content = []
        nfo_content.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
        nfo_content.append('<movie>')
        
        # Basic metadata
        if metadata.get('title'):
            nfo_content.append(f'  <title>{self._escape_xml(metadata["title"])}</title>')
        
        if metadata.get('year'):
            nfo_content.append(f'  <year>{metadata["year"]}</year>')
        
        if metadata.get('description'):
            nfo_content.append(f'  <plot>{self._escape_xml(metadata["description"])}</plot>')
        
        if metadata.get('director'):
            nfo_content.append(f'  <director>{self._escape_xml(metadata["director"])}</director>')
        
        if metadata.get('duration'):
            # Handle different duration formats
            duration = metadata['duration']
            if isinstance(duration, str) and ':' in duration:
                # Parse "44:09" format to minutes
                try:
                    parts = duration.split(':')
                    if len(parts) == 2:
                        minutes = int(parts[0])
                        seconds = int(parts[1])
                        duration = minutes + (seconds / 60)
                    elif len(parts) == 3:  # HH:MM:SS format
                        hours = int(parts[0])
                        minutes = int(parts[1])
                        seconds = int(parts[2])
                        duration = (hours * 60) + minutes + (seconds / 60)
                except (ValueError, IndexError):
                    duration = None
            elif isinstance(duration, (int, float)):
                # Convert to minutes if in seconds
                if duration > 1000:  # Assume seconds if > 1000
                    duration = duration // 60
            
            if duration:
                nfo_content.append(f'  <runtime>{int(duration)}</runtime>')
        
        # Genres
        if metadata.get('genres') and isinstance(metadata['genres'], list):
            for genre in metadata['genres']:
                nfo_content.append(f'  <genre>{self._escape_xml(genre)}</genre>')
        
        # Rating (if available)
        if metadata.get('rating'):
            nfo_content.append(f'  <rating>{metadata["rating"]}</rating>')
        
        # Studio/Source
        if metadata.get('studio'):
            nfo_content.append(f'  <studio>{self._escape_xml(metadata["studio"])}</studio>')
        
        # Unique ID
        if metadata.get('id'):
            nfo_content.append(f'  <uniqueid type="scraperr">{metadata["id"]}</uniqueid>')
        
        # Poster and fanart
        if metadata.get('poster_url'):
            nfo_content.append('  <thumb aspect="poster">poster.jpg</thumb>')
        
        if metadata.get('fanart_url'):
            nfo_content.append('  <fanart>')
            nfo_content.append('    <thumb>fanart.jpg</thumb>')
            nfo_content.append('  </fanart>')
        
        nfo_content.append('</movie>')
        
        return '\n'.join(nfo_content)
    
    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        if not isinstance(text, str):
            text = str(text)
        
        replacements = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }
        
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        
        return text


class OutputPlanner:
    """Plans the complete output structure for processed videos."""
    
    def __init__(self, config: TaggerrConfig):
        """Initialize output planner with configuration."""
        self.config = config
        self.formatter = PlexFormatter(config)
        self.nfo_generator = NFOGenerator(config)
    
    def plan_output(self, video_group: VideoGroup, match_result: MatchResult, 
                   output_base_dir: Path) -> Dict[str, any]:
        """Plan complete output structure for a video group."""
        # Generate folder structure
        file_mapping = self.formatter.format_group_structure(video_group, match_result)
        
        # Calculate output paths
        output_structure = {}
        folder_name = self.formatter.format_folder_name(match_result)
        output_folder = output_base_dir / folder_name
        
        # Plan file moves/copies
        for source_path, relative_path in file_mapping.items():
            source = Path(source_path)
            target = output_base_dir / relative_path
            
            output_structure[str(source)] = {
                'target_path': target,
                'relative_path': relative_path,
                'action': 'copy'  # Will be determined later based on processing mode
            }
        
        # Plan NFO file creation
        nfo_content = self.nfo_generator.generate_movie_nfo(match_result)
        if nfo_content:
            nfo_path = output_folder / 'movie.nfo'
            output_structure['_nfo'] = {
                'target_path': nfo_path,
                'content': nfo_content,
                'action': 'create'
            }
        
        # Plan asset downloads
        if self.config.plex_output.download_assets:
            if match_result.api_response and match_result.api_response.get('poster_url'):
                poster_path = output_folder / 'poster.jpg'
                output_structure['_poster'] = {
                    'target_path': poster_path,
                    'url': match_result.api_response['poster_url'],
                    'action': 'download'
                }
            
            if match_result.api_response and match_result.api_response.get('fanart_url'):
                fanart_path = output_folder / 'fanart.jpg'
                output_structure['_fanart'] = {
                    'target_path': fanart_path,
                    'url': match_result.api_response['fanart_url'],
                    'action': 'download'
                }
        
        return {
            'output_folder': output_folder,
            'structure': output_structure,
            'folder_name': folder_name,
            'total_files': len([k for k in output_structure.keys() if not k.startswith('_')])
        }
    
    def validate_output_plan(self, plan: Dict[str, any]) -> Tuple[bool, List[str]]:
        """Validate that the output plan is feasible."""
        issues = []
        
        # Check if output folder would be too deeply nested
        output_folder = plan['output_folder']
        if len(str(output_folder)) > 250:  # Conservative path length limit
            issues.append(f"Output path too long: {output_folder}")
        
        # Check for potential conflicts
        target_paths = set()
        for item in plan['structure'].values():
            target_path = str(item['target_path'])
            if target_path in target_paths:
                issues.append(f"Duplicate target path: {target_path}")
            target_paths.add(target_path)
        
        # Check for invalid characters in folder name
        folder_name = plan['folder_name']
        if any(char in folder_name for char in '<>:"/\\|?*'):
            issues.append(f"Invalid characters in folder name: {folder_name}")
        
        return len(issues) == 0, issues
    
    def get_plan_summary(self, plan: Dict[str, any]) -> str:
        """Generate a human-readable summary of the output plan."""
        folder_name = plan['folder_name']
        total_files = plan['total_files']
        
        summary_parts = [
            f"Output folder: {folder_name}",
            f"Files to process: {total_files}"
        ]
        
        structure = plan['structure']
        
        # Count different action types
        actions = {}
        for item in structure.values():
            action = item['action']
            actions[action] = actions.get(action, 0) + 1
        
        if actions.get('copy', 0) > 0:
            summary_parts.append(f"Files to copy: {actions['copy']}")
        
        if actions.get('create', 0) > 0:
            summary_parts.append(f"NFO files to create: {actions['create']}")
        
        if actions.get('download', 0) > 0:
            summary_parts.append(f"Assets to download: {actions['download']}")
        
        return " | ".join(summary_parts)