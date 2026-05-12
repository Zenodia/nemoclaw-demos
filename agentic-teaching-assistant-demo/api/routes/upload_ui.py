"""
Upload UI Route

Serves a browser-accessible HTML form so users can push a PDF from their
local machine to the host, without needing curl or API knowledge.

  GET  /upload?user_id=alice          → HTML upload form
  POST /upload/submit?user_id=alice   → accepts multipart PDF, forwards to
                                        /api/files/upload, returns result page
"""

import os
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Shared page chrome
# ---------------------------------------------------------------------------

_CSS = """
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 60px auto;
         padding: 0 24px; background: #f8f9fa; color: #212529; }
  h1   { font-size: 1.4rem; margin-bottom: 4px; }
  p.sub { color: #6c757d; font-size: .9rem; margin-top: 0; margin-bottom: 28px; }
  .card { background: #fff; border-radius: 10px; padding: 32px;
          box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  label { display: block; font-weight: 600; margin-bottom: 6px; }
  input[type=text], input[type=file] {
    width: 100%; box-sizing: border-box; padding: 10px 12px;
    border: 1px solid #ced4da; border-radius: 6px; font-size: .95rem;
    margin-bottom: 18px; }
  button { background: #0d6efd; color: #fff; border: none; border-radius: 6px;
           padding: 11px 26px; font-size: 1rem; cursor: pointer; }
  button:hover { background: #0b5ed7; }
  .ok   { color: #198754; font-weight: 600; }
  .err  { color: #dc3545; font-weight: 600; }
  .msg  { background: #e9ecef; border-radius: 6px; padding: 14px 16px;
          font-size: .88rem; white-space: pre-wrap; margin-top: 18px; }
  a.back { display: inline-block; margin-top: 22px; color: #0d6efd;
           text-decoration: none; font-size: .9rem; }
  a.back:hover { text-decoration: underline; }
"""


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>📚 AI Teaching Assistant</h1>
  <p class="sub">PDF Upload Portal</p>
  <div class="card">{body}</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# GET /upload   — render the form
# ---------------------------------------------------------------------------

@router.get("/upload", response_class=HTMLResponse, include_in_schema=False)
async def upload_form(user_id: str = ""):
    """Render the browser-accessible PDF upload form."""
    uid_value = f'value="{user_id}"' if user_id else 'placeholder="e.g. alice"'
    body = f"""
    <form method="post" action="/upload/submit" enctype="multipart/form-data">
      <label for="uid">Your User ID</label>
      <input type="text" id="uid" name="user_id" {uid_value} required>

      <label for="pdf">PDF file</label>
      <input type="file" id="pdf" name="file" accept="application/pdf" required>

      <button type="submit">Upload PDF</button>
    </form>
    <p style="margin-top:18px;font-size:.85rem;color:#6c757d;">
      The file will be saved on the host and ingested into the vector store.
      Return to the OpenClaw chat once the upload succeeds.
    </p>
    """
    return _page("Upload PDF", body)


# ---------------------------------------------------------------------------
# POST /upload/submit   — receive file, forward to TA API, render result
# ---------------------------------------------------------------------------

@router.post("/upload/submit", response_class=HTMLResponse, include_in_schema=False)
async def upload_submit(
    request: Request,
    user_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Accept a browser file upload and forward it to /api/files/upload."""
    import httpx

    # Validate file type client-side label
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        body = f"""
        <p class="err">Only PDF files are accepted.</p>
        <a class="back" href="/upload?user_id={user_id}">← Try again</a>
        """
        return _page("Upload failed", body)

    # Read uploaded bytes
    content = await file.read()
    if not content:
        body = f"""
        <p class="err">The uploaded file is empty.</p>
        <a class="back" href="/upload?user_id={user_id}">← Try again</a>
        """
        return _page("Upload failed", body)

    # Forward multipart POST to the TA upload endpoint (same process, loopback)
    base = str(request.base_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base}/api/files/upload",
                data={"user_id": user_id},
                files={"files": (file.filename, content, "application/pdf")},
            )
        result = resp.json()
        success = result.get("success", False)
        message = result.get("message", str(result))

        if success:
            body = f"""
            <p class="ok">✅ Upload successful!</p>
            <div class="msg">{message}</div>
            <p style="margin-top:18px;font-size:.9rem;">
              Return to the OpenClaw chat and tell the assistant
              <em>"I've uploaded my PDF — please generate the curriculum."</em>
            </p>
            <a class="back" href="/upload?user_id={user_id}">← Upload another file</a>
            """
        else:
            body = f"""
            <p class="err">Upload failed.</p>
            <div class="msg">{message}</div>
            <a class="back" href="/upload?user_id={user_id}">← Try again</a>
            """
    except Exception as exc:
        body = f"""
        <p class="err">Server error: {type(exc).__name__}</p>
        <div class="msg">{exc}</div>
        <a class="back" href="/upload?user_id={user_id}">← Try again</a>
        """

    return _page("Upload result", body)
