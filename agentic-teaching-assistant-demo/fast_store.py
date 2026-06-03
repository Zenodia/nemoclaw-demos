"""
fast_store.py — Text-file state store for AgenticTA.

Replaces the slow JSON load/save/Pydantic-reconstruct cycle with:
  - state.txt   : flat KEY VALUE lines for metadata + delimited blocks for study material
  - memory.txt  : append-only TURN_JSON lines + summary block

Read strategy:  scan lines and stop at first match (grep-style, no full-file parse)
Write strategy: non-blocking asyncio tasks; atomic rename via .tmp file

File format (state.txt)
-----------------------
# comment lines are ignored
META BUDDY_NAME Ollie
META BUDDY_PREFERENCE friendly and supportive
META BUDDY_PERSONA A warm, patient tutor...
META ACTIVE_CHAPTER_NAME Skills for Claude
META ACTIVE_CHAPTER_IDX 0
META ACTIVE_SUBTOPIC_IDX 0
META SUBTOPIC_COUNT 3
SUB 0 NAME Introduction to Claude
SUB 0 STATUS started
SUB 1 NAME Advanced Prompting
SUB 1 STATUS not_started
>>>MATERIAL_0_START<<<
[study material for subtopic 0]
>>>MATERIAL_0_END<<<
>>>QUIZZES_0_START<<<
[{"question": "..."}, ...]
>>>QUIZZES_0_END<<<

File format (memory.txt)
------------------------
META TURN_COUNT 5
TURN_JSON {"t":1,"ts":"2025-04-29T12:00:00","user":"...","bot":"..."}
TURN_JSON {"t":2,"ts":"2025-04-29T12:01:00","user":"...","bot":"..."}
>>>SUMMARY_START<<<
[LLM-generated summary]
>>>SUMMARY_END<<<
"""

from __future__ import annotations

import asyncio
import json
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── helpers ───────────────────────────────────────────────────────────────────

def _tag_prefix(tag: str, key: str) -> str:
    return f"{tag} {key} "


def _read_tagged_line(filepath: Path, tag: str, key: str) -> Optional[str]:
    """Return the value on the first line matching  '<TAG> <KEY> <value>'.

    Stops reading as soon as the match is found — O(position) not O(file size).
    """
    prefix = _tag_prefix(tag, key)
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(prefix):
                    return line[len(prefix):].rstrip("\n")
    except FileNotFoundError:
        pass
    return None


def _read_all_tagged(filepath: Path, tag: str) -> List[str]:
    """Collect values for every line whose tag matches.  Returns list of raw value strings."""
    prefix = f"{tag} "
    results: List[str] = []
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(prefix):
                    results.append(line[len(prefix):].rstrip("\n"))
                elif results and line.startswith(">>>"):
                    break  # entered content blocks — no more tag lines
    except FileNotFoundError:
        pass
    return results


def _read_block(filepath: Path, start_marker: str, end_marker: str) -> str:
    """Extract lines between start_marker and end_marker (exclusive), sed-style."""
    lines: List[str] = []
    inside = False
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                s = line.rstrip("\n")
                if s == start_marker:
                    inside = True
                    continue
                if s == end_marker:
                    break
                if inside:
                    lines.append(s)
    except FileNotFoundError:
        pass
    return "\n".join(lines)


def _write_atomic(filepath: Path, content: str) -> None:
    """Write content to filepath via a temp file then atomic rename."""
    tmp = filepath.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(filepath)


# ── FastStore ─────────────────────────────────────────────────────────────────

