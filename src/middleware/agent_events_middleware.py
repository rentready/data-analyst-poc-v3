"""Middleware for agent-level events (RunStep, ThreadRun, MessageDeltaChunk)."""

from agent_framework import AgentRunContext, AgentRunResponseUpdate
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Any
import streamlit as st
import logging

async def agent_events_middleware(
    context: AgentRunContext, 
    next: Callable[[AgentRunContext], Awaitable[None]],
    event_handler
) -> None:
    """
    Middleware that intercepts agent-level events and delegates to event handler.
    
    Args:
        context: Agent run context
        next: Next middleware in chain
        event_handler: Event handler instance
    """
    agent_id = getattr(context.agent, 'id', None)
    
    # Execute the original agent logic
    await next(context)
    
    # Handle streaming response
    if context.result is not None and context.is_streaming:
        original_stream = context.result
        
        async def event_processor() -> AsyncIterable[AgentRunResponseUpdate]:
            async for chunk in original_stream:
                # Обрабатываем события через handler
                if chunk.raw_representation:
                    chat_update = chunk.raw_representation
                    
                    if hasattr(chat_update, 'raw_representation'):
                        event = chat_update.raw_representation
                        
                        if hasattr(event, '__class__'):
                            event_class = event.__class__.__name__
                            logging.info(f"📦 Event type: {event_class}")
                            
                            # Добавляем agent_id к событию
                            event.agent_id = agent_id
                            
                            # Делегируем обработку в handler
                            if event_class == 'RunStep':
                                await event_handler.handle_runstep(event)
                            elif event_class == 'ThreadRun':
                                # Safely add agent_name to metadata
                                event.agent_name = getattr(context.agent, 'name', None)
                                await event_handler.handle_threadrun(event)
                            elif event_class == 'MessageDeltaChunk':
                                await event_handler.handle_message_delta(event)
                            elif event_class == 'ThreadMessage':
                                # ThreadMessage events are usually just passed through
                                pass
                
                yield chunk
        
        context.result = event_processor()
