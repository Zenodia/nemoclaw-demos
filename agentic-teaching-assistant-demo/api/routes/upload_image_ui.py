"""
Image Upload UI Route

Serves a browser-accessible HTML form so users can push an image from their
local machine, ask a question, and get a VLM (visual-language model) response
using their full study-buddy context (chapter, subtopic, memory, history).

  GET  /upload-image?user_id=alice&message=explain+this+diagram
         → HTML form with pre-filled question, image file input
  POST /upload-image/submit
         → saves image, loads user study context + memory, calls
           vlm_study_buddy_response(), stores answer, renders result HTML

  GET  /upload-image/result?user_id=alice
         → returns JSON {"response": "..."} for the MCP tool to poll
"""

import os
import sys
import uuid
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# Path setup — mirror what api/main.py does
# ---------------------------------------------------------------------------
_parent = Path(__file__).parent.parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from common.debug import get_debug_logger

logger = get_debug_logger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Shared page chrome (matches upload_ui.py style)
# ---------------------------------------------------------------------------

_CSS = """
  body { font-family: system-ui, sans-serif; max-width: 680px; margin: 60px auto;
         padding: 0 24px; background: #f8f9fa; color: #212529; }
  h1   { font-size: 1.4rem; margin-bottom: 4px; }
  p.sub { color: #6c757d; font-size: .9rem; margin-top: 0; margin-bottom: 28px; }
  .card { background: #fff; border-radius: 10px; padding: 32px;
          box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  label { display: block; font-weight: 600; margin-bottom: 6px; }
  input[type=text], input[type=file], textarea {
    width: 100%; box-sizing: border-box; padding: 10px 12px;
    border: 1px solid #ced4da; border-radius: 6px; font-size: .95rem;
    margin-bottom: 18px; }
  textarea { min-height: 80px; resize: vertical; }
  button { background: #6f42c1; color: #fff; border: none; border-radius: 6px;
           padding: 11px 26px; font-size: 1rem; cursor: pointer; }
  button:hover { background: #5a32a3; }
  .ok   { color: #198754; font-weight: 600; }
  .err  { color: #dc3545; font-weight: 600; }
  .msg  { background: #e9ecef; border-radius: 6px; padding: 14px 16px;
          font-size: .88rem; white-space: pre-wrap; margin-top: 18px; }
  .vlm  { background: #f0ebff; border-left: 4px solid #6f42c1;
          border-radius: 6px; padding: 16px 18px;
          font-size: .92rem; white-space: pre-wrap; margin-top: 18px; }
  a.back { display: inline-block; margin-top: 22px; color: #6f42c1;
           text-decoration: none; font-size: .9rem; }
  a.back:hover { text-decoration: underline; }
"""


def _page(title: str, body: str, subtitle: str = "Image + VLM Study Buddy") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>📚 AI Teaching Assistant</h1>
  <p class="sub">{subtitle}</p>
  <div class="card">{body}</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Result store — simple per-user JSON file so the MCP tool can retrieve it
# ---------------------------------------------------------------------------

_SAVE_TO = Path(os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/"))


def _result_path(user_id: str) -> Path:
    return _SAVE_TO / "users" / user_id / "vlm_last_result.json"


def _store_result(user_id: str, question: str, answer: str) -> None:
    path = _result_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"question": question, "response": answer}, ensure_ascii=False), encoding="utf-8")


