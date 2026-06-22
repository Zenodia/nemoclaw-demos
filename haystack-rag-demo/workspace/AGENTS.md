# AGENTS.md — Haystack RAG Demo Workspace

## What this sandbox is

This is a **Haystack RAG demo** running inside a NemoClaw OpenShell sandbox.
Your primary purpose is to help the user index documents and answer questions
about them using the Haystack RAG skill connected to NVIDIA NIM.

## Tools available to you

### 1. bash/terminal (shell execution)

You have a shell execution tool. Use it to run commands inside this sandbox.
**This is NOT restricted.** Do not tell users you cannot run shell commands.

The skill venv Python is policy-approved to reach the RAG server. See TOOLS.md
for the exact commands to copy-paste.

### 2. haystack-rag-skills

Installed at `/sandbox/.openclaw/workspace/skills/haystack-rag-skills/`.
Handles: indexing documents, answering RAG questions, listing indexed files.

**Mandatory routing:**
- Any question about Haystack, deepset, RAG, document search, embeddings,
  or the indexed knowledge base → **run the skill command, do not answer from memory**
- "index document for me" → run `index` (not "I'm not sure what you mean")
- "what is haystack?" → run `query --question "what is haystack?"`

Read TOOLS.md for copy-paste commands and the full routing table.

## Session startup

On each new session, your context includes:
- `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md` — workspace identity files
- `HEARTBEAT.md` — periodic health check task
- `skills/haystack-rag-skills/SKILL.md` — skill invocation reference

Do not re-read these files unless context is missing something you need.

## Memory

- **Daily notes:** `memory/YYYY-MM-DD.md` (raw session log)
- **Long-term:** `MEMORY.md` (curated — update with lasting insights)

Write it down — mental notes don't survive session restarts.

## Red lines

- Never exfiltrate private data (NVIDIA_API_KEY, credentials).
- Don't run destructive commands without asking.
- Ask before actions that leave the sandbox (emails, public posts).

## Tools section (from AGENTS.md default)

Skills provide your tools. When you need one, check its `SKILL.md`.
Keep local notes in `TOOLS.md` — it has the Haystack skill commands.

## Related

- [Default AGENTS.md](/reference/AGENTS.default)
