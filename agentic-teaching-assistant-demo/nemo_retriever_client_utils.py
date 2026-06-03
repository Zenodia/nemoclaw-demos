import aiohttp
import os 
import json
import re
import base64
import random
import ssl
from typing import List

# Use RAG_SERVER_HOST environment variable if set, otherwise fallback to hardcoded values
# RAG_SERVER_HOST may be a full URL (http://rag-server:8081) or a bare hostname
_rag_host_env = os.environ.get("RAG_SERVER_HOST", None)
if _rag_host_env and ("://" in _rag_host_env):
    RAG_BASE_URL = _rag_host_env.rstrip("/")
else:
    _rag_ip = _rag_host_env or ("rag-server" if os.environ.get("AI_WORKBENCH", "false") == "true" else "localhost")
    _rag_port = os.environ.get("RAG_SERVER_PORT", "8081")
    _rag_proto = "https" if _rag_port == "443" else "http"
    RAG_BASE_URL = f"{_rag_proto}://{_rag_ip}:{_rag_port}"

# Use INGESTOR_SERVER_HOST environment variable if set, otherwise fallback to hardcoded values
# INGESTOR_SERVER_HOST may be a full URL (http://ingestor-server:8082) or a bare hostname
_ingestor_host_env = os.environ.get("INGESTOR_SERVER_HOST", None)
if _ingestor_host_env and ("://" in _ingestor_host_env):
    BASE_URL = _ingestor_host_env.rstrip("/")
else:
    _ingestor_ip = _ingestor_host_env or ("ingestor-server" if os.environ.get("AI_WORKBENCH", "false") == "true" else "localhost")
    _ingestor_port = os.environ.get("INGESTOR_SERVER_PORT", "8082")
    _ingestor_proto = "https" if _ingestor_port == "443" else "http"
    BASE_URL = f"{_ingestor_proto}://{_ingestor_ip}:{_ingestor_port}"

# Milvus endpoint - configurable via env var
# MILVUS_ENDPOINT: empty/"default" = let RAG server use internal Milvus, otherwise use specified endpoint
MILVUS_ENDPOINT = os.environ.get("MILVUS_ENDPOINT", "http://milvus:19530")
USE_EXTERNAL_MILVUS = MILVUS_ENDPOINT and MILVUS_ENDPOINT.lower() not in ("", "default", "internal")

print(f"🔧 [nemo_retriever_client_utils] RAG: {RAG_BASE_URL}, Ingestor: {BASE_URL}, Milvus: {MILVUS_ENDPOINT if USE_EXTERNAL_MILVUS else 'server-internal'}")

# SSL context for HTTPS connections (disable verification for self-signed certs like Astra ingress)
def get_ssl_context():
    """Get SSL context for HTTPS connections, disabling verification for self-signed certs"""
    if BASE_URL.startswith("https") or RAG_BASE_URL.startswith("https"):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context
    return None

async def delete_collections(collection_names: List[str] = ""):
    url = f"{BASE_URL}/v1/collections"
    print(f"🗑️ DELETE_COLLECTIONS: {collection_names} from {url}")
    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.delete(url, json=collection_names) as response:
                await print_response(response)
                print(f"✅ DELETE_COLLECTIONS success")
        except aiohttp.ClientError as e:
            print(f"❌ DELETE_COLLECTIONS FAILED")
            print(f"   URL: {url}")
            print(f"   Error: {e}")


async def create_collection(
    collection_name: list = None,
    embedding_dimension: int = 2048,
    metadata_schema: list = []
):
    url = f"{BASE_URL}/v1/collection"
    print(f"📁 CREATE_COLLECTION: {collection_name} at {url}")
    
    data = {
        "collection_name": collection_name,
        "embedding_dimension": embedding_dimension,
        "metadata_schema": metadata_schema
    }

    HEADERS = {"Content-Type": "application/json"}

    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.post(url, json=data, headers=HEADERS) as response:
                await print_response(response)
                print(f"✅ CREATE_COLLECTION success: {collection_name}")
        except aiohttp.ClientError as e:
            print(f"❌ CREATE_COLLECTION FAILED")
            print(f"   URL: {url}")
            print(f"   Error: {e}")
            return 500, {"error": str(e)}


