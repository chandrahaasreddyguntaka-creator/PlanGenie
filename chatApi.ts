export type Role = "user" | "assistant" | "system";

export interface ToolCall {
  name: string;
  args: Record<string, any>;
  result?: any;
}

export interface Flight {
  id: string;
  airline: string;
  flightNumber: string;
  departAirport: string;
  arriveAirport: string;
  departTime: string;
  arriveTime: string;
  duration: string;
  stops: number;
  cabin: string;
  baggage?: string;
  price: number;
  currency: string;
  bookingLink?: string;
  date?: string; // Departure date (YYYY-MM-DD format)
  dateTooFarAhead?: boolean; // True if date is beyond Google Flights' 330-day limit
}

export interface Hotel {
  id: string;
  name: string;
  stars: number;
  neighborhood: string;
  refundable: boolean;
  nightlyPrice: number;
  totalPrice: number;
  currency: string;
  amenities: string[];
  images?: string[];
  bookingLink?: string;
  phone?: string;
}

export interface Activity {
  id: string;
  name: string;
  category: string;
  openingHours?: string;
  estimatedTime: string;
  ticketInfo?: string;
  mapLink?: string;
  description?: string;
}

export interface ItineraryBlock {
  time: "Morning" | "Afternoon" | "Evening";
  activities: Activity[];
  travelTime?: string;
}

export interface ItineraryDay {
  date: string;
  city: string;
  blocks: ItineraryBlock[];
}

export interface ContentBlock {
  type: "text" | "flights" | "hotels" | "itinerary" | "activities" | "error" | "info";
  text?: string;
  flights?: Flight[];
  hotels?: Hotel[];
  itinerary?: ItineraryDay[];
  activities?: Activity[];
}

export interface Message {
  id: string;
  role: Role;
  createdAt: string;
  content: ContentBlock[];
  toolCalls?: ToolCall[];
  streaming?: boolean;
}

export interface ChatThreadMeta {
  origin?: string;
  destination?: string;
  startDate?: string;
  endDate?: string;
  currency?: string;
  travelers?: number;
}

export interface ChatThread {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: Message[];
  meta?: ChatThreadMeta;
  archived?: boolean;
}

export interface UserPreferences {
  currency: string;
  units: "metric" | "imperial";
  theme: "light" | "dark" | "system";
  experimentalFlags?: Record<string, boolean>;
}
