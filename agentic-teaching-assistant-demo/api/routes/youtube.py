"""
YouTube Routes

Handles YouTube video search for supplementary learning materials.
Uses youtube_search.py for video search.
"""

import os
import sys
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

router = APIRouter()


class YouTubeVideoResponse(BaseModel):
    """Response schema for a YouTube video."""
    video_id: str
    title: str
    channel: str
    thumbnail_url: str
    url: str
    embed_url: str
    duration: Optional[str] = None
    views_text: Optional[str] = None


class YouTubeSearchResponse(BaseModel):
    """Response schema for YouTube search."""
    success: bool
    videos: List[YouTubeVideoResponse]
    message: Optional[str] = None


@router.get("/search", response_model=YouTubeSearchResponse)
async def search_youtube(
    query: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Maximum number of results", ge=1, le=20),
):
    """
    Search for YouTube videos related to a topic.
    
    Args:
        query: The search query
        limit: Maximum number of results to return
        
    Returns:
        YouTubeSearchResponse with video results
    """
    try:
        from youtube_search import fetch_most_relevant_youtube_video, search_youtube_videos
        
        # Try to get multiple videos
        try:
            videos = search_youtube_videos(query, search_limit=limit * 3)  # Get more to filter
            
            if not videos:
                raise ValueError("No videos found")
            
            # Convert to response format
            video_responses = []
            for video in videos[:limit]:
                video_id = video.get("video_id", "")
                video_responses.append(YouTubeVideoResponse(
                    video_id=video_id,
                    title=video.get("title", ""),
                    channel=video.get("channel", ""),
                    thumbnail_url=video.get("thumbnail_url", f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"),
                    url=video.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                    embed_url=f"https://www.youtube.com/embed/{video_id}",
                    duration=video.get("duration"),
                    views_text=video.get("views_text"),
                ))
            
            return YouTubeSearchResponse(
                success=True,
                videos=video_responses,
                message=f"Found {len(video_responses)} videos",
            )
            
        except (AttributeError, TypeError):
            # search_youtube_videos might not exist, try single video
            video = fetch_most_relevant_youtube_video(query, search_limit=limit * 2)
            
            if video:
                video_id = video.get("video_id", "")
                return YouTubeSearchResponse(
                    success=True,
                    videos=[YouTubeVideoResponse(
                        video_id=video_id,
                        title=video.get("title", ""),
                        channel=video.get("channel", ""),
                        thumbnail_url=video.get("thumbnail_url", f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"),
                        url=video.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                        embed_url=f"https://www.youtube.com/embed/{video_id}",
                        duration=video.get("duration"),
                        views_text=video.get("views_text"),
                    )],
                    message="Found 1 video",
                )
            else:
                return YouTubeSearchResponse(
                    success=False,
                    videos=[],
                    message="No videos found for this query",
                )
                
    except ImportError:
        # YouTube module not available - return mock data
        mock_videos = [
            YouTubeVideoResponse(
                video_id="dQw4w9WgXcQ",
                title=f"Learn about {query} - Full Tutorial",
                channel="Educational Channel",
                thumbnail_url="https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                embed_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
                duration="10:30",
                views_text="1.2M views",
            ),
            YouTubeVideoResponse(
                video_id="abc123def",
                title=f"{query} Explained Simply",
                channel="Learn Academy",
                thumbnail_url="https://img.youtube.com/vi/abc123def/mqdefault.jpg",
                url="https://www.youtube.com/watch?v=abc123def",
                embed_url="https://www.youtube.com/embed/abc123def",
                duration="15:45",
                views_text="500K views",
            ),
        ]
        
        return YouTubeSearchResponse(
            success=True,
            videos=mock_videos[:limit],
            message="Mock data - YouTube search module not available",
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error searching YouTube: {str(e)}"
        )


@router.get("/video/{video_id}", response_model=YouTubeVideoResponse)
async def get_video(video_id: str):
    """
    Get details for a specific YouTube video.
    
    Args:
        video_id: The YouTube video ID
        
    Returns:
        YouTubeVideoResponse with video details
    """
    # For now, just construct URLs from video_id
    # In a full implementation, this would fetch video metadata from YouTube API
    return YouTubeVideoResponse(
        video_id=video_id,
        title=f"Video {video_id}",
        channel="Unknown",
        thumbnail_url=f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        url=f"https://www.youtube.com/watch?v={video_id}",
        embed_url=f"https://www.youtube.com/embed/{video_id}",
    )

