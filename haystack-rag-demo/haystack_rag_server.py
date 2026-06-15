#!/usr/bin/env python3
"""
Haystack RAG HTTP server — host-side component.

Runs outside the sandbox so it has access to NVIDIA_API_KEY.
The sandbox skill (haystack_client.py) calls this server via
http://host.openshell.internal:9004 to index documents and run queries.

No MCP protocol — plain JSON REST over HTTP.

Endpoints:
  GET  /health              — liveness check + indexed chunk count
  POST /index               — embed + store documents from a directory
  POST /query               — RAG query → grounded answer
  GET  /documents           — list indexed sources + chunk counts
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path
from typing import Optional

# ── FastAPI ──────────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError as e:
    print(
        f"Missing dependency: {e}\n"
        "Install with: pip install fastapi 'uvicorn[standard]'\n"
        "Or via the project venv: .venv/bin/pip install fastapi 'uvicorn[standard]'",
    )
    raise SystemExit(1)

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1"
EMBEDDING_MODEL = "nvidia/nv-embedqa-e5-v5"
CHAT_MODEL = os.environ.get("NVIDIA_CHAT_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")

RAG_PROMPT_TEMPLATE = """\
Use the following context documents to answer the question.
Be concise and accurate. Cite the source file name when relevant.
If the context does not contain enough information, say so clearly.

Context:
{% for doc in documents %}
[Source: {{ doc.meta.get('file_path', 'unknown') }}]
{{ doc.content }}

