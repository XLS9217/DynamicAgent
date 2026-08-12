"""Central flat-file logging boundary for LLM provider invocations."""

from dataclasses import dataclass
from typing import Any
import uuid

from dynamic_agent_service.logging.cache_log_accessor import CacheLogAccessor
from dynamic_agent_service.logging.log_struct import InvokeLog


@dataclass
class _LogContext:
    resource_id: str | None = None
    trigger_id: str | None = None


class LogInterface:
    """Class-level API appending one complete flat record per provider invoke."""

    _contexts: dict[str, _LogContext] = {}

    @classmethod
    def configure_resource(cls, session_id: str, resource_id: str) -> None:
        cls._contexts.setdefault(session_id, _LogContext()).resource_id = resource_id

    @classmethod
    def start_trigger(cls, session_id: str, trigger_id: str) -> None:
        cls._contexts.setdefault(session_id, _LogContext()).trigger_id = trigger_id

    @classmethod
    def complete_trigger(cls, session_id: str) -> None:
        context = cls._contexts.get(session_id)
        if context is not None:
            context.trigger_id = None

    @classmethod
    def release_session(cls, session_id: str) -> None:
        cls._contexts.pop(session_id, None)

    @classmethod
    async def append_invoke_log(
        cls,
        *,
        session_id: str,
        runner_id: str,
        parent_runner_id: str | None,
        messages: list[dict],
        text: str | None = None,
        tool_use: dict | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        usage_detail: dict | None = None,
        error: dict | None = None,
    ) -> str:
        """Append exactly one finished invocation to its trigger JSONL file."""
        context = cls._contexts.get(session_id)
        if context is None or context.resource_id is None:
            raise RuntimeError(f"Missing resource context for session {session_id}")

        tool_results = [message for message in messages if message.get("role") == "tool"]
        tool_calls = (tool_use or {}).get("items") or []
        invoke_id = str(uuid.uuid4())
        record = InvokeLog(
            invoke_id=invoke_id,
            trigger_id=context.trigger_id,
            runner_id=runner_id,
            parent_runner_id=parent_runner_id,
            text=text,
            tool_id=tool_calls[0].get("id") if len(tool_calls) == 1 else None,
            tool_use=tool_use if tool_calls else None,
            tool_result={"items": tool_results} if tool_results else None,
            resource_id=context.resource_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usage_detail=usage_detail,
            error=error,
        )

        await CacheLogAccessor.append_invoke_log(record)
        return invoke_id

    @classmethod
    def error(cls, exc: BaseException) -> dict[str, Any]:
        return {
            "type": type(exc).__name__,
            "message": str(exc),
        }
