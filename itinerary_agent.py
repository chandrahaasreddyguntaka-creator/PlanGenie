"""SerpAPI tools for finding flights and hotels."""
import os
import json
import re
import httpx
import logging
import time  # --- NEW --- Added for retries
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import quote
from models.plan import Flight, Hotel
import uuid

logger = logging.getLogger(__name__)

SERPAPI_KEY = os.getenv("SERPAPI_API_KEY")
SERPAPI_BASE = "https://serpapi.com/search"


def search_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
    adults: int = 1
) -> Dict[str, Any]:  # --- MODIFIED --- Now returns a Dict
    """
    Search for flights using SerpAPI Google Flights.
    Includes retries for network errors and returns a status dictionary.
    """
    if not SERPAPI_KEY:
        logger.error("SERPAPI_API_KEY not set! Cannot search flights. Please set SERPAPI_API_KEY in .env")
        # --- MODIFIED ---
        return {"status": "error", "message": "SERPAPI_API_KEY is not set in .env"}

    params = {
        "engine": "google_flights",
        "api_key": SERPAPI_KEY,
        "departure_id": origin.upper(),
        "arrival_id": destination.upper(),
        "outbound_date": depart_date,
        "adults": adults,
        "currency": "USD"
    }

    if return_date:
        params["return_date"] = return_date
        params["type"] = 1
    else:
        params["type"] = 2

    logger.info(f"Searching flights via SerpAPI: {origin} -> {destination} on {depart_date} (one-way: {not return_date})")
    logger.info(f"SerpAPI params: {dict((k, v) for k, v in params.items() if k != 'api_key')}")

    # --- NEW RETRY LOGIC ---
    retries = 3
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.get(SERPAPI_BASE, params=params)

                if response.status_code != 200:
                    error_msg = f"SerpAPI returned status {response.status_code}: {response.text[:500]}"
                    logger.error(error_msg)
                    # --- MODIFIED ---
                    return {"status": "error", "message": error_msg}

                response.raise_for_status()
                data = response.json()

                if "error" in data:
                    error_msg = data.get('error', '')
                    logger.error(f"SerpAPI error: {error_msg}")
                    # --- MODIFIED ---
                    return {"status": "no_results", "message": error_msg}

            logger.info(f"SerpAPI response keys: {list(data.keys())}")
            logger.info(f"SerpAPI response sample: {json.dumps(data, indent=2)[:1000]}")

            flights = []
            
            # (Your original parsing logic is preserved below)
            # ...
            best_flights = data.get("best_flights", [])
            other_flights = data.get("other_flights", [])
            flights_list = data.get("flights", [])
            organic_results = data.get("organic_results", [])
            
            logger.info(f"SerpAPI returned: {len(best_flights)} best_flights, {len(other_flights)} other_flights, {len(flights_list)} flights, {len(organic_results)} organic_results")

            all_flight_data = []
            if best_flights:
                all_flight_data.extend(best_flights[:10])
            if other_flights:
                all_flight_data.extend(other_flights[:20])
            if flights_list and not all_flight_data:
                all_flight_data.extend(flights_list[:20])
            if organic_results and not all_flight_data:
                for result in organic_results[:15]:
                    if "flights" in result or "flight" in result.get("title", "").lower():
                        all_flight_data.append(result)
            
            logger.info(f"Processing {len(all_flight_data)} flight data entries from SerpAPI")

            if not all_flight_data:
                logger.error(f"No flight data found in SerpAPI response for {origin} -> {destination} on {depart_date}")
                # --- MODIFIED ---
                return {"status": "no_results", "message": "No structured flight data was found in the API response."}

            currency_param = params.get("currency", "USD")
            is_round_trip = return_date is not None

            for idx, flight_data in enumerate(all_flight_data):
                try:
                    flight = _parse_flight_data(flight_data, origin, destination, depart_date, currency_param, is_return=False, return_date=return_date if is_round_trip else None)
                    if flight:
                        flights.append(flight)
                except Exception as e:
                    logger.error(f"Failed to parse flight data {idx}: {e}", exc_info=True)
                    continue
            
            logger.info(f"Successfully parsed {len(flights)} flights from {len(all_flight_data)} entries")
            
            if not flights:
                logger.error(f"❌ Failed to parse any flights! Check parsing logic.")
                # --- MODIFIED ---
                return {"status": "no_results", "message": "API returned data, but it could not be parsed."}

            # --- MODIFIED ---
            return {"status": "success", "data": flights[:15]}

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError) as e:
            logger.warning(f"Network error on attempt {attempt + 1}/{retries}: {e}")
            if attempt + 1 == retries:
                logger.error(f"SerpAPI flight search failed after {retries} retries.")
                return {"status": "error", "message": f"Network error: {e}"}

        # --- MODIFIED LINE ---
        # Exponential backoff: 1s, 2s, 4s
            wait_time = 2 ** attempt 
            logger.info(f"Waiting {wait_time}s before retrying...")
            time.sleep(wait_time)
            
        except Exception as e:
            logger.error(f"SerpAPI flight search failed: {e}", exc_info=True)
            # --- MODIFIED ---
            return {"status": "error", "message": f"A critical error occurred: {e}"}

    # Fallback in case loop finishes without returning
    return {"status": "error", "message": "Flight search failed after all retries."}


