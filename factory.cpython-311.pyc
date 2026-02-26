"""SSE segment types and models for streaming responses."""
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class SegmentType(str, Enum):
    """SSE event segment types."""
    TEXT_CHUNK = "TEXT_CHUNK"
    FLIGHTS = "FLIGHTS"
    HOTELS = "HOTELS"
    ITINERARY = "ITINERARY"
    SUMMARY = "SUMMARY"
    ERROR = "ERROR"
    DONE = "DONE"


class Segment(BaseModel):
    """SSE segment wrapper."""
    type: SegmentType
    seq: int = Field(default=0, description="Sequence number for multi-part segments")
    data: Any = Field(description="Segment payload")
    final: bool = Field(default=False, description="True if this is the final segment")

    class Config:
        json_schema_extra = {
            "example": {
                "type": "FLIGHTS",
                "seq": 0,
                "data": [],
                "final": False
            }
        }


class TextChunkData(BaseModel):
    """Text chunk data for shimmer messages."""
    message: str


class SummaryData(BaseModel):
    """Summary segment data."""
    summary: str
    notes: Optional[str] = None

