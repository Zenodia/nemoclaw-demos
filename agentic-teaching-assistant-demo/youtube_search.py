import re
from datetime import datetime
from difflib import SequenceMatcher
import subprocess
import json

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
    title_similarity = calculate_text_similarity(video['title'], query)
    title_score = title_similarity * 50
    
    # Description similarity
    description_similarity = calculate_text_similarity(video['description'], query)
    description_score = description_similarity * 20
    
    # View count (normalized, logarithmic scale for fairness)
    view_count = video['views_count']
    if view_count > 0:
        # Normalize views on log scale (max around 100M views = score of 20)
        import math
        view_score = min(20, (math.log10(view_count) / 8) * 20)
    else:
        view_score = 0
    
    # Recency score
    recency_score = parse_published_time(video['published']) * 0.1
    
    # Total score
    total_score = title_score + description_score + view_score + recency_score
    
    return total_score

def _search_with_youtubesearchpython(query, search_limit=15):
    """
    Search using youtube-search-python library.
    May fail with httpx version conflicts.
    """
    from youtubesearchpython import VideosSearch
    
    videos_search = VideosSearch(query, limit=search_limit)
    results = videos_search.result()
    
    if not results.get('result'):
        return None
    
    # Extract and enrich video information
    videos = []
    for video in results['result']:
        view_text = video.get('viewCount', {}).get('text', 'N/A')
        
        # Extract description snippet
        description_snippets = video.get('descriptionSnippet', [])
        description = ' '.join([snippet.get('text', '') for snippet in description_snippets]) if description_snippets else ''
        
        video_info = {
            'title': video.get('title', 'N/A'),
            'url': video.get('link', 'N/A'),
            'video_id': video.get('id', 'N/A'),
            'duration': video.get('duration', 'N/A'),
            'views_text': view_text,
            'views_count': parse_view_count(view_text),
            'published': video.get('publishedTime', 'N/A'),
            'channel': video.get('channel', {}).get('name', 'N/A'),
            'thumbnail': video.get('thumbnails', [{}])[0].get('url', 'N/A'),
            'description': description
        }
        
        # Calculate relevance score
        video_info['relevance_score'] = calculate_relevance_score(video_info, query)
        
        videos.append(video_info)
    
    # Sort by relevance score (descending) and return top 1
    most_relevant = sorted(videos, key=lambda x: x['relevance_score'], reverse=True)[0]
    return most_relevant


def _search_with_ytdlp(query, search_limit=5):
    """
    Fallback search using yt-dlp command line.
    More reliable but slower than youtube-search-python.
    """
    try:
        # Use yt-dlp to search YouTube
        cmd = [
            'yt-dlp',
            f'ytsearch{search_limit}:{query}',
            '--dump-json',
            '--flat-playlist',
            '--no-warnings',
            '--quiet'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"yt-dlp search failed: {result.stderr}")
            return None
        
        # Parse JSON lines output
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    video_data = json.loads(line)
                    video_info = {
                        'title': video_data.get('title', 'N/A'),
                        'url': video_data.get('url', f"https://www.youtube.com/watch?v={video_data.get('id', '')}"),
                        'video_id': video_data.get('id', 'N/A'),
                        'duration': str(video_data.get('duration', 'N/A')),
                        'views_text': f"{video_data.get('view_count', 0)} views",
                        'views_count': video_data.get('view_count', 0) or 0,
                        'published': 'N/A',  # yt-dlp flat playlist doesn't include this
                        'channel': video_data.get('channel', video_data.get('uploader', 'N/A')),
                        'thumbnail': video_data.get('thumbnail', 'N/A'),
                        'description': video_data.get('description', '')[:200] if video_data.get('description') else ''
                    }
                    
                    # Calculate relevance score
                    video_info['relevance_score'] = calculate_relevance_score(video_info, query)
                    videos.append(video_info)
                except json.JSONDecodeError:
                    continue
        
        if not videos:
            return None
        
        # Sort by relevance score and return best match
        most_relevant = sorted(videos, key=lambda x: x['relevance_score'], reverse=True)[0]
        return most_relevant
        
    except subprocess.TimeoutExpired:
        print("yt-dlp search timed out")
        return None
    except Exception as e:
        print(f"yt-dlp search error: {e}")
        return None


def fetch_most_relevant_youtube_video(query, search_limit=15):
    """
    Search YouTube and return the most RELEVANT video based on query.
    
    Tries youtube-search-python first, falls back to yt-dlp if that fails.
    
    Args:
        query: Search query string
        search_limit: Number of results to fetch before scoring (default 15)
    
    Returns:
        Dictionary containing the most relevant video info, or None if no results
    """
    # Try youtube-search-python first (faster)
    try:
        result = _search_with_youtubesearchpython(query, search_limit)
        if result:
            print(f"[YouTube] Found video via youtube-search-python: {result.get('title', 'N/A')[:50]}")
            return result
    except Exception as e:
        error_msg = str(e)
        print(f"[YouTube] youtube-search-python failed: {error_msg}")
        
        # Check if it's the known httpx/proxies error
        if 'proxies' in error_msg or 'post()' in error_msg:
            print("[YouTube] Falling back to yt-dlp due to httpx compatibility issue...")
    
    # Fallback to yt-dlp (more reliable, slightly slower)
    try:
        result = _search_with_ytdlp(query, min(search_limit, 10))  # yt-dlp is slower, limit results
        if result:
            print(f"[YouTube] Found video via yt-dlp: {result.get('title', 'N/A')[:50]}")
            return result
    except Exception as e:
        print(f"[YouTube] yt-dlp fallback also failed: {e}")
    
    print("[YouTube] All search methods failed")
    return None

# Example usage
if __name__ == "__main__":
    query = input("Enter your search query: ")
    top_video = fetch_most_relevant_youtube_video(query, search_limit=15)
    
    if top_video:
        print(f"video_id=", top_video['video_id'])
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