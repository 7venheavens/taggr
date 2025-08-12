"""Client for scraperr API integration."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config.settings import TaggerrConfig
from ..core.models import ConfidenceBreakdown, MatchResult, PlexMetadata, SourceType

logger = logging.getLogger(__name__)


@dataclass
class APIResponse:
    """Response from scraperr API."""
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    status_code: int | None = None


class ScraperAPIClient:
    """Client for interacting with scraperr API."""

    def __init__(self, config: TaggerrConfig):
        """Initialize API client with configuration."""
        self.config = config
        self.base_url = config.api.base_url.rstrip('/')
        self.timeout = config.api.timeout
        self.max_retries = config.api.retries
        self.retry_delay = config.api.retry_delay

        # HTTP client with custom timeout and retry settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def search_video(self, video_id: str, source_hint: SourceType | None = None) -> APIResponse:
        """Search for video by ID."""
        endpoint = f"{self.base_url}/api/public/video/{video_id}"

        params = {}
        if source_hint and source_hint != SourceType.GENERIC:
            params['source'] = source_hint.value

        return await self._make_request("GET", endpoint, params=params)

    async def search_multiple_ids(self, video_ids: list[str],
                                source_hint: SourceType | None = None) -> dict[str, APIResponse]:
        """Search for multiple video IDs concurrently."""
        tasks = []
        for video_id in video_ids:
            task = self.search_video(video_id, source_hint)
            tasks.append((video_id, task))

        results = {}
        for video_id, task in tasks:
            try:
                response = await task
                results[video_id] = response
            except Exception as e:
                logger.error(f"Error searching for video ID '{video_id}': {e}")
                results[video_id] = APIResponse(
                    success=False,
                    error=str(e)
                )

        return results

    async def get_video_metadata(self, video_id: str) -> APIResponse:
        """Get detailed metadata for a specific video."""
        endpoint = f"{self.base_url}/api/public/video/{video_id}/metadata"
        return await self._make_request("GET", endpoint)

    async def download_asset(self, asset_url: str, output_path: Path) -> bool:
        """Download an asset (poster, fanart) from URL."""
        try:
            response = await self.client.get(asset_url, follow_redirects=True)
            response.raise_for_status()

            # Ensure directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(output_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Downloaded asset to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download asset from {asset_url}: {e}")
            return False

    async def _make_request(self, method: str, url: str,
                          params: dict | None = None,
                          json_data: dict | None = None) -> APIResponse:
        """Make HTTP request with retry logic."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data
                )

                # Handle different response codes
                if response.status_code == 200:
                    try:
                        data = response.json()
                        return APIResponse(
                            success=True,
                            data=data,
                            status_code=response.status_code
                        )
                    except Exception as e:
                        return APIResponse(
                            success=False,
                            error=f"Invalid JSON response: {e}",
                            status_code=response.status_code
                        )

                elif response.status_code == 404:
                    return APIResponse(
                        success=False,
                        error="Video not found",
                        status_code=404
                    )

                elif response.status_code == 429:
                    # Rate limited - wait longer before retry
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        await asyncio.sleep(wait_time)
                        continue
                    return APIResponse(
                        success=False,
                        error="Rate limited",
                        status_code=429
                    )

                else:
                    return APIResponse(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}",
                        status_code=response.status_code
                    )

            except httpx.TimeoutException as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(f"Request timeout, retrying... (attempt {attempt + 1}/{self.max_retries + 1})")
                    await asyncio.sleep(self.retry_delay)
                    continue

            except httpx.ConnectError as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(f"Connection error, retrying... (attempt {attempt + 1}/{self.max_retries + 1})")
                    await asyncio.sleep(self.retry_delay)
                    continue

            except Exception as e:
                last_exception = e
                logger.error(f"Unexpected error during API request: {e}")
                break

        return APIResponse(
            success=False,
            error=f"Request failed after {self.max_retries + 1} attempts: {last_exception}"
        )


