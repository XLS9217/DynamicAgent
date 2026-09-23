import asyncio
import json
import re
import time
import uuid
from fastapi import WebSocket, WebSocketDisconnect

from dynamic_agent_client.client_struct import AgentResponseChunk, AgentToolCallMessage
from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.agent.agent_structs import AgentState, AgentToolCall
from dynamic_agent_service.external_service.openai_resource_accessor import OpenAIResourceAccessor
from dynamic_agent_service.external_service.openai_adapter import OpenAIAdapter
from dynamic_agent_service.service.media_storage import MediaStorage
from dynamic_agent_service.service.service_structs import (
    CreateSessionRequest,
    MessageItem,
    StoredImagePart,
)
from dynamic_agent_service.logging.log_interface import LogInterface
from dynamic_agent_service.logging.setup_logging import get_my_logger
from dynamic_agent_service.service.session_accessor import SessionAccessor

logger = get_my_logger()

def _sanitize_json(raw: str) -> str:
    """Fix common LLM JSON quirks like leading zeros (e.g. 00.5 -> 0.5)."""
    return re.sub(r'(?<![0-9])0+(\d+\.)', r'\1', raw)


def _tool_arguments_to_object(raw: str | dict | None) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        arguments = json.loads(_sanitize_json(raw or "{}"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(arguments, dict):
        return {}
    return arguments


class RealtimeSession:
    def __init__(
        self,
        setting: str,
        reconnect_keep: int = 30,
        session_id: str = None,
    ):
        self.session_id = session_id or str(uuid.uuid4())
        self.setting = setting
        self.reconnect_keep = reconnect_keep
        self.disconnect_time: float | None = None
        self.client: WebSocket | None = None
        self.agi: AgentGeneralInterface | None = None
        self.active_trigger_task: asyncio.Task | None = None
        self.subagent_tasks: set[asyncio.Task] = set()
        self.trigger_id: str | None = None
        self._trigger_open = False
        self._terminal_chunk: AgentResponseChunk | None = None
        self._stopping = False
        self._completion_lock = asyncio.Lock()
        self._uncommitted_images: list[StoredImagePart] = []

    @property
    def state(self) -> AgentState:
        if self._stopping:
            return AgentState.RUNNING
        if self.agi is None:
            return AgentState.IDLE
        if (
            self.active_trigger_task is not None
            and not self.active_trigger_task.done()
            and self.agi.state is AgentState.IDLE
        ):
            return AgentState.RUNNING
        return self.agi.state

    # ===== Session message persistence =====

    async def append_message(
        self,
        role: str,
        content: str | MessageItem,
    ) -> str:
        """Store a message in both backends and return its UUID."""
        return await SessionAccessor.append_message(
            self.session_id,
            content if isinstance(content, MessageItem) else MessageItem.from_text(role, content),
        )

    async def load_messages(self) -> list[dict]:
        """Load public history without filesystem paths or encoded image bytes."""
        messages = await SessionAccessor.load_messages(self.session_id)
        return [message.public_message() for message in messages]

    async def load_model_messages(self) -> list[dict]:
        """Materialize stored image references for one model turn."""
        messages = await SessionAccessor.load_messages(self.session_id)
        return [await MediaStorage.materialize(message) for message in messages]

    async def agent_setup(self):
        resource = await OpenAIResourceAccessor.get_active_resource()
        if resource is None:
            raise RuntimeError("No enabled OpenAI resource is configured")

        self.agi = await AgentGeneralInterface.create(
            openai_adapter=OpenAIAdapter(
                api_key=resource.api_key,
                base_url=resource.base_url,
                model=resource.model,
            ),
            setting=self.setting,
            send_tool_calls=self._send_tool_calls,
            log_session_id=self.session_id,
        )
        LogInterface.configure_resource(self.session_id, resource.resource_id)

    async def attach_websocket(self, client: WebSocket):
        # Close old WebSocket if exists
        if self.client is not None:
            await self.client.close()

        self.client = client
        self.disconnect_time = None

        async def stream_callback(chunk: AgentResponseChunk):
            """Persist completed turns and release ownership before sending completion."""
            if self._stopping or (chunk.trigger_id is not None and chunk.trigger_id != self.trigger_id):
                return
            if (
                chunk.finished
                and self.agi is not None
                and chunk.runner_id == self.agi.runner_id
            ):
                async with self._completion_lock:
                    completion_task = asyncio.current_task()
                    self.active_trigger_task = completion_task
                    assistant_text = self.agi.accumulated_assistant_text
                    if assistant_text:
                        await self.append_message("assistant", assistant_text)
                    self._finish_turn(chunk.model_copy(update={"text": assistant_text}))
            await self.client.send_json(chunk.model_dump(exclude_none=True))

        self.agi.set_stream_callback(stream_callback)
        for runner_id, tool_calls in self.agi.pending_tool_calls_by_runner():
            await self._send_tool_calls(runner_id, tool_calls)

    def start_trigger(
        self,
        text: str,
        trigger_id: str,
        images: list[StoredImagePart] | None = None,
    ) -> None:
        """Reserve a turn before its background task starts."""
        self.trigger_id = trigger_id
        self._trigger_open = True
        self.agi.set_trigger(trigger_id)
        LogInterface.start_trigger(self.session_id, trigger_id)
        self._uncommitted_images = list(images or [])
        self.active_trigger_task = asyncio.create_task(self.trigger_agent(text, images=images))

    def accepts_trigger(self, trigger_id: str | None) -> bool:
        """Discard results and subagent requests from cancelled or previous turns."""
        return not self._stopping and (trigger_id is None or (self._trigger_open and trigger_id == self.trigger_id))

    def _finish_turn(self, chunk: AgentResponseChunk) -> None:
        """Release turn state consistently after completion, cancellation, or error."""
        LogInterface.complete_trigger(self.session_id)
        self.agi.reset_after_stop()
        self.active_trigger_task = None
        self._trigger_open = False
        self._stopping = False
        self._terminal_chunk = chunk

    async def stop(self, trigger_id: str | None = None) -> AgentResponseChunk | None:
        """Return the terminal result after cancellation and persistence finish."""
        async with self._completion_lock:
            if self._trigger_open and trigger_id is not None and trigger_id != self.trigger_id:
                return None
            if not self._trigger_open:
                terminal = self._terminal_chunk
                return terminal if terminal and trigger_id in (None, terminal.trigger_id) else None
            self._stopping = True
            tasks = self.agi.execution_tasks() | self.subagent_tasks
            if self.active_trigger_task is not None:
                tasks.add(self.active_trigger_task)
            tasks = {task for task in tasks if not task.done() and task is not asyncio.current_task()}
            try:
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await MediaStorage.delete(self._uncommitted_images)
                self._uncommitted_images = []
                text = self.agi.accumulated_assistant_text
                if text:
                    await self.append_message("assistant", text)
                await LogInterface.cancel_trigger(self.session_id, self.trigger_id, text)
            finally:
                terminal = AgentResponseChunk(
                    type="agent_chunk", text=self.agi.accumulated_assistant_text,
                    finished=True, cancelled=True, trigger_id=self.trigger_id,
                    runner_id=self.agi.runner_id, runner_name="main",
                )
                self._finish_turn(terminal)
        # HTTP carries the same result even when the WebSocket is disconnected.
        if self.client is not None:
            try:
                await self.client.send_json(terminal.model_dump(exclude_none=True))
            except (OSError, RuntimeError, WebSocketDisconnect):
                pass
        return terminal

    def register_operator(self, operator_data: dict):
        """Forward serialized operator data to AGI for registration."""
        self.agi.register_operator(operator_data)

    def is_expired(self) -> bool:
        """Check if session has been disconnected longer than reconnect_keep seconds."""
        return self.disconnect_time is not None and time.time() - self.disconnect_time > self.reconnect_keep

    async def listen(self):
        """Keep WebSocket alive for receiving messages (if needed in future)."""
        try:
            while True:
                await self.client.receive_json()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def trigger_agent(
        self,
        text: str,
        images: list[StoredImagePart] | None = None,
    ):
        """Persist and invoke one text or multimodal user message."""
        if self.client is None:
            raise RuntimeError("WebSocket not connected")
        if self.agi.state is not AgentState.IDLE:
            raise RuntimeError(f"Agent is {self.agi.state}")

        current_task = asyncio.current_task()
        try:
            user_message = MessageItem.from_user(text, images)

            # Do not interrupt a message halfway between PostgreSQL and Redis.
            async with self._completion_lock:
                history = await self.load_model_messages()
                try:
                    message_id = await self.append_message("user", user_message)
                except BaseException:
                    await MediaStorage.delete(images or [])
                    self._uncommitted_images = []
                    raise
                self._uncommitted_images = []
                LogInterface.start_trigger(self.session_id, self.trigger_id, message_id=message_id)

            message = {
                "type": "invoke",
                "content": (await MediaStorage.materialize(user_message))["content"],
            }

            # Trigger agent with history; AGI owns the in-progress invoke state.
            await self.agi.trigger(
                message,
                history=history,
            )
        except Exception as e:
            logger.exception(
                "Turn failed for session %s trigger %s: %s",
                self.session_id,
                self.trigger_id,
                e,
            )
            await MediaStorage.delete(self._uncommitted_images)
            self._uncommitted_images = []
            if self.active_trigger_task not in (None, current_task):
                raise
            if not self._trigger_open and self._terminal_chunk is not None:
                return
            error_chunk = AgentResponseChunk(
                type="agent_chunk",
                text="Error Occurred",
                finished=True,
                runner_id=self.agi.runner_id,
                runner_name="main",
                trigger_id=self.trigger_id,
            )
            async with self._completion_lock:
                self._finish_turn(error_chunk)
            if self.client is not None:
                await self.client.send_json(error_chunk.model_dump())
        finally:
            # Completion may already have allowed another trigger to take ownership.
            if self.active_trigger_task is current_task:
                self.active_trigger_task = None

    async def receive_tool_result(
        self,
        tool_call_id: str,
        ok: bool,
        result: object,
        runner_id: str | None = None,
    ) -> None:
        await self.agi.append_tool_result(
            tool_call_id=tool_call_id,
            ok=ok,
            result=result,
            runner_id=runner_id,
        )

    def init_subagent(
        self,
        parent_runner_id: str,
        name: str,
        setting: str,
        operators: list[dict],
    ) -> str:
        return self.agi.init_subagent(
            parent_runner_id=parent_runner_id,
            name=name,
            setting=setting,
            operators=operators,
        )

    async def trigger_subagent(
        self,
        parent_runner_id: str,
        parent_tool_call_id: str,
        runner_id: str,
        task: str,
    ) -> None:
        self.agi.validate_pending_tool_call(parent_runner_id, parent_tool_call_id)
        self.agi.validate_subagent_trigger(runner_id, parent_runner_id)
        task_handle = asyncio.create_task(
            self._run_subagent(
                parent_runner_id=parent_runner_id,
                parent_tool_call_id=parent_tool_call_id,
                runner_id=runner_id,
                task=task,
            )
        )
        self.subagent_tasks.add(task_handle)
        task_handle.add_done_callback(self.subagent_tasks.discard)

    async def _run_subagent(
        self,
        parent_runner_id: str,
        parent_tool_call_id: str,
        runner_id: str,
        task: str,
    ) -> None:
        try:
            await self.agi.trigger_subagent(
                runner_id=runner_id,
                parent_tool_call_id=parent_tool_call_id,
                task=task,
            )
        except Exception as exc:
            result = f"Subagent {runner_id} failed: {exc}"
            if self.client is not None:
                await self.client.send_json(AgentResponseChunk(
                    type="agent_chunk",
                    text=result,
                    finished=True,
                    runner_id=runner_id,
                    parent_runner_id=parent_runner_id,
                    parent_tool_call_id=parent_tool_call_id,
                ).model_dump(exclude_none=True))

    async def _send_tool_calls(self, runner_id: str, tool_calls: list[AgentToolCall]) -> None:
        if self.client is None:
            return
        for tool_call in tool_calls:
            tool_call.session_id = self.session_id
            tool_call.runner_id = runner_id
            message = AgentToolCallMessage(
                type="tool_call",
                session_id=tool_call.session_id,
                runner_id=tool_call.runner_id,
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=_tool_arguments_to_object(tool_call.arguments),
                trigger_id=self.trigger_id,
            )
            await self.client.send_json(message.model_dump(exclude_none=True))


class RealtimeSessionManager:
    _sessions: dict[str, RealtimeSession] = {}
    _cleanup_task: asyncio.Task | None = None

    @classmethod
    async def create(cls, request: CreateSessionRequest) -> RealtimeSession:
        session = RealtimeSession(
            setting=request.setting,
            reconnect_keep=request.reconnect_keep,
            session_id=request.session_id,
        )
        cls._sessions[session.session_id] = session
        cls._ensure_cleanup_task()
        return session

    @classmethod
    def get(cls, session_id: str) -> RealtimeSession | None:
        return cls._sessions.get(session_id)

    @classmethod
    def mark_disconnected(cls, session: RealtimeSession):
        """Mark session as disconnected, starts reconnect_keep countdown."""
        session.disconnect_time = time.time()

    @classmethod
    async def cleanup_expired(cls):
        """Remove expired sessions from process memory and Redis."""
        expired = [sid for sid, session in cls._sessions.items() if session.is_expired()]
        for sid in expired:
            session = cls._sessions.pop(sid, None)
            if session is not None:
                try:
                    await SessionAccessor.delete_cached_messages(sid)
                except Exception:
                    pass
                LogInterface.release_session(sid)

    @classmethod
    def _ensure_cleanup_task(cls):
        """Start background cleanup task if not already running."""
        if cls._cleanup_task is None or cls._cleanup_task.done():
            cls._cleanup_task = asyncio.create_task(cls._cleanup_loop())

    @classmethod
    async def _cleanup_loop(cls):
        """Background task that runs cleanup_expired every 10 seconds."""
        while True:
            await asyncio.sleep(10)
            await cls.cleanup_expired()
