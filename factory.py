"""Orchestrator: coordinates agents, streaming, and plan generation."""
import asyncio
import json
import logging
import re
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from models.plan import ChatPlan, TripRequest, Flight, Hotel, ItineraryDay, ErrorItem, Meta
from models.segment_types import SegmentType
from agents.flight_agent import search_flights_agent
from agents.hotel_agent import search_hotels_agent
from agents.itinerary_agent import plan_itinerary_agent
from memory.state import MemoryManager
from llm.factory import make_ollama
from llm.ollama_wrapper import call_ollama
from langchain.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


class Orchestrator:
    """Orchestrates plan generation with streaming support."""
    
    def __init__(self, thread_id: str, user_id: Optional[int] = None):
        self.thread_id = thread_id
        self.user_id = user_id
        self.memory = MemoryManager(thread_id, user_id=user_id)
        self.shimmer_active = False
        self.shimmer_task: Optional[asyncio.Task] = None
    
    async def process_request_stream(
        self,
        user_message: str,
        segment_callback: Callable[[str], None]
    ) -> ChatPlan:
        """
        Process a user request and stream results via callback.
        
        Args:
            user_message: User's message
            segment_callback: Function to call with SSE-formatted segments
        
        Returns:
            Final ChatPlan
        """
        try:
            # Check if query is travel-related
            is_travel_query = await self._is_travel_related(user_message)
            
            if not is_travel_query:
                # Handle non-travel queries
                return await self._handle_non_travel_query(user_message, segment_callback)
            
            # Load existing plan if available
            from memory.state import get_latest_plan
            existing_plan_data = get_latest_plan(self.thread_id)
            existing_plan = None
            if existing_plan_data:
                try:
                    existing_plan = ChatPlan(**existing_plan_data)
                    logger.info(f"Loaded existing plan with {len(existing_plan.flights)} flights, {len(existing_plan.hotels)} hotels, {len(existing_plan.itinerary.get('days', []))} itinerary days")
                except Exception as e:
                    logger.warning(f"Failed to parse existing plan: {e}")
                    existing_plan = None
            
            # Detect if this is an edit request
            edit_intent = await self._detect_edit_intent(user_message, existing_plan)
            
            # Fallback: If we have an existing plan and edit keywords but no edit_intent,
            # try to detect if it's a day removal request
            if not edit_intent and existing_plan:
                message_lower = user_message.lower()
                # Check for day removal keywords
                removal_keywords = ['block', 'remove', 'delete', 'skip', 'cancel']
                date_keywords = ['december', 'january', 'february', 'march', 'april', 'may', 'june',
                                'july', 'august', 'september', 'october', 'november', 'dec', 'jan', 'feb', 'mar',
                                'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov']
                has_removal_keyword = any(keyword in message_lower for keyword in removal_keywords)
                has_date_keyword = any(keyword in message_lower for keyword in date_keywords)
                
                if has_removal_keyword and has_date_keyword:
                    # Likely a day removal request
                    logger.info("Fallback: Detected day removal request based on keywords")
                    # Try to extract date
                    extracted_dates = self._extract_dates(user_message)
                    
                    # Fix year to match trip year if we have a depart_date
                    if extracted_dates and existing_plan.request.depart_date:
                        try:
                            from datetime import datetime
                            depart_year = datetime.strptime(existing_plan.request.depart_date, "%Y-%m-%d").year
                            for i, date_str in enumerate(extracted_dates):
                                try:
                                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                                    if date_obj.year != depart_year:
                                        fixed_date = date_obj.replace(year=depart_year)
                                        extracted_dates[i] = fixed_date.strftime("%Y-%m-%d")
                                        logger.info(f"Fallback: Fixed date year to match trip year: {extracted_dates[i]}")
                                except:
                                    pass
                        except:
                            pass
                    
                    if extracted_dates:
                        edit_intent = {
                            "is_edit": True,
                            "edit_type": "itinerary_remove",
                            "target_date": extracted_dates[0],
                            "day_number": None,
                            "details": "Remove/block day from itinerary"
                        }
                        logger.info(f"Created fallback edit_intent: {edit_intent}")
            
            if edit_intent and existing_plan:
                # Handle incremental edit
                return await self._handle_incremental_edit(
                    user_message, 
                    edit_intent, 
                    existing_plan, 
                    segment_callback
                )
            
            # Send immediate progress update
            await self._send_initial_progress(segment_callback, user_message)
            
            # Understand intent
            logger.info("🔍 Step 1: Understanding your request...")
            intent, requested_components = await self._understand_intent(user_message)
            logger.info(f"✅ Intent extracted: {intent.origin} -> {intent.destination}, depart: {intent.depart_date}, return: {intent.return_date}")
            logger.info(f"📋 Requested components: {requested_components}")
            
            # Check for missing critical information and ask user before proceeding
            missing_info = self._check_missing_information(intent, requested_components)
            if missing_info:
                # Ask user for missing information using LLM
                clarification_message = await self._format_clarification_question(missing_info, intent, requested_components)
                from utils.sse import create_text_chunk, create_summary_segment
                segment_callback(create_text_chunk(clarification_message, seq=0))
                segment_callback(create_summary_segment(
                    summary=clarification_message,
                    notes="",
                    final=True
                ))
                
                # Save to memory
                self.memory.save_to_supabase(
                    user_message=user_message,
                    assistant_response=clarification_message,
                    plan=None,
                    trip_constraints=intent
                )
                
                # Return empty plan with clarification
                return ChatPlan(
                    request=intent,
                    summary=clarification_message,
                    notes=""
                )
            
            # Determine which agents to run based on user's requested components
            agents_needed = self._determine_agents_needed(intent, requested_components)
            logger.info(f"🤖 Agents to run: {agents_needed}")
            
            # Start shimmer loop for continuous progress updates
            self.shimmer_active = True
            self.shimmer_task = asyncio.create_task(
                self._shimmer_loop(segment_callback, agents_needed)
            )
            
            # Run agents in parallel
            logger.info("🚀 Step 2: Running agents in parallel...")
            results = await self._run_agents_parallel(intent, agents_needed, segment_callback)
            logger.info(f"✅ Agents completed. Results keys: {list(results.keys())}")
            for agent_name, result in results.items():
                if isinstance(result, dict):
                    if agent_name == "FLIGHTS":
                        logger.info(f"  - FLIGHTS: {len(result.get('flights', []))} flights")
                    elif agent_name == "HOTELS":
                        logger.info(f"  - HOTELS: {len(result.get('hotels', []))} hotels")
                    elif agent_name == "ITINERARY":
                        itinerary_days = result.get('itinerary', {}).get('days', [])
                        logger.info(f"  - ITINERARY: {len(itinerary_days)} days")
            
            # Stop shimmer before generating summary
            self.shimmer_active = False
            if self.shimmer_task:
                self.shimmer_task.cancel()
                try:
                    await self.shimmer_task
                except asyncio.CancelledError:
                    pass
            
            # Send a final progress message before summary
            from utils.sse import create_text_chunk
            segment_callback(create_text_chunk("Finalizing your plan...", seq=999))
            logger.info("📝 Step 3: Generating summary...")
            
            # Generate summary - scope to requested components
            summary = await self._generate_summary(intent, results, requested_components)
            logger.info(f"✅ Summary generated: {summary.get('summary', '')[:100]}...")
            
            # Build unified plan - only include requested components
            logger.info("📦 Step 4: Building unified plan...")
            plan = self._build_plan(intent, results, summary, requested_components)
            logger.info(f"✅ Plan built: {len(plan.flights)} flights, {len(plan.hotels)} hotels, {len(plan.itinerary.get('days', []))} itinerary days")
            
            # Stream summary
            from utils.sse import create_summary_segment
            segment_callback(create_summary_segment(
                summary=summary.get("summary", ""),
                notes=plan.notes,
                final=True
            ))
            
            # Save to memory
            self.memory.save_to_supabase(
                user_message=user_message,
                assistant_response=summary.get("summary", ""),
                plan=plan,
                trip_constraints=intent
            )
            
            return plan
        
        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            self.shimmer_active = False
            if self.shimmer_task:
                self.shimmer_task.cancel()
            
            # Create user-friendly error message
            error_msg = str(e)
            user_message = f"Error processing request: {error_msg[:200]}"
            
            # Stream error
            from utils.sse import create_error_segment
            segment_callback(create_error_segment(
                message=user_message,
                agent="ORCHESTRATOR"
            ))
            
            # Return empty plan with error
            return ChatPlan(
                request=TripRequest(),
                errors=[ErrorItem(message=user_message, agent="ORCHESTRATOR")]
            )
    
    async def _is_travel_related(self, user_message: str) -> bool:
        """
        Check if the user's message is travel-related.
        
        Returns:
            True if travel-related, False otherwise
        """
        # Strong travel-related keywords (removed generic words like 'city', 'place', 'location')
        strong_travel_keywords = [
            'travel', 'trip', 'flight', 'hotel', 'vacation', 'holiday', 'journey',
            'destination', 'visit', 'tour', 'itinerary', 'booking', 'reservation',
            'airport', 'airline', 'accommodation', 'stay', 'lodging', 'resort',
            'attraction', 'sightseeing', 'restaurant', 'dining', 'cuisine',
            'go to', 'going to', 'plan a trip', 'plan trip', 'planning a trip',
            'schedule', 'depart', 'arrive', 'round trip', 'one way', 'return',
            'departure', 'arrival', 'book flight', 'book hotel', 'find flight',
            'find hotel', 'search flight', 'search hotel'
        ]
        
        message_lower = user_message.lower().strip()
        
        # Check if message contains strong travel keywords
        for keyword in strong_travel_keywords:
            if keyword in message_lower:
                logger.info(f"Detected travel keyword: '{keyword}' in message")
                return True
        
        # Use LLM to check if it's travel-related (more nuanced)
        # This is important for edge cases
        try:
            from llm.ollama_wrapper import call_ollama
            from langchain.prompts import ChatPromptTemplate
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a travel assistant. Determine if the user's message is asking about:
- Planning a trip or vacation
- Booking flights, hotels, or travel accommodations
- Finding destinations to visit
- Creating travel itineraries
- Travel-related questions

If the message is about general knowledge, questions unrelated to travel, or anything else, return "no".

