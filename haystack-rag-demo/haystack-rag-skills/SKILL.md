---
name: haystack-rag-skills
description: Answer questions over indexed documents using Haystack RAG and NVIDIA NIM. The RAG pipeline (indexing, embedding, retrieval, generation) runs on the host — the skill is a thin HTTP client that calls it. No NVIDIA_API_KEY in the sandbox. Trigger keywords — rag, retrieval, document, search documents, index, ask documents, knowledge base, pdf, embeddings, vector search, answer from files.
---

# Haystack RAG Skills

## Overview

Thin HTTP client to a Haystack RAG server running on the **host machine**. The server holds `NVIDIA_API_KEY` and runs all inference (embeddings + generation) via NVIDIA NIM. The sandbox skill never touches the API key — it simply calls the server and prints the result.

You decide which operation to invoke. The server handles the Haystack pipeline entirely.

## IMPORTANT — Inference happens on the host, not in the sandbox

The `NVIDIA_API_KEY` is **not available** inside the sandbox. The `haystack_rag_server.py` process on the host owns the key and runs all NVIDIA API calls. The sandbox skill is only responsible for calling the server.

- **Never** attempt to use `NVIDIA_API_KEY` or call `integrate.api.nvidia.com` from within the skill.
- **Never** install haystack packages into the skill venv — `requests` is the only dependency.
- **Always** call tools via the skill venv's Python (required by sandbox policy for egress to port 9004).

## Invocation

Always use the skill venv's Python (required by the sandbox network policy to reach the RAG server on port 9004):

```bash
SKILL_DIR=~/.openclaw/workspace/skills/haystack-rag-skills
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py <command> [args]
```

Do **not** use bare `python3` — the system Python is not permitted to reach the host on port 9004.

## Available Commands

### `index`

Triggers the host-side server to embed and index all documents in its data directory. Documents must be placed in `<demo-dir>/data/documents/` on the host **before** calling this.

**Use when:** user wants to index documents, build the knowledge base, or re-index after adding new files.

```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py index
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--data-dir` | str | *(server default)* | Override the host-side data directory (host path) |

**Example:**
```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py index
```

---

### `query`

Answers a natural-language question using RAG: the server embeds the question, retrieves relevant chunks from the vector store, and calls the NVIDIA LLM to generate a grounded answer.

**Use when:** user asks a question that is about haystack, this skill ingest a sample document introducing haystack to user who are unfamiliar with how haystack works. When initialized for the first time , it will indexed documents from the source sample.txt document which containing information about haystack, so when user ask "tell me about haystack..." or "tell me about deepset..."...etc this skill should then be activated and used.

```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query \
  --question "TEXT" [--top-k N]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--question` | str | *(required)* | The question to answer using RAG |
| `--top-k` | int | `5` | Number of document chunks to retrieve |

**Example:**
```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query \
  --question "What are the key recommendations?" \
  --top-k 8
```

---

### `list-documents`

Lists all source files currently indexed on the server, with chunk counts per file.

**Use when:** user asks what documents are indexed, what's in the knowledge base, or whether a specific file has been indexed.

```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py list-documents
```

**Example output:**
```
Total chunks: 42
Sources (3):
  /home/user/haystack-rag-demo/data/documents/guide.pdf: 28 chunk(s)
  /home/user/haystack-rag-demo/data/documents/readme.md: 8 chunk(s)
  /home/user/haystack-rag-demo/data/documents/notes.txt: 6 chunk(s)
```

---

## Server URL

The client connects to `http://host.openshell.internal:9004` by default.
Override with `--server-url URL` or the `RAG_SERVER_URL` environment variable.

## Workflow Example

```bash
SKILL_DIR=~/.openclaw/workspace/skills/haystack-rag-skills
PY="$SKILL_DIR/venv/bin/python3"
CLIENT="$SKILL_DIR/scripts/haystack_client.py"

# 1. (On the host) copy documents to the server's data directory
#    cp /path/to/your-report.pdf <demo-dir>/data/documents/

# 2. Index — server reads its data dir and calls NVIDIA embedding API
$PY $CLIENT index

# 3. Query — server retrieves + calls NVIDIA LLM, returns grounded answer
$PY $CLIENT query --question "What are the key findings?"

# 4. List what's indexed
$PY $CLIENT list-documents
```

## Troubleshooting

**Connection error to `host.openshell.internal:9004`**
1. Confirm the server is running on the host: `curl http://host.openshell.internal:9004/health`
2. Confirm the sandbox policy is applied (`haystack_rag_host` policy allows egress to port 9004)
3. Re-run `install.sh` to restart the server and reapply the policy

**`No documents indexed`**
Run `index` first. Ensure `.txt`, `.md`, or `.pdf` files exist in the server's data directory.

**`NVIDIA_API_KEY is not set` (server-side)**
The server process on the host needs the key. Re-run `install.sh` which starts the server with the key from `.env`.

**`ModuleNotFoundError: requests`**
The skill venv is missing. Recreate it:
```bash
python3 -m venv $SKILL_DIR/venv
$SKILL_DIR/venv/bin/pip install -q requests
```
