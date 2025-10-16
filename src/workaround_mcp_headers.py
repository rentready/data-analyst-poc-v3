"""
Temporary workaround for HostedMCPTool headers issue.
Use this in your application until the library is updated.
"""

from typing import Any
from collections.abc import MutableMapping, Sequence
from agent_framework.azure import AzureAIAgentClient
from collections.abc import MutableMapping, MutableSequence

from agent_framework import (
    ChatMessage,
    ChatOptions,
    DataContent,
    FunctionApprovalResponseContent,
    FunctionResultContent,
    HostedMCPTool,
    Role,
    TextContent,
    ToolMode,
    UriContent,
)

from azure.ai.agents.models import (
    AgentsNamedToolChoice,
    AgentsNamedToolChoiceType,
    AgentsToolChoiceOptionMode,
    FunctionName,
    MessageImageUrlParam,
    MessageInputContentBlock,
    MessageInputImageUrlBlock,
    MessageInputTextBlock,
    MessageRole,
    ResponseFormatJsonSchema,
    ResponseFormatJsonSchemaType,
    ThreadMessageOptions,
)

import logging

logger = logging.getLogger(__name__)

# Patch state tracking
_patch_applied = False
_original_create_run_options = None
_original_init = None

def patch_azure_ai_client():
    """Apply monkey patch to support HostedMCPTool headers."""
    global _patch_applied, _original_create_run_options, _original_init
    
    # Check if already patched by marker
    if hasattr(AzureAIAgentClient._create_run_options, '_is_patched_by_mcp_workaround'):
        logger.info("✓ AzureAIAgentClient already patched (detected by marker), skipping")
        _patch_applied = True
        return
    
    # Check flag
    if _patch_applied:
        logger.debug("Patch already applied (by flag), skipping")
        return
    
    # Save original method references ONLY if not already saved
    if _original_create_run_options is None:
        _original_create_run_options = AzureAIAgentClient._create_run_options
        _original_init = AzureAIAgentClient.__init__
        logger.info("✓ Saved original AzureAIAgentClient methods")
    else:
        logger.info("Original methods already saved, using existing references")

    async def _patched_create_run_options(
        self,
        messages: MutableSequence[ChatMessage],
        chat_options: ChatOptions | None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[FunctionResultContent | FunctionApprovalResponseContent] | None]:
        # Call the original method to get the standard run_options
        run_options, required_action_results = await _original_create_run_options(
            self, messages, chat_options, **kwargs
        )
        
        # Add headers to MCP tools if present
        if chat_options is not None and chat_options.tools:
            mcp_tools = [tool for tool in chat_options.tools if isinstance(tool, HostedMCPTool)]
            
            # Only modify if we have MCP tools with headers and MCP resources already exist
            if mcp_tools and "tool_resources" in run_options and "mcp" in run_options["tool_resources"]:
                mcp_resources = run_options["tool_resources"]["mcp"]
                
                # Create a mapping of server_label to tool for quick lookup
                mcp_tools_by_label = {
                    tool.name.replace(" ", "_"): tool 
                    for tool in mcp_tools
                }
                
                # Add headers to corresponding MCP resources
                for mcp_resource in mcp_resources:
                    server_label = mcp_resource.get("server_label")
                    if server_label and server_label in mcp_tools_by_label:
                        tool = mcp_tools_by_label[server_label]
                        if tool.headers:
                            mcp_resource["headers"] = tool.headers
        
        return run_options, required_action_results
    
    # Apply the patch
    AzureAIAgentClient._create_run_options = _patched_create_run_options
    
    # Mark the patched method to identify it later
    _patched_create_run_options._is_patched_by_mcp_workaround = True
    
    _patch_applied = True
    
    logger.info("✓ Applied HostedMCPTool headers workaround to AzureAIAgentClient")
    print("✓ Applied HostedMCPTool headers workaround to AzureAIAgentClient")