{% endfor %}
Question: {{ question }}
Answer:"""

# ── Global server state (set at startup via args) ────────────────────────────
_store_path: str = ""
_data_dir: str = ""
_document_store = None
_store_lock = threading.Lock()

app = FastAPI(title="Haystack RAG Server", version="1.0.0")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _require_api_key() -> str:
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="NVIDIA_API_KEY is not set on the host. Export it before starting the server.",
        )
    return key


def _get_store():
    global _document_store
    if _document_store is None:
        _document_store = _load_store(_store_path)
    return _document_store


def _load_store(path: str):
    from haystack.document_stores.in_memory import InMemoryDocumentStore
    store = InMemoryDocumentStore(embedding_similarity_function="cosine")
    p = Path(path)
    if p.exists():
        with open(p) as f:
            data = json.load(f)
        from haystack import Document
        docs = [Document.from_dict(d) for d in data.get("documents", [])]
        if docs:
            store.write_documents(docs)
    return store


def _save_store(store) -> None:
    p = Path(_store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    docs = store.filter_documents()
    serialized = []
    for doc in docs:
        d = doc.to_dict()
        if d.get("embedding") is not None and hasattr(d["embedding"], "tolist"):
            d["embedding"] = d["embedding"].tolist()
        serialized.append(d)
    with open(p, "w") as f:
        json.dump({"documents": serialized}, f)


def _source_counts(store) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in store.filter_documents():
        src = doc.meta.get("file_path") or doc.meta.get("source_id") or "unknown"
        counts[src] = counts.get(src, 0) + 1
    return counts


# ── Request models ───────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    data_dir: Optional[str] = None  # overrides server default if provided


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    with _store_lock:
        store = _get_store()
        n = len(store.filter_documents())
    return {"status": "ok", "indexed_chunks": n, "store_path": _store_path}


@app.post("/index")
def index_documents(req: IndexRequest = None):
    from haystack import Document
    from haystack.components.converters import PyPDFToDocument, TextFileToDocument
    from haystack.components.preprocessors import DocumentCleaner, DocumentSplitter
    from haystack.document_stores.types import DuplicatePolicy
    from haystack.utils import Secret
    from haystack_integrations.components.embedders.nvidia import NvidiaDocumentEmbedder

    api_key = _require_api_key()
    target = Path(req.data_dir if (req and req.data_dir) else _data_dir)

    if not target.exists():
        raise HTTPException(
            status_code=400,
            detail=f"data_dir does not exist: {target}. "
                   f"Create it and add .txt / .md / .pdf files, then retry.",
        )

    txt_files = sorted(target.rglob("*.txt")) + sorted(target.rglob("*.md"))
    pdf_files = sorted(target.rglob("*.pdf"))

    if not txt_files and not pdf_files:
        raise HTTPException(
            status_code=400,
            detail=f"No .txt, .md, or .pdf files found in {target}.",
        )

    # Convert
    raw: list[Document] = []
    if txt_files:
        raw.extend(TextFileToDocument().run(sources=txt_files)["documents"])
    if pdf_files:
        raw.extend(PyPDFToDocument().run(sources=pdf_files)["documents"])

    # Clean + split
    cleaned = DocumentCleaner().run(documents=raw)["documents"]
    chunks = DocumentSplitter(
        split_by="word", split_length=200, split_overlap=30
    ).run(documents=cleaned)["documents"]

    # Embed
    embedder = NvidiaDocumentEmbedder(
        model=EMBEDDING_MODEL,
        api_url=NVIDIA_API_URL,
        api_key=Secret.from_token(api_key),
        truncate="END",
    )
    embedder.warm_up()
    embedded = embedder.run(documents=chunks)["documents"]

    # Write + persist
    with _store_lock:
        store = _get_store()
        written = store.write_documents(embedded, policy=DuplicatePolicy.SKIP)
        total = len(store.filter_documents())
        _save_store(store)

    return {
        "indexed": written,
        "total": total,
        "files": len(txt_files) + len(pdf_files),
        "store_path": _store_path,
    }


@app.post("/query")
def query(req: QueryRequest):
    from haystack.components.builders import ChatPromptBuilder
    from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret
    from haystack_integrations.components.embedders.nvidia import NvidiaTextEmbedder
    from haystack_integrations.components.generators.nvidia import NvidiaChatGenerator

    api_key = _require_api_key()

    with _store_lock:
        store = _get_store()
        if not store.filter_documents():
            raise HTTPException(
                status_code=400,
                detail="No documents indexed. Call POST /index first.",
            )

    api_key_secret = Secret.from_token(api_key)

    # Embed query
    embedder = NvidiaTextEmbedder(
        model=EMBEDDING_MODEL,
        api_url=NVIDIA_API_URL,
        api_key=api_key_secret,
    )
    embedder.warm_up()
    query_embedding = embedder.run(text=req.question)["embedding"]

    # Retrieve
    with _store_lock:
        store = _get_store()
        retriever = InMemoryEmbeddingRetriever(document_store=store, top_k=req.top_k)
        docs = retriever.run(query_embedding=query_embedding)["documents"]

    if not docs:
        raise HTTPException(
            status_code=404,
            detail="No relevant documents found for the question.",
        )

    # Prompt + generate
    prompt_builder = ChatPromptBuilder(
        template=[ChatMessage.from_user(RAG_PROMPT_TEMPLATE)],
        required_variables=["documents", "question"],
    )
    prompt = prompt_builder.run(documents=docs, question=req.question)["prompt"]

    llm = NvidiaChatGenerator(
        model=CHAT_MODEL,
        api_base_url=NVIDIA_API_URL,
        api_key=api_key_secret,
    )
    llm.warm_up()
    result = llm.run(messages=prompt)
    replies = result.get("replies", [])

    if not replies:
        raise HTTPException(status_code=500, detail="LLM returned no response.")

    sources = list({
        doc.meta.get("file_path") or doc.meta.get("source_id") or "unknown"
        for doc in docs
    })

    return {"answer": replies[0].text, "sources": sources}


@app.get("/documents")
def list_documents():
    with _store_lock:
        store = _get_store()
        counts = _source_counts(store)
        total = sum(counts.values())
    return {"total_chunks": total, "sources": counts}


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    global _store_path, _data_dir

    parser = argparse.ArgumentParser(
        description="Haystack RAG HTTP server — host-side component for the sandbox skill",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9004)
    parser.add_argument(
        "--store-path",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "store.json"),
        help="Path to the persisted document store JSON",
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "documents"),
        help="Default directory scanned when POST /index is called without data_dir",
    )
    args = parser.parse_args()

    _store_path = args.store_path
    _data_dir = args.data_dir

    Path(_data_dir).mkdir(parents=True, exist_ok=True)
    Path(_store_path).parent.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        print(
            "WARNING: NVIDIA_API_KEY is not set. "
            "Index and query requests will fail until the key is exported.",
            flush=True,
        )

    print(f"Haystack RAG server starting on {args.host}:{args.port}", flush=True)
    print(f"  Store  : {_store_path}", flush=True)
    print(f"  Data   : {_data_dir}", flush=True)
    print(f"  Model  : {CHAT_MODEL}", flush=True)
    print(f"  Key    : {'set' if api_key else 'NOT SET'}", flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