# [Optional]: Define schema for metadata fields
metadata_schema = [    
    {
        "name": "source_ref",
        "type": "string",
        "description": "Reference name to the source pdf document"
    }
]

async def upload_documents(collection_name: str = "", files_path_ls:list[str] = [], custom_metadata: list[dict] = []):
    upload_url = f"{BASE_URL}/v1/documents"
    print("=" * 60)
    print(f"📤 UPLOAD_DOCUMENTS to NeMo Retriever")
    print(f"   URL: {upload_url}")
    print(f"   Collection: {collection_name}")
    print(f"   Files: {files_path_ls}")
    print("=" * 60)
    
    data = {
        "collection_name": collection_name,
        "blocking": False, # If True, upload is blocking; else async. Status API not needed when blocking
        "split_options": {
            "chunk_size": 512,
            "chunk_overlap": 150
        },
        "custom_metadata": custom_metadata,
        "generate_summary": True # Set to True to optionally generate summaries for all documents after ingestion
    }

    form_data = aiohttp.FormData()
    for file_path in files_path_ls:
        form_data.add_field("documents", open(file_path, "rb"), filename=os.path.basename(file_path), content_type="application/pdf")

    form_data.add_field("data", json.dumps(data), content_type="application/json")

    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.post(upload_url, data=form_data) as response:
                body = await print_response(response)
                if response.status >= 400:
                    raise RuntimeError(
                        f"Ingestor returned HTTP {response.status}: {body[:300]}"
                    )
        except aiohttp.ClientError as e:
            print(f"❌ UPLOAD_DOCUMENTS FAILED")
            print(f"   URL: {upload_url}")
            print(f"   Error: {e}")
            print(f"   💡 Check INGESTOR_SERVER_HOST and INGESTOR_SERVER_PORT env vars")
            raise

async def fetch_collections():
    url = f"{BASE_URL}/v1/collections"
    print(f"📋 FETCH_COLLECTIONS from: {url}")
    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(url) as response:
                # print_response returns a JSON string, parse it to dict
                output_str = await print_response(response)
                if output_str == "error":
                    json_output = {}
                else:
                    json_output = json.loads(output_str)
                print(f"✅ FETCH_COLLECTIONS success: {len(json_output.get('collections', []) if isinstance(json_output, dict) else [])} collections found")
        except aiohttp.ClientError as e:
            json_output = {}
            print(f"❌ FETCH_COLLECTIONS FAILED")
            print(f"   URL: {url}")
            print(f"   Error: {e}")
            print(f"   💡 Check INGESTOR_SERVER_HOST and INGESTOR_SERVER_PORT env vars")
        return json_output




async def upload_files_to_nemo_retriever(files_path_ls : str , username: str , CUSTOM_METADATA: list[dict] = []): 
        # Filepaths
    
    # [Optional]: Add filename specific custom metadata

    output=await upload_documents(username, files_path_ls, CUSTOM_METADATA)
    return output


async def check_collection_document_count(collection_name: str) -> dict:
    """
    Check the number of documents in a collection.
    This can be used to poll for upload completion.
    
    Returns:
        dict with {"document_count": int, "exists": bool}
    """
    url = f"{RAG_BASE_URL}/v1/search"
    
    # Query with minimal parameters to get collection info
    payload = {
        "query": "",  # Empty query to just check collection
        "vdb_top_k": 1,
        "reranker_top_k": 1,
        "collection_names": [collection_name],
        **({"vdb_endpoint": MILVUS_ENDPOINT} if USE_EXTERNAL_MILVUS else {}),
    }
    
    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.post(url=url, json=payload) as response:
                if response.status == 200:
                    response_json = await response.json()
                    doc_count = response_json.get("total_results", 0)
                    return {"document_count": doc_count, "exists": True}
                else:
                    return {"document_count": 0, "exists": False}
        except Exception as e:
            print(f"❌ Failed to check collection status: {e}")
            return {"document_count": 0, "exists": False}


