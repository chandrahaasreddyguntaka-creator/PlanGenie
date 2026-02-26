"""Itinerary planning agent using Ollama and Tavily."""
import json
import logging
import uuid
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from models.plan import ItineraryDay, ItineraryBlock, Activity, TripRequest
from tools.search_tools import search_attractions, search_restaurants, search_experiences
from llm.ollama_wrapper import call_ollama
from langchain.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


def _clean_activity_name(name: str) -> str:
    """
    Clean activity name to remove SEO text, article headings, web page titles, and site names.
    
    Examples:
    - "10 Best Museums in Paris | Travel Guide 2024" -> "Museums in Paris"
    - "Top 5 Restaurants: Where to Eat in Tokyo" -> "Restaurants in Tokyo"
    - "Visit the Eiffel Tower | Official Website" -> "Eiffel Tower"
    - "Bhavani Island - TripAdvisor" -> "Bhavani Island"
    - "15 Best Things to Do in Vijayawada - Holidify" -> "Things to Do in Vijayawada"
    """
    if not name:
        return name
    
    # Site names to remove (case-insensitive)
    site_names = [
        'tripadvisor', 'holidify', 'quora', 'reddit', 'facebook', 'bookmyshow',
        'makemytrip', 'goibibo', 'cleartrip', 'yatra', 'travel guide', 'wikitravel',
        'lonely planet', 'rough guides', 'fodor', 'frommer', 'rick steves',
        'official website', 'official site', 'book now', 'visit website'
    ]
    
    cleaned = name.strip()
    
    # Remove site names
    for site in site_names:
        # Remove site name with various separators
        patterns = [
            rf'\s*-\s*{re.escape(site)}\s*$',
            rf'\s*\|\s*{re.escape(site)}\s*$',
            rf'\s*{re.escape(site)}\s*$',
            rf'^{re.escape(site)}\s*-\s*',
            rf'^{re.escape(site)}\s*\|\s*',
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Remove common SEO patterns and article titles (VERY AGGRESSIVE)
    patterns_to_remove = [
        r'^\d+\s+(best|top|must-see|must visit|amazing|incredible|things to do|places to visit|attractions|restaurants|hotels|activities)\s+',  # "10 Best", "Top 5", "15 Things to Do"
        r'^(best|top|must-see|must visit|amazing|incredible|things to do|places to visit|attractions|restaurants|hotels|activities)\s+',  # "Best restaurants", "Top attractions"
        r'\s*\|\s*.*$',  # Everything after "|"
        r'\s*-\s*(travel guide|official website|book now|visit|guide|2024|2025|review|reviews|article|blog).*$',  # Suffixes
        r'\s*:\s*(where to|what to|how to|guide|tips|list|complete guide|in [a-z]+).*$',  # Colon patterns like "What to do in..."
        r'\s*\(.*?\)',  # Parentheses content (but be careful not to remove important info)
        r'^\s*(visit|explore|discover|see|check out|read about|learn about|find|search for)\s+',  # Action verb prefixes
        r'\s+(guide|review|article|blog|website|official|page|list|complete guide|in [a-z]+|2024|2025)$',  # Common suffixes
        r'\s+(things to do|places to visit|attractions|restaurants|hotels|activities)\s+(in|at|near)',  # "Things to do in..."
    ]
    
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # If cleaning removed too much, return original
    if len(cleaned) < 3:
        return name.strip()
    
    return cleaned


def _create_clean_description(activity: Activity, category: str) -> str:
    """
    Create a clean, short, action-oriented description for an activity.
    Follows the style guide: 1-2 lines explaining what the traveler will do and why it's interesting.
    Avoids search snippets, SEO text, and site names.
    """
    name = _clean_activity_name(activity.name)
    original_desc = activity.description or ""
    
    # For restaurants: create action-oriented description
    if category == "restaurant":
        # Extract cuisine type and create natural description
        desc_lower = original_desc.lower()
        cuisines = {
            'italian': 'Italian', 'french': 'French', 'japanese': 'Japanese', 
            'chinese': 'Chinese', 'indian': 'Indian', 'mexican': 'Mexican',
            'thai': 'Thai', 'mediterranean': 'Mediterranean', 'american': 'American',
            'seafood': 'Seafood', 'steakhouse': 'Steakhouse', 'cafe': 'Café',
            'north indian': 'North Indian', 'south indian': 'South Indian',
            'continental': 'Continental', 'chinese': 'Chinese', 'mexican': 'Mexican'
        }
        
        cuisine_type = None
        for key, value in cuisines.items():
            if key in desc_lower:
                cuisine_type = value
                break
        
        # Create natural, action-oriented description
        # Extract restaurant name (clean, short version)
        restaurant_name = name if len(name) < 50 else name.split()[0]  # Use first word if name is too long
        
        if cuisine_type:
            return f"{cuisine_type} restaurant known for authentic flavors"
        elif "thali" in desc_lower:
            return f"Restaurant known for thali and traditional dishes"
        elif "cafe" in name.lower() or "café" in name.lower():
            return f"Café offering coffee and light meals"
        else:
            return f"Local restaurant serving regional cuisine"
    
    # For attractions: create action-oriented descriptions
    elif category == "attraction":
        name_lower = name.lower()
        
        # Temple/Religious sites
        if "temple" in name_lower or "durga" in name_lower or "shrine" in name_lower:
            if "hill" in name_lower or "hilltop" in desc_lower:
                return "Visit the temple and explore the hilltop views"
            return "Visit the temple and experience the spiritual atmosphere"
        
        # Beaches
        elif "beach" in name_lower or "island" in name_lower:
            if "island" in name_lower:
                return "Spend time at the island for boating and outdoor activities"
            return "Relax at the beach and enjoy the waterfront"
        
        # Parks
        elif "park" in name_lower:
            return "Explore the park and enjoy the natural surroundings"
        
        # Museums
        elif "museum" in name_lower:
            return "Explore the museum and learn about local history and culture"
        
        # Markets
        elif "market" in name_lower or "bazaar" in name_lower:
            return "Browse the market for local goods and street food"
        
        # Monuments/Landmarks
        elif "monument" in name_lower or "tower" in name_lower or "fort" in name_lower:
            return "Visit the landmark and admire the architecture"
        
        # Viewpoints
        elif "viewpoint" in name_lower or "view point" in name_lower or "point" in name_lower:
            return "Enjoy panoramic views from the viewpoint"
        
        # Falls/Waterfalls
        elif "falls" in name_lower or "waterfall" in name_lower:
            return "Visit the waterfall and enjoy the natural beauty"
        
        # Generic attraction - try to extract from description
        else:
            # Look for key phrases in description to create action-oriented text
            desc_lower = original_desc.lower()
            if "view" in desc_lower or "panoramic" in desc_lower:
                return f"Visit {name} and enjoy the scenic views"
            elif "explore" in desc_lower or "discover" in desc_lower:
                return f"Explore {name} and discover local attractions"
            elif "shopping" in desc_lower or "shop" in desc_lower:
                return f"Browse {name} for shopping and local finds"
            else:
                return f"Visit {name} and experience the local culture"
    
    # For experiences
    elif category == "experience":
        name_lower = name.lower()
        if "tour" in name_lower:
            return "Take a guided tour to explore the area"
        elif "show" in name_lower or "theater" in name_lower:
            return "Enjoy a cultural show or performance"
        elif "cruise" in name_lower or "boat" in name_lower:
            return "Take a boat ride and enjoy the waterfront"
        else:
            return f"Experience {name} and enjoy local activities"
    
    # Fallback
    return f"Visit {name} and explore the area"


def _parse_date(date_str: str) -> datetime:
    """Parse date string to datetime."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except:
        return datetime.now()


def _date_range(start_date: str, end_date: str = None) -> List[str]:
    """
    Generate list of dates between start and end.
    
    If end_date (return_date) is provided, it represents the date the user wants to be BACK.
    So the itinerary should end one day BEFORE end_date to allow time for return travel.
    """
    start = _parse_date(start_date)
    
    if end_date:
        # end_date is when user wants to be BACK, so itinerary should end the day before
        end = _parse_date(end_date) - timedelta(days=1)
    else:
        # One-way trip: default to 3 days
        end = start + timedelta(days=3)
    
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    
    return dates

# In agents/itinerary_agent.py, add this function somewhere before plan_itinerary_agent

async def _final_llm_cleaning_pass(activities: List[Activity]) -> List[Activity]:
    """
    Uses LLM to rewrite activities that still look like listicles or generic snippets.
    This is the final quality check.
    """
    if not activities:
        return activities

    # Create a mapping of original names to activity objects
    activity_map = {a.name: a for a in activities}
    raw_names = [a.name for a in activities]
    
    # Send the raw names list to the LLM for cleaning
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a meticulous activity name cleaner. Your task is to review a list of activity titles that have already been partially cleaned by a regex.

        CRITICAL INSTRUCTIONS:
        1. For each item, rewrite the title to be a simple, friendly, real-world activity name.
        2. If a name is generic, short (like 'Morning' or 'Downtown'), or still sounds like a website/blog title (e.g., 'The 10 Best...'), replace it with a clean, descriptive activity title like 'Explore Downtown Chicago' or 'Visit the Old Town Triangle'.
        3. Only clean the titles that need it; keep the rest the same.
        
        Return ONLY a JSON list of strings. The length MUST match the input list length. Do NOT return the original names in the list; return the CLEANED names for every item.
        
        Example Input: ["Old Town Triangle Tours", "in Chicago in the Morning", "Museum of Science and Industry"]
        Example Output: ["Visit the Old Town Triangle", "Explore the City Center", "Museum of Science and Industry"]
        """),
        ("human", f"Clean this list of activity names: {raw_names}")
    ])
    
    try:
        result = await call_ollama(
            "ITINERARY_CLEANER",
            lambda llm: (prompt | llm).ainvoke({}) # Note: The prompt contains the input via f-string
        )
        
        response_text = result.content
        if "{" in response_text:
            json_start = response_text.find("[")
            json_end = response_text.rfind("]") + 1
            cleaned_names_list = json.loads(response_text[json_start:json_end])
        else:
             logger.warning("LLM cleanup failed to return JSON list.")
             return activities

        # Map the cleaned names back to the original activity objects
        if len(cleaned_names_list) == len(activities):
            for i, activity in enumerate(activities):
                new_name = cleaned_names_list[i].strip()
                if new_name:
                    activity.name = new_name
            return activities

    except Exception as e:
        logger.warning(f"Final LLM cleaning pass failed: {e}")
        return activities # Return original list if cleaning crashes


