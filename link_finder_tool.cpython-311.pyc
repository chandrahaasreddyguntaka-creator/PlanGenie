"""Flight search agent using Ollama and SerpAPI."""
import json
import logging
import re
from typing import Dict, Any, List, Optional
from models.plan import Flight, TripRequest
# --- MODIFIED --- Make sure this path is correct for your project
from tools.link_finder_tool import search_flights 
from llm.ollama_wrapper import call_ollama
from langchain.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


async def _convert_city_to_airport_code(city_name: str) -> Optional[str]:
    """
    Convert city name to airport code using Ollama LLM.
    (This function is unchanged, it works well)
    """
    if re.match(r'^[A-Z]{3}$', city_name.upper()):
        logger.info(f"{city_name} is already an airport code")
        return city_name.upper()
    
    try:
        logger.info(f"Converting city '{city_name}' to airport code using Ollama LLM")
        
        async def create_llm_call(llm):
            prompt = ChatPromptTemplate.from_messages([
                ("system", "Return only 3-letter IATA airport code in uppercase. Examples: San Diego->SAN, Mumbai->BOM, London->LHR"),
                ("human", f"{city_name}")
            ])
            chain = prompt | llm
            return await chain.ainvoke({})
        
        response = await call_ollama("FLIGHTS", create_llm_call)
        
        code = response.content.strip().upper()
        code_match = re.search(r'\b([A-Z]{3})\b', code)
        if code_match:
            code = code_match.group(1)
        
        if re.match(r'^[A-Z]{3}$', code):
            logger.info(f"Converted '{city_name}' to airport code via Ollama: {code}")
            return code
        else:
            logger.warning(f"Ollama returned invalid airport code format: '{code}' for city '{city_name}'")
            return None
            
    except Exception as e:
        logger.error(f"Error converting city '{city_name}' to airport code: {e}")
        return None


async def search_flights_agent(intent: TripRequest) -> Dict[str, Any]:
    """
    Search for flights using SerpAPI.
    (This function is now modified to read the status dictionary)
    """
    try:
        logger.info(f"=== FLIGHT AGENT START ===")
        logger.info(f"Flight agent called: {intent.origin} -> {intent.destination} on {intent.depart_date}")
        
        import os
        if not os.getenv("SERPAPI_API_KEY"):
             logger.error("❌ SERPAPI_API_KEY not set! Cannot search flights.")
             # No need to check again, the tool will handle it and return an error
        
        origin_code = None
        if intent.origin and intent.origin.strip():
            origin_code = await _convert_city_to_airport_code(intent.origin)
            if not origin_code:
                 logger.warning(f"⚠️ Failed to convert origin '{intent.origin}' to airport code.")
        
        destination_code = None
        if intent.destination and intent.destination.strip():
            destination_code = await _convert_city_to_airport_code(intent.destination)
        
        flights = []
        agent_reasoning = "" # --- NEW --- To store the reason for failure or success

        if not destination_code:
            logger.error(f"❌ Cannot search flights: missing destination airport code. Destination: {intent.destination}")
            agent_reasoning = f"Could not find an airport code for the destination '{intent.destination}'."
        elif not origin_code:
            logger.info(f"ℹ️ Destination code found ({destination_code}) but origin not specified - creating fallback flight")
            agent_reasoning = "Please specify an origin city or airport to search for flights."
        else:
            logger.info(f"✅ Using airport codes: {origin_code} -> {destination_code}")
            logger.info(f"🔍 Searching SerpAPI for flights: {origin_code} -> {destination_code} on {intent.depart_date}")
            
            # --- MODIFIED --- This is the main logic change
            
            # 1. Call the tool, which now returns a dictionary
            search_result = search_flights(
                origin=origin_code,
                destination=destination_code,
                depart_date=intent.depart_date,
                return_date=intent.return_date,
                adults=intent.adults
            )
            
            # 2. Check the status from the tool
            if search_result["status"] == "success":
                flights = search_result["data"]
                agent_reasoning = f"Found {len(flights)} flight options. Showing top results."
                logger.info(f"✅ SerpAPI returned {len(flights)} flights")
                
            elif search_result["status"] == "no_results":
                agent_reasoning = f"No flights were found for that route or date. Reason: {search_result['message']}"
                logger.warning(f"⚠️ SerpAPI returned 0 flights. Reason: {search_result['message']}")
                
            elif search_result["status"] == "error":
                agent_reasoning = f"An error occurred while searching for flights. Reason: {search_result['message']}"
                logger.error(f"❌ SerpAPI search failed. Reason: {search_result['message']}")
            
            # --- END OF MODIFIED LOGIC ---

        # This fallback logic is still excellent.
        # It will now catch "no_results" and "error" cases automatically.
        if not flights:
            origin_display = origin_code if origin_code else intent.origin
            dest_display = destination_code if destination_code else intent.destination
            
            date_too_far = False
            from datetime import datetime
            try:
                search_date = datetime.strptime(intent.depart_date, "%Y-%m-%d")
                days_ahead = (search_date - datetime.now()).days
                if days_ahead > 330:
                    date_too_far = True
            except:
                pass
            
            logger.warning(f"⚠️ No flights found. Creating fallback flight with Google Flights link.")
            from models.plan import Flight
            import uuid
            
            booking_link = f"http://googleusercontent.com/google.com/travel/flights/search?q=flights%20from%20{origin_display}%20to%20{dest_display}%20on%20{intent.depart_date}"
            
            flight_number_msg = "Search Available"
            if date_too_far:
                flight_number_msg = "Date Too Far Ahead"
            elif not origin_display or not origin_display.strip():
                flight_number_msg = "Origin Required"
            
            fallback_flight = Flight(
                id=str(uuid.uuid4()),
                airline="Multiple Airlines",
                flightNumber=flight_number_msg,
                departAirport=origin_display or "Select Origin",
                arriveAirport=dest_display or "Select Destination",
                departTime="Check Availability",
                arriveTime="Check Availability",
                duration="Varies",
                stops=0,
                cabin="Economy",
                price=0.0,
                currency="USD",
                bookingLink=booking_link,
                date=intent.depart_date,
                dateTooFarAhead=date_too_far
            )
            flights = [fallback_flight]
            
            # --- MODIFIED --- Use the real reason if we have one
            final_reasoning = agent_reasoning if agent_reasoning else f"No flights found via SerpAPI. Created Google Flights search link for {intent.origin} to {intent.destination}."
            
            return {
                "flights": [f.model_dump() for f in flights],
                "reasoning": final_reasoning
            }

        # Success case: We have real flights
        real_flights = [f for f in flights if f.price > 0]
        sorted_real_flights = sorted(real_flights, key=lambda x: (x.price, x.stops))[:10]
        
        flights_dict = [f.model_dump() for f in sorted_real_flights]
        
        return {
            "flights": flights_dict,
            # --- MODIFIED --- Use the success reason
            "reasoning": agent_reasoning
        }

    except Exception as e:
        logger.error(f"Flight agent critical error: {e}", exc_info=True)
        # --- MODIFIED --- Return the critical error message
        return {
            "flights": [],
            "reasoning": f"A critical error occurred in the flight agent: {str(e)}"
        }