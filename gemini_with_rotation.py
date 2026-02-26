"""FastAPI main application with SSE streaming endpoints."""
import os
import sys
import uuid
import json
import asyncio
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta

# Check Python version
if sys.version_info >= (3, 14):
    import warnings
    warnings.warn(
        f"Python 3.14+ detected ({sys.version}). LangChain/Pydantic may have compatibility issues. "
        "Recommended: Use Python 3.11 or 3.12. See PYTHON_VERSION.md for details.",
        UserWarning
    )

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from sse_starlette.sse import EventSourceResponse
from sse_starlette.event import ServerSentEvent
from orchestrator import Orchestrator
from memory.state import get_latest_plan
from models.plan import ChatPlan, TripRequest
from utils.sse import format_sse_event
from models.segment_types import Segment, SegmentType

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="PlanGenie API", version="1.0.0")

# CORS configuration
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory stream session storage (for stateless scaling, use Redis)
stream_sessions: Dict[str, asyncio.Queue] = {}
SESSION_TTL = timedelta(hours=1)


class StreamRequest(BaseModel):
    """Request model for starting a stream."""
    message: str
    thread_id: str = Field(..., alias="threadId")  # Accept camelCase from frontend
    user_id: Optional[int] = Field(None, alias="userId")  # User ID for chat association
    meta: Optional[dict] = None
    
    class Config:
        populate_by_name = True  # Allow both threadId and thread_id


class LoginRequest(BaseModel):
    """Request model for login."""
    email: str
    password: str


class SignupRequest(BaseModel):
    """Request model for signup."""
    email: str
    password: str
    full_name: str


class UpdateProfileRequest(BaseModel):
    """Request model for updating user profile."""
    full_name: Optional[str] = None
    email: Optional[str] = None


class UpdatePasswordRequest(BaseModel):
    """Request model for updating password."""
    current_password: str
    new_password: str


class CreateChatRequest(BaseModel):
    """Request model for creating a chat."""
    user_id: int  # int8 from database
    title: Optional[str] = None


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    services = {
        "api": "ok",
        "supabase": "unknown",
        "serpapi": "unknown",
        "tavily": "unknown"
    }
    
    # Check Supabase
    try:
        from memory.state import supabase
        if supabase:
            services["supabase"] = "reachable"
        else:
            services["supabase"] = "not_configured"
    except Exception as e:
        services["supabase"] = f"error: {str(e)[:50]}"
    
    # Check SerpAPI (just verify key exists)
    if os.getenv("SERPAPI_API_KEY"):
        services["serpapi"] = "configured"
    else:
        services["serpapi"] = "not_configured"
    
    # Check Tavily
    if os.getenv("TAVILY_API_KEY"):
        services["tavily"] = "configured"
    else:
        services["tavily"] = "not_configured"
    
    return {"ok": True, "services": services}


@app.post("/api/chat/message/stream")
async def start_stream(request: StreamRequest):
    """
    Start a streaming plan generation session.
    
    Returns streamId immediately, then processes in background.
    """
    stream_id = str(uuid.uuid4())
    
    # Create queue for this stream session
    queue = asyncio.Queue()
    stream_sessions[stream_id] = queue
    
    logger.info(f"Created stream session {stream_id} for thread {request.thread_id}")
    logger.info(f"Total active sessions: {len(stream_sessions)}")
    
    # Start background task
    asyncio.create_task(
        _process_stream_background(request.thread_id, request.message, queue, request.user_id)
    )
    
    # Schedule cleanup
    asyncio.create_task(_cleanup_session(stream_id))
    
    logger.info(f"Started stream session {stream_id} for thread {request.thread_id}")
    
    return {"streamId": stream_id}


async def _process_stream_background(thread_id: str, message: str, queue: asyncio.Queue, user_id: Optional[int] = None):
    """Process stream in background and push segments to queue."""
    try:
        orchestrator = Orchestrator(thread_id, user_id=user_id)
        
        def segment_callback(segment_str: str):
            """Callback to push segments to queue."""
            try:
                queue.put_nowait(segment_str)
            except Exception as e:
                logger.warning(f"Failed to queue segment: {e}")
        
        # Process request and stream segments
        plan = await orchestrator.process_request_stream(message, segment_callback)
        
        # Mark as complete
        queue.put_nowait("__DONE__")
        
    except Exception as e:
        logger.error(f"Stream processing error: {e}")
        from utils.sse import create_error_segment
        try:
            queue.put_nowait(create_error_segment(
                message=f"Processing error: {str(e)}",
                agent="SYSTEM"
            ))
        except:
            pass
        queue.put_nowait("__DONE__")


