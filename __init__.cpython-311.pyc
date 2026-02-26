"""SSE (Server-Sent Events) formatting utilities."""
import json
from typing import Any, Dict
from models.segment_types import Segment, SegmentType


def format_sse_event(segment: Segment) -> str:
    """
    Format a segment as an SSE event.
    
    Args:
        segment: Segment to format
    
    Returns:
        Formatted SSE string: "data: {...}\n\n"
    """
    data = {
        "type": segment.type.value,
        "seq": segment.seq,
        "data": segment.data,
        "final": segment.final
    }
    json_str = json.dumps(data, ensure_ascii=False)
    return f"data: {json_str}\n\n"


def create_text_chunk(message: str, seq: int = 0) -> str:
    """Create a TEXT_CHUNK SSE event."""
    segment = Segment(
        type=SegmentType.TEXT_CHUNK,
        seq=seq,
        data={"message": message},
        final=False
    )
    return format_sse_event(segment)


def create_flights_segment(flights: list, seq: int = 0, final: bool = False) -> str:
    """Create a FLIGHTS SSE event."""
    segment = Segment(
        type=SegmentType.FLIGHTS,
        seq=seq,
        data=flights,
        final=final
    )
    return format_sse_event(segment)


def create_hotels_segment(hotels: list, seq: int = 0, final: bool = False) -> str:
    """Create a HOTELS SSE event."""
    segment = Segment(
        type=SegmentType.HOTELS,
        seq=seq,
        data=hotels,
        final=final
    )
    return format_sse_event(segment)


def create_itinerary_segment(itinerary_days: list, seq: int = 0, final: bool = False) -> str:
    """Create an ITINERARY SSE event."""
    segment = Segment(
        type=SegmentType.ITINERARY,
        seq=seq,
        data={"days": itinerary_days},
        final=final
    )
    return format_sse_event(segment)


def create_summary_segment(summary: str, notes: str = "", final: bool = True) -> str:
    """Create a SUMMARY SSE event."""
    segment = Segment(
        type=SegmentType.SUMMARY,
        seq=0,
        data={"summary": summary, "notes": notes},
        final=final
    )
    return format_sse_event(segment)


def create_error_segment(message: str, agent: str = None) -> str:
    """Create an ERROR SSE event."""
    segment = Segment(
        type=SegmentType.ERROR,
        seq=0,
        data={"message": message, "agent": agent},
        final=False
    )
    return format_sse_event(segment)

