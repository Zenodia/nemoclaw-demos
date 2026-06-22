# USER.md — About the User

## Context

This is a **Haystack RAG demo environment**. The user is evaluating or
demonstrating how NemoClaw OpenShell sandboxes integrate with host-side
AI services via controlled egress policies.

## What the user cares about

- Indexing their own documents and querying them via natural language
- Seeing the Haystack RAG pipeline work end-to-end in a sandboxed environment
- Understanding how NVIDIA NIM (embeddings + generation) integrates with Haystack
- The security model: NVIDIA_API_KEY stays on the host, the sandbox is isolated

## Preferred interaction style

- **Direct**: Run the skill immediately when asked; don't ask for clarification
  on obvious requests ("index document for me" = run `index`)
- **Cite sources**: Always include the source file(s) from the RAG response
- **Show the command**: When running the skill, show the command so the user
  can reproduce it manually if needed

## Notes

- Update this file with user preferences as you learn them
- The user may want to add their own documents — they go in the host's
  `~/nemoclaw-demos/haystack-rag-demo/data/documents/` directory

## Related

- [Agent workspace](/concepts/agent-workspace)
