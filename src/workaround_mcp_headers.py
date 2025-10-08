"""
Temporary workaround for HostedMCPTool headers issue.
Use this in your application until the library is updated.
"""

from typing import Any
from collections.abc import MutableMapping, Sequence
from agent_framework.azure import AzureAIAgentClient


def patch_azure_ai_client():
    """Apply monkey patch to support HostedMCPTool headers."""
    
    # Save original method reference
    _original_prep_tools = AzureAIAgentClient._prep_tools
    
    async def _patched_prep_tools(
        self, 
        tools: Sequence["ToolProtocol | MutableMapping[str, Any]"], 
        run_options: dict[str, Any] | None = None
    ) -> list[Any]:
        """Patched version that handles HostedMCPTool headers correctly."""
        from agent_framework import HostedMCPTool
        from azure.ai.agents.models import McpTool
        
        # Process each tool individually
        tool_definitions = []
        
        for tool in tools:
            # Special handling for HostedMCPTool with headers
            if isinstance(tool, HostedMCPTool):
                mcp_tool = McpTool(
                    server_label=tool.name.replace(" ", "_"),
                    server_url=str(tool.url),
                    allowed_tools=list(tool.allowed_tools) if tool.allowed_tools else [],
                )
                # Apply headers workaround - update_headers takes (name, value) pairs
                if tool.headers:
                    for header_name, header_value in tool.headers.items():
                        mcp_tool.update_headers(header_name, header_value)
                tool_definitions.extend(mcp_tool.definitions)
            else:
                # For other tools, use original method processing
                single_tool_result = await _original_prep_tools(self, [tool], run_options)
                tool_definitions.extend(single_tool_result)
        
        return tool_definitions
    
    # Apply the patch
    AzureAIAgentClient._prep_tools = _patched_prep_tools
    print("✓ Applied HostedMCPTool headers workaround to AzureAIAgentClient")