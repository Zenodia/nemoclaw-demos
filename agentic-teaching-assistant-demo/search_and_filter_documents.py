import os
import asyncio
import aiohttp
import json
import requests
import ssl
from colorama import Fore
import argparse
import base64
from PIL import Image
import io
from IPython.display import Markdown, display
import markdown

# Import error handling
from errors import RAGConnectionError, LLMAPIError
from logging_config import get_logger

# Initialize logger
logger = get_logger(__name__)


def printmd(markdown_str):
    display(Markdown(markdown_str))



# Use RAG_SERVER_HOST environment variable if set, otherwise fallback to hardcoded values
RAG_SERVER_HOST = os.environ.get("RAG_SERVER_HOST", None)
if RAG_SERVER_HOST:
    IPADDRESS = RAG_SERVER_HOST
else:
    IPADDRESS = "rag-server" if os.environ.get("AI_WORKBENCH", "false") == "true" else "localhost"
RAG_SERVER_PORT = os.environ.get("RAG_SERVER_PORT", "8081")
# Use https:// for port 443 (HTTPS), http:// otherwise
RAG_PROTOCOL = "https" if RAG_SERVER_PORT == "443" else "http"
RAG_BASE_URL = f"{RAG_PROTOCOL}://{IPADDRESS}:{RAG_SERVER_PORT}"  # Replace with your server URL

# Milvus endpoint - configurable via env var
# MILVUS_ENDPOINT: empty/"default" = let RAG server use internal Milvus, otherwise use specified endpoint
MILVUS_ENDPOINT = os.environ.get("MILVUS_ENDPOINT", "http://milvus:19530")
USE_EXTERNAL_MILVUS = MILVUS_ENDPOINT and MILVUS_ENDPOINT.lower() not in ("", "default", "internal")

print(f"🔧 [search_and_filter_documents] RAG: {RAG_BASE_URL}, Milvus: {MILVUS_ENDPOINT if USE_EXTERNAL_MILVUS else 'server-internal'}")

# SSL context for HTTPS connections (disable verification for self-signed certs like Astra ingress)
def get_ssl_context():
    """Get SSL context for HTTPS connections, disabling verification for self-signed certs"""
    if RAG_PROTOCOL == "https":
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context
    return None

async def print_response(response):
    """Helper to print API response."""
    try:
        response_json = await response.json()
        output = json.dumps(response_json, indent=2)
        logger.debug(f"RAG response: {json.dumps(response_json, indent=2)}")
        return output
    except (aiohttp.ClientResponseError, json.JSONDecodeError) as e:
        error_text = await response.text()
        logger.error(f"Failed to parse RAG response: {e}", exc_info=True)
        logger.debug(f"Response text: {error_text}")
        raise RAGConnectionError(f"Invalid response from RAG server: {e}")



## helpful function to quickly get documents
async def document_seach(payload, url):
    """Search documents using RAG server."""
    try:
        ssl_context = get_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url=url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                output = await print_response(response)
                return output
    except aiohttp.ClientError as e:
        print(f"RAG server connection error: {e}")
        raise RAGConnectionError(f"Cannot connect to RAG server at {url}", server_url=url)
    except asyncio.TimeoutError:
        print(f"RAG server timeout for URL: {url}")
        raise RAGConnectionError(f"RAG server timeout", server_url=url)
# possible filter expression
#"filter_expr": '(content_metadata["manufacturer"] like "%ford%" and content_metadata["rating"] > 4.0 and content_metadata["created_date"] between "2020-01-01" and "2024-12-31" and content_metadata["is_public"] == true) or (content_metadata["model"] like "%edge%" and content_metadata["year"] >= 2020 and content_metadata["tags"] in ["technology", "safety", "latest"] and content_metadata["rating"] >= 4.0)'
async def get_documents(username:str , query:str = None, pdf_file_name:str = None, num_docs : int = 5):
    url = f"{RAG_BASE_URL}/v1/search"
    vdb_top_k=int(num_docs*3)
    if pdf_file_name and query :
        # Use 'like' operator for filename matching (exact == doesn't work with the RAG server)
        filter_expr_str=f'content_metadata["filename"] like "%{pdf_file_name}%"'
        payload={
        "query": query , # replace with your own query 
        "reranker_top_k": num_docs,
        "vdb_top_k": vdb_top_k ,
        # Only include vdb_endpoint if using external Milvus (not staging internal)
        **({"vdb_endpoint": MILVUS_ENDPOINT} if USE_EXTERNAL_MILVUS else {}),
        "collection_names": [username], # Multiple collection retrieval can be used by passing multiple collection names
        "messages": [],
        "enable_query_rewriting": False,
        "enable_reranker": True,
        "embedding_model": "nvidia/llama-3.2-nv-embedqa-1b-v2",
        # Provide url of the model endpoints if deployed elsewhere
        #"embedding_endpoint": "",
        #"reranker_endpoint": "",
        "reranker_model": "nvidia/llama-3.2-nv-rerankqa-1b-v2",
        "filter_expr": filter_expr_str
        }
        output=await document_seach(payload, url)
    elif query :
        payload={
        "query": query , # replace with your own query         
        "vdb_top_k": 10,
        # Only include vdb_endpoint if using external Milvus (not staging internal)
        **({"vdb_endpoint": MILVUS_ENDPOINT} if USE_EXTERNAL_MILVUS else {}),
        "collection_names": [username], # Multiple collection retrieval can be used by passing multiple collection names
        "messages": [],
        "enable_query_rewriting": True,
        "enable_reranker": False,
        "embedding_model": "nvidia/llama-3.2-nv-embedqa-1b-v2",
        # Provide url of the model endpoints if deployed elsewhere
        #"embedding_endpoint": "",
        #"reranker_endpoint": "",        
        "filter_expr": ""
        }
        output=await document_seach(payload, url)
    else:
        output=None
    
    return output


async def filter_documents_by_file_name(username, query,pdf_file,num_docs):    
    if ":" in query[:5]:
        query=query.split(":")[-1]
    output = await get_documents(username,query, pdf_file, 3)
    try:
        output_d=json.loads(output)
        if len(output_d["results"])>0:
            flag=True
        else:
            flag=False
        for o in output_d["results"]:
            print( o["document_name"], o["metadata"]["page_number"],'\n', o["metadata"]["description"])
        return flag, output_d["results"], None
    except:
        return False, [], None

if __name__ == "__main__":
    # Test document search with file filter
    #query = "motorway access and restrictions"
    #pdf_file = "SwedenDrivingCourse_Motorway.pdf"    
    query="tell me something about Sweden"
    pdf_file = "SwedenFacts.pdf"    
    username="zeno"
    flag, results = asyncio.run(filter_documents_by_file_name(username,query, pdf_file, 3))
    print("---"*10)
    
    if flag and results:
        # Convert results to markdown string
        markdown_str = "## Search Results\n\n"
        for idx, result in enumerate(results):
            markdown_str += f"### Result {idx + 1}\n"
            markdown_str += f"**Document:** {result.get('document_name', 'N/A')}\n\n"
            markdown_str += f"**Page:** {result.get('metadata', {}).get('page_number', 'N/A')}\n\n"
            markdown_str += f"**Content:**\n\n{result.get('content', 'N/A')}\n\n"
            markdown_str += "---\n\n"
        print(markdown_str)
    else:
        print("No results found or search failed.")
