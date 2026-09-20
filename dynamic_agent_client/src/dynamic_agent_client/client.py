"""
This acts as a final wrapper to user
"""
import asyncio
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
        self._trigger_id: str | None = None
        self._trigger_future: asyncio.Future | None = None
        self._trigger_accepted = asyncio.Event()
        self._stopping_trigger: str | None = None
        self._listen_task = None
        self._tool_tasks: set[asyncio.Task] = set()
        self._connected = True
        self._needs_reconnect = True

        self.tool_map: dict[str, dict[str, Callable]] = {}
        self._operators: list[AgentOperator] = []

    @classmethod
    async def connect(cls, server_addr: str):
        """Configure the shared backend address and HTTP client."""
        await ServiceHandler.connect(server_addr)

    @classmethod
    async def create(
        cls,
        setting: str,
        reconnect_keep: int = 30,
        session_id: str = None,
    ) -> "DynamicAgentClient":
        """Create a session with PostgreSQL history and a Redis message cache."""
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

                if service_message.trigger_id is not None and service_message.trigger_id != self._trigger_id:
                    continue
                if self._stopping_trigger is not None and isinstance(service_message, AgentToolCallMessage):
                    continue

                if isinstance(service_message, AgentResponseChunk):
                    if not self._handle_response_chunk(service_message):
                        continue
                    if service_message.finished and service_message.parent_tool_call_id and not service_message.cancelled:
                        await ServiceHandler.send_tool_result(
                            session_id=self.session_id,
                            runner_id=service_message.parent_runner_id,
                            tool_call_id=service_message.parent_tool_call_id,
                            ok=True,
                            result=service_message.text,
                            trigger_id=service_message.trigger_id,
                        )
                elif isinstance(service_message, AgentToolCallMessage):
                    task = asyncio.create_task(self._handle_tool_call(service_message))
                    self._tool_tasks.add(task)
                    task.add_done_callback(self._tool_tasks.discard)
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass

        finally:
            self._connected = False
            if self._stopping_trigger is None:
                self._fail_turn(ConnectionError("WebSocket disconnected before turn completion"))

    def _fail_turn(self, error: Exception) -> None:
        if self._trigger_future is not None and not self._trigger_future.done():
            self._trigger_future.set_exception(error)

    def _handle_response_chunk(self, chunk: AgentResponseChunk) -> bool:
        """Handle HTTP and WebSocket completion once, using the same turn ID."""
        if chunk.trigger_id is not None and chunk.trigger_id != self._trigger_id:
            return False
        is_main = chunk.runner_id in (None, self.runner_id)
        if is_main and self._trigger_future is not None and self._trigger_future.done():
            return False
        invocation = self._accumulate_invocation(chunk)
        if chunk.cancelled and is_main:
            for task in tuple(self._tool_tasks):
                task.cancel()
        if is_main:
            if chunk.finished:
                if chunk.text or chunk.cancelled:
                    self._accumulated_text = chunk.text
            else:
                self._accumulated_text += chunk.text
        if self._on_chunk and (self._stopping_trigger is None or chunk.finished):
            try:
                self._on_chunk(chunk)
            except Exception as exc:
                print(f"[agent_chunk] WARNING: callback failed: {exc}")
        if invocation is not None:
            self._emit_event(invocation)
        if chunk.finished and is_main and self._trigger_future is not None:
            self._trigger_future.set_result(self._accumulated_text)
        return True

    def _runner_key(self, runner_id: str | None) -> str:
        """Return a stable local key for a main or subagent runner."""
        return runner_id or self.runner_id or "main"

    def _accumulate_invocation(
        self,
        chunk: AgentResponseChunk,
    ) -> AgentInvocationEvent | None:
        """Build one high-level invocation from a runner's streamed chunks."""
        runner_id = self._runner_key(chunk.runner_id)
        if chunk.cancelled:
            invocation = self._active_invocations.pop(runner_id, None)
            if invocation is not None:
                invocation.cancelled = True
                invocation.finished = True
            return invocation
        if chunk.finished and not chunk.invoked:
            return None
        invocation = self._active_invocations.get(runner_id)
        if invocation is None:
            invocation = AgentInvocationEvent(
                session_id=self.session_id,
                invocation_id=uuid4().hex,
                runner_id=runner_id,
                trigger_id=chunk.trigger_id,
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
            trigger_id=tool_call.trigger_id,
        ))
        try:
            callable_func = self.tool_map[runner_id][llm_tool_name]
            callable_func.operator.session_id = self.session_id
            callable_func.operator.runner_id = runner_id
            callable_func.operator.tool_call_id = tool_call_id
            callable_func.operator.trigger_id = tool_call.trigger_id
            result = await callable_func(**arguments)
        except asyncio.CancelledError:
            if tool_call.trigger_id == self._trigger_id:
                self._emit_event(ToolExecutionEvent(
                    session_id=self.session_id, runner_id=runner_id,
                    tool_call_id=tool_call_id, name=llm_tool_name,
                    arguments=arguments, status="cancelled", trigger_id=tool_call.trigger_id,
                ))
            raise
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

        if tool_call.trigger_id is not None and (
            tool_call.trigger_id != self._trigger_id or tool_call.trigger_id == self._stopping_trigger
        ):
            return
        self._emit_event(ToolExecutionEvent(
            session_id=self.session_id,
            runner_id=runner_id,
            tool_call_id=tool_call_id,
            name=llm_tool_name,
            arguments=arguments,
            status="succeeded" if ok else "failed",
            result=result if ok else None,
            error=error,
            trigger_id=tool_call.trigger_id,
        ))

        if result is None:
            return

        await ServiceHandler.send_tool_result(
            session_id=self.session_id,
            runner_id=runner_id,
            tool_call_id=tool_call_id,
            ok=ok,
            result=result,
            trigger_id=tool_call.trigger_id,
        )

    async def trigger(
        self,
        text: str,
        on_chunk: Callable[[AgentResponseChunk], None] = None,
        on_event: Callable[[AgentEvent], None] = None,
    ):
        """Run a turn and return its full or stopped partial response."""
        if self._trigger_future is not None and not self._trigger_future.done():
            raise RuntimeError("A turn is already active")
        await self._ensure_connected()

        if self._trigger_future is not None and not self._trigger_future.done():
            raise RuntimeError("A turn is already active")
        self._trigger_id = uuid4().hex
        self._stopping_trigger = None
        self._trigger_accepted = asyncio.Event()
        accepted = self._trigger_accepted
        future = asyncio.get_running_loop().create_future()
        self._trigger_future = future
        self._on_chunk = on_chunk
        self._on_event = on_event
        self._accumulated_text = ""
        self._active_invocations.clear()
        for operator in self._operators:
            operator.reset_tool_counters()

        # Fire HTTP trigger, response streams via WebSocket
        try:
            await ServiceHandler.trigger(self.session_id, text, trigger_id=self._trigger_id)
        except BaseException:
            future.cancel()
            raise
        finally:
            accepted.set()
        return await asyncio.shield(future)

    async def stop(self) -> None:
        """Stop the current turn and keep the session ready for another trigger."""
        future = self._trigger_future
        trigger_id = self._trigger_id
        if future is None or future.done():
            return
        self._stopping_trigger = trigger_id
        for task in tuple(self._tool_tasks):
            task.cancel()
        await self._trigger_accepted.wait()
        if future.cancelled():
            return
        try:
            response = await ServiceHandler.stop_trigger(self.session_id, trigger_id)
            completion = response.get("completion")
            if completion is not None:
                self._handle_response_chunk(AgentResponseChunk.model_validate(completion))
            elif not future.done():
                raise RuntimeError("Stop returned without a completion for the active turn")
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        await asyncio.shield(future)

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
        self._fail_turn(ConnectionError("Client closed before turn completion"))
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
