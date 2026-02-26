import { mapPlanJsonToUi } from "./planAdapter";
import { Flight, Hotel, ItineraryDay } from "@/types/chat";
import { getCurrentUserId } from "./authApi";

export type SSEEventType = "TEXT_CHUNK" | "FLIGHTS" | "HOTELS" | "ITINERARY" | "SUMMARY" | "ERROR" | "DONE";

export interface SSEEvent {
  type: SSEEventType;
  data: any;
  final?: boolean;
}

export interface PlanStreamCallbacks {
  onTextChunk?: (chunk: string) => void;
  onFlights?: (flights: Flight[]) => void;
  onHotels?: (hotels: Hotel[]) => void;
  onItinerary?: (itineraryDays: ItineraryDay[]) => void;
  onSummary?: (summary: string) => void;
  onError?: (error: Error) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onFinal?: () => void;
}

export interface PlanStreamOptions {
  threadId: string;
  message: string;
  callbacks: PlanStreamCallbacks;
  apiBaseUrl?: string;
}

// Get API base URL from environment or use default
const getApiBaseUrl = (): string => {
  // In production, use VITE_API_URL if set, otherwise use /api (which will be proxied or served from same origin)
  return import.meta.env.VITE_API_URL || "/api";
};

/**
 * Opens a Server-Sent Events stream for plan generation
 * 
 * @param options - Stream configuration
 * @returns Cleanup function to close the stream
 */
