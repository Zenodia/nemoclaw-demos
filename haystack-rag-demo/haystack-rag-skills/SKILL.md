---
name: haystack-rag-skills
description: >-
  Answer questions about Haystack, deepset, RAG pipelines, and indexed documents
  using a Haystack RAG server running on the host. Auto-indexes a built-in sample
  document about Haystack on first use. Triggers on questions about haystack,
  deepset, RAG, retrieval-augmented generation, document search, knowledge base,
  pdf indexing, embeddings, vector search, or what is haystack. Also handles
  indexing documents, listing indexed files, and answering from a knowledge base.
---

# Haystack RAG Skills

## How to invoke this skill

**Always use the shell/bash execution tool** to run these commands. Do NOT use
JavaScript code execution tools — this skill works via shell commands only.

### Step 1 — Resolve paths (run this shell script first)

Run the following as a single shell command using the bash/terminal tool:

```sh
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do [ -d "$_c" ] && echo "SKILL_DIR=$_c" && break; done
```

Take the `SKILL_DIR=...` value from the output and use it in the commands below.

### Step 2 — Run the skill command

Replace `$SKILL_DIR` with the path found above and run via the bash/terminal tool:

**Check server + chunk count:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health
```

**Index the built-in Haystack sample document (run on first use or when 0 chunks):**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py setup
```

**Answer a question using RAG:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "QUESTION_HERE"
```

**Index documents from the server's data directory:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py index
```

**List indexed files:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py list-documents
```

## Complete flow for any question about Haystack or documents

Run these three shell commands in order using the bash/terminal tool:

```sh
# 1. Find SKILL_DIR
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do [ -d "$_c" ] && SKILL_DIR="$_c" && break; done

# 2. Index sample doc if nothing indexed yet
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health | grep -q '"indexed_chunks": 0' && $SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py setup || true

# 3. Query
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "REPLACE_WITH_USER_QUESTION"
```

## Notes

- The server runs on the **host**, not in the sandbox — the skill is a thin HTTP client.
- Always use `$SKILL_DIR/venv/bin/python3` (the skill venv), never bare `python3`.
- If connection fails, check: `curl http://host.openshell.internal:9004/health`
- Server URL default: `http://host.openshell.internal:9004`
