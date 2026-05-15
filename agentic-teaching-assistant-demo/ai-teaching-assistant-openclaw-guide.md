# AI Teaching Assistant — OpenClaw Guide

An AI-powered study assistant that ingests PDFs, generates personalised
curricula, quizzes, calendar events, supports YouTube search, agentic
memory, and study-break games.  This guide covers everything: standing up
the host environment, connecting the OpenClaw sandbox, and using the system
through the NemoClaw chat UI.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
   - [Option A — Minimal (no RAG)](#option-a--minimal-no-rag-no-gpu-required)
   - [Option B — With RAG Stack (recommended)](#option-b--with-rag-stack-recommended-for-large-pdfs)
3. [One-Command Install (OpenClaw + MCP)](#3-one-command-install-openclaw--mcp)
4. [Uploading a PDF from the OpenClaw UI](#4-uploading-a-pdf-from-the-openclaw-ui)
   - [Remote host via WSL + brev port-forward](#accessing-from-a-remote-host-via-wsl--brev)
5. [Full Workflow via OpenClaw Chat](#5-full-workflow-via-openclaw-chat)
6. [REST API Reference (curl)](#6-rest-api-reference-curl)
7. [Daily Operations](#7-daily-operations)
8. [Architecture](#8-architecture)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

| Requirement | Check |
|---|---|
| Docker | `docker --version` |
| Docker Compose v2 | `docker compose version` — install: `sudo apt-get install -y docker-compose-v2` |
| `NVIDIA_API_KEY` | Get one at https://build.nvidia.com — used by Docker containers for embeddings & RAG |
| `INFERENCE_API_KEY` | **Required** — used by the OpenShell gateway as the inference provider credential for OpenClaw chat |
| NemoClaw / OpenShell | `openshell --version` — for the sandbox/skill integration |
| Python 3.10+ | `python3 --version` (host only, not inside Docker) |
| uv | Installed automatically by `install.sh` if missing |

---

## 2. Environment Setup

### Step 1 — Set your API keys

Create a `.env` file in the repo root:

```bash
# .env  (repo root — loaded by Docker Compose and install.sh)
NVIDIA_API_KEY=nvapi-...                              # Docker containers: embeddings, RAG
INFERENCE_API_KEY=nvapi-...                           # OpenShell gateway inference provider credential

# Inference model — also configures openclaw inside the sandbox
INFERENCE_BASE_URL=https://inference-api.nvidia.com/v1
INFERENCE_MODEL=aws/anthropic/bedrock-claude-sonnet-4-6
```

All four variables are required. `install.sh` will fail at Step 3 if any are missing.

For **Option B (RAG)**, also add the key to the RAG compose env file:

```bash
# rag/deploy/compose/.env
NVIDIA_API_KEY=nvapi-...
INFERENCE_API_KEY=sk-...
```

### Step 2 — Start the stack

> `make up` / `make up-with-rag` automatically run `make setup`, start all
> containers, launch the Gradio UI, and start the FastAPI backend — no extra
> steps needed.

---

### Option A — Minimal (no RAG, no GPU required)

PDF text is extracted **directly** from uploaded files.

```bash
make up          # starts agenticta + Gradio UI + FastAPI backend (all-in-one)
```

For a clean start (wipes all user data first):

```bash
make fresh       # wipes mnt/*/pdfs, state.txt, JSON store, memory — then make up
```

**What works in Option A:**

- PDF upload → curriculum generation (direct PDF extraction)
- Study buddy chat (LLM only, no semantic search)
- Quiz generation
- Calendar booking
- YouTube video search
- Agentic memory
- Study break games (`make games-up`)

**Trade-off:** Uses raw extracted text rather than semantically retrieved
chunks.  Quality is good; Option B gives better relevance for large PDFs.

---

### Option B — With RAG Stack (recommended for large PDFs)

Adds Milvus vector DB + ingestor + RAG server using NVIDIA hosted
embedding and reranking.  **No GPU required** — embeddings via `NVIDIA_API_KEY`.

```bash
make up-with-rag    # starts everything in one command
```

For a clean start (wipes user data and Milvus vector store):

```bash
make fresh-with-rag
```

**Additional services started:**

| Service | URL | Purpose |
|---|---|---|
| Gradio UI | http://localhost:7860 | Main interface |
| FastAPI + Swagger | http://localhost:8000/docs | REST API |
| RAG Server | http://localhost:8081 | Semantic search |
| Ingestor | http://localhost:8082 | PDF → Milvus |
| Milvus | http://localhost:19530 | Vector DB |

Check RAG health:

```bash
make rag-health
```

---

### Study Break Games (optional, both modes)

```bash
make games-up     # http://localhost:8080
make games-down
```

---

## 3. One-Command Install (OpenClaw + MCP)

After the Docker stack is running, run the install script to set up the
MCP server and upload the skill to the sandbox:

```bash
bash install.sh [--rag] [--fresh] [sandbox-name]
```

### Flags

| Flag | Description |
|---|---|
| *(none)* | Option A — no RAG stack |
| `--rag` | Option B — start/verify the RAG stack (ingestor + RAG server + Milvus) |
| `--fresh` | Wipe all user data before starting (PDFs, state, memory, Milvus collections) |
| `sandbox-name` | Positional arg — target a specific sandbox. Auto-detected when only one exists. |

### Examples

```bash
# Option A — minimal, no RAG
bash install.sh

# Option B — with RAG stack
bash install.sh --rag

# Fresh wipe + Option B
bash install.sh --rag --fresh

# Target a specific sandbox (positional, any position after the flags)
bash install.sh --rag my-sandbox-name

# Non-interactive: skip the user_id prompt at step 10
  TA_USER_ID=lulu TA_EXTERNAL_URL=http://localhost:8000 bash install.sh --rag    --fresh                                                                                                             

# Override the upload portal URL (when host is not directly reachable)
TA_EXTERNAL_URL=http://my.public.hostname:8000 bash install.sh --rag
```

### Environment variable overrides

| Variable | Default | Description |
|---|---|---|
| `TA_USER_ID` | *(prompts)* | Default `user_id` written into `config.json`; set to skip the interactive prompt at step 10 |
| `TA_EXTERNAL_URL` | `http://<detected-host-ip>:8000` | Upload portal URL embedded in the skill config; override when the auto-detected IP is not reachable by users |

**What `install.sh` does (idempotent — safe to re-run):**

| Step | Action | Skip condition |
|---|---|---|
| 0 | Kill stale MCP process | — |
| 1 | Check prerequisites | fails fast if missing |
| 2 | `make up` / `make up-with-rag` | skipped if container already running |
| 2b | Wait for TA API health (port 8000) | polls 30× / 2 s |
| 2c | Wait for RAG services | only with `--rag` |
| 3 | Load `.env` / `credentials.json` | — |
| 4 | `nemoclaw onboard` | skipped if sandbox exists |
| 5 | `openshell provider + inference set` | provider update/create is idempotent |
| 5c | `openclaw onboard` inside sandbox — sets model from `INFERENCE_MODEL` | always re-applied |
| 5b | Detect host external IP for upload portal | — |
| 6 | Host venv + `uv pip install fastmcp httpx` | skipped if `.venv` exists |
| 7 | Start MCP server on port 8999 (auto-restart) | skipped if port responding |
| 8 | Apply sandbox network policy | always re-applied |
| 9 | Upload skill to sandbox | always re-uploaded |
| 10 | Write `config.json` (user_id + server_url) | prompts once |
| 11 | Bootstrap skill venv + `pip install fastmcp` | skipped if already present |
| 12 | Full verification of all services | — |

---

## 4. Uploading a PDF from the OpenClaw UI

Because the OpenClaw sandbox cannot access the user's local filesystem, PDF
upload uses a **browser-based upload portal** served by the TA API.

### How it works

```
User (browser)  ──POST /upload/submit──▶  TA API (port 8000)
                                               │
                                         saves PDF to host
                                         calls /api/files/upload
                                               │
                                         ingests into Milvus (Option B)
                                               │
                                         returns success page
```

### Step-by-step

1. **In OpenClaw chat**, say: _"I want to upload my PDF"_

   The agent calls `get_upload_link(user_id)` and replies with a URL like:
   ```
   http://<host-ip>:8000/upload?user_id=alice
   ```

2. **Open the URL** in any browser on your local machine.

3. The form has your `user_id` pre-filled.  Click **Choose file**, select
   your PDF, then click **Upload PDF**.

4. Wait for the green **"Upload successful!"** message on the page.

5. Return to the OpenClaw chat and say **"done"** — the agent will
   generate your curriculum automatically.

### If the URL is not reachable

The upload portal runs on port **8000** (the TA API).  The OpenClaw UI dashboard
runs on port **18789**.  When the host machine is remote (e.g. a brev cloud instance)
neither port is directly reachable from your laptop — you must tunnel them first.

---

### Accessing from a remote host via WSL + brev

This is the standard setup when the stack runs on a brev cloud instance and you are
working from a Windows laptop with WSL.

**Ports to forward**

| Port | Service | URL after forwarding |
|------|---------|---------------------|
| `8000` | TA API + upload portal | `http://127.0.0.1:8000/upload` |
| `18789` | OpenClaw UI dashboard | `http://127.0.0.1:18789` |

**Step 1 — Run port-forward commands in your WSL terminal**

Open WSL (e.g. Ubuntu) and run each forward in its own terminal tab — they must
stay open for the duration of the session:

```bash
# Tab 1 — TA API / PDF upload portal
brev port-forward hermes-omni-aita -p 8000:8000

# Tab 2 — OpenClaw UI (only needed if using the browser dashboard)
brev port-forward hermes-omni-aita -p 18789:18789
```

Replace `hermes-omni-aita` with your actual brev instance name
(run `brev ls` to list instances).

**Step 2 — Install with the correct external URL**

Because `install.sh` bakes the upload URL into the skill config and MCP server, you
must pass `TA_EXTERNAL_URL` using `127.0.0.1`, **not** `localhost`.
Some browsers (especially on Windows) resolve `localhost` differently inside WSL
tunnels and the link won't open.

```bash
# Run on the remote host (in your SSH session to the brev instance):
TA_USER_ID=danny TA_EXTERNAL_URL=http://127.0.0.1:8000 bash install.sh --rag
```

**Step 3 — Open in your local browser**

After the agent gives you an upload link, open it in your Windows browser exactly
as shown — using `127.0.0.1`, not `localhost`:

```
http://127.0.0.1:8000/upload?user_id=alice
```

**Step 4 — Open the OpenClaw UI (optional)**

The dashboard token URL is printed at the end of `nemoclaw onboard`.  Forward port
18789 (see Step 1 Tab 2) then open:

```
http://127.0.0.1:18789/#token=<your-token>
```

> **Note**: the `#token=...` URL is printed only once during onboarding and treated
> like a password.  Save it.  If lost, re-run `nemoclaw samba connect` — it will
> print a new tokenized URL.

leverage below bash script for onboarded Openclaw inside the sandbox to obtain the url with the generated token 
```
nohup openclaw gateway run > /tmp/gateway.log 2>&1 &
    sleep 5
    token=$(grep -o '"token"\s*:\s*"[^"]*"' ~/.openclaw/openclaw.json | head -1 | cut -d'"' -f4)
    echo "Open in browser: http://127.0.0.1:18789/#token=$token"
```
---

**Option — Host is directly reachable (public IP / same LAN):**

```bash
TA_EXTERNAL_URL=http://<actual-host-ip>:8000 bash install.sh --rag
```

---

## 5. Full Workflow via OpenClaw Chat

```
You: "I want to upload my study PDF"
Agent: Here is your upload link: http://<host>:8000/upload?user_id=alice
       Open it in your browser, upload the PDF, then come back and say done.

[user uploads PDF via browser]

You: "Done, I uploaded it"
Agent: [calls generate_curriculum] Generating your curriculum...
       ✅ Curriculum ready! You have 5 subtopics in Chapter 1.

You: "What subtopics do I have?"
Agent: [calls list_subtopics]
       0 — Introduction to Claude Skills  (not started)
       1 — Modularity and Orchestration   (not started)
       ...

You: "Explain subtopic 0"
Agent: [calls chat_message] Here's what you need to know about Claude Skills...

You: "Quiz me on subtopic 0"
Agent: [calls generate_quiz]
       Q1: What best defines a Claude skill?
         A) A workflow
         B) A modular capability...
         C) A metadata file
         D) A licensing term

You: "B, A, B"
Agent: [calls submit_quiz(answers="B,A,B")]
       ✅ 3/3 correct! Subtopic completed.

You: "Book a study session for tomorrow at 3pm"
Agent: [calls book_calendar] Here's your .ics event — save it to your calendar.

You: "Plan my week around my Friday quiz"
Agent: [calls plan_study_week] Here's a weekly study plan with prioritized blocks.

You: "Make that study plan downloadable for my calendar"
Agent: [calls plan_study_week --create-calendar-events] Download this .ics file and add it to your calendar.

You: "Find YouTube videos about Claude skills"
Agent: [calls youtube_search] Here are 5 relevant videos...
```

---

## 6. REST API Reference (curl)

The FastAPI backend starts automatically with `make up` / `make up-with-rag`.
Swagger UI is at **http://localhost:8000/docs**.

### Recommended workflow

```
Upload PDF  →  Check ingestion  →  Generate curriculum  →  Chat / Quiz / Calendar
```

Upload automatically ingests the PDF into Milvus in the same call (Option B).
When the response says `"ingested into vector store"`, chunks are already
indexed and you can go straight to curriculum generation.

```bash
# Health check
curl http://localhost:8000/

# 1. Upload a PDF (Option A & B)
curl -X POST http://localhost:8000/api/files/upload \
  -F "user_id=testuser" \
  -F "files=@/path/to/your.pdf"
# → {"success":true,"message":"Successfully uploaded 1 file(s) and ingested into vector store",...}
# → {"success":true,"message":"Successfully uploaded 1 file(s)",...}  (Option A)

# 2. Verify ingestion status (optional)
curl http://localhost:8000/api/files/ingest-status/testuser
# → {"ready": true, "chunk_count": 33, "exists": true, "message": "Ready for curriculum generation"}

# 3. Generate curriculum (SSE stream — wait for "complete")
curl -N "http://localhost:8000/api/curriculum/generate-stream?user_id=testuser"
#
#   data: {"type":"start","total_pdfs":1,"pdfs":["Skills4Claude.pdf"]}
#   data: {"type":"phase","phase":"curriculum","message":"Creating curriculum structure..."}
#   data: {"type":"subtopic_progress","phase":"building","message":"Generating: Introduction..."}
#   data: {"type":"complete","success":true,"message":"Curriculum generated! First chapter ready..."}
#
# ✅ Last event: {"type":"complete",...}
# ❌ Last event: {"type":"error","message":"..."}

# 3b. Verify curriculum
curl http://localhost:8000/api/curriculum/testuser

# 4a. Chat with study buddy
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"testuser","message":"Explain the first topic"}'

# 4b. Quiz workflow
# Step 1 — list subtopics
curl http://localhost:8000/api/quiz/subtopics/testuser

# Step 2 — generate quiz (use index from step 1)
curl -X POST http://localhost:8000/api/quiz/generate \
  -H "Content-Type: application/json" \
  -d '{"user_id":"testuser","subtopic_number":0}'

# Step 3 — submit answers (A/B/C/D or 0/1/2/3)
curl -X POST http://localhost:8000/api/quiz/submit \
  -H "Content-Type: application/json" \
  -d '{"user_id":"testuser","subtopic_number":0,"answers":["B","A","B"]}'

# 4c. Calendar booking
curl -X POST http://localhost:8000/api/calendar/create \
  -H "Content-Type: application/json" \
  -d '{"user_id":"testuser","text":"Study session tomorrow at 3pm for 1 hour"}'

# 4d. YouTube search
curl "http://localhost:8000/api/youtube/search?query=machine+learning"

# --- Vector store management ---

# Reset one user (re-upload a new PDF)
curl -X DELETE http://localhost:8000/api/files/collections/testuser

# Full wipe (all users)
curl -X DELETE http://localhost:8000/api/files/collections
```

> After a container restart, restore the API + RAG network connection:
> ```bash
> docker network connect compose_default agenticta
> make api
> ```

---

## 7. Daily Operations

```bash
# Start
make up                  # Option A — no RAG
make up-with-rag         # Option B — with RAG

# Clean start (wipes all user state: PDFs, state.txt, JSON store, memory)
make fresh               # Option A
make fresh-with-rag      # Option B — also clears Milvus

# Stop everything
make down

# Monitor
make logs-api            # tail FastAPI log
make logs-gradio         # tail Gradio log
make logs                # tail agenticta container log
make status              # show all running containers

# Enter container shell
make shell

# Restart individual services after code changes
make gradio              # restart Gradio (source is volume-mounted)
make api                 # restart FastAPI

# Full rebuild (after Dockerfile or requirements.txt changes)
make rebuild

# MCP server
tail -f /tmp/ta-mcp.log                         # watch MCP logs
kill $(cat /tmp/ta-mcp.pid)                     # stop MCP server
bash install.sh --rag                           # restart everything
```

### MCP tool reference (OpenClaw skill)

| Tool | When to use |
|---|---|
| `get_upload_link` | User asks to upload a PDF |
| `get_image_upload_link` | User wants to share an image/diagram and ask a VLM question |
| `get_last_vlm_response` | Retrieve stored VLM answer after image submission |
| `ingest_uploaded_pdf` | Re-trigger ingestion after upload |
| `upload_pdf` | Admin/automation: PDF already on host filesystem |
| `check_ingest_status` | Verify PDF is ready for curriculum generation |
| `generate_curriculum` | After upload confirmed — builds study plan |
| `get_curriculum` | Retrieve existing curriculum |
| `chat_message` | General study questions |
| `list_subtopics` | Show chapter subtopics with indices |
| `generate_quiz` | Create MCQ quiz for a subtopic |
| `submit_quiz` | Grade answers (A/B/C/D or 0/1/2/3) |
| `plan_study_week` | Create a weekly academic plan from curriculum, schedule, assignments, deadlines, and availability. Use `--create-calendar-events` for a downloadable `.ics` |
| `book_calendar` | Natural-language → .ics calendar event |
| `youtube_search` | Find supplementary videos |
| `delete_user_data` | Wipe one user (before re-upload) |
| `health_check` | Verify TA API reachable |

---

## 8. Architecture

```
User (browser)
     │ open http://<host>:8000/upload
     │ select PDF → POST /upload/submit
     ▼
TA API (port 8000)  ◀───────── OpenClaw sandbox
     │                          │  fastmcp.Client
     │                          │  → MCP tools
     │                    MCP Server (port 8999)
     │
     ├─ /api/files/upload  → saves PDF to mnt/{user_id}/pdfs/
     │       │
     │       └─ (Option B) Ingestor (port 8082)
     │                          │
     │                       Milvus (port 19530)
     │
     ├─ /api/curriculum/generate-stream
     │       │
     │       └─ nodes.py / build_chapters()
     │               │
     │               ├─ chapter_gen_from_pdfs()  ← direct PDF + LLM
     │               └─ sub_topic_builder()
     │                       │
     │                       ├─ RAG server (port 8081)  ← Option B
     │                       └─ Direct PDF fallback     ← Option A
     │                               ▼
     │                          LLM (NVIDIA API)
     │
     ├─ /api/chat/message      → study buddy (router → tool handler)
     ├─ /api/quiz/*            → quiz generation + grading
     ├─ /api/calendar/create   → .ics event
     └─ /api/youtube/search    → YouTube results
```

### Key files

| File | Purpose |
|---|---|
| `ai_teaching_assistant_mcp_server.py` | FastMCP server exposing all tools |
| `ai_teaching_assistant_skills/` | OpenClaw skill (client + policy + SKILL.md) |
| `install.sh` | Full stack installer (idempotent) |
| `mcp_client_test.py` | Host-side MCP test client |
| `api/routes/upload_ui.py` | Browser PDF upload form (`GET /upload`) |
| `gradioUI.py` | Gradio entry point |
| `nodes.py` | Curriculum generation pipeline |
| `fast_store.py` | Text-file state store (grep/sed — replaces JSON) |
| `agent_memory.py` | Agentic memory (lazy-loaded, user-specific files) |
| `standalone_study_buddy_response.py` | Query router + study buddy LLM calls |
| `llm_config.yaml` | Model aliases, temperatures, providers |

---

## 9. Troubleshooting

**`install.sh` fails at Step 2 with `unknown shorthand flag: 'd' in -d`**

The `docker-compose-v2` plugin is not installed, so `docker compose` is not
available as a subcommand — `docker compose up -d` is misread as `docker -d`.
Install the plugin and re-run:

```bash
sudo apt-get install -y docker-compose-v2
# verify
docker compose version
# then retry
TA_USER_ID=demo TA_EXTERNAL_URL=http://localhost:8000 bash install.sh --rag
```

> This affects both `make up` (Option A) and `make up-with-rag` (Option B) — both
> Makefile targets use `docker compose up -d` internally.

**`install.sh --rag` fails with `couldn't find env file`, `NGC_API_KEY is required`, or `invalid mount path: ':'`**

Three things must exist for the RAG compose stack that are not bundled with this
repo: the NVIDIA RAG Blueprint source, a correctly populated
`rag/deploy/compose/.env`, and a `PROMPT_CONFIG_FILE` pointing to a real path.

**`install.sh` now handles all of this automatically** in a new Step 2a:

| Action | What it does |
|---|---|
| Clone `NVIDIA-AI-Blueprints/rag` | Provides `vectordb.yaml`, `docker-compose-ingestor-server.yaml`, `docker-compose-rag-server.yaml`, and `nvdev.env` |
| Build `.env` from `nvdev.env` | Uses the repo's cloud endpoint template; prepends `NGC_API_KEY` from root `.env` |
| Append `PROMPT_CONFIG_FILE` | Points to `rag/src/nvidia_rag/rag_server/prompt.yaml` (avoids the `':'` mount error) |
| `docker login nvcr.io` | Authenticates with NGC so NIM images can be pulled |

The `nvdev.env` template (not the on-prem `.env`) is used as the base because
it has all cloud API endpoints pre-configured — no lines to comment or uncomment.

**Persistent `invalid mount path: ':'` even after re-running `install.sh`**

`nvdev.env` does **not** end with a trailing newline.  If `PROMPT_CONFIG_FILE` is
appended with a plain shell `echo`, it silently concatenates onto the last comment
line:

```
# export MULTITURN_RETRIEVER_SIMPLE=...export PROMPT_CONFIG_FILE=/path/to/prompt.yaml
```

Docker Compose treats the entire line as a comment → `PROMPT_CONFIG_FILE` is blank
→ the ingestor volume mount becomes `':'` → fatal error.

The `_rag_env_ok` check only tests for `NGC_API_KEY`, so a broken `.env` passes the
check, is reused unchanged, and the error repeats on every re-run.

`install.sh` fixes both cases:
- **New `.env`**: uses `printf '\n'` before the `PROMPT_CONFIG_FILE` echo.
- **Existing `.env`**: always verifies `^(export )?PROMPT_CONFIG_FILE=/` is present on
  its own line; strips any broken in-line occurrence and re-appends correctly.

To fix an already-broken `.env` manually:

```bash
# Strip the broken in-line entry (appended to a comment line)
sed -i 's/export PROMPT_CONFIG_FILE=[^[:space:]]*//' rag/deploy/compose/.env

# Re-add on its own line
printf '\nexport PROMPT_CONFIG_FILE=%s\n' \
  "$(pwd)/rag/src/nvidia_rag/rag_server/prompt.yaml" \
  >> rag/deploy/compose/.env

# Verify
grep "PROMPT_CONFIG_FILE" rag/deploy/compose/.env
# Expected: export PROMPT_CONFIG_FILE=/absolute/path/to/prompt.yaml
```

To create the `.env` from scratch manually:

```bash
# 1. Clone
git clone https://github.com/NVIDIA-AI-Blueprints/rag.git rag

# 2. Build .env — note the 'printf' guard before PROMPT_CONFIG_FILE
NGC_KEY=$(grep '^NVIDIA_API_KEY=' .env | cut -d= -f2 | awk '{print $1}')
{
  echo "export NGC_API_KEY=${NGC_KEY}"
  cat rag/deploy/compose/nvdev.env
  printf '\nexport PROMPT_CONFIG_FILE=%s\n' "$(pwd)/rag/src/nvidia_rag/rag_server/prompt.yaml"
} > rag/deploy/compose/.env

# 3. Log in to nvcr.io
echo "${NGC_KEY}" | docker login nvcr.io -u '$oauthtoken' --password-stdin

# 4. Retry
TA_USER_ID=demo TA_EXTERNAL_URL=http://localhost:8000 bash install.sh --rag
```

**`make rag-up` / `milvus-standalone` fails with `could not select device driver "nvidia"`**

`milvus-standalone` in the NVIDIA RAG blueprint defaults to the GPU image
(`milvusdb/milvus:v2.6.5-gpu`) and requires the NVIDIA container runtime.
On a CPU-only host this causes:

```
Error response from daemon: could not select device driver "nvidia" with capabilities: [[gpu]]
```

**Root cause**: Docker Compose merge semantics do **not** support clearing a list via
an override file (`devices: []` in a second compose file does not remove the existing
`devices` list — it is silently ignored).  The only reliable fix is to remove the
`deploy.resources.reservations.devices` block from `vectordb.yaml` directly.

**`install.sh` handles this automatically**: when `nvidia-smi` is not found, Step 2a
uses a Python one-liner to regex-remove the GPU deploy block from
`rag/deploy/compose/vectordb.yaml`, then appends three CPU-specific env vars to
`rag/deploy/compose/.env`:

```
export MILVUS_VERSION=v2.6.5                    # CPU image (no -gpu suffix)
export APP_VECTORSTORE_ENABLEGPUSEARCH=False
export APP_VECTORSTORE_ENABLEGPUINDEX=False
```

The patch is idempotent — if the block is already absent (or `install.sh` was run
before) the script skips it.

To apply the patch manually on a CPU-only host:

```bash
# 1. Remove the GPU deploy block from vectordb.yaml
python3 - rag/deploy/compose/vectordb.yaml <<'PYEOF'
import sys, re
path = sys.argv[1]
with open(path) as f:
    content = f.read()
patched = re.sub(
    r'\n    deploy:\n      resources:\n        reservations:\n          devices:\n(?:            [^\n]*\n)+',
    '\n',
    content
)
if patched != content:
    with open(path, 'w') as f:
        f.write(patched)
    print("Patched")
else:
    print("Already patched")
PYEOF

# 2. Add CPU env vars to the RAG .env
cat >> rag/deploy/compose/.env <<'EOF'
export MILVUS_VERSION=v2.6.5
export APP_VECTORSTORE_ENABLEGPUSEARCH=False
export APP_VECTORSTORE_ENABLEGPUINDEX=False
EOF

# 3. Retry
make rag-up
```

**`make rag-up` fails with `401 Authorization Required` pulling NIM images**

The RAG blueprint images (e.g. `nvcr.io/nvidia/nemo-microservices/nv-ingest`) are
gated behind NVIDIA's container registry and require a one-time Docker login.
**`install.sh` now handles this automatically** using `NGC_API_KEY` from
`rag/deploy/compose/.env`.

To log in manually:

```bash
NGC_KEY=$(grep '^NGC_API_KEY=' rag/deploy/compose/.env | cut -d= -f2 | awk '{print $1}')
echo "$NGC_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin
# then retry
make rag-up
```

> The key must have access to the NGC private registry.  `nvapi-...` keys from
> the NVIDIA API Catalog work here.

**`install.sh --rag` skips RAG services when `agenticta` is already running**

The container-running check in Step 2 previously skipped `make up-with-rag`
entirely when `agenticta` was already up — leaving the ingestor and RAG server
never started.  **`install.sh` now handles this automatically**: when `agenticta`
is running but the ingestor (port 8082) is not, it runs `make rag-up` to bring
the RAG services up without restarting the main container.

If you hit this state before the fix was applied, start the RAG services
manually:

```bash
make rag-up
# verify
make rag-health
```

**Step 8 fails — `filesystem read_write path '/sandbox/.*' cannot be removed on a live sandbox`**

The NemoClaw sandbox image bakes in several paths **explicitly** as `read_write` in its
internal policy.  When `openshell policy set` applies our custom
`policy/sandbox_policy.yaml`, it does a **full replacement** — not a merge.  If our
policy lists `/sandbox` (the parent) but omits the explicit sub-paths, the policy engine
treats them as removed and rejects the change:

```
filesystem read_write path '/sandbox/.openclaw' cannot be removed on a live sandbox
filesystem read_write path '/sandbox/.nemoclaw' cannot be removed on a live sandbox
```

**Root cause**: the OpenShell policy engine tracks explicit path entries independently of
parent paths — `/sandbox` as `read_write` does NOT automatically cover `/sandbox/.openclaw`
in the diff logic.

The paths baked into the sandbox image (confirmed via database inspection) are:
- `/sandbox/.openclaw` — OpenClaw config and plugin runtime
- `/sandbox/.nemoclaw` — NemoClaw blueprints and init scripts

The fix is to list both explicitly in the `read_write` section of
`policy/sandbox_policy.yaml` alongside `/sandbox`.  Both are now present in the file.

Re-running `install.sh` (without `--fresh`, so onboarding is skipped) will apply the
corrected policy to the existing sandbox.

**Gradio not responding**
```bash
docker compose exec agenticta pkill -f gradioUI.py && make gradio
make logs-gradio
```

**TA API not starting**
```bash
make logs-api
# Common cause: NVIDIA_API_KEY not set in .env
```

**Upload portal not reachable from browser**
```bash
# SSH tunnel from your local machine:
ssh -L 8000:<host-ip>:8000 user@<host>
# Then open: http://localhost:8000/upload?user_id=yourname
```

**Curriculum generation fails / empty study materials**
```bash
make logs-gradio   # look for [study_material_gen] lines
# "Direct PDF extraction: N chars" — OK for Option A
# "0 chars" — PDF may be image-only (scanned); try a text-based PDF
```

**RAG services not responding (Option B)**
```bash
make rag-health
make rag-down && make rag-up
docker compose -f rag/deploy/compose/vectordb.yaml --env-file rag/deploy/compose/.env logs milvus
```

**`agenticta` cannot reach `ingestor-server` or `rag-server` by hostname**

The RAG services run on the `nvidia-rag` Docker network.  `agenticta` must be
connected to that network so it can resolve `ingestor-server:8082` and
`rag-server:8081`.  `make up-with-rag` and `make rag-up` now do this
automatically.  To fix manually:

```bash
docker network connect nvidia-rag agenticta
```

**`openclaw tui` — "Missing gateway auth token"**

The OpenShell gateway inference provider is not configured. This is normally handled
by `install.sh` step 5, but can also be done manually:

```bash
# 1. Ensure keys are exported
export NVIDIA_API_KEY=nvapi-...
export INFERENCE_API_KEY=nvapi-...

# 2. Start the gateway (if not already running)
openshell gateway start

# 3. Create the NVIDIA inference provider
openshell provider create \
  --type nvidia \
  --name nvidia \
  --credential INFERENCE_API_KEY \
  --config NVIDIA_BASE_URL=https://inference-api.nvidia.com/v1

# 4. Set the active model
openshell inference set \
  --provider nvidia \
  --model aws/anthropic/bedrock-claude-sonnet-4-6

# 5. Verify
openshell inference get
```

Then retry `openclaw tui` inside the sandbox.

**`--fresh` flag appears to do nothing**

`--fresh` is silently skipped when the `agenticta` container is already running.
Stop the stack first:

```bash
make down
bash install.sh --rag --fresh
```

> Note: `make down` does **not** stop the OpenShell gateway (`openshell-cluster-openshell`).
> That container is managed separately and should be left running.

**install.sh hangs waiting for input (step 10 — user_id prompt)**

The script prompts interactively for a `user_id` unless `TA_USER_ID` is set.
Pass it as an env var to run fully non-interactively:

```bash
TA_USER_ID=alice bash install.sh --rag
```

**MCP server not responding**
```bash
cat /tmp/ta-mcp.log
# Restart:
kill $(cat /tmp/ta-mcp.pid) && bash install.sh --rag
```

**Skill not found in sandbox after reconnect**
```bash
# Re-run install to re-upload
bash install.sh --rag
# Then disconnect and reconnect in NemoClaw
```

**Container won't start**
```bash
make down && make up
# Full rebuild:
make rebuild
```

**Port already in use**
```bash
sudo lsof -i :7860   # find conflicting process
make restart
```
