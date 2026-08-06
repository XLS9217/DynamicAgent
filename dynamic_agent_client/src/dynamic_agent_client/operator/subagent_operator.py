from pydantic import BaseModel, Field, ValidationError, field_validator

from .agent_operator_base import AgentOperator, agent_tool, description
from ..service_handler import ServiceHandler


class InitSubagentRequest(BaseModel):
    name: str = Field(description="A unique name for the subagent")
    setting: str = Field(description="The role and behavior of the subagent")
    operator_list: list[str] = Field(
        min_length=1,
        description="Names of candidate operators the subagent may use",
    )

    @field_validator("name", "setting")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value

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


class TriggerSubagentRequest(BaseModel):
    runner_id: str = Field(description="The runner ID returned by init_subagent")
    task: str = Field(description="A complete, self-contained task for the subagent")

    @field_validator("runner_id", "task")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value


class SubagentOperator(AgentOperator):
    """Initialize reusable subagents and dispatch work to them."""

    def __init__(self, candidate_operators: list[AgentOperator] | None = None):
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

        self._candidate_operators = candidates
        self._candidate_operator_by_name = dict(zip(candidate_names, candidates))
        super().__init__()

    @property
    def candidate_operators(self) -> tuple[AgentOperator, ...]:
        return tuple(self._candidate_operators)

    def serialize_selected_operators(self, operator_names: list[str]) -> list[dict]:
        return [
            self._candidate_operator_by_name[name].get_serialized_operator().model_dump()
            for name in operator_names
        ]

    def reset_tool_counters(self) -> None:
        super().reset_tool_counters()
        for candidate in self._candidate_operators:
            candidate.reset_tool_counters()

    @description
    def get_description(self) -> str:
        description_text = "Initialize a subagent, then delegate self-contained tasks to it."
        if not self._candidate_operators:
            return description_text

        candidates = [
            f"- {serialized.name}: {serialized.description or 'No description provided.'}"
            for serialized in (
                candidate.get_serialized_operator()
                for candidate in self._candidate_operators
            )
        ]
        return (
            f"{description_text}\n\n"
            "Candidate operators available to the subagent:\n"
            + "\n".join(candidates)
        )

    @agent_tool(description="Initialize a reusable subagent and receive its runner ID.")
    async def init_subagent(self, name: str, setting: str, operator_list: list[str]):
        """
        :param name: A unique, descriptive name for the subagent
        :param setting: The role and behavior the subagent should follow
        :param operator_list: Candidate operator names to make available to the subagent
        """
        request = self._build_init_request(name, setting, operator_list)
        self._require_execution_context(require_tool_call=False)
        selected_operators = [
            self._candidate_operator_by_name[name]
            for name in request.operator_list
        ]
        response = await ServiceHandler.init_subagent(
            session_id=self.session_id,
            parent_runner_id=self.runner_id,
            name=request.name,
            setting=request.setting,
            operators=self.serialize_selected_operators(request.operator_list),
        )
        runner_id = response.get("runner_id")
        if response.get("status") != "ok" or not runner_id:
            raise RuntimeError(f"Subagent initialization failed: {response}")
        ServiceHandler.register_runner_operators(
            session_id=self.session_id,
            runner_id=runner_id,
            operators=selected_operators,
        )
        return response

    @agent_tool(description="Send a task to an initialized subagent.")
    async def trigger_subagent(self, runner_id: str, task: str):
        """
        :param runner_id: The runner ID returned by init_subagent
        :param task: A complete, self-contained task for the subagent
        """
        request = self._validate_model(
            TriggerSubagentRequest,
            runner_id=runner_id,
            task=task,
        )
        self._require_execution_context(require_tool_call=True)
        session_id = self.session_id
        parent_runner_id = self.runner_id
        parent_tool_call_id = self.tool_call_id
        response = await ServiceHandler.trigger_subagent(
            session_id=session_id,
            parent_runner_id=parent_runner_id,
            parent_tool_call_id=parent_tool_call_id,
            runner_id=request.runner_id,
            task=request.task,
        )
        if response.get("status") != "accepted":
            raise RuntimeError(f"Subagent dispatch was not accepted: {response}")
        return None

    def _build_init_request(
        self,
        name: str,
        setting: str,
        operator_list: list[str],
    ) -> InitSubagentRequest:
        request = self._validate_model(
            InitSubagentRequest,
            name=name,
            setting=setting,
            operator_list=operator_list,
        )
        available_names = list(self._candidate_operator_by_name)
        if not available_names:
            raise ValueError(
                "No candidate operators are configured for SubagentOperator; "
                "register at least one before initializing a subagent"
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

    def _require_execution_context(self, require_tool_call: bool) -> None:
        missing = not self.session_id or not self.runner_id
        if require_tool_call:
            missing = missing or not self.tool_call_id
        if missing:
            raise RuntimeError("SubagentOperator is missing its tool execution context")

    @staticmethod
    def _validate_model(model_type, **values):
        try:
            return model_type(**values)
        except ValidationError as exc:
            details = []
            for error in exc.errors():
                field = ".".join(str(part) for part in error["loc"])
                message = error["msg"].removeprefix("Value error, ")
                details.append(f"{field}: {message}")
            raise ValueError("Invalid subagent request: " + "; ".join(details)) from None
