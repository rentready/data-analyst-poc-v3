"""
Retry helper for handling rate limit errors.
"""
import asyncio
import logging
from typing import Callable, TypeVar, Any
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


async def retry_on_rate_limit(
    func: Callable,
    *args,
    max_retries: int = 5,
    initial_delay: float = 2.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    **kwargs
) -> Any:
    """
    Retry a function if it fails with rate limit error.
    
    Args:
        func: Async function to retry
        *args: Arguments for the function
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        **kwargs: Keyword arguments for the function
        
    Returns:
        Result from the function
        
    Raises:
        Last exception if all retries failed
    """
    last_exception = None
    delay = initial_delay
    
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
            
        except Exception as e:
            last_exception = e
            error_str = str(e).lower()
            
            # Check if this is a rate limit error
            is_rate_limit = (
                'rate limit' in error_str or
                'rate_limit_exceeded' in error_str or
                'ratelimit' in error_str or
                '429' in error_str
            )
            
            if not is_rate_limit:
                # Not a rate limit error, don't retry
                logger.warning(f"Non-rate-limit error, not retrying: {e}")
                raise
            
            if attempt >= max_retries:
                # Out of retries
                logger.error(f"❌ Max retries ({max_retries}) exceeded for rate limit error: {e}")
                raise
            
            # Extract wait time from error message if available
            wait_time = None
            if 'try again in' in error_str:
                try:
                    import re
                    match = re.search(r'try again in (\d+)', error_str)
                    if match:
                        wait_time = int(match.group(1))
                except:
                    pass
            
            # Use extracted wait time or exponential backoff
            current_delay = wait_time if wait_time else min(delay, max_delay)
            
            logger.warning(
                f"⏳ Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                f"Waiting {current_delay:.1f}s before retry... Error: {str(e)[:200]}"
            )
            
            # Show user-friendly message in Streamlit if available
            try:
                import streamlit as st
                st.info(
                    f"⏳ Превышен лимит запросов (попытка {attempt + 1}/{max_retries}). "
                    f"Ожидание {current_delay:.0f} сек. перед повтором...",
                    icon="⏳"
                )
            except:
                # Streamlit not available or not in streamlit context
                pass
            
            await asyncio.sleep(current_delay)
            
            # Exponential backoff for next attempt
            delay = min(delay * exponential_base, max_delay)
    
    # Should never reach here, but just in case
    raise last_exception


def with_retry(
    max_retries: int = 5,
    initial_delay: float = 2.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0
):
    """
    Decorator for adding retry logic to async functions.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        
    Example:
        @with_retry(max_retries=3, initial_delay=1.0)
        async def my_function():
            # ... code that might hit rate limit ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_on_rate_limit(
                func,
                *args,
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                **kwargs
            )
        return wrapper
    return decorator