def _read_result(user_id: str) -> dict:
    path = _result_path(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Allowed image MIME types
# ---------------------------------------------------------------------------

_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


# ---------------------------------------------------------------------------
# GET /upload-image   — render the form
# ---------------------------------------------------------------------------

@router.get("/upload-image", response_class=HTMLResponse, include_in_schema=False)
async def upload_image_form(user_id: str = "", message: str = ""):
    """Render the browser-accessible image upload + question form."""
    uid_value = f'value="{user_id}"' if user_id else 'placeholder="e.g. alice"'
    msg_value = message  # pre-fill question from MCP tool if provided
    body = f"""
    <form method="post" action="/upload-image/submit" enctype="multipart/form-data">
      <label for="uid">Your User ID</label>
      <input type="text" id="uid" name="user_id" {uid_value} required>

      <label for="img">Image file (JPG, PNG, GIF, WEBP)</label>
      <input type="file" id="img" name="file"
             accept="image/jpeg,image/png,image/gif,image/webp,.jpg,.jpeg,.png,.gif,.webp" required>

      <label for="msg">Your question about the image</label>
      <textarea id="msg" name="message" required
                placeholder="e.g. Explain what this diagram shows in relation to my current topic."
      >{msg_value}</textarea>

      <button type="submit">Ask Study Buddy</button>
    </form>
    <p style="margin-top:18px;font-size:.85rem;color:#6c757d;">
      Your study context (chapter, subtopic, memory) will be loaded automatically.
      After submission, return to the OpenClaw chat — the assistant will have the answer.
    </p>
    """
    return _page("Image Question", body)


# ---------------------------------------------------------------------------
# POST /upload-image/submit   — receive image + question, run VLM, store result
# ---------------------------------------------------------------------------

@router.post("/upload-image/submit", response_class=HTMLResponse, include_in_schema=False)
async def upload_image_submit(
    request: Request,
    user_id: str = Form(...),
    message: str = Form(...),
    file: UploadFile = File(...),
):
    """Receive an image and question, invoke VLM with full study-buddy context."""

    # ── Validate file type ───────────────────────────────────────────────────
    fname = (file.filename or "").lower()
    ext = Path(fname).suffix
    if ext not in _ALLOWED_EXTS:
        body = f"""
        <p class="err">Only image files are accepted (JPG, PNG, GIF, WEBP).</p>
        <a class="back" href="/upload-image?user_id={user_id}&message={message}">← Try again</a>
        """
        return _page("Upload failed", body)

    content = await file.read()
    if not content:
        body = f"""
        <p class="err">The uploaded file is empty.</p>
        <a class="back" href="/upload-image?user_id={user_id}">← Try again</a>
        """
        return _page("Upload failed", body)

    # ── Save image to mnt/users/{user_id}/images/ ────────────────────────────
    img_dir = _SAVE_TO / "users" / user_id / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    img_path = img_dir / safe_name
    img_path.write_bytes(content)
    logger.info("[upload_image] saved %s for user %s", img_path, user_id)

    # ── Load study context ────────────────────────────────────────────────────
    chapter_name = ""
    sub_topic = ""
    study_material = ""
    list_of_quizzes = []
    buddy_name = "Ollie"
    buddy_pref = "friendly and supportive"

    try:
        # Prefer fast_store (same approach as chat.py)
        from fast_store import get_store
        ctx = get_store(_SAVE_TO).load_context(user_id, 0)
        if ctx:
            chapter_name   = ctx.get("chapter_name", "")
            sub_topic      = ctx.get("subtopic_name", "")
            study_material = ctx.get("study_material", "")
            list_of_quizzes = ctx.get("quizzes", [])
            buddy_name     = ctx.get("study_buddy_name", buddy_name)
            buddy_pref     = ctx.get("study_buddy_preference", buddy_pref)
    except Exception as _fse:
        logger.warning("[upload_image] fast_store unavailable: %s", _fse)

    # Fall back to nodes.load_user_state if fast_store had nothing
    if not chapter_name:
        try:
            from nodes import init_user_storage, load_user_state
            init_user_storage(str(_SAVE_TO), user_id)
            u = load_user_state(user_id)
            if u:
                curriculum = (u.get("curriculum") or [{}])[0]
                active_ch  = curriculum.get("active_chapter") or {}
                subs       = active_ch.get("sub_topics") or []
                sub        = subs[0] if subs else {}
                chapter_name    = getattr(active_ch, "name", active_ch.get("name", ""))
                sub_topic       = getattr(sub, "sub_topic", sub.get("sub_topic", ""))
                study_material  = getattr(sub, "study_material", sub.get("study_material", ""))
                list_of_quizzes = getattr(sub, "quizzes", sub.get("quizzes", []))
                buddy_name  = u.get("study_buddy_name", buddy_name)
                buddy_pref  = u.get("study_buddy_preference", buddy_pref)
        except Exception as _nse:
            logger.warning("[upload_image] nodes fallback failed: %s", _nse)

    # ── Load memory context ───────────────────────────────────────────────────
    memory_context = ""
    history_summary = ""
    try:
        from agent_memory import get_memory_ops
        mem_ops = get_memory_ops(user_id)
        memory_context  = mem_ops.get_memory_context(message)
        history_summary = mem_ops.get_history_summary()
    except Exception as _me:
        logger.warning("[upload_image] agent_memory unavailable: %s", _me)

    # ── Call VLM ─────────────────────────────────────────────────────────────
    try:
        from standalone_study_buddy_response_streaming import vlm_study_buddy_response
        vlm_answer = vlm_study_buddy_response(
            chapter_name    = chapter_name or "General Studies",
            sub_topic       = sub_topic or "General",
            study_material  = study_material,
            list_of_quizzes = list_of_quizzes,
            user_input      = message,
            study_buddy_name= buddy_name,
            user_preference = buddy_pref,
            uploaded_img_loc= str(img_path),
            memory_context  = memory_context,
            history_summary = history_summary,
        )
    except Exception as exc:
        logger.error("[upload_image] VLM call failed: %s", exc, exc_info=True)
        body = f"""
        <p class="err">VLM call failed: {type(exc).__name__}</p>
        <div class="msg">{exc}</div>
        <a class="back" href="/upload-image?user_id={user_id}">← Try again</a>
        """
        return _page("VLM error", body)

    # ── Store result so MCP tool can retrieve it ──────────────────────────────
    _store_result(user_id, message, vlm_answer)

    # ── Also update memory with this turn ────────────────────────────────────
    try:
        import asyncio
        from agent_memory import get_memory_ops
        asyncio.get_event_loop().run_until_complete(
            get_memory_ops(user_id).process_message(message, vlm_answer)
        )
    except Exception:
        pass  # non-fatal

    # ── Render result page ────────────────────────────────────────────────────
    body = f"""
    <p class="ok">✅ VLM response ready!</p>
    <p style="font-size:.85rem;color:#6c757d;margin-top:4px;">
      <strong>Your question:</strong> {message}
    </p>
    <div class="vlm">{vlm_answer}</div>
    <p style="margin-top:18px;font-size:.9rem;">
      Return to the OpenClaw chat — the assistant will retrieve this answer automatically.
    </p>
    <a class="back" href="/upload-image?user_id={user_id}">← Ask another question</a>
    """
    return _page("Study Buddy Answer", body)


# ---------------------------------------------------------------------------
# GET /upload-image/result   — JSON endpoint for MCP tool polling
# ---------------------------------------------------------------------------

@router.get("/upload-image/result", include_in_schema=False)
async def upload_image_result(user_id: str):
    """Return the last VLM answer for a user as JSON."""
    result = _read_result(user_id)
    if not result:
        return JSONResponse({"error": "No VLM result found for this user."}, status_code=404)
    return JSONResponse(result)