Return ONLY "yes" or "no" - nothing else."""),
                ("human", "User message: {message}\n\nIs this asking about travel planning or travel-related services?")
            ])
            
            result = await call_ollama(
                "ORCHESTRATOR",
                lambda llm: (prompt | llm).ainvoke({"message": user_message})
            )
            
            response = result.content.strip().lower()
            is_travel = "yes" in response and "no" not in response
            logger.info(f"LLM travel detection result: {response} -> {is_travel}")
            return is_travel
            
        except Exception as e:
            logger.warning(f"Failed to check if query is travel-related: {e}")
            # Default to NOT travel-related if check fails (safer)
            return False
    
    async def _handle_non_travel_query(
        self,
        user_message: str,
        segment_callback: Callable[[str], None]
    ) -> ChatPlan:
        """
        Handle non-travel related queries.
        Provides a basic answer and redirects to travel queries.
        """
        try:
            from llm.ollama_wrapper import call_ollama
            from langchain.prompts import ChatPromptTemplate
            from utils.sse import create_text_chunk, create_summary_segment
            
            # Get a basic answer to the question
            answer_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a helpful assistant. Provide a brief, factual answer to the user's question in 1-2 sentences."""),
                ("human", "{message}")
            ])
            
            try:
                answer_result = await call_ollama(
                    "ORCHESTRATOR",
                    lambda llm: (answer_prompt | llm).ainvoke({"message": user_message})
                )
                basic_answer = answer_result.content.strip()
            except Exception as e:
                logger.warning(f"Failed to generate basic answer: {e}")
                basic_answer = "I can provide some information, but"
            
            # Create response message
            response_message = f"{basic_answer}\n\nI'm a travel planning assistant, so I can help you much better with travel-related queries like planning trips, finding flights, booking hotels, or creating itineraries. How can I assist you with your travel plans?"
            
            # Stream the response
            segment_callback(create_text_chunk(response_message, seq=0))
            
            # Create summary segment
            segment_callback(create_summary_segment(
                summary=response_message,
                notes="",
                final=True
            ))
            
            # Save to memory
            self.memory.save_to_supabase(
                user_message=user_message,
                assistant_response=response_message,
                plan=None,
                trip_constraints=None
            )
            
            # Return empty plan
            return ChatPlan(
                request=TripRequest(),
                summary=response_message,
                notes=""
            )
            
        except Exception as e:
            logger.error(f"Error handling non-travel query: {e}")
            # Fallback response
            from utils.sse import create_text_chunk, create_summary_segment
            
            fallback_message = "I'm a travel planning assistant. I can help you with planning trips, finding flights, booking hotels, or creating itineraries. How can I assist you with your travel plans?"
            
            segment_callback(create_text_chunk(fallback_message, seq=0))
            segment_callback(create_summary_segment(
                summary=fallback_message,
                notes="",
                final=True
            ))
            
            return ChatPlan(
                request=TripRequest(),
                summary=fallback_message,
                notes=""
            )
    
    async def _detect_edit_intent(
        self, 
        user_message: str, 
        existing_plan: Optional[ChatPlan]
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if user wants to edit an existing plan.
        
        Returns:
            Dict with edit type and details, or None if not an edit request
        """
        if not existing_plan:
            return None
        
        message_lower = user_message.lower()
        
        # Check for edit keywords
        edit_keywords = [
            'change', 'edit', 'update', 'modify', 'replace', 'swap', 'remove', 'delete',
            'redo', 'regenerate', 'different', 'instead', 'instead of', 'rather than',
            'block', 'skip', 'cancel'
        ]
        
        has_edit_keyword = any(keyword in message_lower for keyword in edit_keywords)
        
        if not has_edit_keyword:
            return None
        
        # Use LLM to detect what part to edit
        try:
            from llm.ollama_wrapper import call_ollama
            from langchain.prompts import ChatPromptTemplate
            
            # Get summary of existing plan
            plan_summary = f"Plan has {len(existing_plan.flights)} flights, {len(existing_plan.hotels)} hotels, {len(existing_plan.itinerary.get('days', []))} itinerary days"
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are analyzing a user's request to edit an existing travel plan. Determine what part they want to change.

Return ONLY valid JSON:
{{
  "is_edit": true/false,
  "edit_type": "dates" | "flights" | "hotels" | "itinerary_day" | "itinerary_remove" | "itinerary_activity" | "itinerary_swap" | "full" | null,
  "day_number": number or null (if editing specific day, e.g., 2 for "day 2"),
  "target_date": "YYYY-MM-DD or null (if user mentions a specific date like 'december 22')",
  "activity_name": "name of activity to remove/swap or null",
  "source_day": number or null (for swapping activities),
  "target_day": number or null (for swapping activities),
  "details": "brief description of what to change"
}}

Edit types:
- "dates": Changing departure/return dates (start or end date) - ONLY this type should regenerate flights/hotels
- "flights": Changing flight options
- "hotels": Changing hotel options  
- "itinerary_day": Regenerating/replacing a specific day (e.g., "redo day 2", "change day 3")
- "itinerary_remove": Removing/blocking a specific day or date (e.g., "block december 22", "remove day 3")
- "itinerary_activity": Removing or replacing a specific activity (e.g., "remove the beach on day 3", "replace museum with park")
- "itinerary_swap": Swapping activities between days (e.g., "swap day 2 and day 5 morning activities")
- "full": Complete regeneration
- null: Not an edit request

IMPORTANT: 
- Only use "dates" if the user is changing the START or END date of the trip. If they're just modifying/removing a day in the middle, use "itinerary_day" or "itinerary_remove".
- Use "itinerary_activity" for removing or replacing a single activity within a day.
- Use "itinerary_swap" when the user wants to exchange activities between different days."""),
                ("human", """Existing plan: {plan_summary}
User message: {message}

What part does the user want to edit?""")
            ])
            
            result = await call_ollama(
                "ORCHESTRATOR",
                lambda llm: (prompt | llm).ainvoke({
                    "plan_summary": plan_summary,
                    "message": user_message
                })
            )
            
            response_text = result.content.strip()
            # Extract JSON
            if "{" in response_text:
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                json_str = response_text[json_start:json_end]
                edit_intent = json.loads(json_str)
                
                if edit_intent.get("is_edit") and edit_intent.get("edit_type"):
                    logger.info(f"Detected edit intent: {edit_intent}")
                    return edit_intent
            
        except Exception as e:
            logger.warning(f"Failed to detect edit intent: {e}")
        
        return None
    
    async def _handle_incremental_edit(
        self,
        user_message: str,
        edit_intent: Dict[str, Any],
        existing_plan: ChatPlan,
        segment_callback: Callable[[str], None]
    ) -> ChatPlan:
        """
        Handle incremental edits to existing plan.
        Only updates the specific part requested, leaving everything else unchanged.
        """
        from utils.sse import create_text_chunk, create_summary_segment
        
        edit_type = edit_intent.get("edit_type")
        day_number = edit_intent.get("day_number")
        
        logger.info(f"Handling incremental edit: type={edit_type}, day={day_number}")
        
        # Send progress update
        segment_callback(create_text_chunk(f"Updating {edit_type}...", seq=0))
        
        # Create a copy of existing plan to modify
        updated_plan = existing_plan
        
        try:
            if edit_type == "dates":
                # Update dates and regenerate flights/hotels/itinerary
                # Merge new intent with existing plan to preserve origin/destination if not mentioned
                # Start with existing plan's intent
                intent = existing_plan.request
                
                # Add context about existing plan to help intent understanding
                context_message = f"""You are updating an existing travel plan. The current plan is:
- Origin: {existing_plan.request.origin}
- Destination: {existing_plan.request.destination}
- Departure date: {existing_plan.request.depart_date}
- Return date: {existing_plan.request.return_date or 'N/A'}

User request: {user_message}

Extract ONLY the changed information. You MUST preserve the origin and destination from the existing trip unless the user explicitly changes them. If the user only mentions a date change, keep the origin and destination the same."""
                
                new_intent, _ = await self._understand_intent(context_message)
                
                # Update dates from new intent (if provided)
                if new_intent.depart_date:
                    intent.depart_date = new_intent.depart_date
                if new_intent.return_date is not None:  # Allow clearing return_date
                    intent.return_date = new_intent.return_date
                
                # Only update origin/destination if explicitly provided and not empty
                if new_intent.origin and new_intent.origin.strip() and new_intent.origin != existing_plan.request.origin:
                    intent.origin = new_intent.origin
                if new_intent.destination and new_intent.destination.strip() and new_intent.destination != existing_plan.request.destination:
                    intent.destination = new_intent.destination
                
                # If origin/destination are empty in new_intent, ensure we keep existing ones
                if not intent.origin or not intent.origin.strip():
                    intent.origin = existing_plan.request.origin
                if not intent.destination or not intent.destination.strip():
                    intent.destination = existing_plan.request.destination
                
                # Update other fields if provided
                if new_intent.adults:
                    intent.adults = new_intent.adults
                if new_intent.budget:
                    intent.budget = new_intent.budget
                
                updated_plan.request = intent
                
                logger.info(f"Updated intent after date change: origin={intent.origin}, dest={intent.destination}, depart={intent.depart_date}, return={intent.return_date}")
                
                # Always regenerate flights when dates change
                segment_callback(create_text_chunk("Updating flights for new dates...", seq=1))
                flight_result = await self._run_flight_agent(intent, segment_callback)
                updated_plan.flights = [Flight(**f) for f in flight_result.get("flights", [])]
                
                # Always regenerate hotels when dates change
                segment_callback(create_text_chunk("Updating hotels for new dates...", seq=2))
                hotel_result = await self._run_hotel_agent(intent, segment_callback)
                updated_plan.hotels = [Hotel(**h) for h in hotel_result.get("hotels", [])]
                
                # Always regenerate itinerary when dates change (if it's a round trip)
                if intent.return_date:
                    segment_callback(create_text_chunk("Updating itinerary for new dates...", seq=3))
                    itinerary_result = await self._run_itinerary_agent(intent, segment_callback)
                    itinerary_data = itinerary_result.get("itinerary", {})
                    from models.plan import ItineraryDay
                    updated_plan.itinerary["days"] = [ItineraryDay(**d) for d in itinerary_data.get("days", [])]
                else:
                    # Clear itinerary for one-way trips
                    updated_plan.itinerary["days"] = []
            
            elif edit_type == "flights":
                # Regenerate only flights
                intent = existing_plan.request
                # Update intent from message if new info provided
                new_intent, _ = await self._understand_intent(user_message)
                if new_intent.origin:
                    intent.origin = new_intent.origin
                if new_intent.destination:
                    intent.destination = new_intent.destination
                if new_intent.depart_date:
                    intent.depart_date = new_intent.depart_date
                if new_intent.return_date:
                    intent.return_date = new_intent.return_date
                
                segment_callback(create_text_chunk("Updating flights...", seq=1))
                flight_result = await self._run_flight_agent(intent, segment_callback)
                updated_plan.flights = [Flight(**f) for f in flight_result.get("flights", [])]
            
            elif edit_type == "hotels":
                # Regenerate only hotels
                intent = existing_plan.request
                new_intent, _ = await self._understand_intent(user_message)
                if new_intent.destination:
                    intent.destination = new_intent.destination
                if new_intent.depart_date:
                    intent.depart_date = new_intent.depart_date
                
                segment_callback(create_text_chunk("Updating hotels...", seq=1))
                hotel_result = await self._run_hotel_agent(intent, segment_callback)
                updated_plan.hotels = [Hotel(**h) for h in hotel_result.get("hotels", [])]
            
            elif edit_type == "itinerary_remove":
                # Remove/block a specific day from itinerary (DO NOT regenerate flights/hotels)
                intent = existing_plan.request
                days = existing_plan.itinerary.get("days", [])
                
                target_date = edit_intent.get("target_date")
                day_number = edit_intent.get("day_number")
                
                logger.info(f"Attempting to remove day: target_date={target_date}, day_number={day_number}, message={user_message}")
                logger.info(f"Existing plan dates: depart={intent.depart_date}, return={intent.return_date}")
                logger.info(f"Current itinerary has {len(days)} days")
                
                # Always try to extract date from message (LLM might not provide it in correct format)
                # Use the existing plan's year context for better date extraction
                extracted_dates = self._extract_dates(user_message)
                
                # If we have a depart_date, use its year for date extraction
                if extracted_dates and intent.depart_date:
                    try:
                        from datetime import datetime
                        depart_year = datetime.strptime(intent.depart_date, "%Y-%m-%d").year
                        # Fix the year of extracted dates to match the trip year
                        for i, date_str in enumerate(extracted_dates):
                            try:
                                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                                # If the extracted year doesn't match the trip year, fix it
                                if date_obj.year != depart_year:
                                    fixed_date = date_obj.replace(year=depart_year)
                                    extracted_dates[i] = fixed_date.strftime("%Y-%m-%d")
                                    logger.info(f"Fixed extracted date year from {date_str} to {extracted_dates[i]} to match trip year {depart_year}")
                            except:
                                pass
                    except:
                        pass
                
                if extracted_dates:
                    # Use extracted date if we don't have one from LLM, or prefer extracted if it seems more accurate
                    if not target_date:
                        target_date = extracted_dates[0]
                        logger.info(f"Extracted target_date from message: {target_date}")
                    else:
                        # Log both for debugging
                        logger.info(f"LLM provided target_date: {target_date}, extracted dates: {extracted_dates}")
                        # If extracted date seems more reliable (matches format), use it
                        if extracted_dates[0] and re.match(r'\d{4}-\d{2}-\d{2}', extracted_dates[0]):
                            target_date = extracted_dates[0]
                            logger.info(f"Using extracted date instead: {target_date}")
                
                # Find the day to remove by date or day number
                day_to_remove = None
                if target_date:
                    # Normalize target_date to YYYY-MM-DD format if needed
                    from datetime import datetime
                    try:
                        # Try to parse and normalize the date
                        if isinstance(target_date, str):
                            # If it's already in YYYY-MM-DD format, use it
                            if re.match(r'\d{4}-\d{2}-\d{2}', target_date):
                                normalized_target = target_date
                            else:
                                # Try to parse it
                                parsed = datetime.strptime(target_date, "%Y-%m-%d")
                                normalized_target = parsed.strftime("%Y-%m-%d")
                        else:
                            normalized_target = target_date
                    except:
                        normalized_target = target_date
                    
                    logger.info(f"Looking for day with date: {normalized_target}")
                    # Handle both dict and ItineraryDay object formats
                    available_dates = []
                    for d in days:
                        if isinstance(d, dict):
                            available_dates.append(d.get('date', ''))
                        else:
                            # ItineraryDay Pydantic model - use attribute access
                            available_dates.append(getattr(d, 'date', ''))
                    logger.info(f"Available dates in itinerary: {available_dates}")
                    
                    # Find by date (exact match)
                    for idx, day in enumerate(days):
                        # Handle both dict and ItineraryDay object formats
                        if isinstance(day, dict):
                            day_date = day.get("date", "")
                        else:
                            # ItineraryDay Pydantic model - use attribute access
                            day_date = getattr(day, 'date', '')
                        
                        if day_date == normalized_target:
                            day_to_remove = idx
                            logger.info(f"Found day to remove at index {idx} with date {day_date}")
                            break
                    
                    # If not found, log for debugging
                    if day_to_remove is None:
                        logger.warning(f"Could not find day with date {normalized_target} in itinerary. Available dates: {available_dates}")
                elif day_number and 1 <= day_number <= len(days):
                    # Find by day number
                    day_to_remove = day_number - 1
                    logger.info(f"Using day_number {day_number} -> index {day_to_remove}")
                
                if day_to_remove is not None:
                    segment_callback(create_text_chunk(f"Removing day from itinerary...", seq=1))
                    # Remove the day
                    removed_day = days.pop(day_to_remove)
                    # Convert remaining days to dict format if they're Pydantic models
                    from models.plan import ItineraryDay
                    updated_days = []
                    for day in days:
                        if isinstance(day, ItineraryDay):
                            updated_days.append(day.model_dump())
                        elif isinstance(day, dict):
                            updated_days.append(day)
                        else:
                            # Fallback: try to convert to dict
                            updated_days.append(day.model_dump() if hasattr(day, 'model_dump') else day)
                    updated_plan.itinerary["days"] = [ItineraryDay(**d) if isinstance(d, dict) else d for d in updated_days]
                    
                    # Get date for logging
                    removed_date = removed_day.date if hasattr(removed_day, 'date') else (removed_day.get('date') if isinstance(removed_day, dict) else '')
                    logger.info(f"Successfully removed day at index {day_to_remove} (date: {removed_date}) from itinerary")
                else:
                    logger.warning(f"Could not find day to remove: target_date={target_date}, day_number={day_number}, extracted_dates={extracted_dates}")
                    segment_callback(create_text_chunk(f"Could not find the specified day to remove. Please check the date or day number.", seq=1))
            
            elif edit_type == "itinerary_day" and day_number:
                # Regenerate only specific day (DO NOT regenerate flights/hotels)
                intent = existing_plan.request
                days = existing_plan.itinerary.get("days", [])
                
                if 1 <= day_number <= len(days):
                    day_index = day_number - 1
                    # Handle both dict and ItineraryDay object formats
                    day_obj = days[day_index]
                    if isinstance(day_obj, dict):
                        target_date = day_obj.get("date", "")
                    else:
                        # ItineraryDay Pydantic model - use attribute access
                        target_date = getattr(day_obj, 'date', '')
                    
                    segment_callback(create_text_chunk(f"Regenerating Day {day_number}...", seq=1))
                    
                    # Regenerate just this day
                    from agents.itinerary_agent import _plan_single_day
                    from tools.search_tools import search_attractions, search_restaurants, search_experiences
                    
                    # Search for activities again
                    attractions = search_attractions(intent.destination, intent.depart_date, intent.budget)
                    restaurants = search_restaurants(intent.destination, None, intent.budget)
                    experiences = search_experiences(intent.destination)
                    
                    all_activities = []
                    destination_lower = intent.destination.lower()
                    for activity in attractions + restaurants + experiences:
                        activity_text = f"{activity.name} {activity.description or ''}".lower()
                        if destination_lower in activity_text or activity.category == "restaurant":
                            all_activities.append(activity)
                    
                    # Get used activities from other days
                    used_activity_names = set()
                    used_restaurant_names = set()
                    for idx, day in enumerate(days):
                        if idx != day_index:
                            # Handle both dict and ItineraryDay object formats
                            if isinstance(day, dict):
                                blocks = day.get("blocks", [])
                            else:
                                # ItineraryDay Pydantic model - use attribute access
                                blocks = getattr(day, 'blocks', [])
                            
                            for block in blocks:
                                # Handle both dict and block object formats
                                if isinstance(block, dict):
                                    activities = block.get("activities", [])
                                else:
                                    activities = getattr(block, 'activities', [])
                                
                                for activity in activities:
                                    # Handle both dict and activity object formats
                                    if isinstance(activity, dict):
                                        name = activity.get("name", "")
                                        category = activity.get("category", "")
                                    else:
                                        name = getattr(activity, 'name', '')
                                        category = getattr(activity, 'category', '')
                                    
                                    name_lower = name.lower().strip()
                                    if category == "restaurant":
                                        used_restaurant_names.add(name_lower)
                                    else:
                                        used_activity_names.add(name_lower)
                    
                    # Regenerate the day
                    new_day = await _plan_single_day(
                        target_date,
                        intent.destination,
                        all_activities,
                        intent.budget,
                        used_activity_names=used_activity_names,
                        used_restaurant_names=used_restaurant_names,
                        day_number=day_number,
                        total_days=len(days)
                    )
                    
                    # Replace the day - convert to ItineraryDay objects
                    from models.plan import ItineraryDay
                    days[day_index] = new_day.model_dump() if hasattr(new_day, 'model_dump') else new_day
                    # Ensure all days are ItineraryDay objects
                    updated_days = []
                    for day in days:
                        if isinstance(day, ItineraryDay):
                            updated_days.append(day)
                        elif isinstance(day, dict):
                            updated_days.append(ItineraryDay(**day))
                        else:
                            updated_days.append(day)
                    updated_plan.itinerary["days"] = updated_days
                else:
                    logger.warning(f"Invalid day number: {day_number}")
            
            elif edit_type == "itinerary_activity":
                # Swap/change specific activity - detect which day and activity
                intent = existing_plan.request
                days = existing_plan.itinerary.get("days", [])
                
                # Try to extract day number and activity name from message
                day_number = edit_intent.get("day_number")
                activity_name = edit_intent.get("activity_name")
                
                if not day_number or not activity_name:
                    # Ask for clarification
                    clarification = "I can help you update an activity. Which day and which activity would you like to change?"
                    segment_callback(create_text_chunk(clarification, seq=1))
                    segment_callback(create_summary_segment(
                        summary=clarification,
                        notes="",
                        final=True
                    ))
                    return existing_plan
                
                # Find the day and activity
                if 1 <= day_number <= len(days):
                    day_index = day_number - 1
                    # Regenerate the day (simplified approach)
                    segment_callback(create_text_chunk(f"Updating Day {day_number}...", seq=1))
                    # Use the same logic as itinerary_day edit
                    from agents.itinerary_agent import _plan_single_day
                    from tools.search_tools import search_attractions, search_restaurants, search_experiences
                    
                    # Get the date for this day
                    day_obj = days[day_index]
                    if isinstance(day_obj, dict):
                        target_date = day_obj.get("date", "")
                    else:
                        target_date = getattr(day_obj, 'date', '')
                    
                    # Search for activities again
                    attractions = search_attractions(intent.destination, intent.depart_date, intent.budget)
                    restaurants = search_restaurants(intent.destination, None, intent.budget)
                    experiences = search_experiences(intent.destination)
                    
                    all_activities = []
                    destination_lower = intent.destination.lower()
                    for activity in attractions + restaurants + experiences:
                        activity_text = f"{activity.name} {activity.description or ''}".lower()
                        if destination_lower in activity_text or activity.category == "restaurant":
                            all_activities.append(activity)
                    
                    # Get used activities from other days
                    used_activity_names = set()
                    used_restaurant_names = set()
                    for idx, day in enumerate(days):
                        if idx != day_index:
                            if isinstance(day, dict):
                                blocks = day.get("blocks", [])
                            else:
                                blocks = getattr(day, 'blocks', [])
                            
                            for block in blocks:
                                if isinstance(block, dict):
                                    activities = block.get("activities", [])
                                else:
                                    activities = getattr(block, 'activities', [])
                                
                                for activity in activities:
                                    if isinstance(activity, dict):
                                        name = activity.get("name", "")
                                        category = activity.get("category", "")
                                    else:
                                        name = getattr(activity, 'name', '')
                                        category = getattr(activity, 'category', '')
                                    
                                    name_lower = name.lower().strip()
                                    if category == "restaurant":
                                        used_restaurant_names.add(name_lower)
                                    else:
                                        used_activity_names.add(name_lower)
                    
                    # Regenerate the day
                    new_day = await _plan_single_day(
                        target_date,
                        intent.destination,
                        all_activities,
                        intent.budget,
                        used_activity_names=used_activity_names,
                        used_restaurant_names=used_restaurant_names,
                        day_number=day_number,
                        total_days=len(days)
                    )
                    
                    # Replace the day
                    from models.plan import ItineraryDay
                    days[day_index] = new_day.model_dump() if hasattr(new_day, 'model_dump') else new_day
                    updated_days = []
                    for day in days:
                        if isinstance(day, ItineraryDay):
                            updated_days.append(day)
                        elif isinstance(day, dict):
                            updated_days.append(ItineraryDay(**day))
                        else:
                            updated_days.append(day)
                    updated_plan.itinerary["days"] = updated_days
                else:
                    logger.warning(f"Invalid day number: {day_number}")
                    clarification = f"Could not find day {day_number}. Please specify a valid day number (1-{len(days)})."
                    segment_callback(create_text_chunk(clarification, seq=1))
                    segment_callback(create_summary_segment(
                        summary=clarification,
                        notes="",
                        final=True
                    ))
                    return existing_plan
            
            elif edit_type == "itinerary_swap":
                # Swap activities between days
                intent = existing_plan.request
                days = existing_plan.itinerary.get("days", [])
                
                source_day = edit_intent.get("source_day")
                target_day = edit_intent.get("target_day")
                activity_name = edit_intent.get("activity_name")
                
                if not source_day or not target_day:
                    clarification = "I can help you swap activities. Which days would you like to swap activities between? (e.g., 'swap day 2 and day 5 morning activities')"
                    segment_callback(create_text_chunk(clarification, seq=1))
                    segment_callback(create_summary_segment(
                        summary=clarification,
                        notes="",
                        final=True
                    ))
                    return existing_plan
                
                if 1 <= source_day <= len(days) and 1 <= target_day <= len(days):
                    source_index = source_day - 1
                    target_index = target_day - 1
                    
                    segment_callback(create_text_chunk(f"Swapping activities between Day {source_day} and Day {target_day}...", seq=1))
                    
                    # Get the blocks from both days
                    source_day_obj = days[source_index]
                    target_day_obj = days[target_index]
                    
                    if isinstance(source_day_obj, dict):
                        source_blocks = source_day_obj.get("blocks", [])
                    else:
                        source_blocks = getattr(source_day_obj, 'blocks', [])
                    
                    if isinstance(target_day_obj, dict):
                        target_blocks = target_day_obj.get("blocks", [])
                    else:
                        target_blocks = getattr(target_day_obj, 'blocks', [])
                    
                    # If activity_name is specified, try to find and swap that specific activity
                    # Otherwise, swap all activities (or ask for clarification)
                    if activity_name:
                        # Find the activity in source day and swap it with corresponding block in target day
                        # This is a simplified swap - swap the entire block if activity is found
                        for source_block in source_blocks:
                            if isinstance(source_block, dict):
                                activities = source_block.get("activities", [])
                                block_time = source_block.get("time", "")
                            else:
                                activities = getattr(source_block, 'activities', [])
                                block_time = getattr(source_block, 'time', '')
                            
                            for activity in activities:
                                if isinstance(activity, dict):
                                    name = activity.get("name", "")
                                else:
                                    name = getattr(activity, 'name', '')
                                
                                if activity_name.lower() in name.lower():
                                    # Found the activity - swap the entire block with corresponding time block in target day
                                    for target_block in target_blocks:
                                        if isinstance(target_block, dict):
                                            target_time = target_block.get("time", "")
                                        else:
                                            target_time = getattr(target_block, 'time', '')
                                        
                                        if block_time == target_time:
                                            # Swap the blocks
                                            if isinstance(source_day_obj, dict):
                                                source_blocks_list = source_day_obj.get("blocks", [])
                                            else:
                                                source_blocks_list = list(getattr(source_day_obj, 'blocks', []))
                                            
                                            if isinstance(target_day_obj, dict):
                                                target_blocks_list = target_day_obj.get("blocks", [])
                                            else:
                                                target_blocks_list = list(getattr(target_day_obj, 'blocks', []))
                                            
                                            # Find indices
                                            source_block_idx = next((i for i, b in enumerate(source_blocks_list) if (isinstance(b, dict) and b.get("time") == block_time) or (hasattr(b, 'time') and getattr(b, 'time') == block_time)), None)
                                            target_block_idx = next((i for i, b in enumerate(target_blocks_list) if (isinstance(b, dict) and b.get("time") == target_time) or (hasattr(b, 'time') and getattr(b, 'time') == target_time)), None)
                                            
                                            if source_block_idx is not None and target_block_idx is not None:
                                                # Swap
                                                source_blocks_list[source_block_idx], target_blocks_list[target_block_idx] = target_blocks_list[target_block_idx], source_blocks_list[source_block_idx]
                                                
                                                # Update the days
                                                from models.plan import ItineraryDay, ItineraryBlock
                                                if isinstance(source_day_obj, dict):
                                                    source_day_obj["blocks"] = source_blocks_list
                                                else:
                                                    source_day_obj.blocks = source_blocks_list
                                                
                                                if isinstance(target_day_obj, dict):
                                                    target_day_obj["blocks"] = target_blocks_list
                                                else:
                                                    target_day_obj.blocks = target_blocks_list
                                                
                                                # Update the days list
                                                days[source_index] = ItineraryDay(**source_day_obj) if isinstance(source_day_obj, dict) else source_day_obj
                                                days[target_index] = ItineraryDay(**target_day_obj) if isinstance(target_day_obj, dict) else target_day_obj
                                                
                                                updated_plan.itinerary["days"] = [ItineraryDay(**d) if isinstance(d, dict) else d for d in days]
                                                logger.info(f"Swapped {block_time} activities between Day {source_day} and Day {target_day}")
                                                break
                                    break
                    else:
                        # No specific activity - swap all activities (regenerate both days)
                        # This is a simplified approach - just regenerate both days
                        clarification = "To swap activities between days, please specify which activities you'd like to swap. (e.g., 'swap the morning activities from day 2 and day 5')"
                        segment_callback(create_text_chunk(clarification, seq=1))
                        segment_callback(create_summary_segment(
                            summary=clarification,
                            notes="",
                            final=True
                        ))
                        return existing_plan
                else:
                    clarification = f"Could not find the specified days. Please specify valid day numbers (1-{len(days)})."
                    segment_callback(create_text_chunk(clarification, seq=1))
                    segment_callback(create_summary_segment(
                        summary=clarification,
                        notes="",
                        final=True
                    ))
                    return existing_plan
            
            # Generate updated summary
            summary = await self._generate_summary(updated_plan.request, {
                "FLIGHTS": {"flights": [f.model_dump() for f in updated_plan.flights]},
                "HOTELS": {"hotels": [h.model_dump() for h in updated_plan.hotels]},
                "ITINERARY": {"itinerary": updated_plan.itinerary}
            })
            updated_plan.summary = summary.get("summary", updated_plan.summary)
            
            # Stream summary
            segment_callback(create_summary_segment(
                summary=updated_plan.summary,
                notes=updated_plan.notes,
                final=True
            ))
            
            # Save to memory
            self.memory.save_to_supabase(
                user_message=user_message,
                assistant_response=updated_plan.summary,
                plan=updated_plan,
                trip_constraints=updated_plan.request
            )
            
            return updated_plan
            
        except Exception as e:
            logger.error(f"Error handling incremental edit: {e}")
            # Fallback: return existing plan
            return existing_plan
    
    async def _detect_requested_components(self, user_message: str) -> List[str]:
        """
        Detect what the user wants: flights only, hotels only, itinerary only, or all.
        Returns a list of requested components: ["FLIGHTS"], ["HOTELS"], ["ITINERARY"], or combinations.
        
        Intent types:
        - ITINERARY_ONLY: "places to visit", "things to do", "where to eat", "itinerary"
        - FLIGHTS_ONLY: "flights", "tickets", "how to get there by air"
        - HOTELS_ONLY: "hotels", "stay", "accommodation", "where to stay"
        - FULL_PLAN: "plan a trip", "plan everything", "full plan", "make a trip plan"
        - CUSTOM_COMBINATION: "flights and hotels only", "hotels + itinerary"
        """
        message_lower = user_message.lower()
        
        # Keywords for each component
        flight_keywords = [
            'flight', 'flights', 'airline', 'airlines', 'fly', 'flying', 'airport', 
            'book flight', 'find flight', 'search flight', 'show flight', 'get flight', 
            'flight options', 'tickets', 'ticket', 'how to get there by air', 'air travel'
        ]
        hotel_keywords = [
            'hotel', 'hotels', 'accommodation', 'accommodations', 'stay', 'staying', 
            'lodging', 'resort', 'book hotel', 'find hotel', 'search hotel', 'show hotel', 
            'get hotel', 'hotel options', 'where to stay', 'place to stay'
        ]
        # Itinerary keywords - comprehensive list
        itinerary_keywords = [
            'itinerary', 'itineraries', 'places to visit', 'places to see', 'attractions', 
            'sightseeing', 'things to do', 'activities', 'day by day', 'what to do', 
            'where to go', 'places to explore', 'where to eat', 'restaurants', 'dining',
            'places to eat', 'things to see', 'sights', 'tourist spots', 'must see'
        ]
        
        # Full plan keywords - indicates user wants everything
        full_plan_keywords = [
            'plan a trip', 'plan trip', 'planning a trip', 'plan everything', 
            'full plan', 'make a trip plan', 'create a trip plan', 'trip plan',
            'complete plan', 'entire plan', 'whole plan'
        ]
        
        # Check for full plan first (highest priority)
        has_full_plan = any(keyword in message_lower for keyword in full_plan_keywords)
        if has_full_plan:
            logger.info("User requested: FULL_PLAN (all components)")
            return ["FLIGHTS", "HOTELS", "ITINERARY"]
        
        # Check for "only" or "just" keywords (explicit single component)
        has_only = 'only' in message_lower or 'just' in message_lower
        has_flight = any(keyword in message_lower for keyword in flight_keywords)
        has_hotel = any(keyword in message_lower for keyword in hotel_keywords)
        has_itinerary = any(keyword in message_lower for keyword in itinerary_keywords)
        
        # If user says "only" or "just", return only what they asked for
        if has_only:
            if has_flight and not has_hotel and not has_itinerary:
                logger.info("User requested: FLIGHTS_ONLY")
                return ["FLIGHTS"]
            elif has_hotel and not has_flight and not has_itinerary:
                logger.info("User requested: HOTELS_ONLY")
                return ["HOTELS"]
            elif has_itinerary and not has_flight and not has_hotel:
                logger.info("User requested: ITINERARY_ONLY")
                return ["ITINERARY"]
            # If multiple components mentioned with "only", use LLM to clarify
            elif has_flight or has_hotel or has_itinerary:
                # Use LLM to determine intent
                try:
                    from llm.ollama_wrapper import call_ollama
                    from langchain.prompts import ChatPromptTemplate
                    
                    prompt = ChatPromptTemplate.from_messages([
                        ("system", """You are a travel assistant. The user said "only" or "just" in their message. Determine what they want:

- If they want ONLY flights → return "FLIGHTS"
- If they want ONLY hotels → return "HOTELS"  
- If they want ONLY itinerary/places to visit → return "ITINERARY"
- If they want multiple things → return "ALL"

Return ONLY one word: "FLIGHTS", "HOTELS", "ITINERARY", or "ALL" - nothing else."""),
                        ("human", "User message: {message}\n\nWhat does the user want?")
                    ])
                    
                    result = await call_ollama(
                        "ORCHESTRATOR",
                        lambda llm: (prompt | llm).ainvoke({"message": user_message})
                    )
                    
                    response = result.content.strip().upper()
                    if "FLIGHT" in response and "HOTEL" not in response and "ITINERARY" not in response:
                        logger.info("LLM detected: FLIGHTS_ONLY")
                        return ["FLIGHTS"]
                    elif "HOTEL" in response and "FLIGHT" not in response and "ITINERARY" not in response:
                        logger.info("LLM detected: HOTELS_ONLY")
                        return ["HOTELS"]
                    elif "ITINERARY" in response or "PLACES" in response or "VISIT" in response:
                        logger.info("LLM detected: ITINERARY_ONLY")
                        return ["ITINERARY"]
                except Exception as e:
                    logger.warning(f"Failed to detect requested components with LLM: {e}")
        
        # Check for custom combinations (e.g., "flights and hotels only", "hotels + itinerary")
        # Look for explicit combinations
        if has_flight and has_hotel and not has_itinerary:
            logger.info("User requested: CUSTOM_COMBINATION (FLIGHTS + HOTELS)")
            return ["FLIGHTS", "HOTELS"]
        elif has_hotel and has_itinerary and not has_flight:
            logger.info("User requested: CUSTOM_COMBINATION (HOTELS + ITINERARY)")
            return ["HOTELS", "ITINERARY"]
        elif has_flight and has_itinerary and not has_hotel:
            logger.info("User requested: CUSTOM_COMBINATION (FLIGHTS + ITINERARY)")
            return ["FLIGHTS", "ITINERARY"]
        
        # If no "only" keyword, check what's mentioned
        # If only one component is mentioned, assume that's what they want
        if has_flight and not has_hotel and not has_itinerary:
            logger.info("User mentioned only flights - returning FLIGHTS_ONLY")
            return ["FLIGHTS"]
        elif has_hotel and not has_flight and not has_itinerary:
            logger.info("User mentioned only hotels - returning HOTELS_ONLY")
            return ["HOTELS"]
        elif has_itinerary and not has_flight and not has_hotel:
            logger.info("User mentioned only itinerary - returning ITINERARY_ONLY")
            return ["ITINERARY"]
        
        # Default: return all components (FULL_PLAN)
        logger.info("User didn't specify - defaulting to FULL_PLAN (all components)")
        return ["FLIGHTS", "HOTELS", "ITINERARY"]
    
    async def _understand_intent(self, user_message: str) -> tuple[TripRequest, List[str]]:
        """
        Extract trip intent from user message using LLM.
        Returns both the TripRequest and a list of requested components (FLIGHTS, HOTELS, ITINERARY).
        
        Primary method: Use Ollama LLM to extract structured trip information.
        Fallback: Use regex-based extraction if LLM fails.
        """
        # First, detect what the user wants (flights only, hotels only, itinerary only, or all)
        requested_components = await self._detect_requested_components(user_message)
        
        # Comprehensive prompt for LLM extraction
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a travel planning assistant. Extract trip information from the user's message.

