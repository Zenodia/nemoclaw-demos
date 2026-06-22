# Haystack RAG Demo — Periodic Health Check

## Task: Monitor Haystack RAG server

On each heartbeat, silently check the RAG server and speak only if something
needs attention:

```sh
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do [ -d "$_c" ] && SKILL_DIR="$_c" && break; done && $SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py health 2>&1
```

- Status **ok** + `indexed_chunks > 0`: stay silent.
- Status **ok** + `indexed_chunks = 0`: offer once to run `setup` and load the sample doc.
- Server **unreachable**: say "Haystack RAG server is offline — let me know when to retry."

## Reminder: mandatory skill routing

When the user mentions any of these topics, ALWAYS run the haystack-rag-skills
shell commands — NEVER reply from general knowledge:

- Haystack, deepset, RAG, retrieval-augmented generation
- "index my documents" / "index document for me"
- "what is indexed" / "list documents"
- "tell me what is haystack" / "how does RAG work"
- Any question answerable from the indexed knowledge base

## Related

- [Heartbeat config](/gateway/config-agents)
