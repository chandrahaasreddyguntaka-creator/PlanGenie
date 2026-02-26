import { Flight, Hotel, ItineraryDay } from "@/types/chat";

/**
 * Unified plan JSON format from backend
 */
export type UnifiedPlanJson = {
  flights?: Flight[] | null;
  hotels?: Hotel[] | null;
  itinerary?: { days?: ItineraryDay[] | null } | ItineraryDay[] | null;
  summary?: string | null;
  notes?: string | null;
};

/**
 * Legacy plan format (for backward compatibility)
 */
export type LegacyPlanJson = {
  flights?: Flight[] | null;
  hotels?: Hotel[] | null;
  itinerary?: ItineraryDay[] | null;
  summary?: string | null;
  notes?: string | null;
};

/**
 * Normalized UI format
 */
export type NormalizedPlanData = {
  flights: Flight[];
  hotels: Hotel[];
  itineraryDays: ItineraryDay[];
  summary: string;
  notes: string;
};

/**
 * Adapter function that normalizes unified JSON or legacy format to UI format.
 * Handles nulls, missing keys, and different itinerary structures.
 * 
 * @param plan - Either unified JSON ({ itinerary: { days: [] } }) or legacy ({ itinerary: [] })
 * @returns Normalized plan data with guaranteed arrays/strings (never null/undefined)
 */
export function mapPlanJsonToUi(plan: UnifiedPlanJson | LegacyPlanJson | null | undefined): NormalizedPlanData {
  if (!plan) {
    return {
      flights: [],
      hotels: [],
      itineraryDays: [],
      summary: "",
      notes: ""
    };
  }

  // Normalize flights - coerce to array, filter undefined
  let flights: Flight[] = [];
  if (Array.isArray(plan.flights)) {
    flights = plan.flights.filter((f): f is Flight => f != null);
  }

  // Normalize hotels - coerce to array, filter undefined
  let hotels: Hotel[] = [];
  if (Array.isArray(plan.hotels)) {
    hotels = plan.hotels.filter((h): h is Hotel => h != null);
  }

  // Normalize itinerary - handle both unified { days: [] } and legacy [] formats
  let itineraryDays: ItineraryDay[] = [];
  if (plan.itinerary) {
    // Check if it's the unified format: { days: [...] }
    if (typeof plan.itinerary === "object" && !Array.isArray(plan.itinerary) && "days" in plan.itinerary) {
      const days = plan.itinerary.days;
      if (Array.isArray(days)) {
        itineraryDays = days.filter((d): d is ItineraryDay => d != null);
      }
    }
    // Check if it's the legacy format: [...]
    else if (Array.isArray(plan.itinerary)) {
      itineraryDays = plan.itinerary.filter((d): d is ItineraryDay => d != null);
    }
  }

  // Normalize summary and notes - coerce to strings
  const summary = plan.summary != null ? String(plan.summary) : "";
  const notes = plan.notes != null ? String(plan.notes) : "";

  return {
    flights,
    hotels,
    itineraryDays,
    summary,
    notes
  };
}