async def print_response(response):
    """Helper to print API response."""
    try:
        response_json = await response.json()
        output = json.dumps(response_json, indent=2)
        print(json.dumps(response_json, indent=2))
    except aiohttp.ClientResponseError:
        print(await response.text())
        output="error"
    return output

async def fetch_health_status():
    """Fetch health status asynchronously."""
    url = f"{RAG_BASE_URL}/v1/health"
    print("Fetching RAG server health status with url = ", url)
    params = {"check_dependencies": "True"} # Check health of dependencies as well
    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(url, params=params) as response:
            await print_response(response)

# Run the async function
#await fetch_health_status()
## helpful function to quickly get documents
async def document_search(payload, url):
    print(f"🔍 DOCUMENT_SEARCH")
    print(f"   URL: {url}")
    print(f"   Collection: {payload.get('collection_names', 'N/A')}")
    print(f"   Query: {payload.get('query', 'N/A')[:80]}...")
    ssl_context = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.post(url=url, json=payload) as response:
                output = await print_response(response)
                print(f"✅ DOCUMENT_SEARCH success")
                flag = True
        except aiohttp.ClientError as e:
            print(f"❌ DOCUMENT_SEARCH FAILED")
            print(f"   URL: {url}")
            print(f"   Error: {e}")
            print(f"   💡 Check RAG_SERVER_HOST and RAG_SERVER_PORT env vars")
            output="error"
            flag = False
    return flag, output
    
async def get_documents(query, username):
    url = f"{RAG_BASE_URL}/v1/search"
    payload={
      "query": query , # replace with your own query 
      "reranker_top_k": 5,
      "vdb_top_k": 20,
      # Only include vdb_endpoint if using external Milvus (not staging internal)
      **({"vdb_endpoint": MILVUS_ENDPOINT} if USE_EXTERNAL_MILVUS else {}),
      "collection_names": [username], # Multiple collection retrieval can be used by passing multiple collection names
      "messages": [],
      "enable_query_rewriting": True,
      "enable_reranker": True,
      "embedding_model": "nvidia/llama-3.2-nv-embedqa-1b-v2",
      # Provide url of the model endpoints if deployed elsewhere
      #"embedding_endpoint": "",
      #"reranker_endpoint": "",
      "reranker_model": "nvidia/llama-3.2-nv-rerankqa-1b-v2",
    
    }
    
    flag, output=await document_search(payload, url)
    return flag, output

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
    pattern = re.compile(r'^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)?$')
    return bool(pattern.match(s))


def fetch_rag_context(output:str)-> str :
    context_ls=[]
    output_d=json.loads(output)
    source_ref_ls=[]
    i=1
    for o in output_d["results"]:
        #print("---"*10) 
        print(o["metadata"].keys())
        #print(o["content"])
        page_nr=o["metadata"].get("page_number", "?")
        
        # Try multiple sources for the document reference (nv-ingest uses different structure)
        source_ref = None
        content_metadata = o["metadata"].get("content_metadata", {})
        if isinstance(content_metadata, dict):
            source_ref = content_metadata.get("source_ref") or content_metadata.get("filename")
        if not source_ref:
            # Fallback: check other common locations
            source_ref = o["metadata"].get("filename") or o.get("filename") or "unknown"
        
        source_ref_w_page= f"{source_ref} page:{str(page_nr)}"
        context=o["content"]
        if is_base64_regex(context) or is_base64(context):
            print("skipping base64 string, which is not actually text content....")
            try: 
                table_or_text=o["metadata"]["description"]                
                context_ls.append(f"extra_info:{table_or_text}")
            except :
                pass 
            
        else:
            context_ls.append(f"context:{context}"+'\n'+ f"source_ref:{source_ref_w_page}")
            try: 
                table_or_text=o["metadata"]["description"]                
                context_ls.append(f"extra_info:{table_or_text}")
            except :
                pass 
        
        i+=1
    n=len(context_ls)
    if n>=5:
        context_ls=random.sample(context_ls,5)
    
    return '\n'.join(context_ls)