def _parse_flight_data(flight_data: Dict[str, Any], origin: str, destination: str, depart_date: str = "", currency: str = "USD", is_return: bool = False, return_date: str = None) -> Optional[Flight]:
    """Parse SerpAPI flight data into Flight model."""
    # (Your original _parse_flight_data function is unchanged)
    # (It's very robust, no changes needed here)
    try:
        flights = flight_data.get("flights", [])
        if not flights:
            if isinstance(flight_data, dict) and "airline" in flight_data:
                flights = [flight_data]
            else:
                logger.debug(f"No flights array found in flight_data. Keys: {list(flight_data.keys())}")
                return None
        
        if not flights or len(flights) == 0:
            logger.debug("Empty flights array")
            return None
        
        first_seg = flights[0]
        last_seg = flights[-1]
        
        logger.debug(f"First segment keys: {list(first_seg.keys())}")
        logger.debug(f"Last segment keys: {list(last_seg.keys())}")
        logger.debug(f"First segment: {json.dumps(first_seg, indent=2)[:500]}")
        logger.debug(f"Last segment: {json.dumps(last_seg, indent=2)[:500]}")
        
        airline_obj = first_seg.get("airline", {})
        if isinstance(airline_obj, dict):
            airline = airline_obj.get("name", airline_obj.get("name", "Unknown"))
        elif isinstance(airline_obj, str):
            airline = airline_obj
        else:
            airline = "Unknown"
        
        flight_number = first_seg.get("flight_number", "")
        if not flight_number:
            flight_number = first_seg.get("number", "")
        
        total_duration = 0
        duration_obj = flight_data.get("duration", {})
        logger.debug(f"Duration object type: {type(duration_obj)}, value: {duration_obj}")
        
        if isinstance(duration_obj, dict):
            total_duration = (
                duration_obj.get("total") or
                duration_obj.get("total_minutes") or
                duration_obj.get("minutes") or
                (duration_obj.get("hours", 0) * 60 + duration_obj.get("minutes", 0)) or
                0
            )
            if not total_duration and (duration_obj.get("hours") or duration_obj.get("minutes")):
                hours = duration_obj.get("hours", 0) or 0
                minutes = duration_obj.get("minutes", 0) or 0
                total_duration = hours * 60 + minutes
        elif isinstance(duration_obj, (int, float)):
            total_duration = int(duration_obj)
        elif isinstance(duration_obj, str):
            match = re.search(r'(\d+)h\s*(\d+)m', duration_obj, re.IGNORECASE)
            if match:
                total_duration = int(match.group(1)) * 60 + int(match.group(2))
            else:
                match = re.search(r'(\d+)', duration_obj)
                if match:
                    total_duration = int(match.group(1))
        
        if not total_duration:
            segment_durations = []
            for seg in flights:
                seg_dur = seg.get("duration", {})
                if isinstance(seg_dur, dict):
                    seg_min = seg_dur.get("minutes", seg_dur.get("total", 0))
                    if seg_min:
                        segment_durations.append(seg_min)
                elif isinstance(seg_dur, (int, float)):
                    segment_durations.append(int(seg_dur))
            if segment_durations:
                total_duration = sum(segment_durations)
                logger.debug(f"Calculated duration from segment durations: {total_duration} minutes")
        
        stops = len(flights) - 1
        
        price = 0
        price_data = flight_data.get("price", {})
        logger.debug(f"Price data type: {type(price_data)}, value: {price_data}")
        
        if isinstance(price_data, dict):
            price = (
                price_data.get("total") or
                price_data.get("price") or
                price_data.get("amount") or
                price_data.get("value") or
                0
            )
            if not price:
                for key in ["total", "price", "amount", "value"]:
                    val = price_data.get(key)
                    if val:
                        try:
                            if isinstance(val, str):
                                match = re.search(r'(\d+\.?\d*)', val)
                                if match:
                                    price = float(match.group(1))
                                    break
                            else:
                                price = float(val)
                                break
                        except:
                            continue
        elif isinstance(price_data, (int, float)):
            price = float(price_data)
        elif isinstance(price_data, str):
            match = re.search(r'(\d+\.?\d*)', price_data)
            if match:
                price = float(match.group(1))
        
        if not price:
            alt_price = flight_data.get("total_price") or flight_data.get("flight_price") or flight_data.get("cost")
            if alt_price:
                if isinstance(alt_price, (int, float)):
                    price = float(alt_price)
                elif isinstance(alt_price, str):
                    match = re.search(r'(\d+\.?\d*)', alt_price)
                    if match:
                        price = float(match.group(1))
        
        currency_str = currency
        currency_data = flight_data.get("currency")
        if currency_data:
            if isinstance(currency_data, str):
                currency_str = currency_data.upper()
            elif isinstance(currency_data, dict):
                currency_str = currency_data.get("code", currency_data.get("currency", currency)).upper()
        
        logger.info(f"💰 Price extraction - Raw: {price_data}, Extracted: ${price} {currency_str}")
        
        depart_airport = origin
        arrive_airport = destination
        depart_time = ""
        arrive_time = ""
        
        dep_airport_obj = first_seg.get("departure_airport", {})
        if isinstance(dep_airport_obj, dict):
            depart_airport = dep_airport_obj.get("id", dep_airport_obj.get("name", origin))
            time_str = dep_airport_obj.get("time", "")
            if time_str:
                try:
                    if " " in time_str:
                        depart_time = time_str.split(" ")[1]
                    elif "T" in time_str:
                        depart_time = time_str.split("T")[1].split("+")[0].split("Z")[0][:5]
                    else:
                        depart_time = time_str
                except:
                    depart_time = time_str
        elif isinstance(dep_airport_obj, str):
            depart_airport = dep_airport_obj
        
        arr_airport_obj = last_seg.get("arrival_airport", {})
        if isinstance(arr_airport_obj, dict):
            arrive_airport = arr_airport_obj.get("id", arr_airport_obj.get("name", destination))
            time_str = arr_airport_obj.get("time", "")
            if time_str:
                try:
                    if " " in time_str:
                        arrive_time = time_str.split(" ")[1]
                    elif "T" in time_str:
                        arrive_time = time_str.split("T")[1].split("+")[0].split("Z")[0][:5]
                    else:
                        arrive_time = time_str
                except:
                    arrive_time = time_str
        elif isinstance(arr_airport_obj, str):
            arrive_airport = arr_airport_obj
        
        if not depart_time:
            dep_time_obj = first_seg.get("departure_time", {})
            if isinstance(dep_time_obj, dict):
                depart_time = (dep_time_obj.get("time") or dep_time_obj.get("datetime") or "")
                if depart_time and "T" in str(depart_time):
                    try:
                        depart_time = str(depart_time).split("T")[1].split("+")[0].split("Z")[0][:5]
                    except: pass
            elif isinstance(dep_time_obj, str):
                depart_time = dep_time_obj
                if "T" in depart_time:
                    try:
                        depart_time = depart_time.split("T")[1].split("+")[0].split("Z")[0][:5]
                    except: pass
        
        if not arrive_time:
            arr_time_obj = last_seg.get("arrival_time", {})
            if isinstance(arr_time_obj, dict):
                arrive_time = (arr_time_obj.get("time") or arr_time_obj.get("datetime") or "")
                if arrive_time and "T" in str(arrive_time):
                    try:
                        arrive_time = str(arrive_time).split("T")[1].split("+")[0].split("Z")[0][:5]
                    except: pass
            elif isinstance(arr_time_obj, str):
                arrive_time = arr_time_obj
                if "T" in arrive_time:
                    try:
                        arrive_time = arrive_time.split("T")[1].split("+")[0].split("Z")[0][:5]
                    except: pass
        
        if not total_duration and depart_time and arrive_time:
            try:
                dep_dt = datetime.strptime(depart_time, "%H:%M")
                arr_dt = datetime.strptime(arrive_time, "%H:%M")
                if arr_dt < dep_dt:
                    arr_dt = arr_dt.replace(day=arr_dt.day + 1)
                diff = arr_dt - dep_dt
                total_duration = int(diff.total_seconds() / 60)
                logger.debug(f"Calculated duration from extracted times: {total_duration} minutes")
            except Exception as e:
                logger.debug(f"Could not calculate duration from extracted times: {e}")
        
        hours = total_duration // 60 if total_duration else 0
        minutes = total_duration % 60 if total_duration else 0
        duration_str = f"{hours}h {minutes}m" if hours or minutes else "Unknown"
        
        logger.info(f"⏰ Time extraction results - Depart: '{depart_time or 'MISSING'}', Arrive: '{arrive_time or 'MISSING'}', Duration: '{duration_str}'")
        
        booking_link = None
        booking_token = flight_data.get("booking_token")
        if isinstance(booking_token, dict):
            booking_link = booking_token.get("url") or booking_token.get("link")
        elif isinstance(booking_token, str):
            booking_link = booking_token
        
        if not booking_link:
            booking_url = flight_data.get("booking_url") or flight_data.get("link")
            if isinstance(booking_url, str):
                booking_link = booking_url
        
        date_str = flight_data.get("date", "")
        if not date_str and depart_date:
            date_str = depart_date
        if not date_str and "departure_time" in first_seg:
            dep_time = first_seg.get("departure_time", {})
            if isinstance(dep_time, dict):
                date_str = dep_time.get("date", "")
        
        try:
            is_round_trip = return_date is not None and str(return_date).strip() != ""
            if is_round_trip:
                search_query = f"Round-trip flights from {depart_airport} to {arrive_airport} on {date_str or depart_date} return {return_date}"
                params = {"q": search_query, "curr": "USD"}
            else:
                search_query = f"One-way flights from {depart_airport} to {arrive_airport} on {date_str or depart_date}"
                params = {"q": search_query, "curr": "USD"}
            
            query_string = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
            constructed_url = f"https://www.google.com/travel/flights?{query_string}"
            
            if not booking_link or not booking_link.startswith("http"):
                booking_link = constructed_url
            else:
                logger.debug(f"Using provided booking link: {booking_link}")
                logger.debug(f"Alternative constructed URL: {constructed_url}")
            
            logger.debug(f"Final booking link: {booking_link}")
        except Exception as e:
            logger.warning(f"Failed to construct Google Flights URL: {e}")
            is_round_trip = return_date is not None and str(return_date).strip() != ""
            if is_round_trip:
                booking_link = booking_link or f"https://www.google.com/travel/flights?q=Round-trip+flights+from+{depart_airport}+to+{arrive_airport}+on+{depart_date}+return+{return_date}&curr=USD"
            else:
                booking_link = booking_link or f"https://www.google.com/travel/flights?q=One-way+flights+from+{depart_airport}+to+{arrive_airport}+on+{depart_date}&curr=USD"
        
        if not booking_link or not booking_link.startswith("http"):
            is_round_trip = return_date is not None and str(return_date).strip() != ""
            if is_round_trip:
                booking_link = f"https://www.google.com/travel/flights?q=Round-trip+flights+from+{depart_airport}+to+{arrive_airport}+on+{depart_date}+return+{return_date}&curr=USD"
            else:
                booking_link = f"https://www.google.com/travel/flights?q=One-way+flights+from+{depart_airport}+to+{arrive_airport}+on+{depart_date}&curr=USD"
        
        flight_display_number = flight_number
        
        flight = Flight(
            id=str(uuid.uuid4()),
            airline=str(airline),
            flightNumber=str(flight_display_number),
            departAirport=str(depart_airport),
            arriveAirport=str(arrive_airport),
            departTime=str(depart_time) if depart_time else "Unknown",
            arriveTime=str(arrive_time) if arrive_time else "Unknown",
            duration=duration_str,
            stops=stops,
            cabin="Economy",
            price=float(price) if price else 0.0,
            currency=currency_str,
            bookingLink=booking_link,
            date=depart_date,
            dateTooFarAhead=False
        )
        
        logger.info(f"✅ Parsed flight: {airline} {flight_number} | {depart_airport} → {arrive_airport} | {depart_time} → {arrive_time} | Duration: {duration_str} | Price: ${price} | Booking: {'Yes' if booking_link else 'No'}")
        return flight
        
    except Exception as e:
        logger.error(f"Error parsing flight: {e}", exc_info=True)
        logger.debug(f"Flight data that failed: {json.dumps(flight_data, indent=2)[:500]}")
        return None


