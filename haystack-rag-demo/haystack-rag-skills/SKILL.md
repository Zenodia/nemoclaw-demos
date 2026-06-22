---
name: haystack-rag-skills
description: >-
  MANDATORY skill for any question about Haystack, deepset, RAG, retrieval-augmented
  generation, document search, knowledge base, pdf indexing, embeddings, vector
  search, indexed documents, or "what is haystack". Also mandatory for indexing
  documents or listing what is indexed. NEVER answer these topics from your general
  knowledge — ALWAYS run the shell commands. EXEC-READY COPY-PASTE RECIPES — pick
  the one matching user intent and run it, substituting USER_QUESTION. STEP 1
  (always first — find SKILL_DIR): for _c in
  /sandbox/.openclaw/workspace/skills/haystack-rag-skills
  /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills
  "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do [ -d "$_c" ] &&
  SKILL_DIR="$_c" && break; done (A) "what is haystack" / "tell me about RAG" /
  any knowledge question → TWO steps: first run
  `$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health` and
  if indexed_chunks is 0 run setup, then run
  `$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "USER_QUESTION"`.
  (B) "index documents" / "index my files" →
  `$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py index`. (C)
  "index the sample" / "set up" / first use →
  `$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py setup`. (D)
  "what is indexed" / "list documents" →
  `$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py list-documents`.
  (E) health check →
  `$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health`.
  HARD RULES — (1) "what is haystack?" = recipe A, NOT a general-knowledge reply.
  (2) "index document for me" = recipe B or C, NOT "I'm not sure what you mean".
  (3) ALWAYS use $SKILL_DIR/venv/bin/python3 (skill venv), never bare python3.
  (4) If health shows indexed_chunks=0, run setup before any query. (5) The server
  runs on the host at http://172.18.0.1:9004 — it is always reachable; if it
  fails retry once then report the error. ANTI-PATTERNS — DO NOT answer Haystack
  or RAG questions from training data. DO NOT say "I'm not sure what you mean by
  index document". DO NOT skip the SKILL_DIR discovery step. DO NOT use bare
  python3 instead of the venv interpreter.
---

# Haystack RAG Skills

## ⚠️ Hard rules — read first

1. **NEVER answer Haystack / RAG / document questions from your general knowledge.**
   If the user asks "what is Haystack?", "how does RAG work?", "what is indexed?",
   "index my documents" — run the shell command immediately. Do not compose a
   text answer before running the tool.

2. **ALWAYS resolve `SKILL_DIR` first** (one-liner in Step 1 below). Every command
   is relative to it. Do not hard-code a path.

3. **Check `indexed_chunks` before querying.** Run `health` first. If `indexed_chunks`
   is 0, run `setup` to load the built-in sample, then run the query.

4. **Use `$SKILL_DIR/venv/bin/python3`, not bare `python3`.** The skill venv has
   `requests`; the sandbox's system Python does not.

5. **The RAG server is on the host, not in the sandbox.** It lives at
   `http://172.18.0.1:9004`. If a request fails, retry once. If it still fails,
   read the URL from `$SKILL_DIR/server_url.txt` and retry with that URL.

6. **"index document for me" is not ambiguous.** It means: run `index` (embed
   all files in the server's data directory). Do not ask for clarification.

---

## Step 1 — Resolve SKILL_DIR (run first, always)

```sh
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do [ -d "$_c" ] && SKILL_DIR="$_c" && break; done && echo "SKILL_DIR=$SKILL_DIR"
```

---

## Step 2 — Run the skill command

Replace `$SKILL_DIR` with the path found above.

**Health check + chunk count:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health
```

**Index the built-in Haystack sample document (run when `indexed_chunks` is 0):**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py setup
```

**Answer a question using RAG (replace USER_QUESTION):**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "USER_QUESTION"
```

**Index documents from the server's data directory:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py index
```

**List indexed files:**
```sh
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py list-documents
```

---

## Complete flow for any Haystack / document / RAG question

Run these shell commands in order using the bash/terminal tool:

```sh
# 1. Find SKILL_DIR
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do [ -d "$_c" ] && SKILL_DIR="$_c" && break; done

# 2. Check health; if indexed_chunks=0, load the built-in sample first
CHUNKS=$($SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health | python3 -c "import sys,json; print(json.load(sys.stdin).get('indexed_chunks',0))" 2>/dev/null || echo 0)
[ "$CHUNKS" = "0" ] && $SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py setup

# 3. Query — replace with the actual user question
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "REPLACE_WITH_USER_QUESTION"
```

---

## Notes

- The server runs on the **host**, not in the sandbox — the skill is a thin HTTP client.
- Always use `$SKILL_DIR/venv/bin/python3` (the skill venv), never bare `python3`.
- The server URL (`http://172.18.0.1:9004`) is written by install.sh to
  `$SKILL_DIR/server_url.txt`. The client reads it automatically. The bridge IP
  `172.18.0.1` is the only host address reachable from inside the sandbox
  network namespace — do NOT use `10.x.x.x` IPs or `host.openshell.internal`.
- If connection fails, verify from the host: `curl $(cat $SKILL_DIR/server_url.txt)/health`
- `query` is a subcommand — `--question` is its argument. Wrong: `haystack_client.py --question "..."`. Right: `haystack_client.py query --question "..."`.
