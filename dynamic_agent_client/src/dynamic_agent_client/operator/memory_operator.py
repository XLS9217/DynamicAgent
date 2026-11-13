"""Script name: memory_operator.py. Expose conversation memory tools to the agent."""
from .agent_operator_base import AgentOperator, agent_tool, description
from ..service_handler import ServiceHandler


class MemoryOperator(AgentOperator):
    """Discover, inspect, and write memory for the current session."""

    @description
    def get_description(self) -> str:
        """Explain how the running agent manages its own memory."""
        return (
            "Use list and check to inspect prior memory. Call compact with no arguments when "
            "context grows large. A separate Compact Agent summarizes the conversation and the "
            "service resumes you from a generated compacted user message. Call compact alone."
        )

    @agent_tool(description="List current-session memory IDs and brief summaries.")
    async def list(self):
        """Discover memory without loading detailed content."""
        return await self._request("list")

    @agent_tool(description="Read one current-session checkpoint without changing active context.")
    async def check(self, checkpoint_id: str):
        """Read detailed memory.

        :param checkpoint_id: Memory ID returned by list.
        """
        return await self._request("check", checkpoint_id=checkpoint_id)

    @agent_tool(description="Request conversation compaction by a separate task agent.")
    async def compact(self):
        """Pause for compaction before the main agent resumes."""
        return await self._request("compact")

    async def _request(self, action: str, **values):
        """Forward the current tool execution identity to the service."""
        return await ServiceHandler.memory(
            session_id=self.session_id, runner_id=self.runner_id,
            trigger_id=self.trigger_id, tool_call_id=self.tool_call_id,
            action=action, **values,
        )
