from typing import Callable

from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class AgentResponseHandler:
    """
    The response wrapper for generating response
    """
    def __init__(self, llm_engine: LanguageEngine):
        self.llm_engine = llm_engine

    async def _stream_response_flow(
            self,
            messages: list,
            system_prompt: str,
            tools_with_ref: list | None,
            stream_callback: Callable[[str], None] | None
    ) -> tuple[str, list, dict | None]:
        """
        Handle streaming response flow.

        :param messages: Conversation history in OpenAI format
        :param system_prompt: System message
        :param tools_with_ref: Tools with operator reference (for execution)
        :param stream_callback: Async callback for content chunks
        :return: Tuple of (full_response, tool_calls_with_results, assistant_msg)
        """
        full_response = ""
        tool_calls_in_progress: dict[int, dict] = {}

        # Build lookup: tool_name -> operator, and extract tools for LLM
        tool_operator_map = {}
        tools = None
        if tools_with_ref:
            tools = [{"type": t["type"], "function": t["function"]} for t in tools_with_ref]
            for t in tools_with_ref:
                tool_name = t["function"]["name"]
                tool_operator_map[tool_name] = t["_operator"]

        for chunk in self.llm_engine.stream_response(messages, system_prompt, tools):
            if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta

                # Collect content and pass to callback
                if hasattr(delta, 'content') and delta.content:
                    full_response += delta.content
                    if stream_callback:
                        await stream_callback(delta.content)

                # Handle tool calls
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if hasattr(tc, 'index') else 0

                        if idx not in tool_calls_in_progress:
                            tool_calls_in_progress[idx] = {"id": "", "name": "", "arguments": ""}

                        # Capture tool_call_id from first delta
                        if hasattr(tc, 'id') and tc.id:
                            tool_calls_in_progress[idx]["id"] = tc.id

                        if hasattr(tc, 'function'):
                            if tc.function.name:
                                tool_calls_in_progress[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_in_progress[idx]["arguments"] += tc.function.arguments

        # Build assistant message with tool_calls (for proper message history)
        assistant_msg = None
        if tool_calls_in_progress:
            assistant_msg = {
                "role": "assistant",
                "content": full_response or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]}
                    }
                    for tc in tool_calls_in_progress.values()
                ]
            }

        # Execute only the first tool
        tool_calls_with_results = []
        if tool_calls_in_progress:
            first_idx = next(iter(tool_calls_in_progress))
            tc_data = tool_calls_in_progress[first_idx]
            tool_name = tc_data["name"]
            if tool_name and tool_name in tool_operator_map:
                logger.info(f"Tool: {tool_name}")

                # Get operator for this tool and execute
                operator = tool_operator_map[tool_name]
                result = await operator.execute_tool(tool_name, tc_data["arguments"])

                # Build result text with ignored tools info
                if len(tool_calls_in_progress) > 1:
                    ignored_tools = [tc["name"] for idx, tc in tool_calls_in_progress.items() if idx != first_idx]
                    result_text = f"{result}\n\nImportant: First tool call executed only, rest ignored. Remember to call one tool at a time. You need to call {', '.join(ignored_tools)} again in order."
                else:
                    result_text = str(result)

                tool_calls_with_results.append({
                    "id": tc_data["id"],
                    "name": tool_name,
                    "args": tc_data["arguments"],
                    "result": result_text
                })

        logger.info(f"Tool calls executed: {len(tool_calls_with_results)}")
        return full_response, tool_calls_with_results, assistant_msg

    async def _block_response_flow(
            self,
            messages: list,
            system_prompt: str,
            tools: list | None
    ) -> tuple[str, list]:
        """Block response flow - not implemented yet."""
        raise NotImplementedError("Block response flow is not supported yet")

    async def invoke(
            self,
            messages: list,
            system_prompt: str,
            tools_with_ref: list | None = None,
            stream_callback: Callable[[str], None] | None = None,
            is_stream: bool = True
    ) -> tuple[str, list, dict | None]:
        """
        Invoke the response flow.

        :param messages: Conversation history in OpenAI format
        :param system_prompt: System message
        :param tools_with_ref: Tools with operator reference (for execution)
        :param stream_callback: Async callback for content chunks (stream mode only)
        :param is_stream: Whether to use streaming mode
        :return: Tuple of (full_response, tool_calls_list, assistant_msg)
        """
        if is_stream:
            return await self._stream_response_flow(messages, system_prompt, tools_with_ref, stream_callback)
        else:
            tools = [{"type": t["type"], "function": t["function"]} for t in tools_with_ref] if tools_with_ref else None
            result = await self._block_response_flow(messages, system_prompt, tools)
            return result[0], result[1], None
