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
    ToolProtocol,
    UriContent,
)

from azure.ai.agents.models import (
    AgentsNamedToolChoice,
    AgentsNamedToolChoiceType,
    AgentsToolChoiceOptionMode,
    AsyncAgentEventHandler,
    AsyncAgentRunStream,
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

def patch_azure_ai_client():
    """Apply monkey patch to support HostedMCPTool headers."""
    
    # Save original method references
    _original_prep_tools = AzureAIAgentClient._prep_tools
    _original_create_run_options = AzureAIAgentClient._create_run_options
    
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

    async def _patched_create_run_options(
        self,
        messages: MutableSequence[ChatMessage],
        chat_options: ChatOptions | None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[FunctionResultContent | FunctionApprovalResponseContent] | None]:
        run_options: dict[str, Any] = {**kwargs}

        if chat_options is not None:
            run_options["max_completion_tokens"] = chat_options.max_tokens
            run_options["model"] = chat_options.model_id
            run_options["top_p"] = chat_options.top_p
            run_options["temperature"] = chat_options.temperature
            run_options["parallel_tool_calls"] = chat_options.allow_multiple_tool_calls

            if chat_options.tool_choice is not None:
                if chat_options.tool_choice != "none" and chat_options.tools:
                    tool_definitions = await self._prep_tools(chat_options.tools, run_options)
                    if tool_definitions:
                        run_options["tools"] = tool_definitions

                    # Handle MCP tool resources for approval mode
                    mcp_tools = [tool for tool in chat_options.tools if isinstance(tool, HostedMCPTool)]
                    if mcp_tools:
                        mcp_resources = []
                        for mcp_tool in mcp_tools:
                            server_label = mcp_tool.name.replace(" ", "_")
                            mcp_resource: dict[str, Any] = {"server_label": server_label}

                            # Add headers if present
                            if mcp_tool.headers:
                                mcp_resource["headers"] = mcp_tool.headers

                            if mcp_tool.approval_mode is not None:
                                match mcp_tool.approval_mode:
                                    case str():
                                        # Map agent framework approval modes to Azure AI approval modes
                                        approval_mode = (
                                            "always" if mcp_tool.approval_mode == "always_require" else "never"
                                        )
                                        mcp_resource["require_approval"] = approval_mode
                                    case _:
                                        if "always_require_approval" in mcp_tool.approval_mode:
                                            mcp_resource["require_approval"] = {
                                                "always": mcp_tool.approval_mode["always_require_approval"]
                                            }
                                        elif "never_require_approval" in mcp_tool.approval_mode:
                                            mcp_resource["require_approval"] = {
                                                "never": mcp_tool.approval_mode["never_require_approval"]
                                            }

                            mcp_resources.append(mcp_resource)

                        # Add MCP resources to tool_resources
                        if "tool_resources" not in run_options:
                            run_options["tool_resources"] = {}
                        run_options["tool_resources"]["mcp"] = mcp_resources

                if chat_options.tool_choice == "none":
                    run_options["tool_choice"] = AgentsToolChoiceOptionMode.NONE
                elif chat_options.tool_choice == "auto":
                    run_options["tool_choice"] = AgentsToolChoiceOptionMode.AUTO
                elif (
                    isinstance(chat_options.tool_choice, ToolMode)
                    and chat_options.tool_choice == "required"
                    and chat_options.tool_choice.required_function_name is not None
                ):
                    run_options["tool_choice"] = AgentsNamedToolChoice(
                        type=AgentsNamedToolChoiceType.FUNCTION,
                        function=FunctionName(name=chat_options.tool_choice.required_function_name),
                    )

            if chat_options.response_format is not None:
                run_options["response_format"] = ResponseFormatJsonSchemaType(
                    json_schema=ResponseFormatJsonSchema(
                        name=chat_options.response_format.__name__,
                        schema=chat_options.response_format.model_json_schema(),
                    )
                )

        instructions: list[str] = [chat_options.instructions] if chat_options and chat_options.instructions else []
        required_action_results: list[FunctionResultContent | FunctionApprovalResponseContent] | None = None

        additional_messages: list[ThreadMessageOptions] | None = None

        # System/developer messages are turned into instructions, since there is no such message roles in Azure AI.
        # All other messages are added 1:1, treating assistant messages as agent messages
        # and everything else as user messages.
        for chat_message in messages:
            if chat_message.role.value in ["system", "developer"]:
                for text_content in [content for content in chat_message.contents if isinstance(content, TextContent)]:
                    instructions.append(text_content.text)

                continue

            message_contents: list[MessageInputContentBlock] = []

            for content in chat_message.contents:
                if isinstance(content, TextContent):
                    message_contents.append(MessageInputTextBlock(text=content.text))
                elif isinstance(content, (DataContent, UriContent)) and content.has_top_level_media_type("image"):
                    message_contents.append(MessageInputImageUrlBlock(image_url=MessageImageUrlParam(url=content.uri)))
                elif isinstance(content, (FunctionResultContent, FunctionApprovalResponseContent)):
                    if required_action_results is None:
                        required_action_results = []
                    required_action_results.append(content)
                elif isinstance(content.raw_representation, MessageInputContentBlock):
                    message_contents.append(content.raw_representation)

            if len(message_contents) > 0:
                if additional_messages is None:
                    additional_messages = []
                additional_messages.append(
                    ThreadMessageOptions(
                        role=MessageRole.AGENT if chat_message.role == Role.ASSISTANT else MessageRole.USER,
                        content=message_contents,
                    )
                )

        if additional_messages is not None:
            run_options["additional_messages"] = additional_messages

        if len(instructions) > 0:
            run_options["instructions"] = "".join(instructions)

        return run_options, required_action_results


    async def _patched_create_agent_stream(
        self,
        thread_id: str | None,
        agent_id: str,
        run_options: dict[str, Any],
        required_action_results: list[FunctionResultContent | FunctionApprovalResponseContent] | None,
    ) -> tuple[AsyncAgentRunStream[AsyncAgentEventHandler[Any]] | AsyncAgentEventHandler[Any], str]:
        """Create the agent stream for processing.

        Returns:
            tuple: (stream, final_thread_id)
        """
        # Get any active run for this thread
        thread_run = await self._get_active_thread_run(thread_id)

        stream: AsyncAgentRunStream[AsyncAgentEventHandler[Any]] | AsyncAgentEventHandler[Any]
        handler: AsyncAgentEventHandler[Any] = AsyncAgentEventHandler()
        tool_run_id, tool_outputs, tool_approvals = self._convert_required_action_to_tool_output(
            required_action_results
        )

        if (
            thread_run is not None
            and tool_run_id is not None
            and tool_run_id == thread_run.id
            and (tool_outputs or tool_approvals)
        ):  # type: ignore[reportUnknownMemberType]
            # There's an active run and we have tool results to submit, so submit the results.
            args: dict[str, Any] = {
                "thread_id": thread_run.thread_id,
                "run_id": tool_run_id,
                "event_handler": handler,
            }
            if tool_outputs:
                args["tool_outputs"] = tool_outputs
            if tool_approvals:
                args["tool_approvals"] = tool_approvals
            await self.project_client.agents.runs.submit_tool_outputs_stream(**args)  # type: ignore[reportUnknownMemberType]
            # Pass the handler to the stream to continue processing
            stream = handler  # type: ignore
            final_thread_id = thread_run.thread_id
        else:
            # Handle thread creation or cancellation
            final_thread_id = await self._prepare_thread(thread_id, thread_run, run_options)

            # Now create a new run and stream the results.
            run_options.pop("conversation_id", None)
            logger.info(f"Run options: {run_options}")
            stream = await self.project_client.agents.runs.stream(  # type: ignore[reportUnknownMemberType]
                final_thread_id, agent_id=agent_id, **run_options
            )

        return stream, final_thread_id

    
    # Apply the patch
    AzureAIAgentClient._prep_tools = _patched_prep_tools
    AzureAIAgentClient._create_run_options = _patched_create_run_options
    AzureAIAgentClient._create_agent_stream = _patched_create_agent_stream
    print("✓ Applied HostedMCPTool headers workaround to AzureAIAgentClient")