"""
Temporary workaround for Magentic One to intercept agent events.
Use this in your application until the library is updated.
"""

import logging
from agent_framework._workflows._magentic import MagenticAgentExecutor, MagenticAgentDeltaEvent, CallbackSink
from agent_framework import AgentRunResponseUpdate

logger = logging.getLogger(__name__)

global_runstep_callback = None  # Callable[[str, RunStep], Awaitable[None]]

# Храним последний обработанный (id, status) для каждого агента
_last_runstep_state = {}  # {agent_id: (step_id, status)}

def patch_magentic_for_event_interception():
    """Apply monkey patch to intercept agent streaming events."""
    
    # Save original method
    _original_agent_executor_init = MagenticAgentExecutor.__init__
    
    # Patched MagenticAgentExecutor.__init__ to wrap streaming callback
    def _patched_agent_executor_init(
        self,
        agent,
        agent_id: str,
        agent_response_callback=None,
        streaming_agent_response_callback=None,
    ):
        # Wrap the streaming callback if it exists
        if streaming_agent_response_callback is not None:
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
                        from azure.ai.agents.models import RunStep, RunStepDeltaChunk
                        
                        if isinstance(raw, RunStep):
                            runstep_id = getattr(raw, 'id', None)
                            runstep_status = getattr(raw, 'status', None)
                            
                            # Проверяем, не дубликат ли это (тот же id и status)
                            last_state = _last_runstep_state.get(aid)
                            if last_state and last_state == (runstep_id, runstep_status):
                                logger.debug(f"   ⏭️  Skipping duplicate: id={runstep_id}, status={runstep_status}")
                            else:
                                # Сохраняем новое состояние
                                _last_runstep_state[aid] = (runstep_id, runstep_status)
                                logger.info(f"   📋 RunStep detected: type={raw.type}, status={runstep_status}, id={runstep_id}")
                                # Вызываем отдельный обработчик RunStep событий
                                if global_runstep_callback is not None:
                                    await global_runstep_callback(aid, raw)
                        
                        elif isinstance(raw, RunStepDeltaChunk):
                            logger.debug(f"   📝 RunStepDelta detected")
                    
                    except ImportError:
                        # Azure AI not available, skip
                        logger.debug("   Azure AI models not available for import")
                    except Exception as e:
                        logger.warning(f"   Error processing raw_representation: {e}", exc_info=True)
                
                # Call the original callback
                await original_callback(aid, update, is_final)
            
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
    
    logger.info("✓ Applied Magentic Agent event interception patch")
    print("✓ Applied Magentic Agent event interception patch")