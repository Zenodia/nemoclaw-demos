import aiohttp
import httpx
import json
import base64
import os
import asyncio
import requests
from colorama import Fore
import argparse
import io
import markdown
from PIL import Image as PILImage
from IPython.display import Image as IPythonImage, display, Markdown
import base64
from io import BytesIO
# Import error handling
from errors import RAGConnectionError, LLMAPIError
from logging_config import get_logger
from vllm_client_multimodal_requests import query_qwen_vllm_served
from PIL import Image as PILImage
from IPython.display import Image as IPythonImage, display, Markdown
import base64
from io import BytesIO
from colorama import Fore
# Initialize logger
logger = get_logger(__name__)

# RAG Server Configuration — env vars may be full URLs or bare hostnames
def _make_base_url(env_var: str, default_host: str, default_port: str) -> str:
    val = os.environ.get(env_var, "")
    if val and "://" in val:
        return val.rstrip("/")
    host = val or default_host
    port = os.environ.get(env_var.replace("HOST", "PORT"), default_port)
    proto = "https" if port == "443" else "http"
    return f"{proto}://{host}:{port}"

_default_host = "rag-server" if os.environ.get("AI_WORKBENCH", "false") == "true" else "localhost"
RAG_BASE_URL = _make_base_url("RAG_SERVER_HOST", _default_host, "8081")
INGESTOR_BASE_URL = _make_base_url("INGESTOR_SERVER_HOST", _default_host, "8082")

MILVUS_ENDPOINT = os.environ.get("MILVUS_ENDPOINT", "http://milvus:19530")
USE_EXTERNAL_MILVUS = MILVUS_ENDPOINT and MILVUS_ENDPOINT.lower() not in ("", "default", "internal")

# For backward compatibility
IPADDRESS = RAG_BASE_URL

rag_url = f"{RAG_BASE_URL}/v1/generate"

# Log RAG configuration on module load
print(f"🔧 RAG Configuration:")
print(f"   RAG Server: {RAG_BASE_URL}")
print(f"   Ingestor: {INGESTOR_BASE_URL}")
print(f"   Milvus: {MILVUS_ENDPOINT}")
print(f"   RAG URL: {rag_url}")


async def print_response(response, to_print=True):
    """Helper to print API response."""
    try:
        response_json = await response.json()
        if to_print:
            print(json.dumps(response_json, indent=2))
        return response_json
    except aiohttp.ClientResponseError:
        print(await response.text())