async def plan_itinerary_agent(
    intent: TripRequest, 
    max_days: int = 7,
    day_callback = None
) -> Dict[str, Any]:
    """
    Plan itinerary using Ollama reasoning and Tavily.
    Plans days incrementally, streaming each day as it's completed.
    
    Args:
        intent: Trip request with destination, dates, etc.
        max_days: Maximum number of days to plan
        day_callback: Optional callback function(day: ItineraryDay, all_days: List[ItineraryDay]) 
                     to stream each day as it's completed
    
    Returns:
        Dict with "itinerary" (with "days" key) and "reasoning" string
    """
    try:
        # Get trip length from preferences if available
        trip_length = None
        if intent.preferences and isinstance(intent.preferences, dict):
            trip_length = intent.preferences.get("trip_length")
        
        # Generate date range
        # Priority: return_date > trip_length > default (3 days)
        if intent.return_date:
            # Use return_date if provided
            dates = _date_range(intent.depart_date, intent.return_date)
            logger.info(f"Using return_date for itinerary: {intent.return_date}")
        elif trip_length and isinstance(trip_length, (int, float)) and trip_length > 0:
            # Use trip_length if provided
            from datetime import datetime, timedelta
            start = _parse_date(intent.depart_date)
            end = start + timedelta(days=int(trip_length) - 1)  # -1 because start day counts as day 1
            dates = []
            current = start
            while current <= end:
                dates.append(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
            logger.info(f"Using trip_length for itinerary: {trip_length} days")
        else:
            # Default: use _date_range which defaults to 3 days
            dates = _date_range(intent.depart_date, None)
            # Limit to max_days if no return_date or trip_length
            if len(dates) > max_days:
                dates = dates[:max_days]
            logger.info(f"Using default date range for itinerary: {len(dates)} days")
        
        if intent.return_date:
            logger.info(f"Planning itinerary for {len(dates)} days: {dates[0] if dates else 'N/A'} to {dates[-1] if dates else 'N/A'} (return by {intent.return_date})")
        else:
            logger.info(f"Planning itinerary for {len(dates)} days: {dates[0] if dates else 'N/A'} to {dates[-1] if dates else 'N/A'}")
        
        if not dates:
            return {
                "itinerary": {"days": []},
                "reasoning": "Invalid date range"
            }
        
        # Search for activities
        logger.info(f"Searching activities for destination: {intent.destination}")
        attractions = search_attractions(intent.destination, intent.depart_date, intent.budget)
        restaurants = search_restaurants(intent.destination, None, intent.budget)
        experiences = search_experiences(intent.destination)
        
        logger.info(f"Found {len(attractions)} attractions, {len(restaurants)} restaurants, {len(experiences)} experiences")
        
        # Filter activities to only include those relevant to the destination
        # Clean activity names to remove SEO text, article headings, and site names
        destination_lower = intent.destination.lower()
        all_activities = []
        
        # Patterns that indicate article titles or listicles (should be filtered out)
        article_patterns = [
            r'^\d+\s+(best|top|must-see|things to do|places to visit|attractions|restaurants)',
            r'^(best|top|must-see|things to do|places to visit|attractions|restaurants)\s+',
            r'(tripadvisor|holidify|quora|reddit|facebook|instagram|bookmyshow)',
            r'what to do|where to go|how to|guide to|complete guide',
        ]
        
        def is_article_title(name: str) -> bool:
            """Check if activity name is an article title or listicle."""
            name_lower = name.lower()
            for pattern in article_patterns:
                if re.search(pattern, name_lower):
                    return True
            return False
        
        for activity in attractions + restaurants + experiences:
            # Clean the activity name
            cleaned_name = _clean_activity_name(activity.name)
            
            # Skip if it's still an article title after cleaning
            if is_article_title(cleaned_name):
                logger.debug(f"Filtered out article title: {cleaned_name}")
                continue
            
            # Skip if name is too generic or empty after cleaning
            if len(cleaned_name.strip()) < 3:
                logger.debug(f"Filtered out empty/generic name: {cleaned_name}")
                continue
            
            activity.name = cleaned_name  # Update the activity with cleaned name
            
            # Filter by relevance
            activity_text = f"{cleaned_name} {activity.description or ''}".lower()
            if destination_lower in activity_text or activity.category == "restaurant":
                all_activities.append(activity)
            else:
                logger.debug(f"Filtered out irrelevant activity: {cleaned_name}")
        
        logger.info(f"After filtering, {len(all_activities)} activities remain relevant to {intent.destination}")

        logger.info("Running final LLM pass to sanitize activity names...")
        all_activities = await _final_llm_cleaning_pass(all_activities)
        logger.info(f"After LLM cleaning, {len(all_activities)} activities remain.")
        
        if not all_activities:
            return {
                "itinerary": {"days": []},
                "reasoning": "No activities found for destination"
            }
        
        # Plan days ONE AT A TIME to stream incrementally
        # This ensures we can stream partial results as they're completed
        logger.info(f"Planning {len(dates)} days incrementally (one at a time)")
        
        itinerary_days = []
        # Track used activities to prevent duplicates across days
        used_activity_names = set()
        used_restaurant_names = set()
        
        for idx, date in enumerate(dates):
            try:
                logger.info(f"Planning day {idx + 1}/{len(dates)}: {date}")
                
                # Plan single day (with fallback if Ollama fails)
                # Pass used activities to prevent duplicates
                day_plan = await _plan_single_day(
                    date,
                    intent.destination,
                    all_activities,
                    intent.budget,
                    used_activity_names=used_activity_names,
                    used_restaurant_names=used_restaurant_names,
                    day_number=idx + 1,
                    total_days=len(dates)
                )
                
                # Track activities used in this day
                if day_plan and day_plan.blocks:
                    for block in day_plan.blocks:
                        for activity in block.activities:
                            activity_name_lower = activity.name.lower().strip()
                            if activity.category == "restaurant":
                                used_restaurant_names.add(activity_name_lower)
                            else:
                                used_activity_names.add(activity_name_lower)
                
                if day_plan and day_plan.blocks:
                    itinerary_days.append(day_plan)
                    
                    # Stream this day immediately to frontend
                    if day_callback:
                        try:
                            day_callback(day_plan, itinerary_days)
                            logger.info(f"Streamed day {date} to frontend ({len(itinerary_days)}/{len(dates)} complete)")
                        except Exception as e:
                            logger.warning(f"Failed to stream day {date}: {e}")
                    
                    # Small delay between days to avoid rate limits
                    import asyncio
                    await asyncio.sleep(1)
                else:
                    logger.warning(f"Day {date} plan is empty, skipping")
                    
            except Exception as e:
                logger.warning(f"Failed to plan day {date}: {e}")
                # Continue with next day even if one fails
        
        if len(itinerary_days) < len(dates):
            logger.warning(f"Only planned {len(itinerary_days)}/{len(dates)} days. Some days may be missing.")
        
        return {
            "itinerary": {"days": [d.model_dump() for d in itinerary_days]},
            "reasoning": f"Created {len(itinerary_days)}-day itinerary with activities and restaurants"
        }
    
    except Exception as e:
        logger.error(f"Itinerary agent error: {e}")
        return {
            "itinerary": {"days": []},
            "reasoning": f"Error planning itinerary: {str(e)}"
        }


async def _plan_multiple_days_batch(
    dates: List[str],
    city: str,
    available_activities: List[Activity],
    budget: str = None
) -> List[ItineraryDay]:
    """
    Plan multiple days in a single Ollama API call to improve speed.
    This is much faster than planning days individually.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Itinerary Planner for a travel application. Your job is to turn raw search results into a clean, human-friendly itinerary.

CORE RULES (VERY STRICT):

1. USE ONLY REAL PLACE NAMES:
   - Do NOT output article titles or list titles (e.g., "15 Best Things To Do...", "Top 24 Places...", "What to do in...", "Best restaurants...")
   - Do NOT output website/platform names (TripAdvisor, Holidify, Facebook, Reddit, Quora, Instagram, BookMyShow, etc.)
   - From search results, EXTRACT actual places: "15 Best Things To Do in Vizag – TripAdvisor" → extract "RK Beach", "Kailasagiri Park"
   - "Top 10 Restaurants in Vizag" → extract actual restaurant names, NOT the list itself

2. NO DUPLICATES (STRICT):
   - Do NOT repeat any place anywhere in the entire itinerary
   - Once a place is used, it cannot appear again (applies to attractions, restaurants, experiences)
   - Treat similar names as duplicates (case-insensitive)

3. DAILY STRUCTURE (MANDATORY):
   - Morning: 2-3 attractions (parks, beaches, viewpoints, museums, temples, malls, islands, etc.)
   - Afternoon: Exactly ONE lunch restaurant AND 1-2 attractions
   - Evening: Exactly ONE dinner restaurant (optionally 1 small activity, but fine with only dinner)
   - Restaurants must be REAL places, not listicles

4. DESCRIPTIONS:
   - Short, clean, action-oriented (1-2 lines)
   - Examples: "Relax at RK Beach and enjoy the coastal views", "Visit Kailasagiri Park for panoramic hilltop scenery"
   - Do NOT copy random website descriptions or SEO text

5. YOUR PROCESS:
   - Identify unique places hidden in search results
   - Remove duplicates
   - Clean their names
   - Build proper itinerary using that information

6. FALLBACK:
   - If search results insufficient, fill gaps with plausible local activities (e.g., "Local beach walk", "City viewpoint", "Street-food lane visit")

WHAT YOU MUST NEVER OUTPUT:
- Article titles, SEO list names, website names
- "Things to do in..." style results
- Placeholder text, repeated places
- Activities without clear real-world names

WHAT YOU MUST ALWAYS OUTPUT:
- Real places (one-time-only usage)
- Clean morning/afternoon/evening structure
- Exactly one lunch restaurant + one dinner restaurant each day
- Clear, simple activity descriptions

RETURN FORMAT: Return ONLY valid JSON (no descriptions in JSON, just structure):
{{
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "morning": [{{"name": "Exact activity name from list", "category": "attraction", "estimatedTime": "2-3h"}}],
      "afternoon": [{{"name": "Exact restaurant name from list", "category": "restaurant", "estimatedTime": "1-2h"}}, {{"name": "Exact activity name from list", "category": "attraction", "estimatedTime": "2-3h"}}],
      "evening": [{{"name": "Exact restaurant name from list", "category": "restaurant", "estimatedTime": "1-2h"}}]
    }}
  ]
}}

Use EXACT activity names from the provided list. Return ONLY the JSON object, no other text."""),
        ("human", """Dates: {dates}, City: {city}

Available activities (use EXACT names only):
{activities}

Return JSON with selected activity names for each day (no descriptions).""")
    ])
    
    # Separate restaurants from other activities
    restaurants_list = [a for a in available_activities if a.category == "restaurant"]
    other_activities = [a for a in available_activities if a.category != "restaurant"]
    
    # Prioritize restaurants and relevant activities
    prioritized_activities = restaurants_list[:15] + other_activities[:20]  # More activities for multi-day
    
    # Create a mapping of activity names to Activity objects for lookup
    activity_map = {a.name.lower().strip(): a for a in prioritized_activities}
    
    # Build simple list of activity names only (no descriptions to avoid echoing search snippets)
    activity_list = [
        f"- {a.name} ({a.category})"
        for a in prioritized_activities
    ]
    
    logger.info(f"Planning {len(dates)} days in batch for {city} with {len(prioritized_activities)} activities")
    
    try:
        result = await call_ollama(
            "ITINERARY",
            lambda llm: (prompt | llm).ainvoke({
                "dates": ", ".join(dates),
                "city": city,
                "activities": "\n".join(activity_list)
            })
        )
    except Exception as e:
        logger.warning(f"Ollama batch itinerary planning failed: {e}")
        # Return empty list to trigger fallback
        return []
    
    # Parse response
    try:
        response_text = result.content
        if "{" in response_text:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_str = response_text[json_start:json_end]
            plan_data = json.loads(json_str)
        else:
            plan_data = {}
    except Exception as e:
        logger.warning(f"Failed to parse batch day plan: {e}")
        return []
    
    # Map LLM-selected activity names back to actual Activity objects
    def find_activity_by_name_batch(activity_name: str, category: str) -> Optional[Activity]:
        """Find Activity object by name (case-insensitive fuzzy matching)."""
        activity_name_clean = _clean_activity_name(activity_name).lower().strip()
        
        # Try exact match first
        if activity_name_clean in activity_map:
            return activity_map[activity_name_clean]
        
        # Try fuzzy matching
        for stored_name, activity in activity_map.items():
            if activity.category == category:
                if activity_name_clean in stored_name or stored_name in activity_name_clean:
                    return activity
        
        return None
    
    # Convert to ItineraryDay objects
    def create_activity_from_plan_batch(activity_data: dict) -> Optional[Activity]:
        """Create Activity from LLM plan by mapping name back to original Activity."""
        activity_name = activity_data.get("name", "").strip()
        category = activity_data.get("category", "attraction")
        
        if not activity_name:
            return None
        
        # Find the original Activity object
        activity = find_activity_by_name_batch(activity_name, category)
        
        if activity:
            # Create a copy with clean description
            clean_desc = _create_clean_description(activity, category)
            return Activity(
                id=activity.id,
                name=activity.name,
                category=category,
                estimatedTime=activity_data.get("estimatedTime", activity.estimatedTime),
                description=clean_desc,
                openingHours=activity.openingHours,
                ticketInfo=activity.ticketInfo,
                mapLink=activity.mapLink
            )
        
        return None
    
    itinerary_days = []
    days_data = plan_data.get("days", [])
    
    for day_data in days_data:
        date = day_data.get("date")
        if not date or date not in dates:
            continue
        
        morning_activities = [a for a in [create_activity_from_plan_batch(a) for a in day_data.get("morning", []) if isinstance(a, dict)] if a is not None]
        afternoon_activities = [a for a in [create_activity_from_plan_batch(a) for a in day_data.get("afternoon", []) if isinstance(a, dict)] if a is not None]
        evening_activities = [a for a in [create_activity_from_plan_batch(a) for a in day_data.get("evening", []) if isinstance(a, dict)] if a is not None]
        
        # Ensure restaurants are included
        if afternoon_activities and not any(a.category == "restaurant" for a in afternoon_activities):
            restaurant = next((a for a in available_activities if a.category == "restaurant"), None)
            if restaurant:
                clean_desc = _create_clean_description(restaurant, "restaurant")
                afternoon_activities.append(Activity(
                    id=restaurant.id,
                    name=restaurant.name,
                    category="restaurant",
                    estimatedTime="1-2 hours",
                    description=clean_desc,
                    openingHours=restaurant.openingHours,
                    ticketInfo=restaurant.ticketInfo,
                    mapLink=restaurant.mapLink
                ))
        
        if evening_activities and not any(a.category == "restaurant" for a in evening_activities):
            restaurant = next((a for a in available_activities if a.category == "restaurant" and a.name.lower() != (afternoon_activities[-1].name.lower() if afternoon_activities and afternoon_activities[-1].category == "restaurant" else "")), None)
            if restaurant:
                clean_desc = _create_clean_description(restaurant, "restaurant")
                evening_activities.append(Activity(
                    id=restaurant.id,
                    name=restaurant.name,
                    category="restaurant",
                    estimatedTime="1-2 hours",
                    description=clean_desc,
                    openingHours=restaurant.openingHours,
                    ticketInfo=restaurant.ticketInfo,
                    mapLink=restaurant.mapLink
                ))
        
        blocks = []
        if morning_activities:
            blocks.append(ItineraryBlock(time="Morning", activities=morning_activities))
        if afternoon_activities:
            blocks.append(ItineraryBlock(time="Afternoon", activities=afternoon_activities))
        if evening_activities:
            blocks.append(ItineraryBlock(time="Evening", activities=evening_activities))
        
        if blocks:
            itinerary_days.append(ItineraryDay(date=date, city=city, blocks=blocks))
    
    logger.info(f"Batch planning returned {len(itinerary_days)} days")
    return itinerary_days


