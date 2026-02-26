"""Retry utilities with exponential backoff and jitter for Ollama."""
import asyncio
import random
import time
from typing import Callable, TypeVar, Any
from functools import wraps
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)
import httpx
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


def should_retry(exception: Exception) -> bool:
    """Determine if an exception should trigger a retry."""
    # HTTP errors
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        return status in [429, 500, 502, 503, 504]
    
    # Timeout errors
    if isinstance(exception, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return True
    
    # Rate limit errors - check for HTTP 429
    error_str = str(exception).lower()
    if "429" in error_str or "rate limit" in error_str:
        return True
    
    return False


def extract_retry_delay(exception: Exception) -> float:
    """Extract retry delay from exception message if available."""
    error_str = str(exception)
    
    # Try to extract retry_delay from error message
    # Format: "Please retry in X.XXXXXXs"
    import re
    match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
    if match:
        try:
            delay = float(match.group(1))
            # Add a small buffer (10%)
            return delay * 1.1
        except ValueError:
            pass
    
    return None


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0
):
    """
    Decorator for async functions that retries with exponential backoff.
    Simplified for Ollama - no key rotation needed.
    
    Usage:
        @retry_with_backoff(max_attempts=3)
        async def my_agent_call(llm, prompt):
            return await llm.ainvoke(prompt)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if not should_retry(e):
                        logger.error(f"Non-retryable error in {func.__name__}: {e}")
                        raise
                    
                    if attempt < max_attempts:
                        # Try to extract retry delay from error message
                        retry_delay = extract_retry_delay(e)
                        
                        if retry_delay:
                            delay = min(retry_delay, max_delay * 2)
                            logger.warning(
                                f"Attempt {attempt}/{max_attempts} failed for {func.__name__} (rate limit). "
                                f"Retrying in {delay:.2f}s..."
                            )
                        else:
                            # Calculate delay with exponential backoff and jitter
                            delay = min(
                                base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1),
                                max_delay
                            )
                            logger.warning(
                                f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                                f"Retrying in {delay:.2f}s..."
                            )
                        
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


# Alias for backward compatibility
retry_with_key_rotation = retry_with_backoff


# Tenacity-based retry for sync functions
retry_on_http_errors = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    reraise=True
)

