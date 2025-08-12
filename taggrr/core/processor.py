"""Main processing pipeline for video file organization."""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import VideoGroup, MatchResult, ProcessingResult, ProcessingMode
from .analyzer import NameAnalyzer
from .formatter import OutputPlanner
from ..api.scraperr_client import VideoMatcher
from ..config.settings import TaggerrConfig


logger = logging.getLogger(__name__)


class VideoProcessor:
    """Main video processing pipeline coordinator."""
    
    def __init__(self, config: TaggerrConfig):
        """Initialize processor with configuration."""
        self.config = config
        self.analyzer = NameAnalyzer(
            folder_weight=config.matching.name_analysis.folder_weight,
            file_weight=config.matching.name_analysis.file_weight,
            context_boost=config.matching.name_analysis.context_boost
        )
        self.matcher = VideoMatcher(config)
        self.output_planner = OutputPlanner(config)
    
    async def process_groups(self, video_groups: List[VideoGroup], 
                           output_dir: Path, dry_run: bool = False) -> List[ProcessingResult]:
        """Process all video groups through the complete pipeline."""
        results = []
        
        for i, group in enumerate(video_groups, 1):
            logger.info(f"Processing group {i}/{len(video_groups)}: {group.group_name}")
            
            try:
                result = await self.process_single_group(group, output_dir, dry_run)
                results.append(result)
                
                # Log result
                if result.status == "success":
                    logger.info(f"[SUCCESS] Successfully processed: {result.original_path}")
                elif result.status == "review_needed":
                    logger.warning(f"[REVIEW] Manual review needed: {result.original_path}")
                elif result.status == "skipped":
                    logger.info(f"[SKIPPED] Skipped: {result.original_path}")
                else:
                    logger.error(f"[FAILED] Failed: {result.original_path} - {result.error_message}")
                    
            except Exception as e:
                logger.error(f"Unexpected error processing group {group.group_name}: {e}", exc_info=True)
                results.append(ProcessingResult(
                    original_path=group.folder_path,
                    output_path=None,
                    match_result=None,
                    status="failed",
                    error_message=str(e)
                ))
        
        return results
    
    async def process_single_group(self, video_group: VideoGroup, 
                                 output_dir: Path, dry_run: bool = False) -> ProcessingResult:
        """Process a single video group through the pipeline."""
        # Step 1: Analyze primary file for ID extraction
        primary_file = video_group.primary_file
        analysis = self.analyzer.analyze(primary_file)
        
        logger.debug(f"Analysis result: ID={analysis.primary_id}, confidence={analysis.confidence_scores['combined']:.2f}")
        
        # Step 2: Check confidence thresholds
        combined_confidence = analysis.confidence_scores['combined'] * 100  # Convert to percentage
        
        if combined_confidence < self.config.matching.confidence_thresholds.skip_threshold:
            return ProcessingResult(
                original_path=video_group.folder_path,
                output_path=None,
                match_result=None,
                status="skipped",
                error_message=f"Confidence too low: {combined_confidence:.1f}%"
            )
        
        if (combined_confidence < self.config.matching.confidence_thresholds.manual_review and 
            combined_confidence < self.config.matching.confidence_thresholds.auto_process):
            return ProcessingResult(
                original_path=video_group.folder_path,
                output_path=None,
                match_result=None,
                status="review_needed",
                error_message=f"Manual review required: {combined_confidence:.1f}%"
            )
        
        # Step 3: Match against API if we have a good ID
        match_result = None
        if analysis.primary_id:
            logger.info(f"Searching API for ID: {analysis.primary_id}")
            
            # Determine source hint from analysis
            source_hint = None
            if analysis.source_hints:
                source_hint = analysis.source_hints[0].source_type
            
            try:
                match_result = await self.matcher.match_video(
                    analysis.primary_id,
                    analysis.alternative_ids,
                    source_hint
                )
            except Exception as e:
                logger.warning(f"API search failed: {e}")
        
        # Step 4: Create fallback match if API failed
        if not match_result:
            logger.info("Creating fallback match from analysis")
            match_result = self._create_fallback_match(analysis, video_group)
        
        # Step 5: Plan output structure
        output_plan = self.output_planner.plan_output(video_group, match_result, output_dir)
        
        # Step 6: Validate plan
        is_valid, issues = self.output_planner.validate_output_plan(output_plan)
        if not is_valid:
            return ProcessingResult(
                original_path=video_group.folder_path,
                output_path=None,
                match_result=match_result,
                status="failed",
                error_message=f"Output validation failed: {'; '.join(issues)}"
            )
        
        # Step 7: Execute plan (if not dry run)
        if not dry_run:
            try:
                assets_downloaded = await self._execute_output_plan(output_plan, match_result)
                
                return ProcessingResult(
                    original_path=video_group.folder_path,
                    output_path=output_plan['output_folder'],
                    match_result=match_result,
                    status="success",
                    assets_downloaded=assets_downloaded
                )
            except Exception as e:
                return ProcessingResult(
                    original_path=video_group.folder_path,
                    output_path=None,
                    match_result=match_result,
                    status="failed",
                    error_message=f"Execution failed: {e}"
                )
        else:
            # Dry run - just return the plan
            return ProcessingResult(
                original_path=video_group.folder_path,
                output_path=output_plan['output_folder'],
                match_result=match_result,
                status="success",
                error_message="DRY RUN - No changes made"
            )
    
    def _create_fallback_match(self, analysis, video_group: VideoGroup) -> MatchResult:
        """Create a fallback match result when API lookup fails."""
        from ..core.models import ConfidenceBreakdown
        
        # Use analysis data to create a basic match
        title = analysis.primary_id or video_group.group_name or "Unknown Video"
        
        # Clean up title
        if title.startswith("FC2-PPV-"):
            clean_title = f"FC2 PPV {title[8:]}"
        else:
            clean_title = title.replace("_", " ").replace("-", " ").title()
        
        metadata = {
            "title": clean_title,
            "id": analysis.primary_id,
            "year": analysis.year,
            "source": analysis.source_hints[0].source_type.value if analysis.source_hints else "unknown"
        }
        
        confidence = ConfidenceBreakdown(
            folder_name_match=analysis.confidence_scores.get("folder", 0.0),
            file_name_match=analysis.confidence_scores.get("filename", 0.0), 
            source_match=0.5,  # Moderate confidence for fallback
            overall_confidence=analysis.confidence_scores.get("combined", 0.0)
        )
        
        from ..core.models import SourceType
        
        return MatchResult(
            video_metadata=metadata,
            confidence_breakdown=confidence,
            source=analysis.source_hints[0].source_type if analysis.source_hints else SourceType.GENERIC,
            suggested_output_name=clean_title,
            video_id=analysis.primary_id
        )
    
    async def _execute_output_plan(self, output_plan: Dict[str, Any], 
                                 match_result: MatchResult) -> List[str]:
        """Execute the output plan by copying files and creating assets."""
        import shutil
        
        assets_downloaded = []
        output_folder = output_plan['output_folder']
        
        # Create output directory
        output_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created output directory: {output_folder}")
        
        # Process each item in the structure
        for key, item in output_plan['structure'].items():
            target_path = item['target_path']
            action = item['action']
            
            try:
                if action == 'copy':
                    # Copy video file
                    source_path = Path(key)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, target_path)
                    logger.info(f"Copied: {source_path.name} -> {target_path.name}")
                
                elif action == 'create':
                    # Create NFO file
                    content = item['content']
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(target_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"Created: {target_path.name}")
                    assets_downloaded.append(target_path.name)
                
                elif action == 'download':
                    # Download asset
                    url = item['url']
                    success = await self.matcher.download_assets(match_result, output_folder)
                    if success:
                        assets_downloaded.extend(success)
            
            except Exception as e:
                logger.error(f"Failed to process {key}: {e}")
                # Continue with other files even if one fails
        
        return assets_downloaded
    
    def get_processing_summary(self, results: List[ProcessingResult]) -> Dict[str, Any]:
        """Generate a summary of processing results."""
        summary = {
            "total_groups": len(results),
            "successful": len([r for r in results if r.status == "success"]),
            "failed": len([r for r in results if r.status == "failed"]),
            "skipped": len([r for r in results if r.status == "skipped"]),
            "review_needed": len([r for r in results if r.status == "review_needed"]),
            "total_assets": sum(len(r.assets_downloaded) for r in results if r.assets_downloaded)
        }
        
        summary["success_rate"] = (summary["successful"] / summary["total_groups"] * 100) if summary["total_groups"] > 0 else 0
        
        return summary