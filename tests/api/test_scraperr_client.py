"""Test scraperr API client functionality."""

import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from taggrr.api.scraperr_client import (
    APIResponse,
    MetadataProcessor,
    ScraperAPIClient,
    VideoMatcher,
)
from taggrr.core.models import ConfidenceBreakdown, MatchResult, SourceType


class TestAPIResponse:
    """Test APIResponse data class."""

    def test_create_success_response(self):
        """Test creating successful API response."""
        data = {
            "id": "FC2-PPV-1234567",
            "title": "Test Movie",
            "year": 2024,
            "source": "fc2",
            "confidence": 0.95,
        }
        response = APIResponse(success=True, data=data, status_code=200)

        assert response.success is True
        assert response.data == data
        assert response.status_code == 200
        assert response.error is None

    def test_create_error_response(self):
        """Test creating error API response."""
        response = APIResponse(success=False, error="Video not found", status_code=404)

        assert response.success is False
        assert response.error == "Video not found"
        assert response.status_code == 404
        assert response.data is None


class TestScraperAPIClient:
    """Test scraperr API client."""

    @pytest.fixture
    def mock_client(self, test_config):
        """Create API client with mocked HTTP client."""
        client = ScraperAPIClient(test_config)
        client.client = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_search_video_success(self, mock_client):
        """Test successful video search."""
        # Mock successful response matching expected API structure
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "FC2-PPV-1234567",
            "title": "Test Video Title",
            "year": 2024,
            "description": "A test video description",
            "poster_url": "https://example.com/poster.jpg",
            "fanart_url": "https://example.com/fanart.jpg",
            "source": "fc2",
            "confidence": 0.95,
            "genres": ["Action", "Drama"],
            "director": "Test Director",
            "duration": 7200,
            "rating": 8.5,
            "studio": "Test Studio",
        }
        mock_client.client.request.return_value = mock_response

        result = await mock_client.search_video("FC2-PPV-1234567", SourceType.FC2)

        assert result.success is True
        assert result.data["id"] == "FC2-PPV-1234567"
        assert result.data["title"] == "Test Video Title"
        assert result.data["source"] == "fc2"
        assert result.data["confidence"] == 0.95
        assert result.status_code == 200

        # Verify request parameters
        mock_client.client.request.assert_called_once()
        args, kwargs = mock_client.client.request.call_args
        assert kwargs["method"] == "GET"
        assert "FC2-PPV-1234567" in kwargs["url"]
        assert kwargs["params"] == {"source": "fc2"}

    @pytest.mark.asyncio
    async def test_search_video_without_source_hint(self, mock_client):
        """Test video search without source hint."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "TEST-123",
            "title": "Generic Video",
            "source": "generic",
        }
        mock_client.client.request.return_value = mock_response

        result = await mock_client.search_video("TEST-123")

        assert result.success is True

        # Verify no source parameter when no hint provided
        args, kwargs = mock_client.client.request.call_args
        assert kwargs.get("params") == {}

    @pytest.mark.asyncio
    async def test_search_video_not_found(self, mock_client):
        """Test video not found response."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_client.client.request.return_value = mock_response

        result = await mock_client.search_video("nonexistent")

        assert result.success is False
        assert result.error == "Video not found"
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_search_video_invalid_json(self, mock_client):
        """Test handling of invalid JSON response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_client.client.request.return_value = mock_response

        result = await mock_client.search_video("test")

        assert result.success is False
        assert "Invalid JSON response" in result.error
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_search_video_rate_limited_with_retry(self, mock_client):
        """Test rate limiting with successful retry."""
        # First call is rate limited, second succeeds
        responses = [
            Mock(status_code=429),
            Mock(status_code=200, json=lambda: {"id": "test", "title": "Test"}),
        ]
        mock_client.client.request.side_effect = responses

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await mock_client.search_video("test")

        assert result.success is True
        assert result.data["id"] == "test"
        assert mock_client.client.request.call_count == 2
        mock_sleep.assert_called_once()  # Should wait before retry

    @pytest.mark.asyncio
    async def test_search_video_rate_limited_max_retries(self, mock_client):
        """Test rate limiting exceeding max retries."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_client.client.request.return_value = mock_response

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mock_client.search_video("test")

        assert result.success is False
        assert result.error == "Rate limited"
        assert result.status_code == 429
        assert mock_client.client.request.call_count == mock_client.max_retries + 1

    @pytest.mark.asyncio
    async def test_search_video_server_error(self, mock_client):
        """Test server error handling."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.client.request.return_value = mock_response

        result = await mock_client.search_video("test")

        assert result.success is False
        assert "HTTP 500" in result.error
        assert "Internal Server Error" in result.error
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_search_multiple_ids(self, mock_client):
        """Test searching multiple IDs concurrently."""

        def mock_request(method, url, **kwargs):
            """Mock request that returns different responses based on URL."""
            if "FC2-PPV-1111111" in url:
                return Mock(
                    status_code=200,
                    json=lambda: {
                        "id": "FC2-PPV-1111111",
                        "title": "Video 1",
                        "source": "fc2",
                    },
                )
            elif "FC2-PPV-2222222" in url:
                return Mock(status_code=404)
            else:
                return Mock(
                    status_code=200,
                    json=lambda: {
                        "id": "FC2-PPV-3333333",
                        "title": "Video 3",
                        "source": "fc2",
                    },
                )

        mock_client.client.request.side_effect = mock_request

        results = await mock_client.search_multiple_ids(
            ["FC2-PPV-1111111", "FC2-PPV-2222222", "FC2-PPV-3333333"], SourceType.FC2
        )

        assert len(results) == 3
        assert results["FC2-PPV-1111111"].success is True
        assert results["FC2-PPV-1111111"].data["title"] == "Video 1"
        assert results["FC2-PPV-2222222"].success is False
        assert results["FC2-PPV-3333333"].success is True

    @pytest.mark.asyncio
    async def test_search_multiple_ids_with_exception(self, mock_client):
        """Test multiple ID search with exception handling."""

        def mock_request(method, url, **kwargs):
            if "good_id" in url:
                return Mock(
                    status_code=200, json=lambda: {"id": "good_id", "title": "Good"}
                )
            else:
                raise httpx.TimeoutException("Timeout")

        mock_client.client.request.side_effect = mock_request

        results = await mock_client.search_multiple_ids(["good_id", "bad_id"])

        assert len(results) == 2
        assert results["good_id"].success is True
        assert results["bad_id"].success is False
        assert "Timeout" in results["bad_id"].error

    @pytest.mark.asyncio
    async def test_get_video_metadata(self, mock_client):
        """Test getting detailed video metadata."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "FC2-PPV-1234567",
            "title": "Detailed Video",
            "description": "Detailed description with more information",
            "duration": 7200,
            "genres": ["Action", "Adventure"],
            "director": "Famous Director",
            "rating": 9.2,
            "studio": "Premium Studio",
        }
        mock_client.client.request.return_value = mock_response

        result = await mock_client.get_video_metadata("FC2-PPV-1234567")

        assert result.success is True
        assert result.data["duration"] == 7200
        assert result.data["director"] == "Famous Director"
        assert len(result.data["genres"]) == 2

        # Verify correct endpoint
        args, kwargs = mock_client.client.request.call_args
        assert "/metadata" in kwargs["url"]
        assert "FC2-PPV-1234567" in kwargs["url"]

    @pytest.mark.asyncio
    async def test_download_asset_success(self, mock_client, temp_dir):
        """Test successful asset download."""
        asset_content = b"fake image data"
        mock_response = Mock()
        mock_response.content = asset_content
        mock_response.raise_for_status = Mock()
        mock_client.client.get.return_value = mock_response

        output_path = temp_dir / "assets" / "poster.jpg"
        result = await mock_client.download_asset(
            "https://example.com/poster.jpg", output_path
        )

        assert result is True
        assert output_path.exists()
        assert output_path.read_bytes() == asset_content

        # Verify directory was created
        assert output_path.parent.exists()

        mock_client.client.get.assert_called_once_with(
            "https://example.com/poster.jpg", follow_redirects=True
        )

    @pytest.mark.asyncio
    async def test_download_asset_http_error(self, mock_client, temp_dir):
        """Test asset download with HTTP error."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=Mock(), response=Mock()
        )
        mock_client.client.get.return_value = mock_response

        output_path = temp_dir / "poster.jpg"
        result = await mock_client.download_asset(
            "https://example.com/missing.jpg", output_path
        )

        assert result is False
        assert not output_path.exists()

    @pytest.mark.asyncio
    async def test_context_manager(self, test_config):
        """Test async context manager functionality."""
        async with ScraperAPIClient(test_config) as client:
            assert client.client is not None
            assert hasattr(client.client, "get")

        # Client should be closed after context exit
        # Note: We can't test the exact exception since it depends on httpx internals
        # But we can verify close was called
        assert client.client.is_closed


class TestMetadataProcessor:
    """Test metadata processing functionality."""

    @pytest.fixture
    def processor(self, test_config):
        """Create metadata processor."""
        return MetadataProcessor(test_config)

    def test_process_success_response(self, processor):
        """Test processing successful API response."""
        api_response = APIResponse(
            success=True,
            data={
                "id": "FC2-PPV-1234567",
                "title": "Test Movie",
                "year": 2024,
                "description": "A test movie description",
                "poster_url": "https://example.com/poster.jpg",
                "fanart_url": "https://example.com/fanart.jpg",
                "source": "fc2",
                "confidence": 0.95,
                "genres": ["Action", "Drama"],
                "director": "Test Director",
                "duration": 7200,
            },
        )

        result = processor.process_search_response(
            api_response, "FC2-PPV-1234567", SourceType.FC2
        )

        assert result is not None
        assert isinstance(result, MatchResult)
        assert result.video_id == "FC2-PPV-1234567"
        assert result.source == SourceType.FC2
        assert result.suggested_output_name == "Test Movie (2024)"
        assert result.confidence_breakdown.overall_confidence > 0.8
        assert result.api_response == api_response.data

    def test_process_response_without_year(self, processor):
        """Test processing response without year."""
        api_response = APIResponse(
            success=True,
            data={"id": "TEST-123", "title": "Movie Without Year", "source": "generic"},
        )

        result = processor.process_search_response(api_response, "TEST-123")

        assert result is not None
        assert result.suggested_output_name == "Movie Without Year"

    def test_process_failed_response(self, processor):
        """Test processing failed API response."""
        api_response = APIResponse(success=False, error="Video not found")

        result = processor.process_search_response(api_response, "nonexistent")

        assert result is None

    def test_process_empty_data_response(self, processor):
        """Test processing response with empty data."""
        api_response = APIResponse(success=True, data=None)

        result = processor.process_search_response(api_response, "test")

        assert result is None

    def test_calculate_match_confidence_exact_match(self, processor):
        """Test confidence calculation with exact ID match."""
        data = {"id": "FC2-PPV-1234567", "confidence": 0.9, "source": "fc2"}

        confidence = processor._calculate_match_confidence(
            data, "FC2-PPV-1234567", SourceType.FC2
        )

        assert isinstance(confidence, ConfidenceBreakdown)
        assert confidence.source_match > 0.9  # Exact source match
        assert confidence.overall_confidence > 0.85  # High overall confidence

    def test_calculate_confidence_different_id(self, processor):
        """Test confidence calculation with different ID."""
        data = {"id": "DIFFERENT-123", "confidence": 0.8, "source": "fc2"}

        confidence = processor._calculate_match_confidence(
            data, "FC2-PPV-1234567", SourceType.FC2
        )

        # Should have lower confidence due to ID mismatch
        assert confidence.overall_confidence < 0.85

    def test_calculate_confidence_conflicting_sources(self, processor):
        """Test confidence with conflicting sources."""
        data = {
            "id": "TEST-123",
            "confidence": 0.9,
            "source": "dmm",  # Different from hint
        }

        confidence = processor._calculate_match_confidence(
            data,
            "TEST-123",
            SourceType.FC2,  # Hint is FC2
        )

        assert confidence.source_match < 0.7  # Lower due to source conflict

    def test_calculate_confidence_no_api_confidence(self, processor):
        """Test confidence calculation when API doesn't provide confidence."""
        data = {
            "id": "TEST-123",
            "source": "fc2",
            # No 'confidence' field
        }

        confidence = processor._calculate_match_confidence(
            data, "TEST-123", SourceType.FC2
        )

        # Should use default confidence
        assert confidence.overall_confidence > 0.7

    def test_determine_source_from_api(self, processor):
        """Test source determination from API response."""
        test_cases = [
            ({"source": "fc2"}, None, SourceType.FC2),
            ({"source": "fc2-ppv"}, None, SourceType.FC2),
            ({"source": "dmm"}, None, SourceType.DMM),
            ({"source": "r18"}, None, SourceType.DMM),
            ({"source": "unknown"}, SourceType.FC2, SourceType.FC2),  # Fallback to hint
            ({}, SourceType.DMM, SourceType.DMM),  # Use hint when no API source
            ({"source": ""}, None, SourceType.GENERIC),  # Empty source
        ]

        for data, hint, expected in test_cases:
            result = processor._determine_source(data, hint)
            assert result == expected, f"Failed for data={data}, hint={hint}"

    def test_generate_output_name_with_year(self, processor):
        """Test output name generation with year."""
        from taggrr.core.models import PlexMetadata

        metadata = PlexMetadata("Amazing Movie", 2024)
        result = processor._generate_output_name(metadata)

        assert result == "Amazing Movie (2024)"

    def test_generate_output_name_without_year(self, processor):
        """Test output name generation without year."""
        from taggrr.core.models import PlexMetadata

        metadata = PlexMetadata("Movie Title", None)
        result = processor._generate_output_name(metadata)

        assert result == "Movie Title"

    def test_process_response_with_malformed_data(self, processor):
        """Test processing response with malformed data."""
        api_response = APIResponse(
            success=True, data={"invalid": "structure", "missing": "required_fields"}
        )

        # Should handle gracefully and not crash
        result = processor.process_search_response(api_response, "test")

        assert result is not None
        assert result.suggested_output_name == "Unknown Title"  # Default title
        assert result.video_id == "test"  # Uses original_id as fallback

    def test_process_response_with_exception(self, processor):
        """Test processing response that raises exception."""
        api_response = APIResponse(
            success=True,
            data={"title": None},  # This might cause issues in processing
        )

        # Mock the processing to raise an exception
        with patch.object(processor, "_generate_output_name") as mock_gen:
            mock_gen.side_effect = Exception("Processing error")

            result = processor.process_search_response(api_response, "test")

        assert result is None  # Should return None on exception


