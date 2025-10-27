"""Async utilities for Streamlit and other sync contexts.

This module provides helpers for running async code in synchronous contexts
like Streamlit, which may close event loops between reruns.
"""

import asyncio
from typing import TypeVar, Awaitable

T = TypeVar('T')


def run_async_safe(coro: Awaitable[T]) -> T:
    """
    Safely run async coroutine in sync context (e.g., Streamlit).
    
    This function handles closed event loops gracefully by creating
    a new loop if the current one is closed or doesn't exist.
    
    Args:
        coro: Async coroutine to execute
        
    Returns:
        Result of the coroutine execution
        
    Example:
        ```python
        # In Streamlit app
        result = run_async_safe(my_async_function())
        ```
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)

