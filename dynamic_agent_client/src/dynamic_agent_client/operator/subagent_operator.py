from collections.abc import Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from .agent_operator_base import AgentOperator, agent_tool, description


class SubagentRequest(BaseModel):
    """Validated task and candidate-operator selection for one subagent run."""

    task: str = Field(description="A complete, self-contained task for the subagent")
    operator_list: list[str] = Field(
        min_length=1,
        description="Names of candidate operators the subagent may use",
    )

    @field_validator("task")
    @classmethod
    def validate_task(cls, task: str) -> str:
        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")
        return task

    @field_validator("operator_list")
    @classmethod
    def validate_operator_list(cls, operator_list: list[str]) -> list[str]:
        normalized = [name.strip() for name in operator_list]
        if any(not name for name in normalized):
            raise ValueError("operator_list must not contain empty names")
        duplicates = sorted({name for name in normalized if normalized.count(name) > 1})
        if duplicates:
            raise ValueError(f"operator_list contains duplicate names: {', '.join(duplicates)}")
        return normalized


class SubagentOperator(AgentOperator):
    """Client-side bridge for delegating one task to a subagent trigger."""

    def __init__(
        self,
        trigger: Callable[[SubagentRequest], object],
        candidate_operators: list[AgentOperator] | None = None,
    ):
        if not callable(trigger):
            raise TypeError("trigger must be callable")
        candidates = list(candidate_operators or [])
        if any(not isinstance(candidate, AgentOperator) for candidate in candidates):
            raise TypeError("candidate_operators must contain only AgentOperator instances")

        candidate_names = [candidate.__class__.__name__ for candidate in candidates]
        duplicate_names = sorted({name for name in candidate_names if candidate_names.count(name) > 1})
        if duplicate_names:
            raise ValueError(
                "candidate_operators must have unique class names; duplicates: "
                + ", ".join(duplicate_names)
            )

        self._trigger = trigger
        self._candidate_operators = candidates
        self._candidate_operator_by_name = dict(zip(candidate_names, candidates))
        super().__init__()

    @property
    def candidate_operators(self) -> tuple[AgentOperator, ...]:
        return tuple(self._candidate_operators)

    @description
    def get_description(self) -> str:
        description_text = "Delegate a self-contained task to a subagent and return its result."
        if not self._candidate_operators:
            return description_text

        candidate_sections = []
        for candidate in self._candidate_operators:
            serialized = candidate.get_serialized_operator()
            candidate_sections.append(
                f"- {serialized.name}: {serialized.description or 'No description provided.'}"
            )

        return (
            f"{description_text}\n\n"
            "Candidate operators available to the subagent:\n"
            + "\n".join(candidate_sections)
        )

    @agent_tool(description="""
Delegate a self-contained task to a subagent.
""")
    def trigger_subagent(self, task: str, operator_list: list[str]):
        """
        :param task: A complete, self-contained task for the subagent
        :param operator_list: Candidate operator names to make available to the subagent
        """
        request = self._build_request(task=task, operator_list=operator_list)
        return self._trigger(request)

    def _build_request(self, task: str, operator_list: list[str]) -> SubagentRequest:
        try:
            request = SubagentRequest(task=task, operator_list=operator_list)
        except ValidationError as exc:
            details = []
            for error in exc.errors():
                field = ".".join(str(part) for part in error["loc"])
                message = error["msg"].removeprefix("Value error, ")
                details.append(f"{field}: {message}")
            raise ValueError("Invalid subagent request: " + "; ".join(details)) from None

        available_names = list(self._candidate_operator_by_name)
        if not available_names:
            raise ValueError(
                "No candidate operators are configured for SubagentOperator; "
                "register at least one before delegating a task"
            )

        unknown_names = [
            name for name in request.operator_list
            if name not in self._candidate_operator_by_name
        ]
        if unknown_names:
            raise ValueError(
                f"Unknown candidate operator(s): {', '.join(unknown_names)}. "
                f"Available operators: {', '.join(available_names)}"
            )

        return request
