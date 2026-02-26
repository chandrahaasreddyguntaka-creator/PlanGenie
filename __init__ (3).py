"""Tavily search tools for POIs, restaurants, and experiences."""
import os
import httpx
import logging
from typing import List, Dict, Any, Optional
from models.plan import Activity
import uuid

logger = logging.getLogger(__name__)

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
TAVILY_BASE = "https://api.tavily.com/search"


def search_attractions(
    city: str,
    date_range: Optional[str] = None,
    budget: Optional[str] = None
) -> List[Activity]:
    """
    Search for attractions and POIs using Tavily.
    
    Args:
        city: City name
        date_range: Date range (optional, for context)
        budget: Budget level (optional)
    
    Returns:
        List of Activity objects
    """
    if not TAVILY_KEY:
        logger.warning("TAVILY_API_KEY not set, returning empty attraction results")
        return []
    
    try:
        query = f"top attractions things to do {city}"
        if budget:
            query += f" {budget} budget"
        
        payload = {
            "api_key": TAVILY_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 10
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAVILY_BASE}", json=payload)
            response.raise_for_status()
            data = response.json()
        
        activities = []
        results = data.get("results", [])
        
        for result in results[:10]:
            try:
                activity = _parse_activity_data(result, "attraction")
                if activity:
                    activities.append(activity)
            except Exception as e:
                logger.warning(f"Failed to parse activity: {e}")
                continue
        
        return activities
    
    except Exception as e:
        logger.error(f"Tavily attraction search failed: {e}")
        return []


def search_restaurants(
    city: str,
    cuisine: Optional[str] = None,
    budget: Optional[str] = None
) -> List[Activity]:
    """
    Search for restaurants using Tavily.
    
    Args:
        city: City name
        cuisine: Cuisine type (optional)
        budget: Budget level (optional)
    
    Returns:
        List of Activity objects
    """
    if not TAVILY_KEY:
        logger.warning("TAVILY_API_KEY not set, returning empty restaurant results")
        return []
    
    try:
        query = f"best restaurants {city}"
        if cuisine:
            query += f" {cuisine}"
        if budget:
            query += f" {budget} budget"
        
        payload = {
            "api_key": TAVILY_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 10
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAVILY_BASE}", json=payload)
            response.raise_for_status()
            data = response.json()
        
        activities = []
        results = data.get("results", [])
        
        for result in results[:10]:
            try:
                activity = _parse_activity_data(result, "restaurant")
                if activity:
                    activities.append(activity)
            except Exception as e:
                logger.warning(f"Failed to parse restaurant: {e}")
                continue
        
        return activities
    
    except Exception as e:
        logger.error(f"Tavily restaurant search failed: {e}")
        return []


def search_experiences(
    city: str,
    activity_type: Optional[str] = None
) -> List[Activity]:
    """
    Search for experiences and activities using Tavily.
    
    Args:
        city: City name
        activity_type: Type of experience (optional, e.g., "tours", "museums", "nightlife")
    
    Returns:
        List of Activity objects
    """
    if not TAVILY_KEY:
        logger.warning("TAVILY_API_KEY not set, returning empty experience results")
        return []
    
    try:
        query = f"experiences activities {city}"
        if activity_type:
            query += f" {activity_type}"
        
        payload = {
            "api_key": TAVILY_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 10
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{TAVILY_BASE}", json=payload)
            response.raise_for_status()
            data = response.json()
        
        activities = []
        results = data.get("results", [])
        
        for result in results[:10]:
            try:
                activity = _parse_activity_data(result, "experience")
                if activity:
                    activities.append(activity)
            except Exception as e:
                logger.warning(f"Failed to parse experience: {e}")
                continue
        
        return activities
    
    except Exception as e:
        logger.error(f"Tavily experience search failed: {e}")
        return []


def _parse_activity_data(result: Dict[str, Any], category: str) -> Optional[Activity]:
    """Parse Tavily result into Activity model."""
    try:
        title = result.get("title", "Unknown Activity")
        content = result.get("content", "")
        url = result.get("url", "")
        
        # Extract description (first 200 chars of content)
        description = content[:200] + "..." if len(content) > 200 else content
        
        return Activity(
            id=str(uuid.uuid4()),
            name=title,
            category=category,
            description=description if description else None,
            estimatedTime="2-3 hours",  # Default
            mapLink=url if url else None
        )
    except Exception as e:
        logger.error(f"Error parsing activity: {e}")
        return None