class MetadataProcessor:
    """Processes scraperr API responses into standardized formats."""

    def __init__(self, config: TaggerrConfig):
        """Initialize processor with configuration."""
        self.config = config

    def process_search_response(self, api_response: APIResponse,
                              original_id: str, source_hint: SourceType | None = None) -> MatchResult | None:
        """Process API search response into MatchResult."""
        if not api_response.success or not api_response.data:
            return None

        try:
            data = api_response.data

            # Extract basic metadata
            title = data.get('title', 'Unknown Title')
            year = data.get('year')
            video_id = data.get('id', original_id)

            # Create Plex-compatible metadata
            plex_metadata = PlexMetadata(
                title=title,
                year=year,
                poster_url=data.get('poster_url'),
                fanart_url=data.get('fanart_url'),
                plot=data.get('description'),
                genre=data.get('genres', []) if isinstance(data.get('genres'), list) else None,
                director=data.get('director'),
                duration=data.get('duration')
            )

            # Calculate confidence based on match quality
            confidence = self._calculate_match_confidence(data, original_id, source_hint)

            # Determine source from API response or hint
            detected_source = self._determine_source(data, source_hint)

            # Generate output name
            output_name = self._generate_output_name(plex_metadata)

            return MatchResult(
                video_metadata=data,
                confidence_breakdown=confidence,
                source=detected_source,
                suggested_output_name=output_name,
                video_id=video_id,
                api_response=data
            )

        except Exception as e:
            logger.error(f"Error processing API response: {e}")
            return None

    def _calculate_match_confidence(self, data: dict, original_id: str,
                                  source_hint: SourceType | None = None) -> ConfidenceBreakdown:
        """Calculate confidence scores for the match."""
        # Base confidence from API response
        api_confidence = data.get('confidence', 0.8)  # Default if not provided

        # ID match confidence
        id_match = 0.9 if data.get('id') == original_id else 0.7

        # Source match confidence
        source_match = 0.8
        if source_hint and source_hint != SourceType.GENERIC:
            detected_source = data.get('source', '').lower()
            if detected_source == source_hint.value:
                source_match = 0.95
            elif detected_source and detected_source != source_hint.value:
                source_match = 0.6  # Conflicting sources

        # Overall confidence calculation
        overall = (api_confidence * 0.4 + id_match * 0.4 + source_match * 0.2)

        return ConfidenceBreakdown(
            folder_name_match=0.0,  # Not applicable for API matches
            file_name_match=0.0,    # Not applicable for API matches
            source_match=source_match,
            overall_confidence=overall
        )

    def _determine_source(self, data: dict, source_hint: SourceType | None = None) -> SourceType:
        """Determine the source type from API response."""
        api_source = data.get('source', '').lower()

        # Map API source strings to SourceType
        source_mapping = {
            'fc2': SourceType.FC2,
            'fc2-ppv': SourceType.FC2,
            'dmm': SourceType.DMM,
            'r18': SourceType.DMM,
        }

        detected_source = source_mapping.get(api_source, SourceType.GENERIC)

        # Use hint if detection failed
        if detected_source == SourceType.GENERIC and source_hint:
            return source_hint

        return detected_source

    def _generate_output_name(self, metadata: PlexMetadata) -> str:
        """Generate Plex-compatible output name."""
        title = metadata.title
        year = metadata.year

        if year:
            return f"{title} ({year})"
        else:
            return title


class VideoMatcher:
    """High-level video matching orchestrator."""

    def __init__(self, config: TaggerrConfig):
        """Initialize matcher with configuration."""
        self.config = config
        self.processor = MetadataProcessor(config)

    async def match_video(self, primary_id: str, alternative_ids: list[str],
                         source_hint: SourceType | None = None) -> MatchResult | None:
        """Match video using primary ID and alternatives."""
        async with ScraperAPIClient(self.config) as client:
            # Try primary ID first
            response = await client.search_video(primary_id, source_hint)
            match = self.processor.process_search_response(response, primary_id, source_hint)

            if match and match.confidence_breakdown.overall_confidence > 0.6:
                logger.info(f"Found match for primary ID '{primary_id}' with confidence {match.confidence_breakdown.overall_confidence:.2f}")
                return match

            # Try alternative IDs if primary failed
            if alternative_ids:
                logger.info(f"Primary ID failed, trying {len(alternative_ids)} alternatives")

                for alt_id in alternative_ids:
                    response = await client.search_video(alt_id, source_hint)
                    match = self.processor.process_search_response(response, alt_id, source_hint)

                    if match and match.confidence_breakdown.overall_confidence > 0.5:
                        logger.info(f"Found match for alternative ID '{alt_id}' with confidence {match.confidence_breakdown.overall_confidence:.2f}")
                        return match

            logger.warning(f"No suitable matches found for video ID '{primary_id}'")
            return None

    async def download_assets(self, match_result: MatchResult, output_dir: Path) -> list[str]:
        """Download video assets (poster, fanart, etc.)."""
        if not self.config.plex_output.download_assets:
            return []

        downloaded = []
        async with ScraperAPIClient(self.config) as client:

            # Download poster
            if (match_result.api_response and
                'poster' in self.config.plex_output.asset_types and
                match_result.api_response.get('poster_url')):

                poster_path = output_dir / "poster.jpg"
                if await client.download_asset(match_result.api_response['poster_url'], poster_path):
                    downloaded.append("poster.jpg")

            # Download fanart
            if (match_result.api_response and
                'fanart' in self.config.plex_output.asset_types and
                match_result.api_response.get('fanart_url')):

                fanart_path = output_dir / "fanart.jpg"
                if await client.download_asset(match_result.api_response['fanart_url'], fanart_path):
                    downloaded.append("fanart.jpg")

        return downloaded
