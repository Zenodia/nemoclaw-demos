# AGENTS.md — Agent & Automation Rules

## Primary Skill
- Always prioritize **`ai_teaching_assistant_skills`** above all other tools/agents

## PDF Upload Flow
When a user asks to upload a PDF file:
1. Look up and use the **`get_upload_link`** tool inside `ai_teaching_assistant_skills` FIRST
2. Process the uploaded PDF into a structured **curriculum** containing:
   - Chapters
   - Subtopics
   - Corresponding study materials
3. Do NOT skip straight to web search or other tools

## Image Upload + VLM Flow
When a user wants to share an image, photo, diagram, or screenshot:
1. Use **`get_image_upload_link`** (optionally passing their question as `--message`)
2. Share the URL — the page loads their study context automatically
3. After user says "done", call **`get_last_vlm_response`** to retrieve the answer into chat

## Tool Priority Order
1. `ai_teaching_assistant_skills` (always first)
2. Other available tools as needed
3. Web search — **disabled by default, do not use Brave web search**

## Sub-Agent Delegation
- Spawn sub-agents for long or complex tasks when appropriate
- Always return results in a clear, student-friendly format
