"""Pydantic models for plan data structures."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Flight(BaseModel):
    """Flight information."""
    id: str
    airline: str
    flightNumber: str
    departAirport: str
    arriveAirport: str
    departTime: str
    arriveTime: str
    duration: str
    stops: int
    cabin: str
    baggage: Optional[str] = None
    price: float
    currency: str
    bookingLink: Optional[str] = None
    date: Optional[str] = None  # Departure date (YYYY-MM-DD format)
    dateTooFarAhead: Optional[bool] = False  # True if date is beyond Google Flights' 330-day limit


class Hotel(BaseModel):
    """Hotel information."""
    id: str
    name: str
    stars: int
    neighborhood: str
    refundable: bool
    nightlyPrice: float
    totalPrice: float
    currency: str
    amenities: List[str]
    images: Optional[List[str]] = None
    bookingLink: Optional[str] = None
    phone: Optional[str] = None


class Activity(BaseModel):
    """Activity/POI information."""
    id: str
    name: str
    category: str
    openingHours: Optional[str] = None
    estimatedTime: str
    ticketInfo: Optional[str] = None
    mapLink: Optional[str] = None
    description: Optional[str] = None


class ItineraryBlock(BaseModel):
    """Time block within a day."""
    time: str = Field(description="Morning, Afternoon, or Evening")
    activities: List[Activity]
    travelTime: Optional[str] = None


class ItineraryDay(BaseModel):
    """Single day itinerary."""
    date: str = Field(description="ISO-8601 date string")
    city: str
    blocks: List[ItineraryBlock]


class TripRequest(BaseModel):
    """Trip request parameters."""
    origin: str = ""
    destination: str = ""
    depart_date: str = ""
    return_date: Optional[str] = None
    adults: int = 1
    children: Optional[int] = 0
    budget: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None


class Meta(BaseModel):
    """Plan metadata."""
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    sources: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ErrorItem(BaseModel):
    """Error information."""
    agent: Optional[str] = None
    message: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ChatPlan(BaseModel):
    """Unified plan JSON structure (matches frontend contract)."""
    version: str = "1.0"
    request: TripRequest
    summary: str = ""
    notes: str = ""
    flights: List[Flight] = Field(default_factory=list)
    hotels: List[Hotel] = Field(default_factory=list)
    itinerary: Dict[str, List[ItineraryDay]] = Field(
        default_factory=lambda: {"days": []},
        description="Nested structure with 'days' key"
    )
    meta: Meta = Field(default_factory=Meta)
    errors: List[ErrorItem] = Field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict matching frontend contract exactly."""
        import logging
        logger = logging.getLogger(__name__)
        flights_dict = [f.model_dump() for f in self.flights]
        logger.info(f"ChatPlan.to_dict: Converting {len(self.flights)} flights to dict, result: {len(flights_dict)} items")
        if flights_dict:
            logger.info(f"Sample flight dict keys: {list(flights_dict[0].keys()) if flights_dict else 'None'}")
        return {
            "version": self.version,
            "request": self.request.model_dump(),
            "summary": self.summary,
            "notes": self.notes,
            "flights": flights_dict,
            "hotels": [h.model_dump() for h in self.hotels],
            "itinerary": {
                "days": [d.model_dump() for d in self.itinerary.get("days", [])]
            },
            "meta": self.meta.model_dump(),
            "errors": [e.model_dump() for e in self.errors]
        }

