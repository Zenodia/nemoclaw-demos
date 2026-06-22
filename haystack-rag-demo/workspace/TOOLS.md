# TOOLS.md — Haystack RAG Demo

## Execution: you CAN and MUST run shell commands

**The bash/terminal tool is available and policy-approved.** Do NOT tell the user
you "cannot execute Python scripts" or that "shell access is restricted" — that
is incorrect for this environment. When a task requires running a skill command,
use the bash/terminal tool immediately.

## Haystack RAG Skill

Skill name: `haystack-rag-skills`
Installed at: `/sandbox/.openclaw/workspace/skills/haystack-rag-skills/`
RAG server: `http://172.18.0.1:9004` (host bridge IP — always reachable from sandbox)

The skill is a thin HTTP client. All NVIDIA inference runs on the host;
the sandbox only makes approved HTTP calls to `172.18.0.1:9004`.

### Copy-paste commands

```sh
# Step 1 — resolve SKILL_DIR (run this first every time)
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills \
           /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills \
           "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do
  [ -d "$_c" ] && SKILL_DIR="$_c" && break
done

# Health check (run before any query to confirm server is up + chunk count)
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health

# Load built-in Haystack sample doc (run once when indexed_chunks = 0)
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py setup

# Answer a question via RAG
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "YOUR QUESTION"

# Index documents from the host data directory
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py index

# List indexed documents
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py list-documents
```

**Key rules:**
- Always use `$SKILL_DIR/venv/bin/python3`, never bare `python3`
- `query --question` is correct; `--question` before `query` fails
- If `indexed_chunks` is 0, run `setup` before `query`
- Server URL is written to `$SKILL_DIR/server_url.txt` by install.sh

## When to use the skill vs answer directly

| User says | Do this |
|---|---|
| "what is haystack?" | Run `query --question "what is haystack?"` — do NOT write from memory |
| "index my documents" | Run `index` |
| "index document for me" | Run `index` — this is not ambiguous |
| "what is indexed?" | Run `list-documents` |
| "how does RAG work?" | Run `query --question "how does RAG work?"` |
| "setup the sample" / first use | Run `setup` |
| General question unrelated to Haystack/RAG | Answer normally — no skill needed |