async def print_streaming_response_and_citations(response_generator):
    first_chunk_data = None
    text_string = ""  # Collect the complete text here
    markdown_str = ""  # Build complete markdown string with images
    img_str = None  # Initialize to avoid UnboundLocalError

    async for chunk in response_generator:
        if chunk.startswith("data: "):
            chunk = chunk[len("data: "):].strip()

        if not chunk:
            continue

        try:
            data = json.loads(chunk)
        except Exception as e:
            print(f"JSON decode error: {e}")
            print(f"⚠️ Raw chunk content: {repr(chunk)}")
            continue

        choices = data.get("choices", [])
        if not choices:
            continue

        # Capture first chunk with citations (if any)
        if first_chunk_data is None and data.get("citations"):
            first_chunk_data = data

        # Stream the content
        delta = choices[0].get("delta", {})
        text = delta.get("content")
        if not text:
            message = choices[0].get("message", {})
            text = message.get("content", "")
        
        if text:
            text_string += text  # Accumulate the text
            print(text, end='', flush=True)

    print()  # Newline after completion

    # Start building markdown string with the main response
    markdown_str = text_string + "\n\n"

    # Display and add citations to markdown if any
    if first_chunk_data and first_chunk_data.get("citations"):
        citations = first_chunk_data["citations"]
        markdown_str += "---\n\n## Citations\n\n"
        img_str=None
        for idx, citation in enumerate(citations.get("results", [])):
            doc_type = citation.get("document_type", "text")
            content = citation.get("content", "")
            doc_name = citation.get("document_name", f"Citation {idx+1}")

            display(Markdown(f"\n**Citation {idx+1}: {doc_name}**"))
            markdown_str += f"### source: {idx+1}\n\n"

            # Handle different content types properly
            if doc_type in ["image", "chart", "table"]:
                try:
                    # Try to decode as base64 and display as image
                    image_bytes = base64.b64decode(content)
                    image = PILImage.open(BytesIO(image_bytes))
                    print(Fore.GREEN + "image in document type ", type(image), Fore.RESET)
                    display(IPythonImage(data=image_bytes))
                    query="this image is embedded in a page, describe this image take into consideration of other relevant parts in this pdf"
                    image_file_loc=content
                    audio_path = None
                    sys_prompt=f"pdf title:{doc_name}, and retrieved relevant parts of this pdf page are:{markdown_str}. Be short and concise in your response"
                    
                    vlm_output=query_qwen_vllm_served(query,image_file_loc, sys_prompt, None)
                    if vlm_output:
                        markdown_str += f"\n{vlm_output}\n"                        
                    print(Fore.BLUE + "VLM parsed image output =\n", vlm_output)
                    
                    # Determine image format
                    image_format = image.format.lower() if image.format else "png"
                    
                    # Add base64 image to markdown string
                    img_str += f"![{doc_name}](data:image/{image_format};base64,{content})\n\n"
                    
                    
                except Exception as e:
                    display(Markdown(f"⚠️ Could not decode {doc_type} content. Error: {e}"))
                    display(Markdown(f"```\nContent preview: {content[:200]}...\n```"))
                    markdown_str += f"⚠️ Could not decode {doc_type} content. Error: {e}\n\n"
                    markdown_str += f"```\nContent preview: {content[:200]}...\n```\n\n"
                    
            elif doc_type == "text":
                display(Markdown(f"```\n{content}\n```"))
                markdown_str += f"\n{content}\n\n\n"
            else:
                # Unknown content type - display as text with warning
                content_preview = content[:500] + ('...' if len(content) > 500 else '')
                display(Markdown(f"⚠️ Unknown content type '{doc_type}':\n```\n{content_preview}\n```"))
                markdown_str += f"⚠️ Unknown content type '{doc_type}':\n```\n{content_preview}\n```\n\n"
    
    return markdown_str, img_str  # Return the complete markdown string with embedded images


async def generate_answer(payload):
    # Disable SSL verification for staging/self-signed certificates
    verify_ssl = False if RAG_BASE_URL.startswith("https") else True
    async with httpx.AsyncClient(verify=verify_ssl, timeout=60.0) as client:
        try:
            async with client.stream('POST', url=rag_url, json=payload) as response:
                async for line in response.aiter_lines():
                    yield line.strip()
        except httpx.HTTPError as e:
            print(f"Error: {e}")

