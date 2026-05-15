"""
Academic planner service for weekly study planning.

The service combines user-provided schedule constraints with the existing
curriculum state, then asks the configured LLM to produce structured study
blocks. If the LLM is unavailable, it falls back to a deterministic plan so the
agent can still help the learner move forward.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    import zoneinfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    from backports import zoneinfo

from langchain_core.messages import HumanMessage, SystemMessage


@dataclass
class PlannerBlock:
    """One scheduled block in a study plan."""

    day: str
    date: str
    start_time: str
    duration_hours: float
    title: str
    focus: str
    priority: str = "medium"
    task_type: str = "study"
    source: str = "planner"
    calendar_text: str = ""
    ics_content: Optional[str] = None


@dataclass
class PlannerResult:
    """Result returned by the academic planner."""

    success: bool
    markdown: str
    blocks: List[PlannerBlock] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    curriculum_context: Dict[str, Any] = field(default_factory=dict)
    raw_plan: Dict[str, Any] = field(default_factory=dict)
    calendar_filename: Optional[str] = None
    calendar_file_path: Optional[str] = None
    calendar_download_path: Optional[str] = None
    error: Optional[str] = None


class PlannerService:
    """Create curriculum-aware academic plans."""

    def __init__(
        self,
        mnt_folder: str = "/workspace/mnt",
        timezone: str = "Europe/Paris",
    ):
        self.mnt_folder = mnt_folder
        self.timezone = timezone or "Europe/Paris"
        try:
            self._tz = zoneinfo.ZoneInfo(self.timezone)
        except Exception:
            self.timezone = "Europe/Paris"
            self._tz = zoneinfo.ZoneInfo(self.timezone)

    def create_weekly_plan(
        self,
        user_id: str,
        request: str = "Plan my week",
        course_schedule: str = "",
        assignments: Optional[List[str]] = None,
        availability: str = "",
        start_date: Optional[str] = None,
        days: int = 7,
        daily_study_limit_hours: float = 3.0,
        create_calendar_events: bool = False,
    ) -> PlannerResult:
        """Create a structured academic study plan."""
        assignments = assignments or []
        days = max(1, min(days or 7, 31))
        daily_study_limit_hours = max(0.5, min(daily_study_limit_hours or 3.0, 12.0))

        curriculum_context = self._load_curriculum_context(user_id)
        follow_up_questions = self._missing_detail_questions(
            course_schedule=course_schedule,
            assignments=assignments,
            availability=availability,
        )

        payload = {
            "user_request": request or "Plan my week",
            "course_schedule": course_schedule,
            "assignments": assignments,
            "availability": availability,
            "timezone": self.timezone,
            "start_date": start_date or self._today().isoformat(),
            "days": days,
            "daily_study_limit_hours": daily_study_limit_hours,
            "curriculum_context": curriculum_context,
            "missing_detail_questions": follow_up_questions,
        }

        try:
            raw_plan = self._plan_with_llm(payload)
            result = self._result_from_raw(raw_plan, curriculum_context, follow_up_questions)
        except Exception as exc:
            result = self._heuristic_plan(
                payload=payload,
                curriculum_context=curriculum_context,
                follow_up_questions=follow_up_questions,
                error=f"{type(exc).__name__}: {exc}",
            )

        if create_calendar_events:
            self._attach_calendar_events(result.blocks)
            self._save_combined_calendar(user_id, result)

        return result

    def _today(self):
        return datetime.now(self._tz).date()

    def _load_curriculum_context(self, user_id: str) -> Dict[str, Any]:
        """Read a compact curriculum summary for planning."""
        context: Dict[str, Any] = {
            "available": False,
            "active_chapter": None,
            "next_chapter": None,
            "topics": [],
        }

        try:
            from nodes import convert_to_json_safe, init_user_storage, load_user_state

            init_user_storage(self.mnt_folder, user_id)
            user_state = load_user_state(user_id)
            if not user_state:
                return context

            safe_user = convert_to_json_safe(user_state)
            curriculum_list = safe_user.get("curriculum") or []
            if not curriculum_list:
                return context

            curriculum = curriculum_list[0]
            context["available"] = True
            context["active_chapter"] = self._chapter_summary(curriculum.get("active_chapter"))
            context["next_chapter"] = self._chapter_summary(curriculum.get("next_chapter"))

            study_plan = curriculum.get("study_plan") or {}
            chapters = study_plan.get("study_plan") or []
            topics: List[Dict[str, Any]] = []
            for chapter in chapters[:12]:
                chapter_name = chapter.get("name", "")
                chapter_status = self._status_value(chapter.get("status"))
                subtopics = chapter.get("sub_topics") or []
                if not subtopics:
                    topics.append(
                        {
                            "chapter": chapter_name,
                            "topic": chapter_name,
                            "status": chapter_status,
                            "kind": "chapter",
                        }
                    )
                    continue

                for subtopic in subtopics[:10]:
                    topics.append(
                        {
                            "chapter": chapter_name,
                            "topic": self._clean_topic_name(subtopic.get("sub_topic", "")),
                            "status": self._status_value(subtopic.get("status")),
                            "kind": "subtopic",
                        }
                    )

            context["topics"] = topics[:40]
            return context
        except Exception as exc:
            context["error"] = f"{type(exc).__name__}: {exc}"
            return context

    def _chapter_summary(self, chapter: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not chapter:
            return None
        return {
            "name": chapter.get("name", ""),
            "number": chapter.get("number", 0),
            "status": self._status_value(chapter.get("status")),
            "subtopics": [
                {
                    "name": self._clean_topic_name(st.get("sub_topic", "")),
                    "status": self._status_value(st.get("status")),
                }
                for st in (chapter.get("sub_topics") or [])[:10]
            ],
        }

    def _status_value(self, value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value or "not_started")

    def _clean_topic_name(self, value: str) -> str:
        return value.strip().lstrip("0123456789:.- ").strip()

    def _missing_detail_questions(
        self,
        course_schedule: str,
        assignments: List[str],
        availability: str,
    ) -> List[str]:
        questions: List[str] = []
        if not course_schedule.strip():
            questions.append("What classes, labs, work shifts, or fixed commitments are on your schedule?")
        if not assignments:
            questions.append("What assignments, exams, or deadlines should I prioritize?")
        if not availability.strip():
            questions.append("When are you free to study, and how long can each study block be?")
        return questions

    def _plan_with_llm(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from llm import create_llm

        llm = create_llm("academic_planning")
        system_prompt = """You are an academic planner for a teaching assistant agent.
