"""Script name: agent_operator_base.py. Define async tools and generate their schemas."""

import inspect
import re
from abc import ABC
from typing import Callable, get_type_hints
from logging import getLogger

from pydantic import BaseModel, Field, create_model

logger = getLogger(__name__)


def _parse_docstring_params(docstring: str | None) -> dict[str, str]:
    """Parse :param name: description lines from a docstring."""
    if not docstring:
        return {}

    param_descriptions = {}
    pattern = r':param\s+(\w+):\s*(.+?)(?=:param|:return|:rtype|$)'
    matches = re.findall(pattern, docstring, re.DOTALL)

    for name, desc in matches:
        cleaned_desc = ' '.join(desc.split())
        if cleaned_desc:
            param_descriptions[name] = cleaned_desc

    return param_descriptions


def _build_schema(func: Callable, description: str) -> dict:
    """Generate a tool's argument schema from annotations, defaults, and docstrings."""
    type_hints = get_type_hints(func, include_extras=True)
    param_descriptions = _parse_docstring_params(func.__doc__)
    fields = {}

    # Tool arguments arrive as named JSON fields.
    for name, param in inspect.signature(func).parameters.items():
        if name == "self":
            continue
        if param.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            raise TypeError(f"Tool {func.__qualname__}: {name} must be a named parameter")
        default = ... if param.default is inspect.Parameter.empty else param.default
        field = Field(default=default, description=param_descriptions[name]) if name in param_descriptions else default
        fields[name] = (type_hints.get(name, str), field)

    # Keep nested definitions and references together in the parameter schema.
    arguments_model = create_model(f"{func.__name__}Arguments", **fields)
    return {
        "name": func.__name__,
        "description": description or func.__doc__ or "",
        "parameters": arguments_model.model_json_schema(),
    }


def agent_tool(description: str = "", count_limit: int | None = None, max_calls_per_trigger: int | None = None):
    """
    Decorator to mark a method as an agent tool.
    Only works on class methods (must have self as first param).
    """
    if count_limit is not None and count_limit < 1:
        raise ValueError("count_limit must be greater than 0")
    if max_calls_per_trigger is not None and max_calls_per_trigger < 1:
        raise ValueError("max_calls_per_trigger must be greater than 0")

    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        if not params or params[0] != 'self':
            raise ValueError("@agent_tool can only decorate class methods")

        if not inspect.iscoroutinefunction(func):
            raise TypeError("@agent_tool methods must use async def")

        func._agent_tool_schema = _build_schema(func, description)
        func._agent_tool_count_limit = count_limit if count_limit is not None else max_calls_per_trigger
        return func

    return decorator


def description(func: Callable) -> Callable:
    """
    Decorator to mark a method as the operator's description provider.
    The method must take only self and return a str.
    Used to supply the agent's system prompt description.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    if not params or params[0] != 'self':
        raise ValueError("@description can only decorate class methods")
    func._is_operator_description = True
    return func


def flow(func: Callable) -> Callable:
    """
    Decorator to mark a method as the operator's flow provider.
    The method must take only self and return a str.
    Used to supply the agent's step-by-step flow instructions.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    if not params or params[0] != 'self':
        raise ValueError("@flow can only decorate class methods")
    func._is_operator_flow = True
    return func

class SerializedOperatorStructure(BaseModel):
    """
    Work with service's operator handler
    """
    name: str # name of class
    tools: list[dict] #openai tools schema
    description: str | None = None # description of the operator
    flows: list[dict[str,str]] | None = None # each individual flow, yes, there could be multiple flow, flow_name: flow_text

class AgentOperator(ABC):
    """
    Base class for operators that provide tools to the agent.
    Subclasses define @agent_tool methods.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._tool_call_counts: dict[str, int] = {}
        self._description_func = None
        self._flow_funcs: list[tuple[str, Callable]] = []
        self.session_id: str | None = None
        self.runner_id: str | None = None
        self.tool_call_id: str | None = None
        self.trigger_id: str | None = None
        self._collect_tools()

    def _collect_tools(self):
        """Find all @agent_tool, @description, and @flow methods on this instance"""
        for name in dir(self):
            if name.startswith('_'):
                continue

            try:
                attr = getattr(self, name)
            except Exception as e:
                print(f"Warning: Failed to get attribute '{name}': {e}")
                continue

            if not callable(attr):
                continue

            func = getattr(attr, '__func__', attr)

            if hasattr(func, '_agent_tool_schema'):
                self._tools[name] = {
                    "schema": func._agent_tool_schema,
                    "callable": attr,
                    "count_limit": getattr(func, "_agent_tool_count_limit", None),
                }
                self._tool_call_counts[name] = 0
                logger.info(f"Collected tool: {name}")

            elif hasattr(func, '_is_operator_description'):
                self._description_func = attr
                logger.info(f"Collected description: {name}")

            elif hasattr(func, '_is_operator_flow'):
                self._flow_funcs.append((name, attr))
                logger.info(f"Collected flow: {name}")

        logger.info(f"Total tools collected: {len(self._tools)}")

    def get_serialized_operator(self) -> SerializedOperatorStructure:
        """Serialize this operator into a SerializedOperatorStructure."""
        class_name = self.__class__.__name__
        tools = []
        for t in self._tools.values():
            schema = dict(t["schema"])
            schema["name"] = f"{class_name}_{schema['name']}"
            tools.append({"type": "function", "function": schema})

        desc = self._description_func() if self._description_func else None

        flows = [{name: func()} for name, func in self._flow_funcs] if self._flow_funcs else None

        return SerializedOperatorStructure(
            name=class_name,
            tools=tools,
            description=desc,
            flows=flows,
        )

    async def execute(self, tool_name: str, arguments: dict):
        """Execute a tool by name with given arguments."""
        if tool_name not in self._tools:
            raise ValueError(f"Tool {tool_name} not found in operator")

        tool_info = self._tools[tool_name]
        count_limit = tool_info.get("count_limit")
        current_count = self._tool_call_counts.get(tool_name, 0)
        if count_limit is not None and current_count >= count_limit:
            return (
                f"Tool use limit reached for {self.__class__.__name__}.{tool_name}: "
                f"maximum {count_limit} call(s) per trigger. Do not call this tool again in this trigger; "
                "answer with the information already available or explain what could not be retrieved."
            )

        self._tool_call_counts[tool_name] = current_count + 1
        callable_func = tool_info["callable"]
        return await callable_func(**arguments)

    def reset_tool_counters(self) -> None:
        """Reset per-trigger tool call counters."""
        for tool_name in self._tools:
            self._tool_call_counts[tool_name] = 0