async def filter_documents_by_file_name(username, query,pdf_file,num_docs):    
    if ":" in query[:5]:
        query=query.split(":")[-1]    
    
    vdb_top_k=int(num_docs*3)
    
    # Log RAG query attempt
    print(Fore.CYAN + "=" * 60 + Fore.RESET)
    print(Fore.CYAN + "📡 RAG RETRIEVAL ATTEMPT" + Fore.RESET)
    print(Fore.CYAN + f"   Username/Collection: {username}" + Fore.RESET)
    print(Fore.CYAN + f"   Query: {query[:100]}..." + Fore.RESET)
    print(Fore.CYAN + f"   PDF Filter: {pdf_file}" + Fore.RESET)
    print(Fore.CYAN + f"   RAG URL: {rag_url}" + Fore.RESET)
    print(Fore.CYAN + f"   Milvus Endpoint: {MILVUS_ENDPOINT}" + Fore.RESET)
    print(Fore.CYAN + "=" * 60 + Fore.RESET)
    
    try:
        if pdf_file and query :
            # Use 'like' operator for filename matching (exact == doesn't work with the RAG server)
            filter_expr_str=f'content_metadata["filename"] like "%{pdf_file}%"'
            payload = {
            "messages": [
                {
                "role": "user",
                "content": query
                }
            ],
            "use_knowledge_base": True,
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 1024,
            "reranker_top_k": 10,
            "vdb_top_k": 100,
            "collection_names": [username],
            "enable_query_rewriting": True,
            "enable_reranker": True,
            "enable_citations": True,
            "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "reranker_model": "nvidia/llama-3.2-nv-rerankqa-1b-v2",
            "embedding_model": "nvidia/llama-3.2-nv-embedqa-1b-v2",
            "stop": [],
            "filter_expr": filter_expr_str
            }
            # Only include vdb_endpoint if using external Milvus (not staging internal)
            if USE_EXTERNAL_MILVUS:
                payload["vdb_endpoint"] = MILVUS_ENDPOINT
        elif query :
            # Fallback to username as collection name if no specific collection defined
            collection_name = username
            payload = {
            "messages": [
                {
                "role": "user",
                "content": query
                }
            ],
            "use_knowledge_base": True,
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 1024,
            "reranker_top_k": 10,
            "vdb_top_k": 100,
            "collection_names": [collection_name],
            "enable_query_rewriting": True,
            "enable_reranker": True,
            "enable_citations": True,
            "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "reranker_model": "nvidia/llama-3.2-nv-rerankqa-1b-v2",
            "embedding_model": "nvidia/llama-3.2-nv-embedqa-1b-v2",
            "stop": [],
            "filter_expr": ""
            }
            # Only include vdb_endpoint if using external Milvus (not staging internal)
            if USE_EXTERNAL_MILVUS:
                payload["vdb_endpoint"] = MILVUS_ENDPOINT
        else:
            print(Fore.YELLOW + f"⚠️ Missing query parameters: username={username}, query={query}, pdf_file={pdf_file}" + Fore.RESET)
            return False, "", ""
            
        print(Fore.BLUE + f"📤 Sending RAG request to: {rag_url}" + Fore.RESET)
        print(Fore.BLUE + f"   Payload collection: {payload.get('collection_names')}" + Fore.RESET)
        print(Fore.BLUE + f"   Payload vdb_endpoint: {payload.get('vdb_endpoint', 'server-internal')}" + Fore.RESET)
        
        markdown_str, img_str = await print_streaming_response_and_citations(generate_answer(payload))
        
        if markdown_str:
            print(Fore.GREEN + f"✅ RAG retrieval successful! Got {len(markdown_str)} chars" + Fore.RESET)
            flag=True
        else:
            print(Fore.YELLOW + "⚠️ RAG returned empty response" + Fore.RESET)
            flag=False
    except Exception as exc:
            print(Fore.RED + "=" * 60 + Fore.RESET)
            print(Fore.RED + f"❌ RAG RETRIEVAL FAILED" + Fore.RESET)
            print(Fore.RED + f"   Error: {exc}" + Fore.RESET)
            print(Fore.RED + f"   This means LLM will generate from its own knowledge (hallucinations likely!)" + Fore.RESET)
            print(Fore.RED + "=" * 60 + Fore.RESET)
            import traceback
            traceback.print_exc()
            markdown_str=""
            img_str=""
            flag=False
    return flag, markdown_str, img_str
    
    

if __name__ == "__main__":
    # Test document search with file filter
    #query = "motorway access and restrictions"
    #pdf_file = "SwedenDrivingCourse_Motorway.pdf"    
    
    query="what is the Merging lanes sign look like?"
    pdf_file="SwedenDrivingCourse_Motorway.pdf"
    username="test"
    flag, markdown_str , img_str = asyncio.run(filter_documents_by_file_name(username,query, pdf_file, 3))
    print("---"*10)
    
    if flag and markdown_str:
        if img_str :
            
            formatted_markdown_str = markdown.markdown(f'''                
                {markdown_str}

                <br/><br/>
                Reference_document:{pdf_file}
                <br/><br/>
                Reference_images :
                {img_str}               
                ''')
        else:
            formatted_markdown_str = markdown.markdown(f'''                
                {markdown_str}

                <br/><br/>
                Reference_document:{pdf_file}
                           
                ''')
        print(formatted_markdown_str)
    else:
        print("No results found or search failed.")