class FastStore:
    """
    Non-blocking text-file state store.

    Usage
    -----
    store = FastStore("/workspace/mnt")

    # fast context read for chat (replaces load_user_state + Pydantic reconstruction)
    ctx = store.load_context("testuser", subtopic_idx=0)

    # non-blocking write (call from async context — fire and forget)
    asyncio.create_task(store.write_state_async("testuser", user_obj_dict))

    # non-blocking memory turn append
    asyncio.create_task(store.append_turn_async("testuser", user_msg, bot_msg))
    """

    def __init__(self, base_dir: str = "/workspace/mnt"):
        self.base = Path(base_dir)

    # ── path helpers ──────────────────────────────────────────────────────────

    def _state(self, user_id: str) -> Path:
        return self.base / user_id / "state.txt"

    def _memory(self, user_id: str) -> Path:
        return self.base / user_id / "memory" / f"{user_id}_memory.txt"

    def _ensure(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    # ── state reads ───────────────────────────────────────────────────────────

    def read_meta(self, user_id: str, key: str) -> str:
        return _read_tagged_line(self._state(user_id), "META", key) or ""

    def read_subtopic_list(self, user_id: str) -> List[Dict[str, str]]:
        """Return [{name, status}, ...] for all subtopics. Single file pass."""
        filepath = self._state(user_id)
        subtopics: Dict[int, Dict[str, str]] = {}
        prefix = "SUB "
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.startswith(prefix):
                        if line.startswith(">>>"):
                            break
                        continue
                    # format: SUB <idx> <field> <value>
                    parts = line[len(prefix):].rstrip("\n").split(" ", 2)
                    if len(parts) < 3:
                        continue
                    idx, field, val = int(parts[0]), parts[1].lower(), parts[2]
                    subtopics.setdefault(idx, {})[field] = val
        except FileNotFoundError:
            pass
        return [subtopics[i] for i in sorted(subtopics)]

    def read_material(self, user_id: str, subtopic_idx: int) -> str:
        return _read_block(
            self._state(user_id),
            f">>>MATERIAL_{subtopic_idx}_START<<<",
            f">>>MATERIAL_{subtopic_idx}_END<<<",
        )

    def read_quizzes(self, user_id: str, subtopic_idx: int) -> List[dict]:
        raw = _read_block(
            self._state(user_id),
            f">>>QUIZZES_{subtopic_idx}_START<<<",
            f">>>QUIZZES_{subtopic_idx}_END<<<",
        )
        if not raw.strip():
            return []
        try:
            return json.loads(raw)
        except Exception:
            return []

    def load_context(self, user_id: str, subtopic_idx: int = 0) -> Dict[str, Any]:
        """
        Load the minimal chat context in a single-pass read per section.

        Returns a flat dict — no Pydantic reconstruction, no full JSON parse.
        Returns {} if no state.txt exists (user hasn't generated curriculum yet).
        """
        f = self._state(user_id)
        if not f.exists():
            return {}

        # One pass: collect all META and SUB lines, stop at first block marker
        meta: Dict[str, str] = {}
        subtopics: Dict[int, Dict[str, str]] = {}
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if line.startswith("META "):
                        parts = line[5:].split(" ", 1)
                        if len(parts) == 2:
                            meta[parts[0]] = parts[1]
                    elif line.startswith("SUB "):
                        parts = line[4:].split(" ", 2)
                        if len(parts) == 3:
                            idx, field, val = int(parts[0]), parts[1].lower(), parts[2]
                            subtopics.setdefault(idx, {})[field] = val
                    elif line.startswith(">>>"):
                        break
        except FileNotFoundError:
            return {}

        if not meta:
            return {}

        sub = subtopics.get(subtopic_idx, {})

        # Lazy-load study material + quizzes only for the requested subtopic
        material = self.read_material(user_id, subtopic_idx)
        quizzes = self.read_quizzes(user_id, subtopic_idx)

        return {
            "user_id": user_id,
            "study_buddy_name": meta.get("BUDDY_NAME", ""),
            "study_buddy_preference": meta.get("BUDDY_PREFERENCE", ""),
            "study_buddy_persona": meta.get("BUDDY_PERSONA", ""),
            "chapter_name": meta.get("ACTIVE_CHAPTER_NAME", ""),
            "active_chapter_idx": int(meta.get("ACTIVE_CHAPTER_IDX", "0")),
            "active_subtopic_idx": int(meta.get("ACTIVE_SUBTOPIC_IDX", "0")),
            "subtopic_count": int(meta.get("SUBTOPIC_COUNT", "0")),
            "subtopic_name": sub.get("name", ""),
            "subtopic_status": sub.get("status", ""),
            "study_material": material,
            "quizzes": quizzes,
            "subtopics": [subtopics[i] for i in sorted(subtopics)],
        }

    # ── state writes (non-blocking) ───────────────────────────────────────────

    async def write_state_async(self, user_id: str, user_obj: Dict[str, Any]) -> None:
        """
        Serialize the user state dict to state.txt in the background.
        Called via asyncio.create_task() — does NOT block the caller.
        """
        await asyncio.get_event_loop().run_in_executor(
            None, self._write_state_sync, user_id, user_obj
        )

    def write_state_sync(self, user_id: str, user_obj: Dict[str, Any]) -> None:
        """Synchronous version for use inside non-async save_user_state hooks."""
        self._write_state_sync(user_id, user_obj)

    def _write_state_sync(self, user_id: str, user_obj: Dict[str, Any]) -> None:
        """Blocking worker — run via executor to avoid blocking the event loop."""
        f = self._state(user_id)
        self._ensure(f)

        # Extract curriculum from user_obj (may be dict or contain Pydantic models)
        curriculum_list = user_obj.get("curriculum") or []
        curriculum = curriculum_list[0] if curriculum_list else {}

        # active_chapter may be a dict or a Pydantic Chapter
        active_chapter = curriculum.get("active_chapter") if isinstance(curriculum, dict) else {}
        if hasattr(active_chapter, "dict"):
            active_chapter = active_chapter.dict()
        elif hasattr(active_chapter, "model_dump"):
            active_chapter = active_chapter.model_dump()

        chapter_name = (active_chapter or {}).get("name", "") if active_chapter else ""
        sub_topics_raw = (active_chapter or {}).get("sub_topics", []) if active_chapter else []

        # Normalise subtopics — each may be SubTopic Pydantic or plain dict
        subtopics: List[Dict[str, Any]] = []
        for st in sub_topics_raw:
            if hasattr(st, "dict"):
                subtopics.append(st.dict())
            elif hasattr(st, "model_dump"):
                subtopics.append(st.model_dump())
            elif isinstance(st, dict):
                subtopics.append(st)

        lines: List[str] = [
            f"# AgenticTA state — {user_id} — {datetime.now().isoformat()}",
            f"META BUDDY_NAME {user_obj.get('study_buddy_name', '')}",
            f"META BUDDY_PREFERENCE {user_obj.get('study_buddy_preference', '')}",
            f"META BUDDY_PERSONA {user_obj.get('study_buddy_persona', '')}",
            f"META ACTIVE_CHAPTER_NAME {chapter_name}",
            f"META ACTIVE_CHAPTER_IDX 0",
            f"META ACTIVE_SUBTOPIC_IDX 0",
            f"META SUBTOPIC_COUNT {len(subtopics)}",
        ]

        for i, st in enumerate(subtopics):
            name = st.get("sub_topic") or st.get("name", "")
            status_raw = st.get("status")
            # Status may be enum or string
            status = status_raw.value if hasattr(status_raw, "value") else str(status_raw or "not_started")
            lines.append(f"SUB {i} NAME {name}")
            lines.append(f"SUB {i} STATUS {status}")

        # Study material + quizzes as delimited blocks (one per subtopic)
        for i, st in enumerate(subtopics):
            material = st.get("display_markdown") or st.get("study_material") or ""
            quizzes = st.get("quizzes") or []
            lines.append(f">>>MATERIAL_{i}_START<<<")
            if material:
                lines.append(material)
            lines.append(f">>>MATERIAL_{i}_END<<<")
            lines.append(f">>>QUIZZES_{i}_START<<<")
            lines.append(json.dumps(quizzes, ensure_ascii=False))
            lines.append(f">>>QUIZZES_{i}_END<<<")

        _write_atomic(f, "\n".join(lines) + "\n")

    async def update_meta_async(self, user_id: str, key: str, value: str) -> None:
        """Update a single META field using sed (non-blocking subprocess)."""
        f = self._state(user_id)
        if not f.exists():
            return
        # Escape special sed chars in value
        safe_val = value.replace("\\", "\\\\").replace("/", "\\/").replace("&", "\\&")
        proc = await asyncio.create_subprocess_exec(
            "sed", "-i", f"s/^META {key} .*/META {key} {safe_val}/", str(f),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    async def update_subtopic_status_async(
        self, user_id: str, subtopic_idx: int, status: str
    ) -> None:
        """Update a single subtopic's STATUS line using sed (non-blocking)."""
        f = self._state(user_id)
        if not f.exists():
            return
        proc = await asyncio.create_subprocess_exec(
            "sed", "-i",
            f"s/^SUB {subtopic_idx} STATUS .*/SUB {subtopic_idx} STATUS {status}/",
            str(f),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    # ── memory reads ──────────────────────────────────────────────────────────

    def read_recent_turns(self, user_id: str, n: int = 10) -> List[Dict[str, Any]]:
        """Read the last N turns. Single file pass — no full-file parse."""
        f = self._memory(user_id)
        turns: List[Dict[str, Any]] = []
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("TURN_JSON "):
                        try:
                            turns.append(json.loads(line[10:].rstrip("\n")))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
        return turns[-n:]

    def read_memory_summary(self, user_id: str) -> str:
        return _read_block(self._memory(user_id), ">>>SUMMARY_START<<<", ">>>SUMMARY_END<<<")

    def search_memory(
        self, user_id: str, query: str, case_insensitive: bool = True
    ) -> List[Dict[str, Any]]:
        """grep-style search across all TURN_JSON lines."""
        f = self._memory(user_id)
        flags = re.IGNORECASE if case_insensitive else 0
        results: List[Dict[str, Any]] = []
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("TURN_JSON ") and re.search(query, line, flags):
                        try:
                            results.append(json.loads(line[10:].rstrip("\n")))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
        return results

    def build_history_string(self, user_id: str, n: int = 5) -> str:
        """Return the last N turns formatted as a conversation string for LLM context."""
        turns = self.read_recent_turns(user_id, n)
        if not turns:
            return ""
        parts = []
        for t in turns:
            parts.append(f"User: {t.get('user', '')}")
            parts.append(f"Assistant: {t.get('bot', '')}")
        return "\n".join(parts)

    # ── memory writes (non-blocking) ──────────────────────────────────────────

    async def append_turn_async(
        self, user_id: str, user_msg: str, bot_msg: str
    ) -> None:
        """
        Append a turn to memory.txt.
        File append is O(1) and fast enough to run directly in the event loop
        without a thread pool — no LLM call, just a write().
        """
        f = self._memory(user_id)
        self._ensure(f)
        turn_n = self._count_turns(user_id) + 1
        record = json.dumps(
            {
                "t": turn_n,
                "ts": datetime.now().isoformat(),
                "user": user_msg,
                "bot": bot_msg,
            },
            ensure_ascii=False,
        )
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"TURN_JSON {record}\n")

    def _count_turns(self, user_id: str) -> int:
        f = self._memory(user_id)
        count = 0
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("TURN_JSON "):
                        count += 1
        except FileNotFoundError:
            pass
        return count

    async def update_summary_async(self, user_id: str, summary: str) -> None:
        """
        Rewrite the summary block in memory.txt (background task).
        Called via asyncio.create_task() — caller does not wait.
        """
        asyncio.create_task(self._rewrite_summary(user_id, summary))

    async def _rewrite_summary(self, user_id: str, summary: str) -> None:
        f = self._memory(user_id)
        try:
            content = f.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""

        new_block = f">>>SUMMARY_START<<<\n{summary}\n>>>SUMMARY_END<<<\n"
        if ">>>SUMMARY_START<<<" in content:
            content = re.sub(
                r">>>SUMMARY_START<<<.*?>>>SUMMARY_END<<<\n",
                new_block,
                content,
                flags=re.DOTALL,
            )
        else:
            content = content.rstrip("\n") + "\n" + new_block

        await asyncio.get_event_loop().run_in_executor(
            None, _write_atomic, f, content
        )


# ── module-level singleton ─────────────────────────────────────────────────────

_DEFAULT_BASE = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt")
_store: Optional[FastStore] = None


def get_store(base_dir: Optional[str] = None) -> FastStore:
    """Return the module-level FastStore singleton."""
    global _store
    if _store is None or (base_dir and str(_store.base) != base_dir):
        _store = FastStore(base_dir or _DEFAULT_BASE)
    return _store
