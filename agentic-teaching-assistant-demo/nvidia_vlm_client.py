"""
NVIDIA VLM Client - Vision Language Model via NVIDIA Inference API

Uses Nemotron Nano 12B VL model for image understanding.
"""

import requests
import base64
import os


def img2base64_str(img_file_loc):
    """Encode local image as base64"""
    with open(img_file_loc, "rb") as f:
        return base64.b64encode(f.read()).decode()


def is_base64(s):
    """Check if string is valid base64"""
    if not s or not isinstance(s, str):
        return False
    try:
        decoded = base64.b64decode(s, validate=True)
        encoded = base64.b64encode(decoded).decode('utf-8')
        return encoded.rstrip('=') == s.rstrip('=')
    except Exception:
        return False


def query_nvidia_vlm(query, image_file_loc=None, sys_prompt=None):
    """
    Query NVIDIA VLM (Nemotron Nano 12B VL) via Inference API.
    
    Args:
        query (str): The text query/question (required)
        image_file_loc (str, optional): Path to image file or base64 string
        sys_prompt (str, optional): System prompt for the model
    
    Returns:
        str: Model response
    
    Examples:
        # Text only
        response = query_nvidia_vlm("What is AI?")
        
        # Image + text
        response = query_nvidia_vlm("What's in this image?", image_file_loc="image.jpg")
    """
    url = os.environ.get("VLM_API_URL", "https://inference-api.nvidia.com/v1/chat/completions")
    model = os.environ.get("VLM_MODEL", "nvidia/nvidia/nemotron-nano-12b-v2-vl")
    
    api_key = os.environ.get("INFERENCE_API_KEY", "")
    if not api_key:
        raise ValueError("INFERENCE_API_KEY not found. Set INFERENCE_API_KEY in .env")
    
    # Use default system prompt if none provided
    if sys_prompt is None:
        sys_prompt = "You are a helpful AI assistant that can understand text and images."
    
    # Check if image is base64 or file path
    image_base64 = None
    image_mime = "image/jpeg"  # Default to jpeg
    if image_file_loc:
        if is_base64(image_file_loc):
            image_base64 = image_file_loc
        elif os.path.exists(image_file_loc):
            image_base64 = img2base64_str(image_file_loc)
            # Detect MIME type from file extension
            ext = image_file_loc.lower().split('.')[-1] if '.' in image_file_loc else ''
            if ext in ('png',):
                image_mime = "image/png"
            elif ext in ('gif',):
                image_mime = "image/gif"
            elif ext in ('webp',):
                image_mime = "image/webp"
            # Default is jpeg for jpg, jpeg, or unknown
    
    print(f"🖼️ NVIDIA VLM: image provided = {image_base64 is not None}")
    print(f"🤖 NVIDIA VLM: model = {model}")
    print(f"🔗 NVIDIA VLM: url = {url}")
    print(f"🔑 NVIDIA VLM: key ending = ...{api_key[-4:] if api_key else 'NONE'}")
    
    # Build content array for user message - IMAGE FIRST, then text
    user_content = []
    
    # Add image FIRST if available (many VLMs expect image before text)
    if image_base64:
        user_content.append({
            "type": "image_url", 
            "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}
        })
        print(f"🖼️ NVIDIA VLM: Added image ({image_mime}, base64 length: {len(image_base64)})")
    
    # Add text query after image
    user_content.append({"type": "text", "text": query})
    
    # Build messages array
    messages = []
    
    # Add system prompt if provided
    if sys_prompt:
        messages.append({
            "role": "system",
            "content": sys_prompt
        })
    
    # Add user message with text and optional image
    messages.append({
        "role": "user",
        "content": user_content
    })
    
    # Build payload
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "top_p": 0.7,
        "max_tokens": 1024,
        "stream": False
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # Debug: print message structure (without full base64)
    debug_messages = []
    for msg in messages:
        if msg["role"] == "user" and isinstance(msg["content"], list):
            debug_content = []
            for item in msg["content"]:
                if item["type"] == "image_url":
                    debug_content.append({"type": "image_url", "image_url": {"url": "data:...truncated..."}})
                else:
                    debug_content.append(item)
            debug_messages.append({"role": "user", "content": debug_content})
        else:
            debug_messages.append(msg)
    print(f"📋 NVIDIA VLM: Message structure: {debug_messages}")
    
    print(f"📤 NVIDIA VLM: Sending request...")
    response = requests.post(url, json=payload, headers=headers, timeout=60)
    print(f"📥 NVIDIA VLM: Status Code: {response.status_code}")
    
    # Debug: print response content
    if response.status_code == 200:
        resp_json = response.json()
        content = resp_json["choices"][0]["message"]["content"]
        print(f"📝 NVIDIA VLM: Response content preview: {content[:200]}...")
    
    if response.status_code != 200:
        print(f"❌ NVIDIA VLM ERROR: {response.status_code}")
        print(f"Response: {response.text[:500]}")
        raise Exception(f"VLM error: {response.status_code} - {response.text[:200]}")
    
    output = response.json()["choices"][0]["message"]["content"]
    print(f"✅ NVIDIA VLM: Response received ({len(output)} chars)")
    return output


# Alias for backward compatibility with vllm_client imports
query_vlm = query_nvidia_vlm


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Query NVIDIA VLM')
    parser.add_argument('--query', required=True, help='Your question')
    parser.add_argument('--img_loc', help='Path to image file', default=None)
    
    args = parser.parse_args()
    
    output = query_nvidia_vlm(
        query=args.query,
        image_file_loc=args.img_loc
    )
    print("\n" + "=" * 70)
    print("RESPONSE:")
    print("=" * 70)
    print(output)
