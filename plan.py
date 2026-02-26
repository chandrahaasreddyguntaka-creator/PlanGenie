"""Wrapper for Gemini LLM calls with automatic key rotation on rate limits."""
import os
import re
import asyncio
import logging
from typing import Callable, TypeVar, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from .key_manager import get_key_manager

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_rate_limit_error(exception: Exception) -> bool:
    """Check if exception is a rate limit/quota error."""
    error_str = str(exception).lower()
    return any(keyword in error_str for keyword in [
        "429", "rate limit", "quota", "exceeded your current quota",
        "generativelanguage.googleapis.com"
    ])


async def call_with_key_rotation(
    agent_name: str,
    llm_call: Callable[[ChatGoogleGenerativeAI], Any],
    max_keys_to_try: Optional[int] = None
) -> Any:
    """
    Call an LLM function with automatic key rotation on rate limit errors.
    
    Args:
        agent_name: Role name for key assignment
        llm_call: Async function that takes an LLM instance and returns a result
        max_keys_to_try: Maximum number of keys to try (None = try all)
    
    Returns:
        Result from llm_call
    
    Raises:
        Exception: If all keys fail with non-rate-limit errors, or all keys exhausted
    """
    key_manager = get_key_manager()
    all_keys = key_manager.get_all_keys()
    
    if max_keys_to_try is None:
        max_keys_to_try = len(all_keys)
    else:
        max_keys_to_try = min(max_keys_to_try, len(all_keys))
    
    last_rate_limit_error = None
    keys_tried = set()
    
    # Start with assigned key
    current_key_index = 0
    assigned_key = key_manager.get_key_for_role(agent_name)
    try:
        assigned_index = all_keys.index(assigned_key)
        current_key_index = assigned_index
    except ValueError:
        current_key_index = 0
    
    for attempt in range(max_keys_to_try):
        # Get next key (round-robin from current position)
        # Try to find a key we haven't tried yet
        key = None
        key_index = None
        
        for offset in range(len(all_keys)):
            candidate_index = (current_key_index + attempt + offset) % len(all_keys)
            candidate_key = all_keys[candidate_index]
            if candidate_key not in keys_tried:
                key = candidate_key
                key_index = candidate_index
                break
        
        # If all keys have been tried, break
        if key is None:
            break
        
        keys_tried.add(key)
        
        try:
            # Set the key in environment and create LLM instance
            os.environ["GOOGLE_API_KEY"] = key
            
            # Create LLM instance with this key
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash-exp",
                temperature=0.0,
                streaming=False,
                max_retries=0,
                convert_system_message_to_human=True
            )
            
            logger.info(f"Trying Gemini key {key_index + 1}/{len(all_keys)} for {agent_name}")
            
            # Make the call
            result = await llm_call(llm)
            
            # Success! Log which key worked
            if attempt > 0:
                logger.info(f"Successfully used key {key_index + 1} for {agent_name} after {attempt} rotation(s)")
            
            return result
        
        except Exception as e:
            error_msg = str(e)
            
            # Check if it's a rate limit error
            if is_rate_limit_error(e):
                last_rate_limit_error = e
                logger.warning(
                    f"Rate limit on key {key_index + 1} for {agent_name}. "
                    f"Rotating to next key... (attempt {attempt + 1}/{max_keys_to_try})"
                )
                
                # Extract retry delay if available
                delay_match = re.search(r'retry in ([\d.]+)s', error_msg, re.IGNORECASE)
                if delay_match:
                    try:
                        delay = float(delay_match.group(1)) * 1.1  # Add 10% buffer
                        logger.info(f"Waiting {delay:.2f}s before trying next key...")
                        await asyncio.sleep(min(delay, 5.0))  # Cap at 5 seconds
                    except ValueError:
                        pass
                
                # Continue to next key
                continue
            else:
                # Non-rate-limit error - log and re-raise
                logger.error(f"Non-rate-limit error on key {key_index + 1} for {agent_name}: {e}")
                raise
    
    # All keys exhausted with rate limit errors
    if last_rate_limit_error:
        logger.error(
            f"All {len(keys_tried)} Gemini keys exhausted for {agent_name} due to rate limits. "
            f"Last error: {last_rate_limit_error}"
        )
        raise last_rate_limit_error
    
    # Should not reach here, but just in case
    raise Exception(f"Failed to call LLM for {agent_name} after trying {max_keys_to_try} keys")