async def _plan_single_day(
    date: str,
    city: str,
    available_activities: List[Activity],
    budget: str = None,
    used_activity_names: set = None,
    used_restaurant_names: set = None,
    day_number: int = 1,
    total_days: int = 1
) -> ItineraryDay:
    """
    Plan activities for a single day.
    
    Args:
        date: Date string
        city: City name
        available_activities: List of available activities
        budget: Budget constraint
        used_activity_names: Set of activity names already used in previous days
        used_restaurant_names: Set of restaurant names already used in previous days
        day_number: Current day number (1-indexed)
        total_days: Total number of days in itinerary
    """
    used_activity_names = used_activity_names or set()
    used_restaurant_names = used_restaurant_names or set()
    
    # Filter out already-used activities (case-insensitive matching)
    def is_activity_used(activity: Activity) -> bool:
        """Check if activity name is similar to any used activity."""
        activity_name_lower = activity.name.lower().strip()
        
        # For restaurants, allow some repetition but prefer variety
        if activity.category == "restaurant":
            # Check exact match first
            if activity_name_lower in used_restaurant_names:
                return True
            # Check for similar names (fuzzy matching for common variations)
            for used_name in used_restaurant_names:
                # Check if names are very similar (one contains the other or vice versa)
                if activity_name_lower in used_name or used_name in activity_name_lower:
                    # Allow if it's a different location/branch (e.g., "Starbucks Downtown" vs "Starbucks Airport")
                    if len(activity_name_lower) > 15 and len(used_name) > 15:
                        # If both are long, they might be different locations
                        continue
                    return True
            return False
        else:
            # For attractions, be stricter - no duplicates
            if activity_name_lower in used_activity_names:
                return True
            # Check for similar names
            for used_name in used_activity_names:
                # Exact substring match (one contains the other)
                if activity_name_lower in used_name or used_name in activity_name_lower:
                    # If one is much shorter, it's likely a duplicate
                    if abs(len(activity_name_lower) - len(used_name)) < 5:
                        return True
            return False
    
    # Filter available activities to exclude already-used ones
    unused_activities = [a for a in available_activities if not is_activity_used(a)]
    
    # If we've used too many, allow some restaurants to repeat (but prefer unused)
    restaurants_list = [a for a in available_activities if a.category == "restaurant"]
    other_activities = [a for a in unused_activities if a.category != "restaurant"]
    
    # For restaurants, prioritize unused but allow some repetition if needed
    unused_restaurants = [a for a in restaurants_list if not is_activity_used(a)]
    if len(unused_restaurants) < 2 and len(restaurants_list) > 0:
        # If we're running low on unused restaurants, allow one repeat per day
        # But still prefer unused ones
        available_restaurants = unused_restaurants + [a for a in restaurants_list if a not in unused_restaurants][:2]
    else:
        available_restaurants = unused_restaurants
    
    # Combine: unused restaurants + unused other activities
    filtered_activities = available_restaurants + other_activities
    
    # If we filtered out too many, log a warning but continue
    if len(filtered_activities) < 5:
        logger.warning(f"Only {len(filtered_activities)} unused activities available for day {day_number}. May need to allow some repetition.")
        # Allow some activities to be reused if we're running low
        filtered_activities = available_activities[:20]  # Fallback to original list
    
    # Build list of used activities for the prompt
    used_activities_text = ""
    if used_activity_names:
        used_activities_text = f"\n\nIMPORTANT: Do NOT repeat these activities already used in previous days: {', '.join(list(used_activity_names)[:10])}"
    if used_restaurant_names and day_number > 1:
        used_restaurants_text = f"\nRestaurants already used (prefer different ones): {', '.join(list(used_restaurant_names)[:5])}"
        used_activities_text += used_restaurants_text
    
    # Create JSON example as a string to avoid template variable issues
    # Use double braces to escape literal braces in the JSON example
    json_example = """{{
  "morning": [{{"name": "Exact activity name from list", "category": "attraction", "estimatedTime": "2-3h"}}],
  "afternoon": [{{"name": "Exact restaurant name from list", "category": "restaurant", "estimatedTime": "1-2h"}}, {{"name": "Exact activity name from list", "category": "attraction", "estimatedTime": "2-3h"}}],
  "evening": [{{"name": "Exact restaurant name from list", "category": "restaurant", "estimatedTime": "1-2h"}}]
}}"""
    
    # Build system message without f-string to avoid template variable conflicts
    system_message = f"""You are the Itinerary Planner for a travel application. Your job is to turn raw search results into a clean, human-friendly itinerary.

CORE RULES (VERY STRICT):

1. USE ONLY REAL PLACE NAMES:
   - Do NOT output article titles or list titles (e.g., "15 Best Things To Do...", "Top 24 Places...", "What to do in...", "Best restaurants...")
   - Do NOT output website/platform names (TripAdvisor, Holidify, Facebook, Reddit, Quora, Instagram, BookMyShow, etc.)
   - From search results, EXTRACT actual places: "15 Best Things To Do in Vizag – TripAdvisor" → extract "RK Beach", "Kailasagiri Park"
   - "Top 10 Restaurants in Vizag" → extract actual restaurant names, NOT the list itself

2. NO DUPLICATES (STRICT):
   - Do NOT repeat any place anywhere in the entire itinerary
   - Once a place is used, it cannot appear again (applies to attractions, restaurants, experiences)
   - Treat similar names as duplicates (case-insensitive)
   - This is Day {day_number} of {total_days} - DO NOT repeat any activities from previous days{used_activities_text}

3. DAILY STRUCTURE (MANDATORY):
   - Morning: 2-3 attractions (parks, beaches, viewpoints, museums, temples, malls, islands, etc.)
   - Afternoon: Exactly ONE lunch restaurant AND 1-2 attractions
   - Evening: Exactly ONE dinner restaurant (optionally 1 small activity, but fine with only dinner)
   - Restaurants must be REAL places, not listicles

4. DESCRIPTIONS:
   - Short, clean, action-oriented (1-2 lines)
   - Examples: "Relax at RK Beach and enjoy the coastal views", "Visit Kailasagiri Park for panoramic hilltop scenery"
   - Do NOT copy random website descriptions or SEO text

5. YOUR PROCESS:
   - Identify unique places hidden in search results
   - Remove duplicates
   - Clean their names
   - Build proper itinerary using that information

6. FALLBACK:
   - If search results insufficient, fill gaps with plausible local activities (e.g., "Local beach walk", "City viewpoint", "Street-food lane visit")

WHAT YOU MUST NEVER OUTPUT:
- Article titles, SEO list names, website names
- "Things to do in..." style results
- Placeholder text, repeated places
- Activities without clear real-world names

WHAT YOU MUST ALWAYS OUTPUT:
- Real places (one-time-only usage)
- Clean morning/afternoon/evening structure
- Exactly one lunch restaurant + one dinner restaurant each day
- Clear, simple activity descriptions

RETURN FORMAT: Return ONLY valid JSON (no descriptions in JSON, just structure):
{json_example}

Use EXACT activity names from the provided list. Return ONLY the JSON object, no other text."""
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_message),
        ("human", """Date: {date}, City: {city}

Available activities (use EXACT names only):
{activities}

Return JSON with selected activity names (no descriptions).""")
    ])
    
    # Use filtered activities (already excludes duplicates)
    # Separate restaurants from other activities for better organization
    restaurants_list = [a for a in filtered_activities if a.category == "restaurant"]
    other_activities = [a for a in filtered_activities if a.category != "restaurant"]
    
    # Prioritize restaurants and relevant activities
    # Include more restaurants since we need them for lunch and dinner
    prioritized_activities = restaurants_list[:10] + other_activities[:15]  # More restaurants
    
    # Create a mapping of activity names to Activity objects for lookup
    activity_map = {a.name.lower().strip(): a for a in prioritized_activities}
    
    # Build simple list of activity names only (no descriptions to avoid echoing search snippets)
    activity_list = [
        f"- {a.name} ({a.category})"
        for a in prioritized_activities
    ]
    
    logger.info(f"Planning day {date} for {city} with {len(prioritized_activities)} activities ({len(restaurants_list)} restaurants)")
    
    try:
        result = await call_ollama(
            "ITINERARY",
            lambda llm: (prompt | llm).ainvoke({
                "date": date,
                "city": city,
                "activities": "\n".join(activity_list)
            })
        )
    except Exception as e:
        logger.warning(f"Ollama itinerary day planning failed. Using fallback: {e}")
        # Create summarized fallback activities from search results
        fallback_activities = []
        for activity in available_activities[:5]:
            # Create summarized version
            summarized = Activity(
                id=str(uuid.uuid4()),
                name=activity.name,
                category=activity.category,
                estimatedTime=activity.estimatedTime,
                description=(activity.description or f"Visit {activity.name}")[:200] if activity.description else f"Visit {activity.name}",
                openingHours=activity.openingHours,
                ticketInfo=activity.ticketInfo,
                mapLink=activity.mapLink
            )
            fallback_activities.append(summarized)
        
        return ItineraryDay(
            date=date,
            city=city,
            blocks=[
                ItineraryBlock(
                    time="Morning",
                    activities=fallback_activities[:3] if fallback_activities else []
                )
            ] if fallback_activities else []
        )
    
    # Parse response - now expects summarized activities, not IDs
    # Only reach here if the try block succeeded
    try:
        response_text = result.content
        if "{" in response_text:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_str = response_text[json_start:json_end]
            plan = json.loads(json_str)
        else:
            plan = {}
    except Exception as e:
        logger.warning(f"Failed to parse day plan: {e}")
        plan = {}
    
    # Map LLM-selected activity names back to actual Activity objects
    def find_activity_by_name(activity_name: str, category: str) -> Optional[Activity]:
        """Find Activity object by name (case-insensitive fuzzy matching)."""
        activity_name_clean = _clean_activity_name(activity_name).lower().strip()
        
        # Try exact match first
        if activity_name_clean in activity_map:
            return activity_map[activity_name_clean]
        
        # Try fuzzy matching (check if name contains or is contained in any activity name)
        for stored_name, activity in activity_map.items():
            if activity.category == category:
                # Check if names are similar (one contains the other)
                if activity_name_clean in stored_name or stored_name in activity_name_clean:
                    return activity
        
        # If not found, create a new Activity with clean name
        logger.warning(f"Activity '{activity_name}' not found in available activities, creating new")
        return Activity(
            id=str(uuid.uuid4()),
            name=_clean_activity_name(activity_name),
            category=category,
            estimatedTime="2-3 hours",
            description=None,  # Will be set below
        )
    
    # Build activities from LLM plan - map names back to Activity objects
    def create_activity_from_plan(activity_data: dict) -> Optional[Activity]:
        """Create Activity from LLM plan by mapping name back to original Activity."""
        activity_name = activity_data.get("name", "").strip()
        category = activity_data.get("category", "attraction")
        
        if not activity_name:
            return None
        
        # Final safety check: reject article titles or site names
        article_patterns = [
            r'^\d+\s+(best|top|must-see|things to do|places to visit|attractions|restaurants)',
            r'^(best|top|must-see|things to do|places to visit|attractions|restaurants)\s+',
            r'(tripadvisor|holidify|quora|reddit|facebook|instagram|bookmyshow)',
            r'what to do|where to go|how to|guide to|complete guide',
        ]
        activity_name_lower = activity_name.lower()
        for pattern in article_patterns:
            if re.search(pattern, activity_name_lower):
                logger.warning(f"Rejected article title from LLM output: {activity_name}")
                return None
        
        # Find the original Activity object
        activity = find_activity_by_name(activity_name, category)
        
        if activity:
            # Create a copy with clean description
            clean_desc = _create_clean_description(activity, category)
            return Activity(
                id=activity.id,
                name=activity.name,  # Use cleaned name from original
                category=category,
                estimatedTime=activity_data.get("estimatedTime", activity.estimatedTime),
                description=clean_desc,  # Clean, short description
                openingHours=activity.openingHours,
                ticketInfo=activity.ticketInfo,
                mapLink=activity.mapLink
            )
        
        return None
    
    # Build activities from plan
    morning_activities = [a for a in [create_activity_from_plan(a) for a in plan.get("morning", []) if isinstance(a, dict)] if a is not None]
    afternoon_activities = [a for a in [create_activity_from_plan(a) for a in plan.get("afternoon", []) if isinstance(a, dict)] if a is not None]
    evening_activities = [a for a in [create_activity_from_plan(a) for a in plan.get("evening", []) if isinstance(a, dict)] if a is not None]
    
    # Ensure restaurants are included in afternoon and evening
    # Use filtered activities to avoid duplicates
    # If no restaurant in afternoon, create a summary from available restaurants
    if afternoon_activities and not any(a.category == "restaurant" for a in afternoon_activities):
        # Find an unused restaurant
        restaurant_for_lunch = next((a for a in filtered_activities if a.category == "restaurant" and a.name.lower() not in [act.name.lower() for act in afternoon_activities]), None)
        if not restaurant_for_lunch:
            restaurant_for_lunch = next((a for a in filtered_activities if a.category == "restaurant"), None)
        if restaurant_for_lunch:
            # Create clean version
            lunch_activity = Activity(
                id=restaurant_for_lunch.id,
                name=restaurant_for_lunch.name,
                category="restaurant",
                estimatedTime="1-2 hours",
                description=_create_clean_description(restaurant_for_lunch, "restaurant"),
                openingHours=restaurant_for_lunch.openingHours,
                ticketInfo=restaurant_for_lunch.ticketInfo,
                mapLink=restaurant_for_lunch.mapLink
            )
            afternoon_activities.append(lunch_activity)
            logger.info(f"Added restaurant for lunch: {restaurant_for_lunch.name}")
    
    # If no restaurant in evening, create a summary from available restaurants
    if evening_activities and not any(a.category == "restaurant" for a in evening_activities):
        # Find a different restaurant from lunch
        lunch_restaurant_name = afternoon_activities[-1].name.lower() if afternoon_activities and afternoon_activities[-1].category == "restaurant" else ""
        restaurant_for_dinner = next((a for a in filtered_activities if a.category == "restaurant" and a.name.lower() != lunch_restaurant_name and a.name.lower() not in [act.name.lower() for act in evening_activities]), None)
        if not restaurant_for_dinner:
            # Fallback: any unused restaurant
            restaurant_for_dinner = next((a for a in filtered_activities if a.category == "restaurant" and a.name.lower() != lunch_restaurant_name), None)
        if restaurant_for_dinner:
            # Create clean version
            dinner_activity = Activity(
                id=restaurant_for_dinner.id,
                name=restaurant_for_dinner.name,
                category="restaurant",
                estimatedTime="1-2 hours",
                description=_create_clean_description(restaurant_for_dinner, "restaurant"),
                openingHours=restaurant_for_dinner.openingHours,
                ticketInfo=restaurant_for_dinner.ticketInfo,
                mapLink=restaurant_for_dinner.mapLink
            )
            evening_activities.append(dinner_activity)
            logger.info(f"Added restaurant for dinner: {restaurant_for_dinner.name}")
    
    # Final deduplication check: remove any duplicate activities within the same day
    def deduplicate_activities(activities: List[Activity]) -> List[Activity]:
        """Remove duplicate activities from a list."""
        seen_names = set()
        unique_activities = []
        for activity in activities:
            activity_name_lower = activity.name.lower().strip()
            if activity_name_lower not in seen_names:
                seen_names.add(activity_name_lower)
                unique_activities.append(activity)
            else:
                logger.debug(f"Removed duplicate activity within day: {activity.name}")
        return unique_activities
    
    morning_activities = deduplicate_activities(morning_activities)
    afternoon_activities = deduplicate_activities(afternoon_activities)
    evening_activities = deduplicate_activities(evening_activities)
    
    blocks = []
    if morning_activities:
        blocks.append(ItineraryBlock(
            time="Morning",
            activities=morning_activities,
            travelTime=plan.get("travel_time")
        ))
    if afternoon_activities:
        blocks.append(ItineraryBlock(
            time="Afternoon",
            activities=afternoon_activities
        ))
    if evening_activities:
        blocks.append(ItineraryBlock(
            time="Evening",
            activities=evening_activities
        ))
    
    # Fallback: if no blocks or missing required slots, fill with realistic activities
    if not blocks or not any(b.time == "Afternoon" and any(a.category == "restaurant" for a in b.activities) for b in blocks):
        # Need to add lunch restaurant
        restaurant_for_lunch = next((a for a in filtered_activities if a.category == "restaurant"), None)
        if restaurant_for_lunch:
            lunch_activity = Activity(
                id=restaurant_for_lunch.id,
                name=restaurant_for_lunch.name,
                category="restaurant",
                estimatedTime="1-2 hours",
                description=_create_clean_description(restaurant_for_lunch, "restaurant"),
                openingHours=restaurant_for_lunch.openingHours,
                ticketInfo=restaurant_for_lunch.ticketInfo,
                mapLink=restaurant_for_lunch.mapLink
            )
            # Add afternoon block if missing
            afternoon_block = next((b for b in blocks if b.time == "Afternoon"), None)
            if afternoon_block:
                afternoon_block.activities.insert(0, lunch_activity)
            else:
                blocks.append(ItineraryBlock(time="Afternoon", activities=[lunch_activity]))
    
    if not blocks or not any(b.time == "Evening" and any(a.category == "restaurant" for a in b.activities) for b in blocks):
        # Need to add dinner restaurant
        lunch_restaurant_name = ""
        for block in blocks:
            if block.time == "Afternoon":
                for act in block.activities:
                    if act.category == "restaurant":
                        lunch_restaurant_name = act.name.lower()
                        break
        
        restaurant_for_dinner = next((a for a in filtered_activities if a.category == "restaurant" and a.name.lower() != lunch_restaurant_name), None)
        if restaurant_for_dinner:
            dinner_activity = Activity(
                id=restaurant_for_dinner.id,
                name=restaurant_for_dinner.name,
                category="restaurant",
                estimatedTime="1-2 hours",
                description=_create_clean_description(restaurant_for_dinner, "restaurant"),
                openingHours=restaurant_for_dinner.openingHours,
                ticketInfo=restaurant_for_dinner.ticketInfo,
                mapLink=restaurant_for_dinner.mapLink
            )
            # Add evening block if missing
            evening_block = next((b for b in blocks if b.time == "Evening"), None)
            if evening_block:
                evening_block.activities.append(dinner_activity)
            else:
                blocks.append(ItineraryBlock(time="Evening", activities=[dinner_activity]))
    
    # If still no blocks, create minimal fallback with available activities
    if not blocks and filtered_activities:
        fallback_activities = []
        for activity in filtered_activities[:3]:
            clean_desc = _create_clean_description(activity, activity.category)
            fallback_activities.append(Activity(
                id=activity.id,
                name=activity.name,
                category=activity.category,
                estimatedTime=activity.estimatedTime,
                description=clean_desc,
                openingHours=activity.openingHours,
                ticketInfo=activity.ticketInfo,
                mapLink=activity.mapLink
            ))
        blocks.append(ItineraryBlock(
            time="Morning",
            activities=fallback_activities
        ))
    
    # If we don't have enough activities for all slots, fill with realistic local activities
    # This ensures every day has a complete schedule
    if blocks:
        # Check if we need to add generic activities
        morning_block = next((b for b in blocks if b.time == "Morning"), None)
        afternoon_block = next((b for b in blocks if b.time == "Afternoon"), None)
        evening_block = next((b for b in blocks if b.time == "Evening"), None)
        
        # If morning is empty or has too few activities, add realistic local activities
        if not morning_block or len(morning_block.activities) < 2:
            if not morning_block:
                morning_block = ItineraryBlock(time="Morning", activities=[])
                blocks.insert(0, morning_block)
            # Add realistic local activities if needed
            if len(morning_block.activities) < 2:
                # Create realistic local activities based on city type
                city_lower = city.lower()
                if "beach" in city_lower or any(word in city_lower for word in ["coast", "seaside", "shore"]):
                    generic_morning = Activity(
                        id=str(uuid.uuid4()),
                        name="Local beach walk",
                        category="attraction",
                        estimatedTime="2-3 hours",
                        description="Take a morning walk along the beach and enjoy the coastal views",
                    )
                elif any(word in city_lower for word in ["hill", "mountain", "view"]):
                    generic_morning = Activity(
                        id=str(uuid.uuid4()),
                        name="City viewpoint",
                        category="attraction",
                        estimatedTime="2-3 hours",
                        description="Visit a viewpoint to enjoy panoramic city views",
                    )
                else:
                    generic_morning = Activity(
                        id=str(uuid.uuid4()),
                        name=f"Explore {city}",
                        category="attraction",
                        estimatedTime="2-3 hours",
                        description=f"Explore the city and discover local attractions",
                    )
                morning_block.activities.append(generic_morning)
        
        # If afternoon has no non-restaurant activities, add realistic one
        if afternoon_block:
            non_restaurant_activities = [a for a in afternoon_block.activities if a.category != "restaurant"]
            if len(non_restaurant_activities) < 1:
                city_lower = city.lower()
                if "market" in city_lower or any(word in city_lower for word in ["bazaar", "shopping"]):
                    generic_afternoon = Activity(
                        id=str(uuid.uuid4()),
                        name="Street-food lane visit",
                        category="attraction",
                        estimatedTime="2-3 hours",
                        description="Explore local street food and shopping areas",
                    )
                else:
                    generic_afternoon = Activity(
                        id=str(uuid.uuid4()),
                        name="Local activities",
                        category="attraction",
                        estimatedTime="2-3 hours",
                        description="Enjoy local activities and explore the area",
                    )
                # Insert after restaurant if present
                restaurant_index = next((i for i, a in enumerate(afternoon_block.activities) if a.category == "restaurant"), len(afternoon_block.activities))
                afternoon_block.activities.insert(restaurant_index + 1, generic_afternoon)
    
    return ItineraryDay(
        date=date,
        city=city,
        blocks=blocks
    )