async def _cleanup_session(stream_id: str):
    """Clean up stream session after TTL."""
    await asyncio.sleep(SESSION_TTL.total_seconds())
    if stream_id in stream_sessions:
        del stream_sessions[stream_id]
        logger.info(f"Cleaned up stream session {stream_id}")


@app.get("/api/chat/{thread_id}/stream")
async def consume_stream(thread_id: str, streamId: str = Query(..., alias="streamId")):
    """
    SSE endpoint to consume stream events.
    
    Headers set for SSE:
    - Content-Type: text/event-stream
    - Cache-Control: no-cache, no-transform
    - X-Accel-Buffering: no
    """
    logger.info(f"Stream request received: thread_id={thread_id}, streamId={streamId}")
    logger.info(f"Available stream sessions: {list(stream_sessions.keys())}")
    
    if streamId not in stream_sessions:
        logger.warning(f"Stream session {streamId} not found. Available sessions: {list(stream_sessions.keys())}")
        raise HTTPException(status_code=404, detail=f"Stream session not found: {streamId}")
    
    queue = stream_sessions[streamId]
    
    async def event_generator():
        """Generate SSE events from queue."""
        logger.info(f"Event generator started for stream {streamId}")
        try:
            while True:
                # Check if client disconnected
                if await asyncio.to_thread(lambda: False):  # Placeholder for disconnect check
                    logger.info(f"Client disconnected for stream {streamId}")
                    break
                
                try:
                    # Get segment with timeout - increased timeout to 60 seconds to allow for longer processing
                    segment_str = await asyncio.wait_for(queue.get(), timeout=60.0)
                    
                    if segment_str == "__DONE__":
                        # Send final event and close - yield as properly formatted SSE string
                        logger.info(f"Sending DONE event for stream {streamId}")
                        done_event = json.dumps({"type": "DONE", "final": True})
                        yield done_event
                        break
                    
                    # segment_str is already formatted as "data: {...}\n\n"
                    # sse-starlette expects just the data part (the JSON string)
                    if segment_str.startswith("data: "):
                        # Extract JSON part after "data: "
                        json_start = segment_str.find("data: ") + 6
                        json_end = segment_str.find("\n\n", json_start)
                        if json_end == -1:
                            json_end = len(segment_str)
                        json_str = segment_str[json_start:json_end].strip()
                    else:
                        # If it's already JSON string, use it directly
                        json_str = segment_str
                    
                    # Log events for debugging
                    try:
                        parsed = json.loads(json_str)
                        event_type = parsed.get("type")
                        if event_type == "FLIGHTS":
                            logger.info(f"Streaming FLIGHTS event with {len(parsed.get('data', []))} flights")
                        elif event_type == "HOTELS":
                            logger.info(f"Streaming HOTELS event with {len(parsed.get('data', []))} hotels")
                        elif event_type == "ITINERARY":
                            itinerary_data = parsed.get('data', {})
                            days = itinerary_data.get('days', []) if isinstance(itinerary_data, dict) else []
                            logger.info(f"Streaming ITINERARY event with {len(days)} days")
                        else:
                            logger.debug(f"Streaming {event_type} event")
                    except Exception as e:
                        logger.debug(f"Could not parse event for logging: {e}")
                    
                    # Yield the JSON string directly (sse-starlette will format it as "data: ...")
                    yield json_str
                    
                except asyncio.TimeoutError:
                    # Send keepalive comment using ServerSentEvent
                    # This ensures it's properly formatted as an SSE comment (not data)
                    yield ServerSentEvent(comment="keepalive")
                    continue
                except Exception as e:
                    logger.error(f"Error in event generator: {e}")
                    error_event = json.dumps({"type": "ERROR", "data": {"message": str(e)}, "final": False})
                    yield error_event
                    break
        
        finally:
            # Don't cleanup session here - let it be cleaned up by TTL
            # The session might still be needed if the client reconnects
            # Only log that the generator is done
            logger.info(f"Event generator finished for stream {streamId}, session will be cleaned up by TTL")
    
    return EventSourceResponse(
        event_generator(),
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/chat/{thread_id}/plan")
async def get_plan(thread_id: str):
    """
    Fetch latest plan (non-streaming).
    
    Returns unified plan JSON from Supabase or empty scaffold.
    """
    try:
        plan_data = get_latest_plan(thread_id)
        
        if plan_data:
            return plan_data
        
        # Return empty scaffold
        empty_plan = ChatPlan(
            request=TripRequest(),
            summary="",
            notes="",
            flights=[],
            hotels=[],
            itinerary={"days": []}
        )
        return empty_plan.to_dict()
    
    except Exception as e:
        logger.error(f"Error fetching plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """Login user and return user info."""
    try:
        from memory.state import supabase
        import bcrypt
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Query users table to get stored password hash
        response = supabase.table("users").select("*").eq("email", request.email).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        user = response.data[0]
        stored_password_hash = user.get("password", "")
        
        # Verify password against stored hash
        # Handle both bcrypt hashes and legacy SHA256 hashes for migration
        password_valid = False
        try:
            # Try bcrypt first (starts with $2b$)
            if stored_password_hash.startswith("$2b$") or stored_password_hash.startswith("$2a$"):
                password_valid = bcrypt.checkpw(
                    request.password.encode('utf-8'),
                    stored_password_hash.encode('utf-8')
                )
            else:
                # Legacy SHA256 support (for existing users)
                import hashlib
                password_hash = hashlib.sha256(request.password.encode()).hexdigest()
                password_valid = (password_hash == stored_password_hash)
        except Exception as e:
            logger.warning(f"Password verification error: {e}")
            password_valid = False
        
        if not password_valid:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/signup")
async def signup(request: SignupRequest):
    """Create a new user account."""
    try:
        from memory.state import supabase
        import bcrypt
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Check if email already exists
        existing = supabase.table("users").select("id").eq("email", request.email).execute()
        if existing.data and len(existing.data) > 0:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Hash password using bcrypt (secure hashing with salt)
        password_hash = bcrypt.hashpw(
            request.password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')
        
        # Insert new user (id will be auto-generated by database)
        response = supabase.table("users").insert({
            "email": request.email,
            "password": password_hash,  # Stored as bcrypt hash
            "full_name": request.full_name,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        user = response.data[0]
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during signup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/profile")
async def get_profile(user_id: int = Query(..., description="User ID")):
    """Get user profile information."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Query users table to get user info
        response = supabase.table("users").select("id, email, full_name").eq("id", user_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = response.data[0]
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/auth/profile")
async def update_profile(request: UpdateProfileRequest, user_id: int = Query(..., description="User ID")):
    """Update user profile information."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Check if user exists
        existing = supabase.table("users").select("id, email").eq("id", user_id).execute()
        if not existing.data or len(existing.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        # If email is being updated, check if new email already exists
        if request.email and request.email != existing.data[0].get("email"):
            email_check = supabase.table("users").select("id").eq("email", request.email).execute()
            if email_check.data and len(email_check.data) > 0:
                raise HTTPException(status_code=400, detail="Email already registered")
        
        # Build update dict with only provided fields
        update_data = {}
        if request.full_name is not None:
            update_data["full_name"] = request.full_name
        if request.email is not None:
            update_data["email"] = request.email
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Update user
        response = supabase.table("users").update(update_data).eq("id", user_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to update profile")
        
        user = response.data[0]
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/auth/password")
async def update_password(request: UpdatePasswordRequest, user_id: int = Query(..., description="User ID")):
    """Update user password."""
    try:
        from memory.state import supabase
        import bcrypt
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Validate new password length
        if len(request.new_password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        
        # Query users table to get stored password hash
        response = supabase.table("users").select("password").eq("id", user_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = response.data[0]
        stored_password_hash = user.get("password", "")
        
        # Verify current password
        password_valid = False
        try:
            # Try bcrypt first (starts with $2b$)
            if stored_password_hash.startswith("$2b$") or stored_password_hash.startswith("$2a$"):
                password_valid = bcrypt.checkpw(
                    request.current_password.encode('utf-8'),
                    stored_password_hash.encode('utf-8')
                )
            else:
                # Legacy SHA256 support (for existing users)
                import hashlib
                password_hash = hashlib.sha256(request.current_password.encode()).hexdigest()
                password_valid = (password_hash == stored_password_hash)
        except Exception as e:
            logger.warning(f"Password verification error: {e}")
            password_valid = False
        
        if not password_valid:
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        
        # Hash new password using bcrypt
        new_password_hash = bcrypt.hashpw(
            request.new_password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')
        
        # Update password
        supabase.table("users").update({
            "password": new_password_hash
        }).eq("id", user_id).execute()
        
        logger.info(f"Password updated for user {user_id}")
        return {"ok": True, "message": "Password updated successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating password: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/create")
async def create_chat(request: CreateChatRequest):
    """Create a new chat thread."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        chat_id = str(uuid.uuid4())
        title = request.title or f"Trip Plan {datetime.utcnow().strftime('%Y-%m-%d')}"
        
        # Use chat_id column and user_id as int8
        # Store title in chat_memory JSON
        supabase.table("chats").insert({
            "chat_id": chat_id,  # UUID column
            "user_id": request.user_id,  # int8 column
            "created_at": datetime.utcnow().isoformat(),
            "chat_memory": {
                "title": title,  # Store title in chat_memory
                "messages": [],
                "plan": None,
                "trip_constraints": None
            }
        }).execute()
        
        return {"id": chat_id, "title": title}
    
    except Exception as e:
        logger.error(f"Error creating chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/user/{user_id}")
async def get_user_chats(user_id: int):
    """Get all chats for a user."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Use chat_id and user_id as int8
        response = supabase.table("chats").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        
        # Transform response to match frontend expectations
        chats = []
        for chat in response.data:
            chat_memory = chat.get("chat_memory", {})
            # Extract title from chat_memory or use default
            title = chat_memory.get("title") or f"Trip Plan {chat.get('created_at', '')[:10]}"
            chats.append({
                "id": chat["chat_id"],  # Use chat_id as id for frontend
                "chat_id": chat["chat_id"],
                "user_id": chat["user_id"],
                "title": title,
                "created_at": chat["created_at"],
                "updated_at": chat.get("created_at"),  # Use created_at if no updated_at
                "chat_memory": chat_memory
            })
        
        return {"chats": chats}
    
    except Exception as e:
        logger.error(f"Error fetching user chats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chat/{chat_id}")
async def delete_chat(chat_id: str):
    """Delete a chat thread."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Validate UUID format
        try:
            import uuid as uuid_lib
            uuid_lib.UUID(chat_id)  # Validate UUID format
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {chat_id}")
        
        # Use chat_id column (UUID type) - Supabase should handle UUID strings correctly
        # Delete operation - chat_id is now the primary key with UUID type
        result = supabase.table("chats").delete().eq("chat_id", chat_id).execute()
        
        # Supabase delete returns the deleted rows in result.data
        # If result.data is empty, the chat didn't exist (idempotent delete is fine)
        if result.data:
            logger.info(f"Successfully deleted chat: {chat_id}")
        else:
            logger.warning(f"No chat found with chat_id: {chat_id} (idempotent delete)")
        
        return {"ok": True}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting chat: {e}")
        error_msg = str(e)
        # Provide more detailed error message
        if "bigint" in error_msg.lower() or "invalid input syntax" in error_msg.lower():
            raise HTTPException(
                status_code=500, 
                detail=f"Database column type mismatch. Ensure chat_id column is UUID type. Error: {error_msg}"
            )
        raise HTTPException(status_code=500, detail=str(e))


class GenerateTitleRequest(BaseModel):
    """Request model for generating chat title."""
    message: str


@app.post("/api/chat/generate-title")
async def generate_chat_title(request: GenerateTitleRequest):
    """Generate a chat title from the user's message."""
    try:
        from llm.factory import make_ollama
        from langchain.prompts import ChatPromptTemplate
        from llm.ollama_wrapper import call_ollama
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a helpful assistant. Generate a short, descriptive title (max 50 characters) for a trip planning chat based on the user's message.

Examples:
- "find me a flight from MAA to VTZ on 12th december" → "MAA to VTZ Trip"
- "I want to visit Paris for 3 days" → "Paris 3-Day Trip"
- "Plan a trip to Tokyo with hotels" → "Tokyo Trip Planning"
- "Round trip to New York" → "New York Round Trip"

Return ONLY the title, nothing else."""),
            ("human", "{message}")
        ])
        
        try:
            result = await call_ollama(
                "ORCHESTRATOR",
                lambda llm: (prompt | llm).ainvoke({"message": request.message})
            )
            
            title = result.content.strip()
            # Clean up title (remove quotes, limit length)
            title = title.replace('"', '').replace("'", "").strip()
            if len(title) > 50:
                title = title[:47] + "..."
            
            return {"title": title or "New Trip Planning"}
        except Exception as e:
            logger.warning(f"Failed to generate title with LLM: {e}, using fallback")
            # Fallback: extract simple title
            title = _extract_simple_title(request.message)
            return {"title": title}
    
    except Exception as e:
        logger.error(f"Error generating chat title: {e}")
        # Fallback
        title = _extract_simple_title(request.message)
        return {"title": title}


def _extract_simple_title(message: str) -> str:
    """Extract a simple title from message (fallback)."""
    import re
    
    # Look for "from X to Y" pattern
    from_to_match = re.search(r'from\s+([A-Z]{3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+to\s+([A-Z]{3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', message, re.IGNORECASE)
    if from_to_match:
        return f"Trip: {from_to_match.group(1)} → {from_to_match.group(2)}"
    
    # Look for "to X" pattern
    to_match = re.search(r'to\s+([A-Z]{3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', message, re.IGNORECASE)
    if to_match:
        return f"Trip to {to_match.group(1)}"
    
    # Default
    return "New Trip Planning"


class UpdateTitleRequest(BaseModel):
    """Request model for updating chat title."""
    title: str


@app.patch("/api/chat/{chat_id}/title")
async def update_chat_title(chat_id: str, request: UpdateTitleRequest):
    """Update a chat thread's title."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Get existing chat_memory and update title in it
        response = supabase.table("chats").select("chat_memory").eq("chat_id", chat_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        chat_memory = response.data[0].get("chat_memory", {})
        chat_memory["title"] = request.title
        
        # Update chat_memory JSON
        supabase.table("chats").update({
            "chat_memory": chat_memory
        }).eq("chat_id", chat_id).execute()
        
        return {"ok": True}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating chat title: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateChatRequest(BaseModel):
    """Request to update chat with messages."""
    messages: List[Dict[str, Any]]
    title: Optional[str] = None


@app.put("/api/chat/{chat_id}")
async def update_chat(chat_id: str, request: UpdateChatRequest):
    """Update a chat thread with messages (including content blocks for persistence)."""
    try:
        from memory.state import supabase
        
        if not supabase:
            raise HTTPException(status_code=500, detail="Supabase not configured")
        
        # Get existing chat_memory
        response = supabase.table("chats").select("chat_memory").eq("chat_id", chat_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        chat_memory = response.data[0].get("chat_memory", {})
        
        # Convert frontend message format to backend format
        backend_messages = []
        for msg in request.messages:
            backend_msg = {
                "id": msg.get("id"),
                "role": msg.get("role"),
                "createdAt": msg.get("createdAt") or msg.get("timestamp"),
                "content": msg.get("content", [])
            }
            backend_messages.append(backend_msg)
        
        # Update chat_memory with messages
        chat_memory["messages"] = backend_messages
        
        # Update title if provided
        if request.title:
            chat_memory["title"] = request.title
        
        # Update chat_memory JSON
        supabase.table("chats").update({
            "chat_memory": chat_memory
        }).eq("chat_id", chat_id).execute()
        
        logger.info(f"Updated chat {chat_id} with {len(backend_messages)} messages")
        
        return {"ok": True}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    logger.info(f"Starting PlanGenie API server on {host}:{port}")
    logger.info("API Documentation: http://localhost:{}/docs".format(port))
    
    uvicorn.run(
        "main:app",  # String format required for reload to work
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )

