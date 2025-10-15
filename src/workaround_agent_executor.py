"""
Temporary workaround for Magentic One to intercept agent events.
Use this in your application until the library is updated.
"""

import logging
from agent_framework._workflows._magentic import MagenticAgentExecutor, MagenticAgentDeltaEvent, CallbackSink
from agent_framework import AgentRunResponseUpdate

logger = logging.getLogger(__name__)

global_runstep_callback = None  # Callable[[str, RunStep], Awaitable[None]]

# Флаг, показывающий был ли уже применён патч
_patch_applied = False

# Сохраняем оригинальный метод __init__ до патча
_original_agent_executor_init = None

# Set to track wrapped callbacks by ID to prevent re-wrapping
_wrapped_callback_ids = set()

def patch_magentic_for_event_interception():
    """Apply monkey patch to intercept agent streaming events."""
    global _patch_applied, _original_agent_executor_init, _wrapped_callback_ids
    
    # Check if current __init__ is already our patched version
    current_init = MagenticAgentExecutor.__init__
    if hasattr(current_init, '_is_patched_by_workaround'):
        logger.info("✓ MagenticAgentExecutor.__init__ already patched (detected by marker), skipping")
        _patch_applied = True  # Ensure flag is set
        return
    
    # Применяем патч только один раз
    if _patch_applied:
        logger.debug("Patch already applied (by flag), skipping")
        return
    
    # Save original method ONLY if not already saved
    if _original_agent_executor_init is None:
        # Double-check that current __init__ is truly original (no marker)
        if hasattr(current_init, '_is_patched_by_workaround'):
            logger.error("ERROR: Attempting to save already-patched method as original!")
            logger.error("This should not happen - logic error in patch guard")
            return
        _original_agent_executor_init = current_init
        logger.info(f"✓ Saved original MagenticAgentExecutor.__init__ (id={id(_original_agent_executor_init)})")
    else:
        logger.info("Original method already saved, using existing reference")
    
    # Patched MagenticAgentExecutor.__init__ to wrap streaming callback
    def _patched_agent_executor_init(
        self,
        agent,
        agent_id: str,
        agent_response_callback=None,
        streaming_agent_response_callback=None,
    ):
        logger.debug(f"_patched_agent_executor_init called for agent '{agent_id}'")
        logger.debug(f"  streaming_agent_response_callback: {streaming_agent_response_callback}")
        logger.debug(f"  callback id: {id(streaming_agent_response_callback)}")
        
        # Wrap the streaming callback if it exists
        if streaming_agent_response_callback is not None:
            callback_id = id(streaming_agent_response_callback)
            
            # Check if callback is already wrapped (prevent cascading wraps)
            # Use both attribute check and ID tracking
            if (hasattr(streaming_agent_response_callback, '_is_wrapped_by_agent_executor') or 
                callback_id in _wrapped_callback_ids):
                logger.info(f"✓ Callback for agent '{agent_id}' already wrapped (id={callback_id}), skipping wrap")
                # Call original __init__ with the already-wrapped callback
                _original_agent_executor_init(
                    self,
                    agent,
                    agent_id,
                    agent_response_callback,
                    streaming_agent_response_callback,
                )
                return
            
            logger.info(f"🔄 Wrapping callback for agent '{agent_id}' (id={callback_id})")
            original_callback = streaming_agent_response_callback
            
            async def wrapped_streaming_callback(
                aid: str, 
                update: AgentRunResponseUpdate, 
                is_final: bool
            ) -> None:
                # Log/process the event BEFORE calling original
                logger.debug(f"🔍 Agent Event from '{aid}' (final={is_final})")
                logger.debug(f"   Update type: {type(update).__name__}")
                logger.debug(f"   Text: {update.text[:100] if update.text else None}")
                
                # Check for Azure AI step events
                # The raw_representation might be a ChatResponseUpdate wrapping the actual event
                raw = update.raw_representation
                logger.debug(f"   Raw type: {type(raw)}")
                
                # Try to unwrap nested ChatResponseUpdate/AgentRunResponseUpdate
                if raw is not None:
                    # If it's a list (accumulated raw_representations), check last item
                    if isinstance(raw, list) and len(raw) > 0:
                        raw = raw[-1]
                        logger.debug(f"   Raw (from list): {type(raw)}")
                    
                    # Azure AI wraps events in ChatResponseUpdate, so we need to dig deeper
                    if hasattr(raw, 'raw_representation') and raw.raw_representation is not None:
                        inner_raw = raw.raw_representation
                        logger.debug(f"   Inner raw type: {type(inner_raw)}")
                        raw = inner_raw
                    
                    try:
                        # Try to detect Azure AI step events
                        from azure.ai.agents.models import RunStep, RunStepDeltaChunk, MessageDeltaChunk, ThreadRun
                        
                        if isinstance(raw, RunStep):
                            # Вызываем отдельный обработчик RunStep событий
                            if global_runstep_callback is not None:
                                await global_runstep_callback(aid, raw)
                        
                        elif isinstance(raw, RunStepDeltaChunk):
                            if global_runstep_callback is not None:
                                await global_runstep_callback(aid, raw)
                        
                        elif isinstance(raw, MessageDeltaChunk):
                            logger.info(f"   💬 MessageDeltaChunk detected")
                            # Передаем в callback для обработки streaming
                            if global_runstep_callback is not None:
                                await global_runstep_callback(aid, raw)

                        elif isinstance(raw, ThreadRun):
                            if global_runstep_callback is not None:
                                await global_runstep_callback(aid, raw)
                        
                        else:
                            logger.info(f"   📝 Unknown event type: {type(raw)}")
                    
                    except ImportError:
                        # Azure AI not available, skip
                        logger.debug("   Azure AI models not available for import")
                    except Exception as e:
                        logger.warning(f"   Error processing raw_representation: {e}", exc_info=True)
                
                # Call the original callback
                await original_callback(aid, update, is_final)
            
            # Mark the wrapped callback to prevent re-wrapping
            wrapped_streaming_callback._is_wrapped_by_agent_executor = True
            
            # Track the new wrapped callback ID
            _wrapped_callback_ids.add(id(wrapped_streaming_callback))
            logger.debug(f"  Added wrapped callback id {id(wrapped_streaming_callback)} to tracking set")
            
            streaming_agent_response_callback = wrapped_streaming_callback
        
        # Call original __init__ with (possibly wrapped) callback
        _original_agent_executor_init(
            self,
            agent,
            agent_id,
            agent_response_callback,
            streaming_agent_response_callback,
        )
    
    # Apply the patch
    MagenticAgentExecutor.__init__ = _patched_agent_executor_init
    
    # Mark the patched function to identify it later
    _patched_agent_executor_init._is_patched_by_workaround = True
    
    _patch_applied = True
    
    logger.info("✓ Applied Magentic Agent event interception patch")
    logger.info(f"  Patched function id: {id(_patched_agent_executor_init)}")
    logger.info(f"  Original function id: {id(_original_agent_executor_init)}")
    print("✓ Applied Magentic Agent event interception patch")