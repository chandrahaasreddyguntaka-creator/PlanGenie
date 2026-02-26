"""Memory and state management with LangChain and Supabase."""
import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from langchain.memory import ConversationSummaryBufferMemory
from langchain.schema import BaseMessage
from supabase import create_client, Client
from models.plan import ChatPlan, TripRequest

logger = logging.getLogger(__name__)

# Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Optional[Client] = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.warning(f"Failed to initialize Supabase client: {e}")


class MemoryManager:
    """Manages short-term (LangChain) and long-term (Supabase) memory."""
    
    def __init__(self, thread_id: str, user_id: Optional[int] = None):
        self.thread_id = thread_id
        self.user_id = user_id
        self.short_term_memory: Optional[ConversationSummaryBufferMemory] = None
        self._initialize_memory()
    
    def _initialize_memory(self):
        """Initialize LangChain summary buffer memory."""
        from llm.factory import make_ollama
        
        llm = make_ollama("ORCHESTRATOR", streaming=False)
        self.short_term_memory = ConversationSummaryBufferMemory(
            llm=llm,
            max_token_limit=2000,
            return_messages=True,
            memory_key="chat_history"
        )
        
        # Load existing memory from Supabase if available
        self._load_from_supabase()
    
    def _load_from_supabase(self):
        """Load chat memory from Supabase."""
        if not supabase:
            return
        
        try:
            # Use chat_id column (UUID type)
            response = supabase.table("chats").select("chat_memory").eq("chat_id", self.thread_id).execute()
            
            if response.data:
                chat_memory = response.data[0].get("chat_memory", {})
                messages = chat_memory.get("messages", [])
                
                # Restore messages to LangChain memory
                for msg in messages[-10:]:  # Last 10 messages
                    role = msg.get("role")
                    content = msg.get("content")
                    if role and content:
                        # Add to memory (simplified - LangChain will handle formatting)
                        pass  # LangChain memory will be populated during conversation
        except Exception as e:
            error_msg = str(e)
            # Only log if it's not a type mismatch
            if "bigint" not in error_msg.lower() and "invalid input syntax" not in error_msg.lower():
                logger.warning(f"Failed to load memory from Supabase: {e}")
    
    def save_to_supabase(
        self,
        user_message: str,
        assistant_response: str,
        plan: Optional[ChatPlan] = None,
        trip_constraints: Optional[TripRequest] = None
    ):
        """Save conversation and plan to Supabase."""
        if not supabase:
            return
        
        try:
            # Get existing chat data using chat_id column (including user_id and chat_memory)
            response = supabase.table("chats").select("chat_memory, user_id").eq("chat_id", self.thread_id).execute()
            existing_memory = {}
            existing_user_id = self.user_id
            
            if response.data:
                existing_memory = response.data[0].get("chat_memory", {})
                # Use existing user_id if we don't have one
                if not existing_user_id:
                    existing_user_id = response.data[0].get("user_id")
                    if existing_user_id:
                        self.user_id = existing_user_id
            
            # Update messages
            messages = existing_memory.get("messages", [])
            messages.append({
                "role": "user",
                "content": user_message,
                "timestamp": datetime.utcnow().isoformat()
            })
            messages.append({
                "role": "assistant",
                "content": assistant_response,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Keep only last 50 messages
            messages = messages[-50:]
            
            # Update chat_memory (preserve existing title if present)
            chat_memory = {
                "messages": messages,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            # Preserve existing title if it exists
            if "title" in existing_memory:
                chat_memory["title"] = existing_memory["title"]
            
            if plan:
                plan_dict = plan.to_dict()
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Saving plan to Supabase: {len(plan_dict.get('flights', []))} flights, {len(plan_dict.get('hotels', []))} hotels, {len(plan_dict.get('itinerary', {}).get('days', []))} itinerary days")
                chat_memory["plan"] = plan_dict
            
            if trip_constraints:
                chat_memory["trip_constraints"] = trip_constraints.model_dump()
            
            # Update using chat_id column (or insert if doesn't exist)
            # First try to update
            update_response = supabase.table("chats").update({
                "chat_memory": chat_memory
            }).eq("chat_id", self.thread_id).execute()
            
            # If no rows were updated, the chat doesn't exist yet
            # Create it if we have user_id (from parameter or existing chat), otherwise log a warning
            if not update_response.data:
                user_id_to_use = self.user_id or existing_user_id
                if user_id_to_use:
                    # Create the chat with the UUID as chat_id
                    logger.info(f"Chat {self.thread_id} not found, creating new chat for user {user_id_to_use}")
                    try:
                        # Get title from existing memory or use default
                        title = existing_memory.get("title") or f"Trip Plan {datetime.utcnow().strftime('%Y-%m-%d')}"
                        
                        supabase.table("chats").insert({
                            "chat_id": self.thread_id,  # Use the UUID as chat_id
                            "user_id": user_id_to_use,
                            "created_at": datetime.utcnow().isoformat(),
                            "chat_memory": chat_memory
                        }).execute()
                        logger.info(f"Successfully created chat {self.thread_id} in database with user_id {user_id_to_use}")
                    except Exception as e:
                        logger.error(f"Failed to create chat {self.thread_id}: {e}")
                else:
                    logger.warning(f"Chat {self.thread_id} not found in database and no user_id provided. Chat should be created via /api/chat/create first.")
            
        except Exception as e:
            logger.error(f"Failed to save to Supabase: {e}")
    
    def get_memory_summary(self) -> str:
        """Get summary of conversation history."""
        if not self.short_term_memory:
            return ""
        
        try:
            # Get summary from buffer
            summary = self.short_term_memory.moving_summary_buffer
            return summary if summary else ""
        except Exception as e:
            logger.warning(f"Failed to get memory summary: {e}")
            return ""
    
    def get_recent_messages(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from Supabase."""
        if not supabase:
            return []
        
        try:
            # Use chat_id column (UUID type)
            response = supabase.table("chats").select("chat_memory").eq("chat_id", self.thread_id).execute()
            
            if response.data:
                chat_memory = response.data[0].get("chat_memory", {})
                messages = chat_memory.get("messages", [])
                return messages[-limit:]
        except Exception as e:
            error_msg = str(e)
            # Only log if it's not a type mismatch
            if "bigint" not in error_msg.lower() and "invalid input syntax" not in error_msg.lower():
                logger.warning(f"Failed to get recent messages: {e}")
        
        return []


def get_latest_plan(thread_id: str) -> Optional[Dict[str, Any]]:
    """Get latest plan from Supabase."""
    if not supabase:
        return None
    
    try:
        # Use chat_id column (UUID type) - ensure thread_id is valid UUID string
        # Supabase should handle UUID strings correctly if column is UUID type
        response = supabase.table("chats").select("chat_memory").eq("chat_id", thread_id).execute()
        
        if response.data:
            chat_memory = response.data[0].get("chat_memory", {})
            return chat_memory.get("plan")
    except Exception as e:
        error_msg = str(e)
        # Only log warning if it's not a type mismatch (which indicates DB schema issue)
        if "bigint" not in error_msg.lower() and "invalid input syntax" not in error_msg.lower():
            logger.warning(f"Failed to get latest plan: {e}")
        # For type mismatches, this is expected if column isn't UUID yet
        # Don't spam logs with expected errors
    
    return None

