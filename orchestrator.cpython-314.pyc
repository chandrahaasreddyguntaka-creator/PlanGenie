"""Hotel search agent using Ollama and SerpAPI."""
import json
import logging
from typing import Dict, Any
from models.plan import Hotel, TripRequest
# --- MODIFIED --- Make sure this path is correct
from tools.link_finder_tool import search_hotels 
from llm.ollama_wrapper import call_ollama
from langchain.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


async def search_hotels_agent(intent: TripRequest) -> Dict[str, Any]:
    """
    Search for hotels using Ollama reasoning and SerpAPI.
    (This function is now modified to read the status dictionary)
    """
    try:
        check_in = intent.depart_date
        if intent.return_date:
            check_out = intent.return_date
        else:
            from datetime import datetime, timedelta
            try:
                check_in_date = datetime.strptime(intent.depart_date, "%Y-%m-%d")
                check_out_date = check_in_date + timedelta(days=1)
                check_out = check_out_date.strftime("%Y-%m-%d")
            except:
                check_out = intent.depart_date
        
        # --- MODIFIED --- This is the main logic change
        
        # 1. Call the tool, which now returns a dictionary
        logger.info(f"🔍 Searching SerpAPI for hotels: {intent.destination}")
        search_result = search_hotels(
            location=intent.destination,
            check_in=check_in,
            check_out=check_out,
            adults=intent.adults,
            rooms=1
        )

        hotels = []
        
        # 2. Check the status from the tool
        if search_result["status"] == "success":
            hotels = search_result["data"]
            if not hotels:
                # Handle case where API succeeds but returns no data
                logger.warning("SerpAPI reported success but data list is empty.")
                return {"hotels": [], "reasoning": "No hotels found for the specified criteria."}
            logger.info(f"✅ SerpAPI returned {len(hotels)} hotels. Proceeding to ranking.")
        
        elif search_result["status"] == "no_results":
            reason = f"No hotels were found. Reason: {search_result['message']}"
            logger.warning(f"⚠️ {reason}")
            return {"hotels": [], "reasoning": reason}
            
        elif search_result["status"] == "error":
            reason = f"An error occurred while searching for hotels: {search_result['message']}"
            logger.error(f"❌ {reason}")
            return {"hotels": [], "reasoning": reason}

        # --- END OF MODIFIED LOGIC ---
        
        # If status was "success", we continue to the ranking logic.
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a hotel search assistant. Analyze the hotel options and select the best 3-5 hotels based on:
- Price per night
- Star rating
- Location/neighborhood
- Amenities
- Overall value

Return ONLY a JSON object with:
{{
  "selected_hotels": [list of hotel IDs to keep],
  "reasoning": "Brief explanation of selection criteria"
}}"""),
            ("human", """Hotel options:
{hotels}

Select the best hotels and explain why.""")
        ])
        
        logger.info(f"Hotels from SerpAPI (before Ollama ranking): {len(hotels)}")
        for idx, hotel in enumerate(hotels[:3]):
            logger.info(f"Hotel {idx} from SerpAPI: {hotel.name} - ${hotel.nightlyPrice}/night, ${hotel.totalPrice} total")
        
        hotel_summaries = [
            f"ID: {h.id}, {h.name}, {h.stars}★, {h.neighborhood}, "
            f"${h.nightlyPrice}/night, Total: ${h.totalPrice}, Amenities: {', '.join(h.amenities[:3])}"
            for h in hotels
        ]
        
        try:
            result = await call_ollama(
                "HOTELS",
                lambda llm: (prompt | llm).ainvoke({"hotels": "\n".join(hotel_summaries)})
            )
        except Exception as e:
            logger.warning(f"Ollama hotel ranking failed. Using fallback results: {e}")
            return {
                "hotels": [h.model_dump() for h in hotels[:5]], 
                "reasoning": "Selected top hotel options (Ollama ranking unavailable)"
            }
        
        try:
            response_text = result.content
            if "{" in response_text:
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                json_str = response_text[json_start:json_end]
                parsed = json.loads(json_str)
                selected_ids = set(parsed.get("selected_hotels", []))
                reasoning = parsed.get("reasoning", "Selected based on best value")
            else:
                selected_ids = set()
                reasoning = "Selected top hotels by default"
        except Exception as e:
            logger.warning(f"Failed to parse Ollama response: {e}")
            selected_ids = set()
            reasoning = "Selected top hotels by default"
        
        selected_hotels = [h for h in hotels if h.id in selected_ids]
        if not selected_hotels:
            selected_hotels = sorted(hotels, key=lambda x: x.nightlyPrice)[:3]
        
        logger.info(f"Selected {len(selected_hotels)} hotels after Ollama ranking")
        
        hotels_dict = [h.model_dump() for h in selected_hotels]
        
        return {
            "hotels": hotels_dict,
            "reasoning": reasoning
        }
    
    except Exception as e:
        logger.error(f"Hotel agent critical error: {e}", exc_info=True)
        return {
            "hotels": [],
            "reasoning": f"A critical error occurred in the hotel agent: {str(e)}"
        }