import re
from datetime import datetime
from difflib import SequenceMatcher
import sys
import json
import subprocess

def parse_view_count(view_text):
    """
    Convert view count text to integer
    Examples: "1.2M views" -> 1200000, "10K views" -> 10000
    """
    if not view_text or view_text == 'N/A':
        return 0
    
    view_text = view_text.lower().replace('views', '').replace(',', '').strip()
    
    try:
        if 'k' in view_text:
            return int(float(view_text.replace('k', '')) * 1000)
        elif 'm' in view_text:
            return int(float(view_text.replace('m', '')) * 1000000)
        elif 'b' in view_text:
            return int(float(view_text.replace('b', '')) * 1000000000)
        else:
            return int(float(view_text))
    except:
        return 0

def parse_published_time(published_text):
    """
    Convert published time to recency score
    More recent = higher score
    """
    if not published_text or published_text == 'N/A':
        return 0
    
    published_lower = published_text.lower()
    
    try:
        if 'hour' in published_lower or 'minute' in published_lower:
            return 100  # Very recent
        elif 'day' in published_lower:
            days = int(re.findall(r'\d+', published_text)[0])
            return max(0, 90 - days)
        elif 'week' in published_lower:
            weeks = int(re.findall(r'\d+', published_text)[0])
            return max(0, 80 - (weeks * 2))
        elif 'month' in published_lower:
            months = int(re.findall(r'\d+', published_text)[0])
            return max(0, 60 - (months * 3))
        elif 'year' in published_lower:
            years = int(re.findall(r'\d+', published_text)[0])
            return max(0, 40 - (years * 10))
    except:
        pass
    
    return 20  # Default for old content

def calculate_text_similarity(text1, text2):
    """
    Calculate similarity between two text strings (0-1)
    """
    if not text1 or not text2:
        return 0
    
    text1 = text1.lower()
    text2 = text2.lower()
    
    # Direct substring match bonus
    if text2 in text1 or text1 in text2:
        return 1.0
    
    # Word overlap
    words1 = set(text1.split())
    words2 = set(text2.split())
    
    if not words1 or not words2:
        return 0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    # Jaccard similarity
    jaccard = len(intersection) / len(union) if union else 0
    
    # Sequence matching
    sequence = SequenceMatcher(None, text1, text2).ratio()
    
    # Combine both metrics
    return (jaccard * 0.6) + (sequence * 0.4)

def search_youtube_videos(query, search_limit=15):
    """
    Search YouTube using yt-dlp (more reliable than youtube-search-python)
    
    Args:
        query: Search query string
        search_limit: Number of results to fetch (default 15)
    
    Returns:
        List of video dictionaries or empty list if error
    """
    try:
        # Use yt-dlp to search YouTube
        cmd = [
            'yt-dlp',
            f'ytsearch{search_limit}:{query}',
            '--dump-json',
            '--no-playlist',
            '--skip-download'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"yt-dlp error: {result.stderr}")
            return []
        
        # Parse the JSON output (one JSON object per line)
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    video_data = json.loads(line)
                    videos.append(video_data)
                except json.JSONDecodeError:
                    continue
        
        return videos
    
    except subprocess.TimeoutExpired:
        print("YouTube search timed out")
        return []
    except FileNotFoundError:
        print("yt-dlp not found. Please install it: pip install yt-dlp")
        return []
    except Exception as e:
        print(f"Error searching YouTube: {e}")
        import traceback
        traceback.print_exc()
        return []

def calculate_relevance_score(video, query):
    """
    Calculate relevance score based on multiple factors
    
    Factors:
    - Title similarity (50% weight)
    - Description similarity (20% weight)
    - View count popularity (20% weight)
    - Recency (10% weight)
    """
    # Title similarity (most important)
    title = video.get('title', '')
    title_similarity = calculate_text_similarity(title, query)
    title_score = title_similarity * 50
    
    # Description similarity
    description = video.get('description', '')
    description_similarity = calculate_text_similarity(description, query)
    description_score = description_similarity * 20
    
    # View count (normalized, logarithmic scale for fairness)
    view_count = video.get('view_count', 0)
    if view_count and view_count > 0:
        # Normalize views on log scale (max around 100M views = score of 20)
        import math
        view_score = min(20, (math.log10(view_count) / 8) * 20)
    else:
        view_score = 0
    
    # Recency score based on upload date
    upload_date = video.get('upload_date', '')
    if upload_date:
        try:
            # upload_date is in format YYYYMMDD
            from datetime import datetime, timedelta
            upload_dt = datetime.strptime(upload_date, '%Y%m%d')
            days_ago = (datetime.now() - upload_dt).days
            
            if days_ago < 1:
                recency_score = 10
            elif days_ago < 7:
                recency_score = 9
            elif days_ago < 30:
                recency_score = 7
            elif days_ago < 90:
                recency_score = 5
            elif days_ago < 365:
                recency_score = 3
            else:
                recency_score = 1
        except:
            recency_score = 2
    else:
        recency_score = 2
    
    # Total score
    total_score = title_score + description_score + view_score + recency_score
    
    return total_score

def fetch_most_relevant_youtube_video(query, search_limit=15):
    """
    Search YouTube and return the most RELEVANT video based on query
    
    Args:
        query: Search query string
        search_limit: Number of results to fetch before scoring (default 15)
    
    Returns:
        Dictionary containing the most relevant video info, or None if no results
    """
    try:
        # Search for videos using yt-dlp
        videos = search_youtube_videos(query, search_limit)
        
        if not videos:
            return None
        
        # Calculate relevance scores
        for video in videos:
            video['relevance_score'] = calculate_relevance_score(video, query)
        
        # Sort by relevance score (descending) and return top 1
        most_relevant = sorted(videos, key=lambda x: x['relevance_score'], reverse=True)[0]
        
        # Format the output to match expected interface
        result = {
            'title': most_relevant.get('title', 'N/A'),
            'url': most_relevant.get('webpage_url', most_relevant.get('url', 'N/A')),
            'video_id': most_relevant.get('id', 'N/A'),
            'duration': most_relevant.get('duration_string', 'N/A'),
            'views_text': f"{most_relevant.get('view_count', 0):,} views",
            'views_count': most_relevant.get('view_count', 0),
            'published': most_relevant.get('upload_date', 'N/A'),
            'channel': most_relevant.get('uploader', 'N/A'),
            'thumbnail': most_relevant.get('thumbnail', 'N/A'),
            'description': most_relevant.get('description', '')[:500] if most_relevant.get('description') else '',
            'relevance_score': most_relevant.get('relevance_score', 0)
        }
        
        return result
    
    except Exception as e:
        print(f"Error fetching YouTube videos: {e}")
        import traceback
        traceback.print_exc()
        return None

# Example usage
if __name__ == "__main__":
    query = input("Enter your search query: ")
    top_video = fetch_most_relevant_youtube_video(query, search_limit=15)
    
    if top_video:
        print(f"\n🎯 MOST RELEVANT VIDEO:\n")
        print(f"Title: {top_video['title']}")
        print(f"URL: {top_video['url']}")
        print(f"Channel: {top_video['channel']}")
        print(f"Views: {top_video['views_text']}")
        print(f"Duration: {top_video['duration']}")
        print(f"Published: {top_video['published']}")
        print(f"Relevance Score: {top_video['relevance_score']:.2f}/100")
        if top_video['description']:
            print(f"\nDescription: {top_video['description'][:200]}...")
    else:
        print("No videos found.")
