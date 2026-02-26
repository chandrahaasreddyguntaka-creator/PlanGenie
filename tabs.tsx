# Plan Stream API Reference

## Overview

The plan stream system provides an adapter and SSE pipeline for consuming unified JSON plan data in the Plan Mode UI.

## Components

### 1. Adapter: `mapPlanJsonToUi(plan)`

Normalizes unified JSON or legacy format to UI format.

**Location:** `src/lib/planAdapter.ts`

**Signature:**
```typescript
function mapPlanJsonToUi(
  plan: UnifiedPlanJson | LegacyPlanJson | null | undefined
): NormalizedPlanData
```

**Input formats:**
- Unified: `{ flights: [], hotels: [], itinerary: { days: [] }, summary: "", notes: "" }`
- Legacy: `{ flights: [], hotels: [], itinerary: [], summary: "", notes: "" }`

**Output:**
```typescript
{
  flights: Flight[];
  hotels: Hotel[];
  itineraryDays: ItineraryDay[];  // Note: unwrapped from itinerary.days
  summary: string;
  notes: string;
}
```

**Example:**
```typescript
import { mapPlanJsonToUi } from "@/lib/planAdapter";

const unified = {
  flights: [...],
  hotels: [...],
  itinerary: { days: [...] },
  summary: "Great trip!",
  notes: "Bring sunscreen"
};

const normalized = mapPlanJsonToUi(unified);
// normalized.itineraryDays contains the unwrapped days array
```

### 2. Plan Store Hook: `usePlanStore()`

Manages plan data state with helper functions.

**Location:** `src/hooks/usePlanStore.ts`

**Returns:**
```typescript
{
  // State
  flights: Flight[];
  hotels: Hotel[];
  itineraryDays: ItineraryDay[];
  summary: string;
  notes: string;
  streamingText: string;
  
  // Setters
  setFlights(flights: Flight[]): void;
  setHotels(hotels: Hotel[]): void;
  setItineraryDays(days: ItineraryDay[]): void;
  setSummary(text: string): void;
  setNotes(text: string): void;
  appendTextChunk(chunk: string): void;
  resetPlan(): void;
  hydratePlan(plan: UnifiedPlanJson): void;
}
```

**Example:**
```typescript
import { usePlanStore } from "@/hooks/usePlanStore";

function MyComponent() {
  const planStore = usePlanStore();
  
  // Update flights
  planStore.setFlights([...]);
  
  // Reset all data
  planStore.resetPlan();
  
  // Hydrate from unified JSON
  planStore.hydratePlan(unifiedPlanJson);
}
```

### 3. SSE Handler: `openPlanStream(options)`

Opens a Server-Sent Events stream for plan generation.

**Location:** `src/lib/planStream.ts`

**Signature:**
```typescript
function openPlanStream(options: PlanStreamOptions): () => void
```

**Options:**
```typescript
{
  threadId: string;
  message: string;
  callbacks: {
    onTextChunk?: (chunk: string) => void;
    onFlights?: (flights: Flight[]) => void;
    onHotels?: (hotels: Hotel[]) => void;
    onItinerary?: (itineraryDays: ItineraryDay[]) => void;
    onSummary?: (summary: string) => void;
    onError?: (error: Error) => void;
    onOpen?: () => void;
    onClose?: () => void;
    onFinal?: () => void;
  };
  apiBaseUrl?: string;  // Default: "/api"
}
```

**Returns:** Cleanup function to close the stream

**SSE Event Types:**
- `TEXT_CHUNK` → `onTextChunk(data.message)`
- `FLIGHTS` → `onFlights(normalized.flights)`
- `HOTELS` → `onHotels(normalized.hotels)`
- `ITINERARY` → `onItinerary(normalized.itineraryDays)`
- `SUMMARY` → `onSummary(data.summary)` + closes if `final: true`
- `ERROR` → `onError(new Error(data.message))`
- `DONE` → `onFinal()` + closes stream

**Example:**
```typescript
import { openPlanStream } from "@/lib/planStream";

const cleanup = openPlanStream({
  threadId: "thread-123",
  message: "Plan a trip to Paris",
  callbacks: {
    onFlights: (flights) => {
      planStore.setFlights(flights);
    },
    onHotels: (hotels) => {
      planStore.setHotels(hotels);
    },
    onItinerary: (days) => {
      planStore.setItineraryDays(days);
    },
    onSummary: (summary) => {
      planStore.setSummary(summary);
    },
    onError: (error) => {
      console.error("Stream error:", error);
    },
    onFinal: () => {
      console.log("Stream complete");
    }
  }
});

// Later, to close:
cleanup();
```

### 4. Non-Streaming Fallback: `fetchPlan(threadId, callbacks, apiBaseUrl)`

Fetches complete plan data from backend (non-streaming).

**Location:** `src/lib/planStream.ts`

**Signature:**
```typescript
async function fetchPlan(
  threadId: string,
  callbacks: Pick<PlanStreamCallbacks, "onFlights" | "onHotels" | "onItinerary" | "onSummary" | "onError">,
  apiBaseUrl?: string
): Promise<void>
```

**Example:**
```typescript
import { fetchPlan } from "@/lib/planStream";

await fetchPlan("thread-123", {
  onFlights: planStore.setFlights,
  onHotels: planStore.setHotels,
  onItinerary: planStore.setItineraryDays,
  onSummary: planStore.setSummary,
  onError: (error) => console.error(error)
});
```

## Backend API Requirements

### POST `/api/chat/message/stream`
Initiates a stream session.

**Request:**
```json
{
  "threadId": "thread-123",
  "message": "Plan a trip to Paris"
}
```

**Response:**
```json
{
  "streamId": "stream-456"
}
```

### GET `/api/chat/{threadId}/stream?streamId={streamId}`
SSE endpoint that streams events.

**Event Format:**
```
data: {"type":"FLIGHTS","data":[...],"final":false}

data: {"type":"HOTELS","data":[...],"final":false}

data: {"type":"ITINERARY","data":{"days":[...]},"final":false}

data: {"type":"SUMMARY","data":{"summary":"..."},"final":true}
```

### GET `/api/chat/{threadId}/plan`
Non-streaming endpoint that returns complete plan.

**Response:**
```json
{
  "flights": [...],
  "hotels": [...],
  "itinerary": {
    "days": [...]
  },
  "summary": "...",
  "notes": "..."
}
```

## Integration in Chat.tsx

The `Chat.tsx` component integrates all components:

1. Uses `usePlanStore()` for state management
2. Calls `openPlanStream()` when user sends a message
3. Updates store via callbacks as events arrive
4. Falls back to `fetchPlan()` on thread load
5. Passes `planStore.itineraryDays` to `TripPlanSidebar`

## Empty Placeholders

Empty placeholders are handled in `TripPlanSidebar.tsx`:
- Shows skeleton loaders when `isLoading && array.length === 0`
- Shows empty state when `!isLoading && array.length === 0`
- Renders cards when `array.length > 0`

