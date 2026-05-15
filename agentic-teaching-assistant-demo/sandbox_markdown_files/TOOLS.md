# TOOLS.md — Tool Usage Guidance

## Preferred Tools
- **`ai_teaching_assistant_skills`** — always reach for this first
  - Use `get_upload_link` for PDF uploads
  - Use `get_image_upload_link` when the user wants to share an image/diagram and ask a VLM question; follow up with `get_last_vlm_response` to retrieve the answer
  - Use `get_study_break_link` when the user wants a break, wants to play a game, or needs a breather — no user ID required
  - Use skill-provided tools for curriculum generation, quizzes, and study sessions

## Tools to Avoid
- 🚫 **Brave web search** — disabled by default, do not use unless explicitly enabled by the user

## General Tool Guidelines
- Prefer skill-native tools over generic search or browser tools
- When in doubt about a tool, check `ai_teaching_assistant_skills` first before reaching elsewhere
- Keep tool usage transparent — let the user know what's happening in simple terms
