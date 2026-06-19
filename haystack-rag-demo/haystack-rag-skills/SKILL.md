---
name: haystack-rag-skills
description: >-
  Answer questions about Haystack, deepset, RAG pipelines, and indexed documents
  using a Haystack RAG server running on the host. Handles indexing documents,
  listing indexed files, checking the knowledge base, and answering questions
  grounded in indexed docs. Triggers on questions about haystack, deepset, RAG,
  retrieval-augmented generation, document search, knowledge base, pdf indexing,
  embeddings, vector search, "what is haystack", "index my documents", or "what
  documents are indexed". HOW TO RUN: there is NO callable tool named
  haystack-rag-skills — instead run its Python client through the shell exec tool
  from inside tool_search_code, e.g. await openclaw.tools.call('openclaw:core:exec',
  { command: '/sandbox/.openclaw/workspace/skills/haystack-rag-skills/venv/bin/python3
  /sandbox/.openclaw/workspace/skills/haystack-rag-skills/scripts/haystack_client.py index' }).
---

# Haystack RAG Skills

## How to run this skill (REQUIRED — read first)

Your only execution tool is **`tool_search_code`**, which runs JavaScript. There is
**no** tool named `haystack-rag-skills` and **no** `indexDocuments` method — do not
call `openclaw.tools.call('haystack-rag-skills', ...)`.

To perform any operation, run the skill's Python client through the built-in shell
exec tool (`openclaw:core:exec`) from inside `tool_search_code`:

```js
const D = '/sandbox/.openclaw/workspace/skills/haystack-rag-skills';
return await openclaw.tools.call('openclaw:core:exec', {
  command: `${D}/venv/bin/python3 ${D}/scripts/haystack_client.py <COMMAND>`
});
```

Replace `<COMMAND>` with exactly one of: `index`, `query --question "..."`,
`list-documents`, `health`, or `setup`. After it runs, report the command's stdout
to the user.

## Commands

| User intent | `<COMMAND>` |
|---|---|
| "Index my documents" / "embed my files" | `index` |
| Answer a question grounded in the docs | `query --question "THE QUESTION"` |
| "What documents are indexed?" | `list-documents` |
| Check server liveness + chunk count | `health` |
| First use / 0 chunks: index bundled sample | `setup` |

### Example — "Index my documents"

```js
const D = '/sandbox/.openclaw/workspace/skills/haystack-rag-skills';
return await openclaw.tools.call('openclaw:core:exec', {
  command: `${D}/venv/bin/python3 ${D}/scripts/haystack_client.py index`
});
```

### Example — answer "What is Haystack?"

```js
const D = '/sandbox/.openclaw/workspace/skills/haystack-rag-skills';
return await openclaw.tools.call('openclaw:core:exec', {
  command: `${D}/venv/bin/python3 ${D}/scripts/haystack_client.py query --question "What is Haystack?"`
});
```

(For a different question, replace the text inside the double quotes; escape any
double quotes inside the question.)

## Notes

- The server runs on the **host** (port 9004); this skill is a thin HTTP client.
  No NVIDIA API key is needed in the sandbox — all inference happens on the host.
- Always invoke `${D}/venv/bin/python3` — the sandbox network policy only permits
  that binary (and the host python) to reach the server on port 9004.
- A harmless `OOM score adjust: Permission denied` line may appear in stderr; ignore it.
- If a command reports it cannot connect, check the host server:
  `curl http://host.openshell.internal:9004/health`
