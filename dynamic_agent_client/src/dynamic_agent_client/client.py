"""
This acts as a final wrapper to user
"""
import asyncio
import inspect
import json
from typing import Callable
from uuid import uuid4

import websockets
from pydantic import ValidationError

from .client_struct import (
    AgentEvent,
    AgentInvocationEvent,
    AgentResponseChunk,
    AgentToolCallMessage,
    ToolExecutionEvent,
    service_to_client_message_adapter,
)
from .operator.agent_operator_base import AgentOperator
from .service_handler import ServiceHandler


class DynamicAgentClient:

    def __init__(self):
        self.session_id: str | None = None
        self.runner_id: str | None = None
        self.websocket = None
        self.messages: list = []

        self._on_chunk: Callable[[AgentResponseChunk], None] | None = None
        self._on_event: Callable[[AgentEvent], None] | None = None
        self._accumulated_text = ""
        self._active_invocations: dict[str, AgentInvocationEvent] = {}
        self._response_done = asyncio.Event()
        self._listen_task = None
        self._tool_tasks: set[asyncio.Task] = set()
        self._connected = True
        self._needs_reconnect = True

        self.tool_map: dict[str, dict[str, Callable]] = {}
        self._operators: list[AgentOperator] = []

    @classmethod
    async def connect(cls, server_addr: str):
        """Start the shared webhook server and store the service address."""
        await ServiceHandler.connect(server_addr)

    @classmethod
    async def create(
        cls,
        setting: str,
        reconnect_keep: int = 30,
        session_id: str = None,
        persist: bool = False,
    ) -> "DynamicAgentClient":
        """Create a Redis-backed session. Set persist=True for PostgreSQL persistence."""
        instance = cls()
        (
            instance.session_id,
            instance.runner_id,
            instance.websocket,
            instance.messages,
        ) = await ServiceHandler.create_session(
            setting,
            instance,
            reconnect_keep=reconnect_keep,
            session_id=session_id,
            persist=persist,
        )
        instance._listen_task = asyncio.ensure_future(instance._listen())
        return instance

    async def _listen(self):
        """Listen for messages from server. Sets _connected=False on disconnect."""
        try:
            async for message in self.websocket:
                try:
                    service_message = service_to_client_message_adapter.validate_json(message)
                except ValidationError as exc:
                    print(f"[websocket] ERROR: Invalid service message: {exc}")
                    continue

                if isinstance(service_message, AgentResponseChunk):
                    text = service_message.text
                    is_main_runner = service_message.runner_id in (None, self.runner_id)

                    invocation = self._accumulate_invocation(service_message)

                    if self._on_chunk:
                        try:
                            self._on_chunk(service_message)
                        except Exception as exc:
                            print(f"[agent_chunk] WARNING: callback failed: {exc}")

                    if invocation is not None:
                        self._emit_event(invocation)

                    if service_message.finished and service_message.parent_tool_call_id:
                        await ServiceHandler.send_tool_result(
                            session_id=self.session_id,
                            runner_id=service_message.parent_runner_id,
                            tool_call_id=service_message.parent_tool_call_id,
                            ok=True,
                            result=text,
                        )

                    if text and is_main_runner:
                        self._accumulated_text += text

                    if service_message.finished and is_main_runner:
                        self._response_done.set()
                elif isinstance(service_message, AgentToolCallMessage):
                    task = asyncio.create_task(self._handle_tool_call(service_message))
                    self._tool_tasks.add(task)
                    task.add_done_callback(self._tool_tasks.discard)
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass

        self._connected = False

    def _runner_key(self, runner_id: str | None) -> str:
        """Return a stable local key for a main or subagent runner."""
        return runner_id or self.runner_id or "main"

    def _accumulate_invocation(
        self,
        chunk: AgentResponseChunk,
    ) -> AgentInvocationEvent | None:
        """Build one high-level invocation from a runner's streamed chunks."""
        runner_id = self._runner_key(chunk.runner_id)
        if chunk.finished and not chunk.invoked:
            return None
        invocation = self._active_invocations.get(runner_id)
        if invocation is None:
            invocation = AgentInvocationEvent(
                session_id=self.session_id,
                invocation_id=uuid4().hex,
                runner_id=runner_id,
            )
            self._active_invocations[runner_id] = invocation

        if chunk.runner_name is not None:
            invocation.runner_name = chunk.runner_name
        if chunk.parent_runner_id is not None:
            invocation.parent_runner_id = chunk.parent_runner_id
        if chunk.parent_tool_call_id is not None:
            invocation.parent_tool_call_id = chunk.parent_tool_call_id
        if chunk.text and not chunk.finished:
            invocation.text += chunk.text
        if chunk.prompt_tokens or chunk.completion_tokens or chunk.total_tokens:
            invocation.prompt_tokens = chunk.prompt_tokens
            invocation.completion_tokens = chunk.completion_tokens
            invocation.total_tokens = chunk.total_tokens

        if chunk.invoked:
            self._active_invocations.pop(runner_id, None)
            invocation.finished = chunk.finished
            return invocation
        return None

    def _emit_event(self, event: AgentEvent) -> None:
        """Emit one high-level agent or tool lifecycle event."""
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as exc:
                print(f"[agent_event] WARNING: callback failed: {exc}")

    async def _handle_tool_call(self, tool_call: AgentToolCallMessage):
        llm_tool_name = tool_call.name
        arguments = dict(tool_call.arguments)
        tool_call_id = tool_call.tool_call_id
        runner_id = tool_call.runner_id

        for key, value in list(arguments.items()):
            if isinstance(value, str):
                try:
                    arguments[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass

        ok = True
        callable_func = None
        error = None
        self._emit_event(ToolExecutionEvent(
            session_id=self.session_id,
            runner_id=runner_id,
            tool_call_id=tool_call_id,
            name=llm_tool_name,
            arguments=arguments,
            status="started",
        ))
        try:
            callable_func = self.tool_map[runner_id][llm_tool_name]
            callable_func.operator.session_id = self.session_id
            callable_func.operator.runner_id = runner_id
            callable_func.operator.tool_call_id = tool_call_id
            result = callable_func(**arguments)
            if inspect.isawaitable(result):
                result = await result
        except KeyError:
            ok = False
            result = f"Tool not found: {llm_tool_name}"
            error = result
            print(f"[tool_call] ERROR: {result}")
        except Exception as exc:
            ok = False
            result = f"Error: Tool execution failed: {exc}"
            error = str(exc)
            print(f"[tool_call] ERROR: {result}")

        self._emit_event(ToolExecutionEvent(
            session_id=self.session_id,
            runner_id=runner_id,
            tool_call_id=tool_call_id,
            name=llm_tool_name,
            arguments=arguments,
            status="succeeded" if ok else "failed",
            result=result if ok else None,
            error=error,
        ))

        if result is None:
            return

        await ServiceHandler.send_tool_result(
            session_id=self.session_id,
            runner_id=runner_id,
            tool_call_id=tool_call_id,
            ok=ok,
            result=result,
        )

    async def trigger(
        self,
        text: str,
        on_chunk: Callable[[AgentResponseChunk], None] = None,
        on_event: Callable[[AgentEvent], None] = None,
        bucket_name: str = None,
    ):
        await self._ensure_connected()

        self._on_chunk = on_chunk
        self._on_event = on_event
        self._accumulated_text = ""
        self._active_invocations.clear()
        self._response_done.clear()
        for operator in self._operators:
            operator.reset_tool_counters()

        # Fire HTTP trigger, response streams via WebSocket
        await ServiceHandler.trigger(self.session_id, text, bucket_name=bucket_name)
        # Wait for streaming response to complete
        await self._response_done.wait()
        result = self._accumulated_text
        self._accumulated_text = ""
        return result

    async def add_operator(self, operator):
        if not isinstance(operator, AgentOperator):
            raise TypeError("operator must be an AgentOperator instance")
        result = await ServiceHandler.add_operator(self.session_id, self, operator)
        self._operators.append(operator)
        return result

    @classmethod
    async def delete_session(cls, session_id: str) -> bool:
        """Delete persisted chat messages for a session."""
        return await ServiceHandler.delete_session(session_id)

    @classmethod
    async def create_bucket(cls, name: str, description: str = ""):
        """Create a new bucket for storing knowledge."""
        return await ServiceHandler.create_bucket(name, description)

    @classmethod
    async def check_bucket(cls, name: str):
        """Check if a bucket exists."""
        return await ServiceHandler.check_bucket(name)

    @classmethod
    async def delete_bucket(cls, name: str):
        """Delete a bucket and all its contents."""
        return await ServiceHandler.delete_bucket(name)

    async def _ensure_connected(self):
        """Ensure websocket is connected, reconnect if needed."""
        if self._connected:
            return

        if not self._needs_reconnect:
            raise Exception("Connection closed and reconnect disabled")

        print("Connection lost. Reconnecting...")
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        self.websocket = await ServiceHandler.reconnect_session(self.session_id)
        self._connected = True
        self._listen_task = asyncio.ensure_future(self._listen())
        print("Reconnected successfully!")

    async def _reconnect(self) -> bool:
        """Attempt to reconnect to existing session. Returns True if successful."""
        if self.session_id is None:
            return False
        try:
            print(f"Attempting to reconnect to session {self.session_id}...")
            self.websocket = await ServiceHandler.reconnect_session(self.session_id)
            print("Reconnection successful!")
            return True
        except Exception as e:
            print(f"Reconnection failed: {e}")
            return False

    async def close(self):
        self._needs_reconnect = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        for task in self._tool_tasks:
            task.cancel()
        self._tool_tasks.clear()

        if self.session_id:
            ServiceHandler.unregister_client(self.session_id, client_instance=self)
            self.session_id = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __del__(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.close())
        except Exception:
            pass
