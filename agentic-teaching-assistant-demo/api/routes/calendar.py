"""
Calendar Routes

Handles calendar event creation from natural language.
Uses calendar_assistant.py for AI-powered event parsing.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, HTTPException

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from common.debug import get_debug_logger
from api.schemas.calendar import (
    CalendarCreateRequest,
    CalendarEventResponse,
)

router = APIRouter()
logger = get_debug_logger(__name__)


def _generate_ics(title: str, date: str, time: str, description: str = "", location: str = "") -> str:
    """Generate ICS file content for a calendar event."""
    # Parse date and time (simple parsing, can be enhanced)
    now = datetime.now()
    
    # Default to tomorrow if parsing fails
    try:
        # Try to parse common date formats
        if "tomorrow" in date.lower():
            event_date = now + timedelta(days=1)
        elif "today" in date.lower():
            event_date = now
        else:
            # Try to parse as a date
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"]:
                try:
                    event_date = datetime.strptime(date, fmt)
                    break
                except ValueError:
                    continue
            else:
                event_date = now + timedelta(days=1)
    except Exception:
        event_date = now + timedelta(days=1)
    
    # Parse time
    try:
        if time:
            # Handle various time formats
            time_clean = time.upper().replace(".", "").strip()
            for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M", "%I %p", "%I%p"]:
                try:
                    parsed_time = datetime.strptime(time_clean, fmt)
                    event_date = event_date.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute,
                        second=0
                    )
                    break
                except ValueError:
                    continue
            else:
                event_date = event_date.replace(hour=14, minute=0, second=0)
        else:
            event_date = event_date.replace(hour=14, minute=0, second=0)
    except Exception:
        event_date = event_date.replace(hour=14, minute=0, second=0)
    
    # Calculate end time (1 hour after start)
    end_date = event_date + timedelta(hours=1)
    
    # Format dates for ICS
    def format_ics_date(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%S")
    
    uid = f"{uuid.uuid4()}@studyassistant"
    
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//AgenticTA Study Assistant//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{format_ics_date(now)}
DTSTART:{format_ics_date(event_date)}
DTEND:{format_ics_date(end_date)}
SUMMARY:{title}
DESCRIPTION:{description}
LOCATION:{location}
END:VEVENT
END:VCALENDAR"""
    
    return ics_content


@router.post("/create", response_model=CalendarEventResponse)
async def create_calendar_event(request: CalendarCreateRequest):
    """
    Create a calendar event from natural language description.
    
    This uses AI to parse the description and extract:
    - Event title
    - Date and time
    - Location (if mentioned)
    - Description
    
    Args:
        request: CalendarCreateRequest with user_id and description
        
    Returns:
        CalendarEventResponse with parsed event and ICS content
    """
    try:
        # Try to use backend calendar service with user's timezone
        from services.calendar_service import CalendarService
        
        # Validate and use timezone if provided
        timezone = None
        if request.timezone:
            try:
                import zoneinfo
                zoneinfo.ZoneInfo(request.timezone)
                timezone = request.timezone
            except Exception:
                logger.warning("Invalid timezone '%s', using default", request.timezone)
        
        calendar_service = CalendarService(timezone=timezone) if timezone else CalendarService()
        result = calendar_service.create_event_from_description(request.description)
        
        if result.success and result.event_data:
            ed = result.event_data
            
            # Read ICS content from file if available
            ics_content = None
            if result.file_path:
                try:
                    with open(result.file_path, 'r') as f:
                        ics_content = f.read()
                except Exception:
                    pass
            
            # Fallback to generating ICS if not available
            if not ics_content:
                ics_content = _generate_ics(
                    title=ed.summary,
                    date=ed.start_date,
                    time=ed.start_time,
                    description=ed.description or request.description,
                    location=ed.location or "",
                )
            
            return CalendarEventResponse(
                success=True,
                id=str(uuid.uuid4()),
                title=ed.summary,
                date=ed.start_date,
                time=ed.start_time,
                location=ed.location,
                description=ed.description or request.description,
                ics_content=ics_content,
                raw_data=str(result),
                message="Event created successfully",
            )
        else:
            raise ValueError(result.status_message or "Failed to parse event")
            
    except ImportError:
        # Backend not available - use simple parsing
        pass
    except Exception:
        logger.exception("Calendar AI error")
    
    # Fallback: Simple keyword-based parsing
    desc_lower = request.description.lower()
    
    # Extract title
    if "exam" in desc_lower:
        title = "Exam"
        # Try to extract subject
        words = request.description.split()
        for i, word in enumerate(words):
            if word.lower() == "exam" and i > 0:
                title = f"{words[i-1]} Exam"
                break
    elif "study" in desc_lower:
        title = "Study Session"
    elif "meeting" in desc_lower:
        title = "Meeting"
    elif "review" in desc_lower:
        title = "Review Session"
    else:
        title = "Event"
    
    # Extract date
    if "tomorrow" in desc_lower:
        date = "Tomorrow"
    elif "today" in desc_lower:
        date = "Today"
    elif "next week" in desc_lower:
        date = "Next Week"
    else:
        date = "Tomorrow"  # Default
    
    # Extract time
    time = "2:00 PM"  # Default
    time_keywords = ["morning", "afternoon", "evening", "night"]
    if "morning" in desc_lower:
        time = "9:00 AM"
    elif "afternoon" in desc_lower:
        time = "2:00 PM"
    elif "evening" in desc_lower:
        time = "6:00 PM"
    elif "night" in desc_lower:
        time = "8:00 PM"
    
    # Check for specific times like "at 3pm"
    import re
    time_match = re.search(r'at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)', desc_lower)
    if time_match:
        time = time_match.group(1).upper()
        if ":" not in time and not time.endswith("M"):
            time = time + ":00 PM"
        elif not time.endswith("M"):
            time = time + " PM"
    
    # Extract location
    location = None
    if "library" in desc_lower:
        location = "Library"
    elif "room" in desc_lower:
        location_match = re.search(r'room\s+(\w+)', desc_lower)
        if location_match:
            location = f"Room {location_match.group(1)}"
    elif "home" in desc_lower:
        location = "Home"
    elif "online" in desc_lower or "virtual" in desc_lower:
        location = "Online"
    
    # Generate ICS
    ics_content = _generate_ics(
        title=title,
        date=date,
        time=time,
        description=request.description,
        location=location or "",
    )
    
    return CalendarEventResponse(
        success=True,
        id=str(uuid.uuid4()),
        title=title,
        date=date,
        time=time,
        location=location,
        description=request.description,
        ics_content=ics_content,
        raw_data=None,
        message="Event created using simple parsing",
    )