class TestVideoMatcher:
    """Test video matching orchestrator."""

    @pytest.fixture
    def matcher(self, test_config):
        """Create video matcher."""
        return VideoMatcher(test_config)

    @pytest.mark.asyncio
    async def test_match_video_primary_success(self, matcher):
        """Test successful match with primary ID."""
        mock_match_result = MatchResult(
            video_metadata={"id": "FC2-PPV-1234567", "title": "Test Video"},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.9, 0.85),
            source=SourceType.FC2,
            suggested_output_name="Test Video (2024)",
            video_id="FC2-PPV-1234567",
        )

        with patch.object(matcher.processor, "process_search_response") as mock_process:
            mock_process.return_value = mock_match_result

            with patch(
                "taggrr.api.scraperr_client.ScraperAPIClient"
            ) as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client.search_video.return_value = APIResponse(
                    success=True, data={}
                )

                result = await matcher.match_video(
                    "FC2-PPV-1234567", [], SourceType.FC2
                )

        assert result is not None
        assert result.video_id == "FC2-PPV-1234567"
        assert result.confidence_breakdown.overall_confidence == 0.85

        # Should only try primary ID
        mock_client.search_video.assert_called_once_with(
            "FC2-PPV-1234567", SourceType.FC2
        )

    @pytest.mark.asyncio
    async def test_match_video_primary_low_confidence(self, matcher):
        """Test primary match with low confidence, should try alternatives."""
        low_confidence_result = MatchResult(
            video_metadata={"id": "FC2-PPV-1234567", "title": "Test"},
            confidence_breakdown=ConfidenceBreakdown(0.3, 0.3, 0.3, 0.3),
            source=SourceType.FC2,
            suggested_output_name="Test",
            video_id="FC2-PPV-1234567",
        )

        high_confidence_result = MatchResult(
            video_metadata={"id": "ALT-456", "title": "Test Alternative"},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Test Alternative",
            video_id="ALT-456",
        )

        with patch.object(matcher.processor, "process_search_response") as mock_process:
            mock_process.side_effect = [low_confidence_result, high_confidence_result]

            with patch(
                "taggrr.api.scraperr_client.ScraperAPIClient"
            ) as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client.search_video.return_value = APIResponse(
                    success=True, data={}
                )

                result = await matcher.match_video(
                    "FC2-PPV-1234567", ["ALT-456"], SourceType.FC2
                )

        assert result is not None
        assert result.video_id == "ALT-456"  # Should use alternative
        assert result.confidence_breakdown.overall_confidence == 0.8

        # Should try both primary and alternative
        assert mock_client.search_video.call_count == 2

    @pytest.mark.asyncio
    async def test_match_video_no_alternatives(self, matcher):
        """Test when primary fails and no alternatives provided."""
        low_confidence_result = MatchResult(
            video_metadata={"id": "TEST-123", "title": "Test"},
            confidence_breakdown=ConfidenceBreakdown(0.3, 0.3, 0.3, 0.3),
            source=SourceType.GENERIC,
            suggested_output_name="Test",
            video_id="TEST-123",
        )

        with patch.object(matcher.processor, "process_search_response") as mock_process:
            mock_process.return_value = low_confidence_result

            with patch(
                "taggrr.api.scraperr_client.ScraperAPIClient"
            ) as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client.search_video.return_value = APIResponse(
                    success=True, data={}
                )

                result = await matcher.match_video("TEST-123", [])

        assert result is None  # Low confidence and no alternatives

        # Should only try primary
        mock_client.search_video.assert_called_once_with("TEST-123", None)

    @pytest.mark.asyncio
    async def test_match_video_all_alternatives_fail(self, matcher):
        """Test when all IDs fail to match."""
        with patch.object(matcher.processor, "process_search_response") as mock_process:
            mock_process.return_value = None  # All searches fail

            with patch(
                "taggrr.api.scraperr_client.ScraperAPIClient"
            ) as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client.search_video.return_value = APIResponse(success=False)

                result = await matcher.match_video("nonexistent", ["alt1", "alt2"])

        assert result is None

        # Should try primary + 2 alternatives
        assert mock_client.search_video.call_count == 3

    @pytest.mark.asyncio
    async def test_download_assets_success(self, matcher, temp_dir):
        """Test successful asset downloading."""
        match_result = MatchResult(
            video_metadata={},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Test Movie",
            api_response={
                "poster_url": "https://example.com/poster.jpg",
                "fanart_url": "https://example.com/fanart.jpg",
            },
        )

        with patch("taggrr.api.scraperr_client.ScraperAPIClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.download_asset.return_value = True

            downloaded = await matcher.download_assets(match_result, temp_dir)

        assert "poster.jpg" in downloaded
        assert "fanart.jpg" in downloaded
        assert len(downloaded) == 2

        # Verify download calls with correct paths
        expected_calls = [
            (match_result.api_response["poster_url"], temp_dir / "poster.jpg"),
            (match_result.api_response["fanart_url"], temp_dir / "fanart.jpg"),
        ]

        actual_calls = mock_client.download_asset.call_args_list
        assert len(actual_calls) == 2

        for call, (expected_url, expected_path) in zip(actual_calls, expected_calls):
            args, kwargs = call
            assert args[0] == expected_url
            assert args[1] == expected_path

    @pytest.mark.asyncio
    async def test_download_assets_disabled(self, matcher, temp_dir):
        """Test when asset downloading is disabled."""
        matcher.config.plex_output.download_assets = False

        match_result = MatchResult(
            video_metadata={},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Test",
            api_response={"poster_url": "https://example.com/poster.jpg"},
        )

        downloaded = await matcher.download_assets(match_result, temp_dir)

        assert len(downloaded) == 0

    @pytest.mark.asyncio
    async def test_download_assets_partial_failure(self, matcher, temp_dir):
        """Test asset downloading with some failures."""
        match_result = MatchResult(
            video_metadata={},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Test",
            api_response={
                "poster_url": "https://example.com/poster.jpg",
                "fanart_url": "https://example.com/fanart.jpg",
            },
        )

        with patch("taggrr.api.scraperr_client.ScraperAPIClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            # Poster succeeds, fanart fails
            mock_client.download_asset.side_effect = [True, False]

            downloaded = await matcher.download_assets(match_result, temp_dir)

        assert "poster.jpg" in downloaded
        assert "fanart.jpg" not in downloaded
        assert len(downloaded) == 1

    @pytest.mark.asyncio
    async def test_download_assets_missing_urls(self, matcher, temp_dir):
        """Test asset downloading when URLs are missing."""
        match_result = MatchResult(
            video_metadata={},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Test",
            api_response={},  # No asset URLs
        )

        downloaded = await matcher.download_assets(match_result, temp_dir)

        assert len(downloaded) == 0

    @pytest.mark.asyncio
    async def test_download_assets_no_api_response(self, matcher, temp_dir):
        """Test asset downloading when no API response available."""
        match_result = MatchResult(
            video_metadata={},
            confidence_breakdown=ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8),
            source=SourceType.FC2,
            suggested_output_name="Test",
            api_response=None,
        )

        downloaded = await matcher.download_assets(match_result, temp_dir)

        assert len(downloaded) == 0