CRITICAL INSTRUCTIONS:
1. Identify if this is a ONE-WAY trip (no return) or ROUND-TRIP (has return date)
2. Extract ALL available information accurately, including trip length if mentioned (e.g., "for 10 days", "10-day trip")
3. Handle typos and variations in city names and dates
4. Convert natural language dates to YYYY-MM-DD format
5. If current date is November 2024, and user says "December 12th", assume 2024 (current year)
6. If user says "return by 20th" after mentioning a departure date, that's the return date
7. If user says "for 10 days starting tomorrow", extract trip_length: 10 and depart_date
8. If the message mentions updating/changing an existing plan and includes context about the existing plan (Origin/Destination), you MUST preserve those values unless the user explicitly changes them
9. If the message only mentions a date change, preserve origin and destination from the context
10. If user mentions trip length (e.g., "10 days", "a week"), extract it as trip_length in preferences

Return ONLY valid JSON (no markdown, no code blocks):
{{
  "origin": "city name or airport code (e.g., 'Hyderabad', 'HYD') - empty string if not mentioned and not in context",
  "destination": "city name or airport code (e.g., 'Vizag', 'VGA') - empty string if not mentioned and not in context",
  "depart_date": "YYYY-MM-DD format (e.g., '2025-11-18') - empty string if not mentioned. Year logic: if date has passed in current year, use next year; if date hasn't passed in current year, use current year. Today is {current_date}.",
  "return_date": "YYYY-MM-DD format - the date user wants to be BACK (arrival date). For round trips, itinerary will end one day before this date. Null if one-way trip or if only trip length is mentioned. Year logic: if date has passed in current year, use next year; if date hasn't passed in current year, use current year.",
  "adults": 1,
  "children": 0,
  "budget": "low/medium/high or null",
  "preferences": {{"trip_length": number or null}} - trip_length is the number of days (e.g., 10 for "10 days", 7 for "a week")
}}