def search_hotels(
    location: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    rooms: int = 1
) -> Dict[str, Any]:  # --- MODIFIED --- Now returns a Dict
    """
    Search for hotels using SerpAPI Google Hotels.
    Includes retries and returns a status dictionary.
    """
    if not SERPAPI_KEY:
        logger.warning("SERPAPI_API_KEY not set, returning empty hotel results")
        # --- MODIFIED ---
        return {"status": "error", "message": "SERPAPI_API_KEY is not set in .env"}

    params = {
        "engine": "google_hotels",
        "api_key": SERPAPI_KEY,
        "q": location,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": adults,
        "rooms": rooms,
        "currency": "USD"
    }

    logger.info(f"Searching hotels via SerpAPI: {location} from {check_in} to {check_out}")
    logger.info(f"SerpAPI params: {dict((k, v) for k, v in params.items() if k != 'api_key')}")

    # --- NEW RETRY LOGIC ---
    retries = 3
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.get(SERPAPI_BASE, params=params)
                logger.info(f"SerpAPI hotel response status: {response.status_code}")
                
                if response.status_code != 200:
                    error_msg = f"SerpAPI returned status {response.status_code}: {response.text[:500]}"
                    logger.error(error_msg)
                    # --- MODIFIED ---
                    return {"status": "error", "message": error_msg}

                response.raise_for_status()
                data = response.json()

            logger.info(f"SerpAPI hotel response keys: {list(data.keys())}")
            logger.info(f"SerpAPI hotel response sample: {json.dumps(data, indent=2)[:1000]}")

            hotels = []
            
            properties = data.get("properties", [])
            if not properties:
                properties = data.get("hotels", []) or data.get("organic_results", [])
            
            logger.info(f"Found {len(properties)} hotel properties in SerpAPI response")

            if not properties:
                logger.warning("No hotel properties found in SerpAPI response.")
                # --- MODIFIED ---
                return {"status": "no_results", "message": "No hotel properties were found for this search."}

            if properties:
                logger.info(f"📋 Sample hotel data structure (first hotel): {json.dumps(properties[0], indent=2)[:2000]}")

            for idx, prop_data in enumerate(properties[:10]):
                try:
                    logger.info(f"🔍 Parsing hotel data entry {idx}: {list(prop_data.keys()) if isinstance(prop_data, dict) else type(prop_data)}")
                    hotel = _parse_hotel_data(prop_data, check_in, check_out)
                    if hotel:
                        hotels.append(hotel)
                        logger.info(f"✅ Successfully parsed hotel {idx}: {hotel.name} - ${hotel.nightlyPrice}/night, ${hotel.totalPrice} total")
                    else:
                        logger.warning(f"❌ Hotel {idx} parsed to None. Data: {json.dumps(prop_data, indent=2)[:500]}")
                except Exception as e:
                    logger.error(f"Failed to parse hotel data {idx}: {e}", exc_info=True)
                    continue
            
            logger.info(f"Successfully parsed {len(hotels)} hotels from {len(properties)} properties")
            if not hotels and properties:
                logger.error(f"Failed to parse any hotels! Check parsing logic. Sample data: {json.dumps(properties[0] if properties else {}, indent=2)[:500]}")
                # --- MODIFIED ---
                return {"status": "no_results", "message": "API returned hotel data, but it could not be parsed."}

            # --- MODIFIED ---
            return {"status": "success", "data": hotels}

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError) as e:
            logger.warning(f"Network error on attempt {attempt + 1}/{retries}: {e}")
            if attempt + 1 == retries:
                logger.error(f"SerpAPI hotel search failed after {retries} retries.")
                return {"status": "error", "message": f"Network error: {e}"}

        # --- MODIFIED LINE ---
        # Exponential backoff: 1s, 2s, 4s
            wait_time = 2 ** attempt 
            logger.info(f"Waiting {wait_time}s before retrying...")
            time.sleep(wait_time)

        except Exception as e:
            logger.error(f"SerpAPI hotel search failed: {e}", exc_info=True)
            # --- MODIFIED ---
            return {"status": "error", "message": f"A critical error occurred: {e}"}
            
    # Fallback
    return {"status": "error", "message": "Hotel search failed after all retries."}


