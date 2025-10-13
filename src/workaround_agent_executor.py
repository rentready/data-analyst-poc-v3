"""
Temporary workaround for Magentic One to intercept agent events.
Use this in your application until the library is updated.
"""

import logging
from agent_framework._workflows._magentic import MagenticAgentExecutor
from agent_framework import AgentRunResponseUpdate

logger = logging.getLogger(__name__)


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
                logger.info(f"🔍 Agent Event from '{aid}' (final={is_final})")
                logger.debug(f"   Update: text={update.text[:100] if update.text else None}")
                logger.debug(f"   Raw: {type(update.raw_representation)}")
                
                # Check for Azure AI step events
                if update.raw_representation is not None:
                    try:
                        # Try to detect Azure AI step events
                        from azure.ai.agents.models import RunStep, RunStepDeltaChunk, RequiredMcpToolCall
                        
                        if isinstance(update.raw_representation, RunStep):
                            logger.info(f"   📋 RunStep: status={update.raw_representation.status}")
                            if hasattr(update.raw_representation, 'step_details'):
                                details = update.raw_representation.step_details
                                if hasattr(details, 'tool_calls'):
                                    for tc in details.tool_calls:
                                        if isinstance(tc, RequiredMcpToolCall):
                                            logger.info(f"   🔧 MCP Tool Call: {tc.mcp.server_name}.{tc.mcp.name}")
                                        else:
                                            logger.info(f"   🔧 Tool Call: {type(tc).__name__}")
                        
                        elif isinstance(update.raw_representation, RunStepDeltaChunk):
                            logger.debug(f"   📝 RunStepDelta: {update.raw_representation}")
                    except ImportError:
                        # Azure AI not available, skip
                        pass
                    except Exception as e:
                        logger.debug(f"   Error processing raw_representation: {e}")
                
                # Check contents for function calls
                if hasattr(update, 'contents'):
                    from agent_framework import FunctionCallContent, FunctionResultContent
                    for content in update.contents:
                        if isinstance(content, FunctionCallContent):
                            logger.info(f"   📞 Function Call: {content.name}")
                        elif isinstance(content, FunctionResultContent):
                            logger.info(f"   ✅ Function Result: {content.call_id}")
                
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