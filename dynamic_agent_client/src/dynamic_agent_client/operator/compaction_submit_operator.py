"""Script name: compaction_submit_operator.py. Collect a task's compaction result."""
from pydantic import BaseModel, Field
from .agent_operator_base import AgentOperator, agent_tool, description


class CompactionSubmission(BaseModel):
    """Validated compacted memory returned to the owning service."""
    summary: str = Field(min_length=1)
    compacted: str = Field(min_length=1)


class CompactionSubmitOperator(AgentOperator):
    """Accept one result per compaction task without writing storage."""

    def __init__(self):
        """Start a fresh submission slot for this task."""
        self.result: CompactionSubmission | None = None
        super().__init__()

    @description
    def get_description(self) -> str:
        """Explain submission separately from checkpoint persistence."""
        return "Submit the completed memory. Acceptance collects the result; the service handles persistence."

    @agent_tool(description="Submit a brief summary and self-contained detailed conversation memory.")
    async def submit(self, summary: str, compacted: str):
        """Validate and collect the completed compaction.

        :param summary: Brief overview for finding this memory in a list.
        :param compacted: Preserve goals, constraints, decisions, verified results, useful references, unfinished work and the latest user instruction.
        """
        if not isinstance(summary, str) or not isinstance(compacted, str):
            raise ValueError("summary and compacted must be strings")
        result = CompactionSubmission(summary=summary.strip(), compacted=compacted.strip())
        if self.result is not None and self.result != result:
            raise ValueError("A different submission was already accepted")
        self.result = result
        return {"status": "accepted"}