def _parse_hotel_data(prop_data: Dict[str, Any], check_in: str, check_out: str) -> Optional[Hotel]:
    """Parse SerpAPI hotel data into Hotel model."""
    # (Your original _parse_hotel_data function is unchanged)
    # (It's very robust, no changes needed here)
    try:
        name = prop_data.get("name", "Unknown Hotel")
        rating = prop_data.get("rating", 0)
        stars = int(rating) if rating else 3
        
        location = prop_data.get("location", {})
        neighborhood = location.get("neighborhood", location.get("city", ""))
        
        nightly_price = 0
        total_price = 0
        
        rate_per_night = prop_data.get("rate_per_night", {})
        if isinstance(rate_per_night, dict):
            nightly_price = rate_per_night.get("extracted_lowest") or rate_per_night.get("lowest") or 0
            if isinstance(nightly_price, str):
                match = re.search(r'(\d+\.?\d*)', nightly_price)
                if match:
                    nightly_price = float(match.group(1))
                else:
                    nightly_price = 0
            elif nightly_price:
                nightly_price = float(nightly_price)
        
        total_rate = prop_data.get("total_rate", {})
        if isinstance(total_rate, dict):
            total_price = total_rate.get("extracted_lowest") or total_rate.get("lowest") or 0
            if isinstance(total_price, str):
                match = re.search(r'(\d+\.?\d*)', total_price)
                if match:
                    total_price = float(match.group(1))
                else:
                    total_price = 0
            elif total_price:
                total_price = float(total_price)
        
        if not total_price and nightly_price:
            total_price = nightly_price
        
        if not nightly_price:
            price_data = prop_data.get("price", {})
            logger.debug(f"Hotel price data type: {type(price_data)}, value: {price_data}")
            
            if isinstance(price_data, dict):
                nightly_price = (
                    price_data.get("nightly") or
                    price_data.get("per_night") or
                    price_data.get("rate") or
                    price_data.get("price") or
                    price_data.get("amount") or
                    0
                )
                if not total_price:
                    total_price = (
                        price_data.get("total") or
                        price_data.get("total_price") or
                        price_data.get("full_price") or
                        price_data.get("cost") or
                        nightly_price
                    )
                
                if isinstance(nightly_price, str):
                    match = re.search(r'(\d+\.?\d*)', nightly_price)
                    if match:
                        nightly_price = float(match.group(1))
                    else:
                        nightly_price = 0
                
                if isinstance(total_price, str):
                    match = re.search(r'(\d+\.?\d*)', str(total_price))
                    if match:
                        total_price = float(match.group(1))
                    else:
                        total_price = nightly_price
            
            elif isinstance(price_data, (int, float)):
                nightly_price = float(price_data)
                if not total_price:
                    total_price = nightly_price
            
            elif isinstance(price_data, str):
                match = re.search(r'(\d+\.?\d*)', price_data)
                if match:
                    nightly_price = float(match.group(1))
                    if not total_price:
                        total_price = nightly_price
        
        if not nightly_price:
            alt_nightly = prop_data.get("nightly_price") or prop_data.get("rate") or prop_data.get("price_per_night")
            if alt_nightly:
                if isinstance(alt_nightly, (int, float)):
                    nightly_price = float(alt_nightly)
                elif isinstance(alt_nightly, str):
                    match = re.search(r'(\d+\.?\d*)', alt_nightly)
                    if match:
                        nightly_price = float(match.group(1))
        
        if not total_price:
            alt_total = prop_data.get("total_price") or prop_data.get("full_price") or prop_data.get("cost")
            if alt_total:
                if isinstance(alt_total, (int, float)):
                    total_price = float(alt_total)
                elif isinstance(alt_total, str):
                    match = re.search(r'(\d+\.?\d*)', alt_total)
                    if match:
                        total_price = float(match.group(1))
            else:
                total_price = nightly_price
        
        currency_str = "USD"
        price_data = prop_data.get("price", {})
        currency_data = prop_data.get("currency") or (price_data.get("currency") if isinstance(price_data, dict) else None)
        if currency_data:
            if isinstance(currency_data, str):
                currency_str = currency_data.upper()
            elif isinstance(currency_data, dict):
                currency_str = currency_data.get("code", currency_data.get("currency", "USD")).upper()
        
        logger.info(f"💰 Hotel price extraction - Raw: {price_data}, Nightly: ${nightly_price}, Total: ${total_price}, Currency: {currency_str}")
        
        if not nightly_price and not total_price:
            logger.warning(f"⚠️ No price found for hotel {name}. Available keys: {list(prop_data.keys())}")
            logger.debug(f"Full hotel data: {json.dumps(prop_data, indent=2)[:1000]}")
        
        amenities = prop_data.get("amenities", [])
        if isinstance(amenities, list):
            amenity_list = [str(a) for a in amenities[:10]]
        else:
            amenity_list = []
        
        images = prop_data.get("images", [])
        if isinstance(images, list):
            image_list = [str(img) for img in images[:5]]
        else:
            image_list = []
        
        return Hotel(
            id=str(uuid.uuid4()),
            name=name,
            stars=stars,
            neighborhood=neighborhood,
            refundable=prop_data.get("refundable", False),
            nightlyPrice=float(nightly_price) if nightly_price else 0.0,
            totalPrice=float(total_price) if total_price else 0.0,
            currency=currency_str,
            amenities=amenity_list,
            images=image_list if image_list else None,
            bookingLink=prop_data.get("link") or prop_data.get("booking_link") or prop_data.get("url"),
            phone=prop_data.get("phone")
        )
    except Exception as e:
        logger.error(f"Error parsing hotel: {e}")
        return None