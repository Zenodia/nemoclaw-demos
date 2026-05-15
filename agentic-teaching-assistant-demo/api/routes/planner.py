"""
Planner Routes

Creates academic study plans from user goals, schedule constraints, deadlines,
and the user's generated curriculum.
"""
import os
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from api.schemas.planner import PlannerRequest, PlannerResponse
from services.planner_service import PlannerService

router = APIRouter()

SAVE_TO = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")


@router.post("/week", response_model=PlannerResponse)
async def plan_week(request: PlannerRequest):
    """Create a curriculum-aware weekly study plan."""
    planner = PlannerService(
        mnt_folder=SAVE_TO,
        timezone=request.timezone,
    )
    result = planner.create_weekly_plan(
        user_id=request.user_id,
        request=request.request,
        course_schedule=request.course_schedule,
        assignments=request.assignments,
        availability=request.availability,
        start_date=request.start_date,
        days=request.days,
        daily_study_limit_hours=request.daily_study_limit_hours,
        create_calendar_events=request.create_calendar_events,
    )
    return PlannerResponse(**asdict(result))


@router.get("/calendar/{user_id}/{filename}")
async def download_study_plan_calendar(user_id: str, filename: str):
    """Download a generated study plan calendar as an .ics file."""
    if "/" in filename or "\\" in filename or not filename.endswith(".ics"):
        raise HTTPException(status_code=400, detail="Invalid calendar filename")

    file_path = Path(SAVE_TO) / user_id / "calendar" / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Calendar file not found")

    return FileResponse(
        path=str(file_path),
        media_type="text/calendar",
        filename=filename,
    )

