"""Simple wrapper for Ollama LLM calls - optimized for low latency."""
import logging
from typing import Callable, TypeVar, Any
from langchain_ollama import ChatOllama
from .factory import make_ollama

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def call_ollama(
    agent_name: str,
    llm_call: Callable[[ChatOllama], Any],
) -> Any:
    """
    Call an Ollama LLM function with optimized settings for low latency.
    
    This is a simplified wrapper that replaces the Gemini key rotation logic.
    Ollama doesn't need key rotation, so this is much simpler and faster.
    
    Args:
        agent_name: Role name for logging/debugging
        llm_call: Async function that takes an LLM instance and returns a result
    
    Returns:
        Result from llm_call
    
    Raises:
        Exception: If the LLM call fails
    """
    try:
        # Create Ollama instance optimized for latency
        llm = make_ollama(agent_name=agent_name, streaming=False)
        
        logger.debug(f"Calling Ollama for {agent_name}")
        
        # Make the call
        result = await llm_call(llm)
        
        return result
    
    except Exception as e:
        logger.error(f"Ollama call failed for {agent_name}: {e}")
        raise