Create a practical study plan that balances coursework, deadlines, review, breaks, and the user's existing curriculum.

Return ONLY a JSON object with this shape:
{
  "markdown": "student-facing weekly plan in markdown",
  "assumptions": ["assumption 1"],
  "follow_up_questions": ["question if critical details are missing"],
  "blocks": [
    {
      "day": "Monday",
      "date": "YYYY-MM-DD",
      "start_time": "HH:MM",
      "duration_hours": 1.5,
      "title": "Study block title",
      "focus": "What the learner should do",
      "priority": "high|medium|low",
      "task_type": "class|assignment|study|review|quiz|break",
      "source": "assignment|curriculum|schedule|user_request",
      "calendar_text": "Natural language calendar event description"
    }
  ]
}

Rules:
- Do not invent exact deadlines or class times. If missing, put questions in follow_up_questions and state assumptions.
- Prefer active and incomplete curriculum topics before new topics.
- Keep each study block within daily_study_limit_hours.
- Include review/quiz time before deadlines or exams.
- Make the markdown concise and directly usable."""
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(payload, indent=2)),
            ]
        )
        content = response.content.strip()
        return self._extract_json(content)

    def _extract_json(self, content: str) -> Dict[str, Any]:
        if "```json" in content:
            start = content.find("```json") + len("```json")
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + len("```")
            end = content.find("```", start)
            content = content[start:end].strip()
        return json.loads(content)

    def _result_from_raw(
        self,
        raw_plan: Dict[str, Any],
        curriculum_context: Dict[str, Any],
        default_questions: List[str],
    ) -> PlannerResult:
        blocks = [self._block_from_dict(item) for item in raw_plan.get("blocks", [])]
        follow_up_questions = raw_plan.get("follow_up_questions") or default_questions
        markdown = raw_plan.get("markdown") or self._build_markdown(blocks, follow_up_questions)
        return PlannerResult(
            success=True,
            markdown=markdown,
            blocks=blocks,
            assumptions=list(raw_plan.get("assumptions") or []),
            follow_up_questions=list(follow_up_questions),
            curriculum_context=curriculum_context,
            raw_plan=raw_plan,
        )

    def _block_from_dict(self, item: Dict[str, Any]) -> PlannerBlock:
        return PlannerBlock(
            day=str(item.get("day", "")),
            date=str(item.get("date", "")),
            start_time=str(item.get("start_time", "")),
            duration_hours=float(item.get("duration_hours") or 1.0),
            title=str(item.get("title", "Study block")),
            focus=str(item.get("focus", "")),
            priority=str(item.get("priority", "medium")),
            task_type=str(item.get("task_type", "study")),
            source=str(item.get("source", "planner")),
            calendar_text=str(item.get("calendar_text", "")),
        )

    def _heuristic_plan(
        self,
        payload: Dict[str, Any],
        curriculum_context: Dict[str, Any],
        follow_up_questions: List[str],
        error: str,
    ) -> PlannerResult:
        start = self._parse_start_date(payload.get("start_date"))
        topics = [
            topic
            for topic in curriculum_context.get("topics", [])
            if topic.get("status") not in {"completed", "done"}
        ]
        assignments = payload.get("assignments") or []

        focus_items: List[Dict[str, str]] = []
        for assignment in assignments:
            focus_items.append(
                {
                    "title": "Assignment priority",
                    "focus": assignment,
                    "priority": "high",
                    "task_type": "assignment",
                    "source": "assignment",
                }
            )
        for topic in topics:
            focus_items.append(
                {
                    "title": f"Study: {topic.get('topic', 'Curriculum topic')}",
                    "focus": f"Review {topic.get('topic', 'the next topic')} from {topic.get('chapter', 'your curriculum')}.",
                    "priority": "medium",
                    "task_type": "study",
                    "source": "curriculum",
                }
            )
        if not focus_items:
            focus_items.append(
                {
                    "title": "Clarify study priorities",
                    "focus": "Share your courses, deadlines, and availability so I can build a sharper plan.",
                    "priority": "medium",
                    "task_type": "planning",
                    "source": "user_request",
                }
            )

        blocks: List[PlannerBlock] = []
        for index, item in enumerate(focus_items[: payload.get("days", 7)]):
            day = start + timedelta(days=index)
            blocks.append(
                PlannerBlock(
                    day=day.strftime("%A"),
                    date=day.isoformat(),
                    start_time="16:00",
                    duration_hours=min(float(payload.get("daily_study_limit_hours", 3.0)), 1.5),
                    title=item["title"],
                    focus=item["focus"],
                    priority=item["priority"],
                    task_type=item["task_type"],
                    source=item["source"],
                    calendar_text=f"{item['title']} on {day.isoformat()} at 16:00 for 1.5 hours",
                )
            )

        assumptions = [
            "Used a default 4:00 PM study time because exact availability was not provided.",
            "Prioritized listed assignments before curriculum review.",
        ]
        markdown = self._build_markdown(blocks, follow_up_questions)
        return PlannerResult(
            success=True,
            markdown=markdown,
            blocks=blocks,
            assumptions=assumptions,
            follow_up_questions=follow_up_questions,
            curriculum_context=curriculum_context,
            raw_plan={"fallback": True},
            error=error,
        )

    def _parse_start_date(self, value: Optional[str]):
        if value:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                pass
        return self._today()

    def _build_markdown(self, blocks: List[PlannerBlock], questions: List[str]) -> str:
        lines = ["# Weekly Study Plan", ""]
        for block in blocks:
            lines.append(
                f"- **{block.day} {block.date} at {block.start_time}** "
                f"({block.duration_hours:g}h): {block.title} - {block.focus}"
            )
        if questions:
            lines.extend(["", "## To personalize this further"])
            lines.extend(f"- {question}" for question in questions)
        return "\n".join(lines)

    def _attach_calendar_events(self, blocks: List[PlannerBlock]) -> None:
        try:
            from services.calendar_service import CalendarService

            calendar_service = CalendarService(timezone=self.timezone)
            for block in blocks:
                if not block.date or not block.start_time:
                    continue
                start_dt = calendar_service.parse_datetime(block.date, block.start_time)
                description = block.focus
                ics = calendar_service.create_calendar_event(
                    summary=block.title,
                    start_datetime=start_dt,
                    duration_hours=block.duration_hours,
                    description=description,
                    reminder_hours=1,
                )
                block.ics_content = ics.decode("utf-8")
        except Exception:
            # The plan itself is still useful if calendar generation fails.
            return

    def _save_combined_calendar(self, user_id: str, result: PlannerResult) -> None:
        """Persist one downloadable .ics file containing all planned blocks."""
        if not result.blocks:
            return

        try:
            from icalendar import Alarm, Calendar, Event

            cal = Calendar()
            cal.add("prodid", "-//AgenticTA Academic Planner//EN")
            cal.add("version", "2.0")
            cal.add("calscale", "GREGORIAN")

            for block in result.blocks:
                if not block.date or not block.start_time:
                    continue
                start_dt = self._parse_block_datetime(block)
                end_dt = start_dt + timedelta(hours=block.duration_hours)

                event = Event()
                event.add("summary", block.title)
                event.add("dtstart", start_dt)
                event.add("dtend", end_dt)
                event.add("dtstamp", datetime.now(zoneinfo.ZoneInfo("UTC")))
                event["uid"] = f"{uuid4()}@agenticta-planner"
                event.add("description", block.focus)

                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("trigger", timedelta(hours=-1))
                alarm.add("description", f"Reminder: {block.title}")
                event.add_component(alarm)
                cal.add_component(event)

            user_dir = Path(self.mnt_folder) / user_id / "calendar"
            user_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(self._tz).strftime("%Y%m%d_%H%M%S")
            filename = f"study_plan_{timestamp}.ics"
            file_path = user_dir / filename
            file_path.write_bytes(cal.to_ical())

            result.calendar_filename = filename
            result.calendar_file_path = str(file_path)
            result.calendar_download_path = f"/api/planner/calendar/{user_id}/{filename}"
        except Exception as exc:
            result.assumptions.append(f"Calendar file could not be saved: {type(exc).__name__}: {exc}")

    def _parse_block_datetime(self, block: PlannerBlock) -> datetime:
        date_value = datetime.fromisoformat(block.date)
        if block.start_time and ":" in block.start_time:
            hour, minute = map(int, block.start_time.split(":")[:2])
            date_value = date_value.replace(hour=hour, minute=minute)
        if date_value.tzinfo is None:
            date_value = date_value.replace(tzinfo=self._tz)
        return date_value