EXAMPLES:
- "I am in Hyderabad, planning to head to Vizag on 12th december and return back by 20th"
  → {{"origin": "Hyderabad", "destination": "Vizag", "depart_date": "2024-12-12", "return_date": "2024-12-20", "adults": 1, "children": 0, "budget": null, "preferences": {{"trip_length": null}}}}

- "Plan a trip to Visakhapatnam for 10 days starting tomorrow"
  → {{"origin": "", "destination": "Visakhapatnam", "depart_date": "2024-12-XX", "return_date": null, "adults": 1, "children": 0, "budget": null, "preferences": {{"trip_length": 10}}}}

- "Flight from NYC to LA on Jan 15"
  → {{"origin": "New York", "destination": "Los Angeles", "depart_date": "2025-01-15", "return_date": null, "adults": 1, "children": 0, "budget": null, "preferences": {{"trip_length": null}}}}

- "Find me an itinerary in vijaywada from november 20-24"
  → {{"origin": "", "destination": "Vijayawada", "depart_date": "2025-11-20", "return_date": "2025-11-24", "adults": 1, "children": 0, "budget": null, "preferences": {{"trip_length": 4}}}}
  NOTE: When user says "itinerary in [city]" or "places to visit in [city]", the city is the DESTINATION, not origin. Origin should be empty for itinerary-only requests unless explicitly mentioned.

