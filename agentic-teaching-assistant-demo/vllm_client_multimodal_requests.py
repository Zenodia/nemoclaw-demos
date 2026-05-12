import requests
import base64
import argparse
import os, re

def is_base64(s):
    if not s or not isinstance(s, str):
        return False
    try:
        # Try decoding with validation
        decoded = base64.b64decode(s, validate=True)
        # Re-encode and compare without padding
        encoded = base64.b64encode(decoded).decode('utf-8')
        return encoded.rstrip('=') == s.rstrip('=')
    except Exception:
        return False

def is_base64_regex(s):
    if not s or not isinstance(s, str):
        return False
    pattern = re.compile(r'^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)?$')
    return bool(pattern.match(s))

# Encode local image as base64
def img2base64_str(img_file_loc):
    with open(img_file_loc, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode()
        return image_base64

def audio2base64_str(audio_path):

    with open(audio_path, 'rb') as f:
        binary_audio = f.read()
        base64_audio = base64.b64encode(binary_audio).decode('utf-8')

    #print(base64_audio)
    return base64_audio

def video2base64_str(video_path):
    """Encode video file to base64 string"""
    with open(video_path, 'rb') as f:
        binary_video = f.read()
        base64_video = base64.b64encode(binary_video).decode('utf-8')
    
    return base64_video


def query_qwen_vllm_served(query, image_file_loc=None, sys_prompt=None, audio_path=None, video_path=None):
    """
    Query Qwen3-Omni vLLM server with multimodal inputs.
    
    Args:
        query (str): The text query/question (required)
        image_file_loc (str, optional): Path to image file or base64 string
        sys_prompt (str, optional): System prompt for the model
        audio_path (str, optional): Path to audio file
        video_path (str, optional): Path to video file
    
    Returns:
        str: Model response
    
    Examples:
        # Text only
        response = query_qwen_vllm_served("What is AI?")
        
        # Image only
        response = query_qwen_vllm_served("What's in this image?", image_file_loc="image.jpg")
        
        # Video only
        response = query_qwen_vllm_served("Describe the video", video_path="video.mp4")
        
        # Multimodal
        response = query_qwen_vllm_served("Analyze all media", 
                                          image_file_loc="img.jpg",
                                          audio_path="audio.wav", 
                                          video_path="video.mp4")
    """
    url = "http://vllm:8901/v1/chat/completions"
    
    # Use default system prompt if none provided
    if sys_prompt is None:
        sys_prompt = "You are a helpful AI assistant that can understand text, images, audio, and video."
    
    # Check if image is base64 or file path
    if image_file_loc is not None and (is_base64_regex(image_file_loc) or is_base64(image_file_loc)):        
        base64_img_str = image_file_loc 
        already_base_64_img_flag = True
        img_file_exist_flag = True
    else:
        base64_img_str = None 
        already_base_64_img_flag = False
        img_file_exist_flag = os.path.exists(image_file_loc) if image_file_loc is not None else False
        
    print(f"image_file_exist_flag={img_file_exist_flag}")
        
    audio_file_exist_flag = os.path.exists(audio_path) if audio_path is not None else False
    video_file_exist_flag = os.path.exists(video_path) if video_path is not None else False
    print(f"audio_file_exist_flag={audio_file_exist_flag}")
    print(f"video_file_exist_flag={video_file_exist_flag}")
    
    # Build content array dynamically based on available media
    user_content = []
    
    # Add video first (if available) - as per Qwen3-Omni docs, multimodal data should come before text
    if video_file_exist_flag:
        video_base64 = video2base64_str(video_path)
        # Detect video format from file extension
        video_ext = os.path.splitext(video_path)[1].lower().lstrip('.')
        if video_ext not in ['mp4', 'avi', 'mov', 'mkv', 'webm']:
            video_ext = 'mp4'  # default to mp4
        user_content.append({
            "type": "video_url", 
            "video_url": {"url": f"data:video/{video_ext};base64,{video_base64}"}
        })
    
    # Add audio (if available)
    if audio_file_exist_flag:
        audio_base64_str = audio2base64_str(audio_path)
        user_content.append({
            "type": "input_audio", 
            "input_audio": {"data": f"{audio_base64_str}", "format": "wav"}
        })
    
    # Add image (if available)
    if img_file_exist_flag:
        if already_base_64_img_flag:
            image_base64 = base64_img_str
        else:
            image_base64 = img2base64_str(image_file_loc)
        user_content.append({
            "type": "image_url", 
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
        })
    
    # Add text query last (as per Qwen3-Omni docs)
    user_content.append({"type": "text", "text": query})
    
    print(f"\nBuilding payload with {len(user_content)} content items:")
    for i, content in enumerate(user_content):
        content_type = content.get('type', 'unknown')
        if content_type == 'text':
            print(f"  [{i}] {content_type}: {content.get('text', '')[:50]}...")
        else:
            print(f"  [{i}] {content_type}")
    
    # Build the payload
    payload = {
        "messages": [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": sys_prompt}
                ]
            },
            {
                "role": "user",
                "content": user_content
            }
        ]
    }
    response = requests.post(url, json=payload)
    print("response=\n", response)
    print(f"Status Code: {response.status_code}")
    
    # Check for errors
    if response.status_code != 200:
        print(f"\nERROR: Server returned status code {response.status_code}")
        print(f"Response text: {response.text}")
        try:
            error_json = response.json()
            print(f"Error details: {error_json}")
        except:
            pass
        raise Exception(f"Server error: {response.status_code} - {response.text}")
    
    output=response.json()["choices"][0]["message"]["content"]
    return output



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='Qwen3-Omni vLLM Client',
        description='Query Qwen3-Omni with text, images, audio, and/or video',
        epilog='Examples:\n'
               '  Text only:      python vllm_client_multimodal_requests.py --query "What is AI?"\n'
               '  Image only:     python vllm_client_multimodal_requests.py --query "Describe this" --img_loc image.jpg\n'
               '  Video only:     python vllm_client_multimodal_requests.py --query "What happens?" --video_loc video.mp4\n'
               '  Multimodal:     python vllm_client_multimodal_requests.py --query "Analyze all" --img_loc img.jpg --video_loc video.mp4\n',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--query', required=True, help='Your question or prompt (required)')
    parser.add_argument('--img_loc', help='Path to image file (optional)', default=None)
    parser.add_argument('--audio_loc', help='Path to audio file (optional)', default=None)
    parser.add_argument('--video_loc', help='Path to video file (optional)', default=None)
    parser.add_argument('--system_prompt', help='Custom system prompt (optional)', default=None)

    args = parser.parse_args()
    
    output = query_qwen_vllm_served(
        query=args.query,
        image_file_loc=args.img_loc,
        sys_prompt=args.system_prompt,
        audio_path=args.audio_loc,
        video_path=args.video_loc
    )
    print("\n" + "=" * 70)
    print("RESPONSE:")
    print("=" * 70)
    print(output)
    print("=" * 70)
