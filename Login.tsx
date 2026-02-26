import { useState, useCallback } from "react";
import { Flight, Hotel, ItineraryDay } from "@/types/chat";
import { mapPlanJsonToUi, NormalizedPlanData } from "@/lib/planAdapter";

export type PlanStoreState = {
  flights: Flight[];
  hotels: Hotel[];
  itineraryDays: ItineraryDay[];
  summary: string;
  notes: string;
  streamingText: string; // Accumulated text chunks during streaming
};

const initialState: PlanStoreState = {
  flights: [],
  hotels: [],
  itineraryDays: [],
  summary: "",
  notes: "",
  streamingText: ""
};

/**
 * Custom hook for managing plan data state with helper functions
 */
export function usePlanStore() {
  const [state, setState] = useState<PlanStoreState>(initialState);

  const setFlights = useCallback((flights: Flight[]) => {
    setState(prev => ({ ...prev, flights }));
  }, []);

  const setHotels = useCallback((hotels: Hotel[]) => {
    setState(prev => ({ ...prev, hotels }));
  }, []);

  const setItineraryDays = useCallback((itineraryDays: ItineraryDay[]) => {
    setState(prev => ({ ...prev, itineraryDays }));
  }, []);

  const setSummary = useCallback((summary: string) => {
    setState(prev => ({ ...prev, summary }));
  }, []);

  const setNotes = useCallback((notes: string) => {
    setState(prev => ({ ...prev, notes }));
  }, []);

  const appendTextChunk = useCallback((chunk: string) => {
    setState(prev => ({ ...prev, streamingText: prev.streamingText + chunk }));
  }, []);

  const resetPlan = useCallback(() => {
    setState(initialState);
  }, []);

  /**
   * Hydrate all plan data from a unified JSON object (non-streaming fallback)
   */
  const hydratePlan = useCallback((plan: Parameters<typeof mapPlanJsonToUi>[0]) => {
    const normalized = mapPlanJsonToUi(plan);
    setState(prev => ({
      ...prev,
      ...normalized
    }));
  }, []);

  return {
    ...state,
    setFlights,
    setHotels,
    setItineraryDays,
    setSummary,
    setNotes,
    appendTextChunk,
    resetPlan,
    hydratePlan
  };
}