- "Things to do in Mumbai for 5 days starting December 1st"
  → {{"origin": "", "destination": "Mumbai", "depart_date": "2024-12-01", "return_date": null, "adults": 1, "children": 0, "budget": null, "preferences": {{"trip_length": 5}}}}

- Context: "Origin: San Diego, Destination: Dallas, Departure: 2024-12-12" + Message: "change to start 13th december"
  → {{"origin": "San Diego", "destination": "Dallas", "depart_date": "2024-12-13", "return_date": null, "adults": 1, "children": 0, "budget": null, "preferences": {{"trip_length": null}}}}

CRITICAL FOR ITINERARY REQUESTS:
- If user asks for "itinerary in [city]", "places to visit in [city]", "things to do in [city]", the city is the DESTINATION
- For itinerary-only requests, origin is usually NOT needed (user may already be there or will be there)
- If only one city is mentioned in an itinerary request and no origin is mentioned, that city is the destination

If information is missing from the message but present in context, use the context value. Use empty strings only if truly not available."""),
            ("human", "User message: {message}\n\nToday's date: {current_date}")
        ])
        
        # Add context from memory if available - load previous trip details
        memory_summary = self.memory.get_memory_summary()
        from memory.state import get_latest_plan
        previous_plan = get_latest_plan(self.thread_id)
        
        # Build context from previous conversation
        context_parts = []
        if previous_plan:
            try:
                prev_request = previous_plan.get("request", {})
                if prev_request:
                    if prev_request.get("origin"):
                        context_parts.append(f"Previous origin: {prev_request.get('origin')}")
                    if prev_request.get("destination"):
                        context_parts.append(f"Previous destination: {prev_request.get('destination')}")
                    if prev_request.get("depart_date"):
                        context_parts.append(f"Previous departure date: {prev_request.get('depart_date')}")
                    if prev_request.get("return_date"):
                        context_parts.append(f"Previous return date: {prev_request.get('return_date')}")
                    if prev_request.get("adults"):
                        context_parts.append(f"Previous travelers: {prev_request.get('adults')} adults")
                    if prev_request.get("budget"):
                        context_parts.append(f"Previous budget: {prev_request.get('budget')}")
            except Exception as e:
                logger.debug(f"Failed to extract context from previous plan: {e}")
        
        if memory_summary:
            context_parts.append(f"Conversation summary: {memory_summary}")
        
        context = "\n".join(context_parts) + "\n\n" if context_parts else ""
        full_message = context + user_message
        
        # Try LLM extraction first
        intent_data = None
        try:
            logger.info(f"Attempting LLM-based intent extraction for: {user_message[:100]}...")
            from datetime import datetime
            current_date_str = datetime.now().strftime("%Y-%m-%d")
            result = await call_ollama(
                "ORCHESTRATOR",
                lambda llm: (prompt | llm).ainvoke({
                    "message": full_message,
                    "current_date": current_date_str
                })
            )
            
            if result:
                response_text = result.content.strip()
                logger.info(f"LLM response received: {response_text[:200]}...")
                
                # Extract JSON from response (handle markdown code blocks)
                json_str = response_text
                if "```json" in response_text:
                    json_start = response_text.find("```json") + 7
                    json_end = response_text.find("```", json_start)
                    json_str = response_text[json_start:json_end].strip()
                elif "```" in response_text:
                    json_start = response_text.find("```") + 3
                    json_end = response_text.find("```", json_start)
                    json_str = response_text[json_start:json_end].strip()
                elif "{" in response_text:
                    json_start = response_text.find("{")
                    json_end = response_text.rfind("}") + 1
                    json_str = response_text[json_start:json_end]
                
                intent_data = json.loads(json_str)
                logger.info(f"LLM extracted intent: origin={intent_data.get('origin')}, dest={intent_data.get('destination')}, depart={intent_data.get('depart_date')}, return={intent_data.get('return_date')}")
                
        except Exception as e:
            logger.error(f"LLM intent extraction failed: {e}, using regex fallback")
            intent_data = None
        
        # Validate and normalize LLM-extracted data
        if intent_data:
            try:
                # Fix common LLM misinterpretation: For ITINERARY-only requests, if destination is empty
                # but origin is set, swap them. This handles cases like "itinerary in vijaywada" where 
                # LLM incorrectly puts city in origin instead of destination.
                if "ITINERARY" in requested_components and len(requested_components) == 1:
                    # Itinerary-only request
                    origin = intent_data.get("origin", "").strip()
                    destination = intent_data.get("destination", "").strip()
                    
                    # If destination is empty but origin is set, for itinerary-only requests,
                    # the city in origin is almost certainly the destination (user wants itinerary for that city)
                    if not destination and origin:
                        logger.info(f"Fixing itinerary-only request: moving '{origin}' from origin to destination (itinerary-only with empty destination)")
                        intent_data["destination"] = origin
                        intent_data["origin"] = ""
                
                # Normalize dates and validate
                intent_data = self._validate_and_normalize_intent(intent_data)
                # If depart_date is still empty/null but we have context, try to extract from context
                if not intent_data.get("depart_date") and "Origin:" in full_message:
                    # Try to extract from context message format
                    import re
                    origin_match = re.search(r"Origin:\s*([^\n,]+)", full_message)
                    dest_match = re.search(r"Destination:\s*([^\n,]+)", full_message)
                    if origin_match and not intent_data.get("origin"):
                        intent_data["origin"] = origin_match.group(1).strip()
                    if dest_match and not intent_data.get("destination"):
                        intent_data["destination"] = dest_match.group(1).strip()
                
                trip_request = TripRequest(**intent_data)
                logger.info(f"Successfully extracted trip intent: {trip_request.origin} -> {trip_request.destination}, depart: {trip_request.depart_date}, return: {trip_request.return_date}")
                return trip_request, requested_components
            except Exception as e:
                logger.warning(f"Failed to create TripRequest from LLM data: {e}, falling back to regex")
                intent_data = None
        
        # Fallback: Use regex-based extraction (with context support)
        logger.info("Using regex fallback for intent extraction")
        trip_request = self._extract_intent_fallback(full_message)  # Use full_message to include context
        return trip_request, requested_components
        
    def _validate_and_normalize_intent(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize intent data extracted by LLM.
        Fixes dates, validates formats, and ensures consistency.
        """
        now = datetime.now()
        
        # Normalize depart_date
        depart_date = intent_data.get("depart_date")
        if depart_date:
            try:
                date_obj = datetime.strptime(depart_date, "%Y-%m-%d")
                # Smart year detection: if date has passed in current year, use next year
                # If date hasn't passed in current year, use current year
                current_year_date = date_obj.replace(year=now.year)
                
                if current_year_date < now:
                    # Date has already passed this year, use next year
                    fixed_date = date_obj.replace(year=now.year + 1)
                    intent_data["depart_date"] = fixed_date.strftime("%Y-%m-%d")
                    logger.info(f"Fixed depart_date from {depart_date} to {intent_data['depart_date']} (date passed this year)")
                elif current_year_date >= now:
                    # Date hasn't passed yet this year, use current year
                    fixed_date = current_year_date
                    if date_obj.year != now.year:
                        intent_data["depart_date"] = fixed_date.strftime("%Y-%m-%d")
                        logger.info(f"Fixed depart_date from {depart_date} to {intent_data['depart_date']} (using current year)")
            except (ValueError, TypeError):
                logger.warning(f"Invalid depart_date format: {depart_date}")
                intent_data["depart_date"] = ""
        else:
            # Handle None or empty string - set to empty string for TripRequest
            intent_data["depart_date"] = ""
        
        # Normalize return_date
        return_date = intent_data.get("return_date")
        if return_date:
            # Handle null, empty string, or "null" string
            if return_date in [None, "", "null", "None"]:
                intent_data["return_date"] = None
            else:
                try:
                    return_date_obj = datetime.strptime(return_date, "%Y-%m-%d")
                    depart_date = intent_data.get("depart_date", "")
                    
                    # Ensure return_date is after depart_date
                    if depart_date:
                        try:
                            depart_obj = datetime.strptime(depart_date, "%Y-%m-%d")
                            if return_date_obj < depart_obj:
                                # Return date before depart date - fix year
                                fixed_return = return_date_obj.replace(year=depart_obj.year)
                                if fixed_return <= depart_obj:
                                    fixed_return = return_date_obj.replace(year=depart_obj.year + 1)
                                intent_data["return_date"] = fixed_return.strftime("%Y-%m-%d")
                                logger.info(f"Fixed return_date from {return_date} to {intent_data['return_date']}")
                                return_date_obj = fixed_return
                        except ValueError:
                            pass
                    
                    # Ensure return_date is not in the past
                    if return_date_obj < now:
                        fixed_return = return_date_obj.replace(year=now.year + 1)
                        if fixed_return > now:
                            intent_data["return_date"] = fixed_return.strftime("%Y-%m-%d")
                            logger.info(f"Fixed return_date from {return_date} to {intent_data['return_date']}")
                except (ValueError, TypeError):
                    logger.warning(f"Invalid return_date format: {return_date}")
                    intent_data["return_date"] = None
        else:
            intent_data["return_date"] = None
        
        # Normalize other fields
        intent_data["origin"] = str(intent_data.get("origin", "")).strip()
        intent_data["destination"] = str(intent_data.get("destination", "")).strip()
        intent_data["adults"] = int(intent_data.get("adults", 1)) if intent_data.get("adults") else 1
        intent_data["children"] = int(intent_data.get("children", 0)) if intent_data.get("children") else 0
        intent_data["budget"] = intent_data.get("budget") if intent_data.get("budget") else None
        intent_data["preferences"] = intent_data.get("preferences") or {}
        
        return intent_data
    
    def _extract_intent_fallback(self, user_message: str) -> TripRequest:
        """
        Fallback regex-based extraction when LLM is unavailable.
        Extracts basic trip information using pattern matching.
        Also extracts from context format (Origin: X, Destination: Y).
        """
        # First, try to extract from context format (for edit requests)
        origin = None
        destination = None
        if "Origin:" in user_message:
            origin_match = re.search(r"Origin:\s*([^\n,]+)", user_message, re.IGNORECASE)
            if origin_match:
                origin = origin_match.group(1).strip()
        if "Destination:" in user_message:
            dest_match = re.search(r"Destination:\s*([^\n,]+)", user_message, re.IGNORECASE)
            if dest_match:
                destination = dest_match.group(1).strip()
        
        # Try multiple patterns for origin (if not found in context)
        if not origin:
            origin = self._extract_airport_code(user_message, "from")
            if not origin:
                # Try "in" pattern for origin (e.g., "I am in Hyderabad")
                origin_match = re.search(r"(?:I\s+am|I'm|currently)\s+in\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", user_message, re.IGNORECASE)
                if origin_match:
                    origin = origin_match.group(1).title()
        
        # Try multiple patterns for destination (if not found in context)
        if not destination:
            destination = self._extract_airport_code(user_message, "to")
            if not destination:
                # Try "head to", "going to", "travel to" patterns first (more specific)
                dest_match = re.search(r"(?:head|going|travel)\s+to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s+(?:on|and|by|return|,)|$)", user_message, re.IGNORECASE)
                if dest_match:
                    destination = dest_match.group(1).title()
                else:
                    # Fallback to general "to X" or "planning to X" pattern
                    dest_match = re.search(r"to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s+(?:on|and|by|return|,)|$)", user_message, re.IGNORECASE)
                    if dest_match:
                        destination = dest_match.group(1).title()
        
        dates = self._extract_dates(user_message)
        logger.info(f"Fallback regex extracted {len(dates)} dates: {dates}")
        
        # Validate and fix dates in fallback too
        depart_date = dates[0] if dates else ""
        return_date = dates[1] if len(dates) > 1 else None
        
        logger.info(f"Fallback: origin={origin}, destination={destination}, depart_date={depart_date}, return_date={return_date}")
        
        # Normalize dates
        if depart_date:
            try:
                date_obj = datetime.strptime(depart_date, "%Y-%m-%d")
                now = datetime.now()
                # Smart year detection: if date has passed in current year, use next year
                # If date hasn't passed in current year, use current year
                current_year_date = date_obj.replace(year=now.year)
                
                if current_year_date < now:
                    # Date has already passed this year, use next year
                    fixed_date = date_obj.replace(year=now.year + 1)
                    depart_date = fixed_date.strftime("%Y-%m-%d")
                    logger.info(f"Fallback: Fixed depart_date to {depart_date} (date passed this year)")
                elif current_year_date >= now and date_obj.year != now.year:
                    # Date hasn't passed yet this year, use current year
                    depart_date = current_year_date.strftime("%Y-%m-%d")
                    logger.info(f"Fallback: Fixed depart_date to {depart_date} (using current year)")
            except ValueError:
                pass
        
        if return_date:
            try:
                return_date_obj = datetime.strptime(return_date, "%Y-%m-%d")
                now = datetime.now()
                
                # Check against depart_date
                if depart_date:
                    try:
                        depart_obj = datetime.strptime(depart_date, "%Y-%m-%d")
                        if return_date_obj < depart_obj:
                            logger.warning(f"Fallback: Parsed return_date {return_date} is before depart_date {depart_date}, fixing year")
                            fixed_return = return_date_obj.replace(year=depart_obj.year)
                            if fixed_return <= depart_obj:
                                fixed_return = return_date_obj.replace(year=depart_obj.year + 1)
                            return_date = fixed_return.strftime("%Y-%m-%d")
                            logger.info(f"Fallback: Fixed return_date to {return_date}")
                            return_date_obj = fixed_return
                    except ValueError:
                        pass
                
                # Check if in the past
                if return_date_obj < now:
                    logger.warning(f"Fallback: Parsed return_date {return_date} is in the past, fixing year")
                    fixed_return = return_date_obj.replace(year=now.year + 1)
                    if fixed_return > now:
                        return_date = fixed_return.strftime("%Y-%m-%d")
                        logger.info(f"Fallback: Fixed return_date to {return_date}")
            except ValueError:
                pass
        
        return TripRequest(
            origin=origin or "",
            destination=destination or "",
            depart_date=depart_date,
            return_date=return_date,
            adults=1,
            children=0,
            budget=None,
            preferences={}
        )
    
    def _extract_airport_code(self, text: str, keyword: str) -> Optional[str]:
        """Extract airport code or city after keyword."""
        # Handle different patterns for origin and destination
        if keyword == "from":
            # Patterns: "from X", "I am in X", "I'm in X", "currently in X", "starting from X"
            patterns = [
                rf"from\s+([A-Z]{{3}}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                rf"(?:I\s+am|I'm|currently|starting)\s+in\s+([A-Z]{{3}}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            ]
        elif keyword == "to":
            # Patterns: "to X", "head to X", "going to X", "planning to X", "travel to X"
            # Stop at common words like 'on', 'and', 'by', 'return', comma, etc.
            # Note: Order matters - try more specific patterns first
            patterns = [
                # More specific: "head to X", "going to X", "travel to X" (not "planning to head to")
                rf"(?:head|going|travel)\s+to\s+([A-Z]{{3}}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s+(?:on|and|by|return|,)|$)",
                # General: "to X" or "planning to X"
                rf"to\s+([A-Z]{{3}}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s+(?:on|and|by|return|,)|$)",
            ]
        else:
            # Fallback to original pattern
            patterns = [rf"{keyword}\s+([A-Z]{{3}}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).title()  # Return with proper capitalization (e.g., "Hyderabad" not "HYDERABAD")
        
        return None
    
    def _extract_dates(self, text: str) -> List[str]:
        """Extract dates in YYYY-MM-DD format or natural language dates. Returns all dates found."""
        # First try YYYY-MM-DD format
        pattern = r"\d{4}-\d{2}-\d{2}"
        dates = re.findall(pattern, text)
        if dates:
            return dates
        
        # Try to extract natural language dates (e.g., "12th december", "December 12")
        # Extract ALL dates, not just the first one
        from datetime import datetime
        extracted_dates = []
        
        try:
            # Look for patterns like "12th december", "december 12", "12 dec"
            # Also handle standalone day numbers like "20th" when context suggests it's a date
            # Use flexible pattern to match month-like words (handles typos like "decemeber")
            date_patterns = [
                r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)",  # Match any word after day (will validate as month)
                r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?",  # Match any word before day (will validate as month)
                r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",  # Short month names
            ]
            
            month_map = {
                "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                # Handle common typos
                "decemeber": 12, "decemebr": 12, "decembe": 12, "decembr": 12,
                "janurary": 1, "feburary": 2, "septmeber": 9, "septembr": 9,
            }
            
            now = datetime.now()
            current_year = now.year
            current_month = now.month
            
            # Find all date matches using finditer instead of search
            for pattern_idx, pattern in enumerate(date_patterns):
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    groups = match.groups()
                    if len(groups) == 2:
                        # Pattern 0: "12th december" -> (day, month)
                        # Pattern 1: "december 12" -> (month, day)
                        # Pattern 2: "12 dec" -> (day, month)
                        if pattern_idx == 1:  # Month comes first
                            month_str, day_str = groups
                        else:  # Day comes first
                            day_str, month_str = groups
                        
                        try:
                            day = int(re.sub(r'\D', '', day_str))  # Remove non-digits
                            month = month_map.get(month_str.lower())
                            if not month:
                                # Try fuzzy matching for typos (e.g., "decemeber" -> "december")
                                month_lower = month_str.lower()
                                if "decem" in month_lower or month_lower[:3] == "dec":
                                    month = 12
                                elif "jan" in month_lower[:3]:
                                    month = 1
                                elif "feb" in month_lower[:3]:
                                    month = 2
                                elif "mar" in month_lower[:3] and "may" not in month_lower:
                                    month = 3
                                elif "apr" in month_lower[:3]:
                                    month = 4
                                elif "may" in month_lower[:3]:
                                    month = 5
                                elif "jun" in month_lower[:3]:
                                    month = 6
                                elif "jul" in month_lower[:3]:
                                    month = 7
                                elif "aug" in month_lower[:3]:
                                    month = 8
                                elif "sep" in month_lower[:3] or "sept" in month_lower[:4]:
                                    month = 9
                                elif "oct" in month_lower[:3]:
                                    month = 10
                                elif "nov" in month_lower[:3]:
                                    month = 11
                            
                            if month and 1 <= day <= 31:
                                # Smart year detection based on user's rule:
                                # - If date has passed in current year → next year
                                # - If date hasn't passed in current year → current year
                                year = current_year
                                
                                # Create a date object for this year to check if it has passed
                                try:
                                    test_date = datetime(current_year, month, day)
                                    if test_date < now:
                                        # Date has already passed this year, use next year
                                        year = current_year + 1
                                    # Otherwise, date hasn't passed yet, use current year
                                except ValueError:
                                    # Invalid date (e.g., Feb 30), skip it
                                    continue
                                
                                date_str = f"{year}-{month:02d}-{day:02d}"
                                if date_str not in extracted_dates:
                                    extracted_dates.append(date_str)
                        except (ValueError, KeyError):
                            continue
            
            # Also try to extract standalone day numbers when context suggests dates
            # Look for patterns like "return back by 20th" or "return by 20"
            # This is a fallback when we have one date with month and another without
            if len(extracted_dates) == 1:
                # We have one date, look for a second date reference
                return_patterns = [
                    r"return\s+(?:back\s+)?by\s+(\d{1,2})(?:st|nd|rd|th)?",
                    r"return\s+on\s+(\d{1,2})(?:st|nd|rd|th)?",
                    r"come\s+back\s+(?:on|by)\s+(\d{1,2})(?:st|nd|rd|th)?",
                ]
                
                for pattern in return_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        day_str = match.group(1)
                        try:
                            day = int(re.sub(r'\D', '', day_str))
                            # Use the same month as the first date, or next month if day is before first date
                            first_date = datetime.strptime(extracted_dates[0], "%Y-%m-%d")
                            second_month = first_date.month
                            second_year = first_date.year
                            
                            # If the return day is before the depart day, assume next month
                            if day < first_date.day:
                                second_month += 1
                                if second_month > 12:
                                    second_month = 1
                                    second_year += 1
                            
                            date_str = f"{second_year}-{second_month:02d}-{day:02d}"
                            if date_str not in extracted_dates:
                                extracted_dates.append(date_str)
                                break
                        except (ValueError, KeyError):
                            continue
            
            return extracted_dates
        except Exception as e:
            logger.debug(f"Date extraction fallback failed: {e}")
        
        return []
    
    def _check_missing_information(
        self, 
        intent: TripRequest, 
        requested_components: List[str]
    ) -> List[str]:
        """
        Check for missing critical information required for requested components.
        Returns a list of missing fields that need clarification.
        
        Args:
            intent: TripRequest with extracted information
            requested_components: List of components user requested (FLIGHTS, HOTELS, ITINERARY)
        
        Returns:
            List of missing field names (e.g., ["origin", "depart_date"])
        """
        missing = []
        
        # Get trip length from preferences if available
        trip_length = None
        if intent.preferences and isinstance(intent.preferences, dict):
            trip_length = intent.preferences.get("trip_length")
        
        # Check requirements for each requested component
        if "FLIGHTS" in requested_components:
            # For flights, we need:
            # - Origin (required for flights)
            # - Destination (required)
            # - Departure date (required)
            # - Return date (optional for one-way)
            if not intent.destination or not intent.destination.strip():
                missing.append("destination")
            if not intent.depart_date or not intent.depart_date.strip():
                missing.append("depart_date")
            # Origin is required for flights
            if not intent.origin or not intent.origin.strip():
                missing.append("origin")
        
        if "HOTELS" in requested_components:
            # For hotels, we need:
            # - Destination (required)
            # - Check-in date (can use depart_date)
            # - Check-out date (can use return_date or depart_date + 1)
            if not intent.destination or not intent.destination.strip():
                if "destination" not in missing:  # Don't duplicate
                    missing.append("destination")
            # If we have destination but no dates, we need at least depart_date
            if intent.destination and (not intent.depart_date or not intent.depart_date.strip()):
                if "depart_date" not in missing:
                    missing.append("depart_date")
        
        if "ITINERARY" in requested_components:
            # For itinerary, we need:
            # - Destination (required)
            # - Start date (can use depart_date)
            # - Trip length OR end date (return_date) - at least one is needed
            if not intent.destination or not intent.destination.strip():
                if "destination" not in missing:
                    missing.append("destination")
            # For itinerary, we need at least a start date
            if intent.destination and (not intent.depart_date or not intent.depart_date.strip()):
                if "depart_date" not in missing:
                    missing.append("depart_date")
            # For itinerary, we need either return_date OR trip_length
            # If we have destination and depart_date but neither return_date nor trip_length, ask for trip length
            if intent.destination and intent.depart_date:
                if not intent.return_date and not trip_length:
                    missing.append("trip_length")
        
        return missing
    
    async def _format_clarification_question(
        self, 
        missing_fields: List[str], 
        intent: TripRequest,
        requested_components: List[str]
    ) -> str:
        """
        Format a friendly clarification question for missing information using LLM.
        Asks only what's necessary, not everything at once.
        """
        # Use LLM to generate a natural, contextual clarification question
        try:
            from llm.ollama_wrapper import call_ollama
            from langchain.prompts import ChatPromptTemplate
            
            # Build context about what we have
            context_parts = []
            if intent.destination:
                context_parts.append(f"Destination: {intent.destination}")
            if intent.depart_date:
                context_parts.append(f"Departure date: {intent.depart_date}")
            if intent.origin:
                context_parts.append(f"Origin: {intent.origin}")
            context_str = ", ".join(context_parts) if context_parts else "No information provided yet"
            
            # Build what's missing
            missing_str = ", ".join(missing_fields)
            
            # Build what user requested
            requested_str = ", ".join(requested_components) if requested_components else "full plan"
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a helpful travel planning assistant. The user wants to {requested_components}, but some information is missing.

You have: {context}
Missing: {missing_fields}

Generate a SINGLE, friendly, conversational question that asks for the missing information. Be specific and helpful. Don't ask multiple questions at once - prioritize the most important missing piece.

Examples:
- If missing origin: "To find flights, I need your departure city. Which city are you flying from?"
- If missing destination: "I'd be happy to help! Which city or destination would you like to visit?"
- If missing depart_date: "When would you like to travel? Please provide a departure date."
- If missing trip_length for itinerary: "How many days will your trip be? (e.g., 5 days, a week, 10 days)"

Return ONLY the question text, nothing else."""),
                ("human", "Generate a clarification question for the missing information.")
            ])
            
            result = await call_ollama(
                "ORCHESTRATOR",
                lambda llm: (prompt | llm).ainvoke({
                    "requested_components": requested_str,
                    "context": context_str,
                    "missing_fields": missing_str
                })
            )
            
            question = result.content.strip()
            # Remove quotes if LLM added them
            if question.startswith('"') and question.endswith('"'):
                question = question[1:-1]
            if question.startswith("'") and question.endswith("'"):
                question = question[1:-1]
            
            return question
            
        except Exception as e:
            logger.warning(f"Failed to generate LLM clarification question: {e}, using fallback")
            # Fallback to simple questions
            if "destination" in missing_fields:
                return "I'd be happy to help! To get started, which city or destination would you like to visit?"
            
            if "depart_date" in missing_fields:
                if intent.destination:
                    return f"Great! I can help you plan a trip to {intent.destination}. When would you like to travel? Please provide a departure date."
                else:
                    return "When would you like to travel? Please provide a departure date."
            
            if "origin" in missing_fields:
                if intent.destination and intent.depart_date:
                    return f"Perfect! I'll help you plan a trip to {intent.destination} starting {intent.depart_date}. From which city or airport are you departing?"
            
            if "trip_length" in missing_fields:
                if intent.destination and intent.depart_date:
                    return f"Great! I can create an itinerary for {intent.destination} starting {intent.depart_date}. How many days will your trip be? (e.g., 5 days, a week, 10 days)"
            
            # Fallback
            missing_str = ", ".join(missing_fields)
            return f"To complete your request, I need a bit more information: {missing_str}. Could you please provide these details?"
    
    def _determine_agents_needed(self, intent: TripRequest, requested_components: List[str]) -> List[str]:
        """
        Determine which agents to run based on intent and user's requested components.
        Only runs agents for components the user actually wants.
        """
        agents = []
        
        # Filter based on what user requested
        if "FLIGHTS" in requested_components:
            # Add flights if we have destination and depart_date
            # Origin can be empty - flight agent will handle it with fallback
            if intent.destination and intent.depart_date:
                agents.append("FLIGHTS")
                logger.info("Adding FLIGHTS agent (user requested)")
                if not intent.origin:
                    logger.info("⚠️ Origin not specified - flight agent will use fallback or prompt user")
            else:
                missing = []
                if not intent.destination:
                    missing.append("destination")
                if not intent.depart_date:
                    missing.append("depart_date")
                logger.info(f"User requested flights but missing: {', '.join(missing)}")
        
        if "HOTELS" in requested_components:
            # Only add hotels if we have destination
            if intent.destination:
                agents.append("HOTELS")
                logger.info("Adding HOTELS agent (user requested)")
            else:
                logger.info("User requested hotels but missing destination")
        
        if "ITINERARY" in requested_components:
            # Only add itinerary if we have destination
            if intent.destination:
                # Get trip length from preferences if available
                trip_length = None
                if intent.preferences and isinstance(intent.preferences, dict):
                    trip_length = intent.preferences.get("trip_length")
                
                # Itinerary can be generated if we have:
                # 1. destination + depart_date + (return_date OR trip_length)
                # 2. OR destination + depart_date (will default to 3 days)
                if intent.depart_date:
                    # We have destination and depart_date - check if we have trip length or return_date
                    if intent.return_date or trip_length:
                        agents.append("ITINERARY")
                        logger.info(f"Adding ITINERARY agent (has destination, depart_date, and {'return_date' if intent.return_date else 'trip_length'})")
                    else:
                        # No return_date or trip_length, but we have destination and depart_date
                        # Generate itinerary with default length (3 days) or ask for trip length
                        # Since missing_info check should have caught this, we can proceed with default
                        agents.append("ITINERARY")
                        logger.info("Adding ITINERARY agent (has destination and depart_date, will use default 3 days or trip_length from context)")
                else:
                    logger.info("User requested itinerary but missing depart_date")
            else:
                logger.info("User requested itinerary but missing destination")
        
        # If no agents were added but user requested something, log warning
        if not agents and requested_components:
            logger.warning(f"User requested {requested_components} but missing required information")
        
        # If no specific requirements and no requested components, default to all (backward compatibility)
        if not agents and not requested_components:
            if intent.origin and intent.destination and intent.depart_date:
                agents.append("FLIGHTS")
            if intent.destination:
                agents.append("HOTELS")
            if intent.destination and intent.return_date:
                agents.append("ITINERARY")
        
        logger.info(f"Final agents to run: {agents} (requested: {requested_components})")
        return agents
    
    async def _run_agents_parallel(
        self,
        intent: TripRequest,
        agents_needed: List[str],
        segment_callback: Callable[[str], None]
    ) -> Dict[str, Any]:
        """Run agents in parallel and stream results."""
        results = {}
        tasks = []
        
        # Create tasks
        if "FLIGHTS" in agents_needed:
            tasks.append(("FLIGHTS", self._run_flight_agent(intent, segment_callback)))
        
        if "HOTELS" in agents_needed:
            tasks.append(("HOTELS", self._run_hotel_agent(intent, segment_callback)))
        
        if "ITINERARY" in agents_needed:
            tasks.append(("ITINERARY", self._run_itinerary_agent(intent, segment_callback)))
        
        # Run in parallel
        for agent_name, task in tasks:
            try:
                result = await task
                logger.info(f"{agent_name} agent completed, result keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'}")
                if agent_name == "FLIGHTS" and isinstance(result, dict):
                    logger.info(f"FLIGHTS result has {len(result.get('flights', []))} flights")
                results[agent_name] = result
            except Exception as e:
                logger.error(f"{agent_name} agent failed: {e}")
                results[agent_name] = {
                    "error": str(e),
                    agent_name.lower(): []
                }
        
        logger.info(f"_run_agents_parallel returning results with keys: {list(results.keys())}")
        return results
    
    async def _run_flight_agent(
        self,
        intent: TripRequest,
        segment_callback: Callable[[str], None]
    ) -> Dict[str, Any]:
        """Run flight agent and stream result. ALWAYS returns flights, even if empty or fallback."""
        try:
            result = await search_flights_agent(intent)
        except Exception as e:
            logger.error(f"Flight agent failed with exception: {e}", exc_info=True)
            result = {"flights": [], "reasoning": f"Error searching flights: {str(e)}"}
        
        # Stream flights - always stream even if empty
        from utils.sse import create_flights_segment
        flights = result.get("flights", [])
        
        logger.info(f"Flight agent returned {len(flights)} flights for {intent.origin} -> {intent.destination}")
        if flights:
            logger.info(f"Sample flight: {flights[0] if flights else 'None'}")
            # Log prices to verify they're preserved (NO LLM processing)
            for idx, flight in enumerate(flights[:3]):  # Log first 3
                logger.info(f"Flight {idx} price before streaming: {flight.get('currency', 'USD')} {flight.get('price', 0)} (direct from SerpAPI, no LLM)")
        else:
            logger.warning(f"No flights found for {intent.origin} -> {intent.destination} on {intent.depart_date}")
        
        # Log before sending - prices should be unchanged
        logger.info(f"Streaming {len(flights)} flights via SSE (prices preserved, no LLM processing)")
        if flights:
            logger.info(f"First flight sample: {flights[0] if flights else 'None'}")
        
        segment_callback(create_flights_segment(
            flights=flights,
            seq=0,
            final=False
        ))
        
        logger.info("FLIGHTS segment sent to callback")
        
        return result
    
    async def _run_hotel_agent(
        self,
        intent: TripRequest,
        segment_callback: Callable[[str], None]
    ) -> Dict[str, Any]:
        """Run hotel agent and stream result."""
        result = await search_hotels_agent(intent)
        
        # Stream hotels
        from utils.sse import create_hotels_segment
        segment_callback(create_hotels_segment(
            hotels=result.get("hotels", []),
            seq=0,
            final=False
        ))
        
        return result
    
    async def _run_itinerary_agent(
        self,
        intent: TripRequest,
        segment_callback: Callable[[str], None]
    ) -> Dict[str, Any]:
        """Run itinerary agent and stream result incrementally (one day at a time)."""
        from utils.sse import create_itinerary_segment
        from models.plan import ItineraryDay
        
        # Track all days for final result
        all_days = []
        
        def day_callback(day: ItineraryDay, all_days_list: list):
            """Callback to stream each day as it's completed."""
            try:
                # Stream current state (all days so far)
                days_data = [d.model_dump() for d in all_days_list]
                segment_callback(create_itinerary_segment(
                    itinerary_days=days_data,
                    seq=len(all_days_list) - 1,
                    final=False
                ))
                logger.info(f"Streamed itinerary update: {len(all_days_list)} days")
            except Exception as e:
                logger.warning(f"Failed to stream itinerary day: {e}")
        
        # Plan itinerary with incremental streaming
        result = await plan_itinerary_agent(intent, day_callback=day_callback)
        
        # Final stream with all days (in case callback wasn't called for last day)
        itinerary_data = result.get("itinerary", {})
        days = itinerary_data.get("days", [])
        if days:
            segment_callback(create_itinerary_segment(
                itinerary_days=days,
                seq=len(days) - 1,
                final=False
            ))
        
        return result
    
    async def _send_initial_progress(self, segment_callback: Callable[[str], None], user_message: str):
        """Send immediate friendly progress update."""
        try:
            # Simple, accurate initial message (no Ollama needed)
            initial_message = "Got it! Let me start planning your trip..."
            from utils.sse import create_text_chunk
            segment_callback(create_text_chunk(initial_message, seq=0))
            logger.info(f"Sent initial progress: {initial_message}")
        except Exception as e:
            logger.warning(f"Failed to send initial progress: {e}")
    
    async def _shimmer_loop(self, segment_callback: Callable[[str], None], agents_needed: List[str] = None):
        """Generate progressive shimmer messages while agents run."""
        try:
            # Simple, accurate step-by-step message templates (no Ollama needed)
            step_templates = {
                "flights": [
                    "Searching for flights...",
                    "Finding the best flight options..."
                ],
                "hotels": [
                    "Searching for hotels...",
                    "Comparing hotel options..."
                ],
                "itinerary": [
                    "Building your itinerary...",
                    "Planning activities and experiences..."
                ]
            }
            
            # Build steps based on agents needed - send all progress messages
            steps = []
            if agents_needed:
                if "FLIGHTS" in agents_needed:
                    steps.extend(step_templates["flights"])  # All flight messages
                if "HOTELS" in agents_needed:
                    steps.extend(step_templates["hotels"])  # All hotel messages
                if "ITINERARY" in agents_needed:
                    steps.extend(step_templates["itinerary"])  # All itinerary messages
            
            if not steps:
                steps = ["Planning your trip..."]
            
            logger.info(f"📊 Shimmer loop will send {len(steps)} progress updates: {steps}")
            
            # Send all progress messages with appropriate delays
            current_step = 0
            
            # Send first message immediately
            if steps:
                from utils.sse import create_text_chunk
                segment_callback(create_text_chunk(steps[0], seq=0))
                logger.info(f"✅ Shimmer: Sent progress update: {steps[0]}")
                current_step = 1
                await asyncio.sleep(2)  # Short delay before next message
            
            # Send remaining messages
            while self.shimmer_active and current_step < len(steps):
                try:
                    message = steps[current_step]
                    # Send progress update
                    from utils.sse import create_text_chunk
                    segment_callback(create_text_chunk(message, seq=current_step))
                    logger.info(f"✅ Shimmer: Sent progress update: {message}")
                    current_step += 1
                    
                    # Wait between messages (2-3 seconds)
                    await asyncio.sleep(2 + (current_step % 2))
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Shimmer message error: {e}")
                    await asyncio.sleep(2)
            
            # Keep loop alive while agents are running (but don't send more messages)
            while self.shimmer_active:
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Shimmer loop error: {e}")
                    await asyncio.sleep(5)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Shimmer loop error: {e}")
    
    # In orchestrator.py
# REPLACE the _generate_summary function (starting at line 1245) with this:

    async def _generate_summary(
        self,
        intent: TripRequest,
        results: Dict[str, Any],
        requested_components: List[str] = None
    ) -> Dict[str, str]:
        """
        Generate plan summary using Ollama.
        Scope the summary to only include what the user requested AND any errors.
        """
        from llm.ollama_wrapper import call_ollama
        
        requested_components = requested_components or ["FLIGHTS", "HOTELS", "ITINERARY"]
        
        # --- NEW LOGIC: Check for results AND errors ---
        summary_parts = []
        
        if "FLIGHTS" in requested_components:
            flight_result = results.get("FLIGHTS", {})
            flights = flight_result.get("flights", [])
            reasoning = flight_result.get("reasoning", "No flight information.")
            
            # Check for errors first (based on our agent's error message)
            if "error" in reasoning.lower() or "failed" in reasoning.lower():
                summary_parts.append(f"Flights: I encountered an error. ({reasoning})")
            # Check for fallback/no results
            elif not flights or (len(flights) == 1 and flights[0].get('price', 0) == 0.0):
                summary_parts.append(f"Flights: {reasoning}")
            else:
                summary_parts.append(f"Found {len(flights)} flight options")

        if "HOTELS" in requested_components:
            hotel_result = results.get("HOTELS", {})
            hotels = hotel_result.get("hotels", [])
            reasoning = hotel_result.get("reasoning", "No hotel information.")
            
            # Check for errors first
            if "error" in reasoning.lower() or "failed" in reasoning.lower():
                summary_parts.append(f"Hotels: I encountered an error. ({reasoning})")
            # Check for no results
            elif not hotels:
                 summary_parts.append(f"Hotels: {reasoning}")
            else:
                summary_parts.append(f"Found {len(hotels)} hotel options")

        if "ITINERARY" in requested_components:
            itinerary_result = results.get("ITINERARY", {})
            # Check for an error first
            if "error" in itinerary_result:
                summary_parts.append(f"Itinerary: An error occurred ({itinerary_result['error']})")
            else:
                itinerary_days = itinerary_result.get("itinerary", {}).get("days", [])
                if itinerary_days:
                    summary_parts.append(f"Created {len(itinerary_days)}-day itinerary")
                else:
                    summary_parts.append("Could not generate an itinerary.")
        
        # --- END OF NEW LOGIC ---

        # Determine scope for summary
        scope_description = ""
        if len(requested_components) == 1:
            if "FLIGHTS" in requested_components:
                scope_description = "flight search results"
            elif "HOTELS" in requested_components:
                scope_description = "hotel search results"
            elif "ITINERARY" in requested_components:
                scope_description = "itinerary plan"
        else:
            scope_description = "trip plan"
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""Generate a brief, friendly summary (2-3 sentences) of the {scope_description}.
Focus ONLY on what the user requested. 
If an error occurred for a component, YOU MUST state that error clearly and friendly.

Examples:
- "I found 3 flight options, but encountered an error searching for hotels: Network error. Here is your 3-day itinerary."
- "I couldn't find any flights for those dates (Google Flights hasn't returned any results). I did find 5 great hotels and a 3-day itinerary."
- "I found 5 flight options, 3 hotel options, and a 3-day itinerary for your trip."
"""),
            ("human", """Trip: {origin} to {destination}
Results: {results}
Requested components: {components}

Generate a focused summary that includes any failures.""")
        ])
        
        try:
            # Call Ollama
            result = await call_ollama(
                "SUMMARY",
                lambda llm: (prompt | llM).ainvoke({
                    "origin": intent.origin or "Unknown",
                    "destination": intent.destination or "Unknown",
                    "results": "; ".join(summary_parts) if summary_parts else "Planning in progress",
                    "components": ", ".join(requested_components)
                })
            )
            
            return {
                "summary": result.content.strip(),
                "notes": ""
            }
        except Exception as e:
            logger.warning(f"Ollama summary generation failed. Using fallback: {e}")
            # Fallback summary now also includes errors
            return {
                "summary": f"{scope_description.capitalize()} for {intent.origin or 'origin'} to {intent.destination or 'destination'}: " + 
                           ("; ".join(summary_parts) if summary_parts else "Planning completed."),
                "notes": "Summary generated without AI enhancement."
            }
    
    def _build_plan(
        self,
        intent: TripRequest,
        results: Dict[str, Any],
        summary: Dict[str, str],
        requested_components: List[str] = None
    ) -> ChatPlan:
        """
        Build unified ChatPlan from results.
        Only includes components that were requested by the user.
        """
        requested_components = requested_components or ["FLIGHTS", "HOTELS", "ITINERARY"]
        
        plan = ChatPlan(
            request=intent,
            summary=summary.get("summary", ""),
            notes=summary.get("notes", "")
        )
        
        # Only add flights if requested
        if "FLIGHTS" in requested_components:
            flights_data = results.get("FLIGHTS", {}).get("flights", [])
            logger.info(f"Building plan: FLIGHTS result has {len(flights_data)} flights")
            if flights_data:
                logger.info(f"Sample flight data: {flights_data[0] if flights_data else 'None'}")
            plan.flights = [Flight(**f) for f in flights_data]
            logger.info(f"Plan.flights after building: {len(plan.flights)} flights")
        else:
            plan.flights = []  # Don't include flights if not requested
        
        # Only add hotels if requested
        if "HOTELS" in requested_components:
            hotels_data = results.get("HOTELS", {}).get("hotels", [])
            plan.hotels = [Hotel(**h) for h in hotels_data]
        else:
            plan.hotels = []  # Don't include hotels if not requested
        
        # Only add itinerary if requested
        if "ITINERARY" in requested_components:
            itinerary_data = results.get("ITINERARY", {}).get("itinerary", {})
            days_data = itinerary_data.get("days", [])
            plan.itinerary["days"] = [ItineraryDay(**d) for d in days_data]
        else:
            plan.itinerary["days"] = []  # Don't include itinerary if not requested
        
        # Add errors
        for agent_name, result in results.items():
            if "error" in result:
                plan.errors.append(ErrorItem(
                    agent=agent_name,
                    message=result["error"]
                ))
        
        # Add metadata
        plan.meta.generated_at = datetime.utcnow().isoformat()
        plan.meta.sources = ["SerpAPI", "Tavily"]
        
        return plan

