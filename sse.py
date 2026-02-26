"""LLM factory for creating Ollama instances optimized for low latency."""
import os
from typing import Optional
from langchain_ollama import ChatOllama


def make_ollama(
    agent_name: str = "DEFAULT",
    streaming: bool = True,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
    temperature: Optional[float] = None
) -> ChatOllama:
    """
    Create an Ollama LLM instance optimized for low latency.
    
    Args:
        agent_name: Role name (for logging/debugging, not used for Ollama)
        streaming: Whether to enable streaming (default: True for faster responses)
        model: Model name (defaults to OLLAMA_MODEL env var or "llama3.1:8b")
        base_url: Base URL (defaults to OLLAMA_BASE_URL env var or "http://localhost:11434")
        timeout: Timeout in seconds (defaults to OLLAMA_TIMEOUT_S env var or 30)
        temperature: Temperature (defaults to 0.0 for fastest, most deterministic responses)
    
    Returns:
        Configured ChatOllama instance optimized for latency
    """
    model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    timeout = timeout or int(os.getenv("OLLAMA_TIMEOUT_S", "30"))
    # Use very low temperature (0.0) for fastest, most deterministic responses
    # This reduces generation time and improves consistency
    temp = temperature if temperature is not None else float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))
    
    return ChatOllama(
        model=model,
        base_url=base_url,
        timeout=timeout,
        temperature=temp,
        num_predict=512,  # Limit max tokens for faster responses
        num_ctx=2048,  # Smaller context window for faster processing
    )


# Alias for backward compatibility and cleaner naming
def make_gemini(agent_name: str, streaming: bool = True) -> ChatOllama:
    """
    Alias for make_ollama for backward compatibility.
    All Gemini calls are now routed to Ollama.
    """
    return make_ollama(agent_name=agent_name, streaming=streaming)


# Legacy alias
def make_olama(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None
) -> ChatOllama:
    """
    Legacy function for backward compatibility.
    Use make_ollama() instead.
    """
    return make_ollama(
        agent_name="LEGACY",
        streaming=True,
        model=model,
        base_url=base_url,
        timeout=timeout
    )