export function openPlanStream(options: PlanStreamOptions): () => void {
  const {
    threadId,
    message,
    callbacks,
    apiBaseUrl = getApiBaseUrl()
  } = options;

  const {
    onTextChunk,
    onFlights,
    onHotels,
    onItinerary,
    onSummary,
    onError,
    onOpen,
    onClose,
    onFinal
  } = callbacks;

  let eventSource: EventSource | null = null;
  let retryCount = 0;
  const maxRetries = 3;
  const baseBackoff = 1000; // 1 second
  let isStopped = false; // Flag to track if stream was stopped
  let isCleaningUp = false; // Flag to prevent multiple cleanup calls

  const cleanup = () => {
    if (isCleaningUp) {
      console.log("[SSE] Cleanup already in progress, skipping");
      return;
    }
    console.log("[SSE] Starting cleanup...");
    isCleaningUp = true;
    isStopped = true; // Mark as stopped to prevent callbacks
    if (eventSource) {
      console.log("[SSE] Closing EventSource connection");
      eventSource.close();
      eventSource = null;
    }
    if (onClose) {
      onClose();
    }
    console.log("[SSE] Cleanup complete");
  };

  const connect = async () => {
    try {
      // Get user ID for chat association
      const userId = getCurrentUserId();
      
      // POST to initiate the stream and get stream token/ID
      const response = await fetch(`${apiBaseUrl}/chat/message/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          threadId,
          message,
          ...(userId && { userId }) // Include userId if available
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Get the stream ID/token from response
      const result = await response.json();
      const streamId = result.streamId || result.id || threadId;
      
      // Construct stream URL - backend should handle GET with query params or path param
      // Option 1: Query params
      const streamUrl = `${apiBaseUrl}/chat/${threadId}/stream?streamId=${encodeURIComponent(streamId)}`;
      
      // Alternative: If backend uses path param
      // const streamUrl = `${apiBaseUrl}/chat/${threadId}/stream/${streamId}`;

      // Open EventSource connection (GET request)
      eventSource = new EventSource(streamUrl);

      eventSource.onopen = () => {
        console.log("[SSE] Connection opened successfully");
        console.log("[SSE] Stream state: isStopped=", isStopped, "isCleaningUp=", isCleaningUp);
        retryCount = 0; // Reset retry count on successful connection
        // Reset cleanup flags when connection opens (in case of reconnection)
        isCleaningUp = false;
        isStopped = false;
        if (onOpen) {
          onOpen();
        }
      };

      eventSource.onmessage = (event) => {
        // Don't process events if we're cleaning up
        if (isCleaningUp) {
          console.log("[SSE] Event received but cleanup in progress, ignoring");
          return;
        }
        
        console.log("[SSE] Raw event received:", {
          hasData: !!event.data,
          dataLength: event.data?.length || 0,
          dataPreview: event.data?.substring(0, 100) || "no data",
          eventType: event.type || "message"
        });
        
        try {
          // EventSource automatically strips "data: " prefix, so event.data should be pure JSON
          let data = event.data;
          
          // Skip empty events or keepalive comments
          if (!data || typeof data !== 'string' || data.trim().length === 0) {
            console.log("[SSE] Skipping empty event");
            return;
          }
          
          // Skip SSE comment lines (keepalive messages start with ":")
          if (data.trim().startsWith(':')) {
            // This is a keepalive comment, ignore it
            console.log("[SSE] Skipping keepalive comment");
            return;
          }
          
          // Handle case where "data: " prefix might still be present (defensive)
          if (data.startsWith('data: ')) {
            data = data.substring(6).trim();
          }
          
          // Skip if still empty after trimming
          if (!data || data.length === 0) {
            console.log("[SSE] Skipping empty data after trimming");
            return;
          }
          
          // Try to parse as JSON - skip if it's not valid JSON
          let parsed: SSEEvent;
          try {
            parsed = JSON.parse(data);
            console.log("[SSE] Successfully parsed JSON event:", {
              type: parsed.type,
              hasData: !!parsed.data,
              dataType: typeof parsed.data,
              isArray: Array.isArray(parsed.data),
              dataLength: Array.isArray(parsed.data) ? parsed.data.length : "not an array"
            });
          } catch (jsonError) {
            // If it's not valid JSON, it might be a keepalive or other non-data event
            // Log for debugging but don't throw error
            console.warn("[SSE] Failed to parse JSON, skipping event:", {
              error: jsonError,
              dataPreview: data.substring(0, 100)
            });
            return;
          }

          // Check again if cleaning up after parsing (in case cleanup was triggered during parsing)
          if (isCleaningUp) {
            return;
          }

          switch (parsed.type) {
            case "TEXT_CHUNK":
              if (onTextChunk && !isCleaningUp) {
                // Handle both { message: "..." } and direct string formats
                let textChunk: string;
                if (parsed.data?.message !== undefined) {
                  textChunk = typeof parsed.data.message === "string" 
                    ? parsed.data.message 
                    : JSON.stringify(parsed.data.message);
                } else if (typeof parsed.data === "string") {
                  textChunk = parsed.data;
                } else {
                  // Fallback: try to stringify the data
                  textChunk = JSON.stringify(parsed.data || "");
                }
                onTextChunk(textChunk);
              }
              break;

            case "FLIGHTS":
              if (!isCleaningUp) {
                console.log("[SSE] FLIGHTS event received:", parsed);
                console.log("[SSE] Flights data type:", typeof parsed.data, Array.isArray(parsed.data));
                console.log("[SSE] Flights length:", Array.isArray(parsed.data) ? parsed.data.length : "not an array");
                if (onFlights) {
                  // Normalize the data - it might be just the flights array or a partial plan object
                  const normalized = mapPlanJsonToUi({ flights: parsed.data });
                  console.log("[SSE] Normalized flights:", normalized.flights);
                  console.log("[SSE] Normalized flights length:", normalized.flights.length);
                  onFlights(normalized.flights);
                } else {
                  console.warn("[SSE] onFlights callback not provided");
                }
              }
              break;

            case "HOTELS":
              if (!isCleaningUp) {
                console.log("[SSE] HOTELS event received:", parsed);
                console.log("[SSE] Hotels data type:", typeof parsed.data, Array.isArray(parsed.data));
                console.log("[SSE] Hotels length:", Array.isArray(parsed.data) ? parsed.data.length : "not an array");
                if (onHotels) {
                  const normalized = mapPlanJsonToUi({ hotels: parsed.data });
                  console.log("[SSE] Normalized hotels:", normalized.hotels);
                  console.log("[SSE] Normalized hotels length:", normalized.hotels.length);
                  onHotels(normalized.hotels);
                } else {
                  console.warn("[SSE] onHotels callback not provided");
                }
              }
              break;

            case "ITINERARY":
              if (!isCleaningUp) {
                console.log("[SSE] ITINERARY event received:", parsed);
                console.log("[SSE] Itinerary data type:", typeof parsed.data, Array.isArray(parsed.data));
                if (onItinerary) {
                  // Handle both { days: [] } and [] formats
                  const normalized = mapPlanJsonToUi({ itinerary: parsed.data });
                  console.log("[SSE] Normalized itinerary days:", normalized.itineraryDays);
                  console.log("[SSE] Normalized itinerary days length:", normalized.itineraryDays.length);
                  onItinerary(normalized.itineraryDays);
                } else {
                  console.warn("[SSE] onItinerary callback not provided");
                }
              }
              break;

            case "SUMMARY":
              if (!isCleaningUp) {
                if (onSummary) {
                  const summary = parsed.data?.summary || parsed.data || "";
                  onSummary(String(summary));
                }
                if (parsed.final === true) {
                  console.log("[SSE] SUMMARY with final=true received, finalizing stream");
                  if (onFinal) {
                    onFinal();
                  }
                  // Cleanup after calling onFinal to ensure callbacks can still run
                  setTimeout(() => {
                    cleanup();
                  }, 100);
                }
              }
              break;

            case "ERROR":
              if (!isCleaningUp) {
                const errorMsg = parsed.data?.message || parsed.data || "Unknown error";
                const error = new Error(String(errorMsg));
                if (onError) {
                  onError(error);
                }
              }
              break;

            case "DONE":
              console.log("[SSE] DONE event received, finalizing stream");
              if (onFinal && !isCleaningUp) {
                onFinal();
              }
              // Cleanup after calling onFinal to ensure callbacks can still run
              setTimeout(() => {
                cleanup();
              }, 100);
              break;

            default:
              console.warn("Unknown SSE event type:", parsed.type);
          }
        } catch (parseError) {
          // Don't handle parse errors if we're cleaning up
          if (isCleaningUp) {
            return;
          }
          console.error("Failed to parse SSE event:", parseError);
          if (onError) {
            onError(parseError instanceof Error ? parseError : new Error("Parse error"));
          }
        }
      };

      eventSource.onerror = (error) => {
        // Don't handle errors if we're cleaning up
        if (isCleaningUp) {
          return;
        }
        
        console.error("[SSE] Connection error:", {
          error,
          readyState: eventSource?.readyState,
          url: streamUrl
        });
        
        // EventSource will auto-retry, but we implement our own backoff
        if (eventSource?.readyState === EventSource.CLOSED) {
          retryCount++;
          if (retryCount < maxRetries && !isCleaningUp) {
            const backoff = baseBackoff * Math.pow(2, retryCount - 1);
            setTimeout(() => {
              if (retryCount < maxRetries && !isCleaningUp) {
                connect();
              } else if (!isCleaningUp) {
                cleanup();
                if (onError) {
                  onError(new Error("Max retries exceeded"));
                }
              }
            }, backoff);
          } else if (!isCleaningUp) {
            cleanup();
            if (onError) {
              onError(new Error("Connection failed after retries"));
            }
          }
        }
      };

    } catch (error) {
      console.error("Failed to open plan stream:", error);
      cleanup();
      if (onError) {
        onError(error instanceof Error ? error : new Error("Failed to open stream"));
      }
    }
  };

  // Start connection
  connect();

  // Return cleanup function
  return cleanup;
}

/**
 * Non-streaming fallback: fetch complete plan and hydrate all sections
 */
export async function fetchPlan(
  threadId: string,
  callbacks: Pick<PlanStreamCallbacks, "onFlights" | "onHotels" | "onItinerary" | "onSummary" | "onError">,
  apiBaseUrl = getApiBaseUrl()
): Promise<void> {
  try {
    const response = await fetch(`${apiBaseUrl}/chat/${threadId}/plan`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json"
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const plan = await response.json();
    const normalized = mapPlanJsonToUi(plan);

    // Hydrate all sections
    if (callbacks.onFlights) {
      callbacks.onFlights(normalized.flights);
    }
    if (callbacks.onHotels) {
      callbacks.onHotels(normalized.hotels);
    }
    if (callbacks.onItinerary) {
      callbacks.onItinerary(normalized.itineraryDays);
    }
    if (callbacks.onSummary) {
      callbacks.onSummary(normalized.summary);
    }
  } catch (error) {
    console.error("Failed to fetch plan:", error);
    if (callbacks.onError) {
      callbacks.onError(error instanceof Error ? error : new Error("Failed to fetch plan"));
    }
    throw error;
  }
}

