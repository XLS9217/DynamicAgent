"""Script name: service_handler.py. Share backend HTTP access and register session clients."""
import asyncio
from contextlib import ExitStack
import mimetypes
import json
from pathlib import Path
import re

import httpx
import websockets


def _make_httpx_client() -> httpx.AsyncClient:
    """Create an httpx client that bypasses proxy for http:// targets."""
    return httpx.AsyncClient(mounts={"http://": None})


def _sanitize_json(raw: str) -> str:
    """Fix common LLM JSON quirks like leading zeros (e.g. 00.5 -> 0.5)."""
    return re.sub(r'(?<![0-9])0+(\d+\.)', r'\1', raw)


def _make_operator_tool_callable(operator, tool_name: str):
    async def call_tool(**arguments):
        return await operator.execute(tool_name, arguments)

    call_tool.operator = operator

    return call_tool


class ServiceHandler:
    """Share the HTTP client, open session WebSockets, and register operator bindings."""

    _server_addr: str = None
    _clients: dict = {}  # session_id -> DynamicAgentClient
    _http: httpx.AsyncClient = None

    @classmethod
    async def connect(cls, server_addr: str):
        """Set the backend address and create the shared HTTP client if needed."""
        cls._server_addr = server_addr.rstrip("/")
        if cls._http is None:
            cls._http = _make_httpx_client()

    @classmethod
    async def create_session(
        cls,
        setting: str,
        client,
        reconnect_keep: int = 30,
        session_id: str = None,
    ) -> tuple:
        """
        POST /create_session to the service, register client, and return session data.
        """
        resp = await cls._http.post(
            f"{cls._server_addr}/create_session",
            json={
                "setting": setting,
                "reconnect_keep": reconnect_keep,
                "session_id": session_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        session_id = data["session_id"]
        runner_id = data["runner_id"]
        socket_url = data["socket_url"]
        messages = data["messages"]

        # Always register/update client - last client wins
        # This handles React strict mode double mount: the second (active) client
        # replaces the first (stale) client that may be garbage collected
        cls._clients[session_id] = client

        ws = await websockets.connect(socket_url)
        return session_id, runner_id, ws, messages

    @classmethod
    async def add_operator(cls, session_id: str, client, operator):
        """
        1. Register tool_map entries on the client
        2. POST serialized operator to the service
        """
        serialized = operator.get_serialized_operator()

        cls.register_runner_operators(
            session_id=session_id,
            runner_id=client.runner_id,
            operators=[operator],
        )

        resp = await cls._http.post(
            f"{cls._server_addr}/agent_operator",
            json={
                "session_id": session_id,
                "operator": serialized.model_dump(),
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def trigger(
        cls,
        session_id: str,
        text: str,
        trigger_id: str | None = None,
        images: list[str | Path] | None = None,
    ):
        """Trigger a text turn or upload raw images for a multimodal turn."""
        if not images:
            resp = await cls._http.post(
                f"{cls._server_addr}/trigger",
                json={"session_id": session_id, "text": text, "trigger_id": trigger_id},
            )
        else:
            with ExitStack() as stack:
                files = []
                for value in images:
                    path = Path(value)
                    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    files.append(("images", (path.name, stack.enter_context(path.open("rb")), media_type)))
                resp = await cls._http.post(
                    f"{cls._server_addr}/trigger_media",
                    data={"session_id": session_id, "text": text, "trigger_id": trigger_id or ""},
                    files=files,
                )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def stop_trigger(cls, session_id: str, trigger_id: str) -> dict:
        """Wait for backend cancellation and session readiness."""
        response = await cls._http.post(
            f"{cls._server_addr}/stop",
            json={"session_id": session_id, "trigger_id": trigger_id},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    @classmethod
    def register_runner_operators(
        cls,
        session_id: str,
        runner_id: str,
        operators: list,
    ) -> None:
        client = cls._clients.get(session_id)
        if client is None:
            raise RuntimeError(f"Client session is not registered: {session_id}")

        runner_tools = client.tool_map.setdefault(runner_id, {})
        for operator in operators:
            serialized = operator.get_serialized_operator()
            operator.session_id = session_id
            operator.runner_id = runner_id
            for tool_name in operator._tools:
                prefixed_name = f"{serialized.name}_{tool_name}"
                runner_tools[prefixed_name] = _make_operator_tool_callable(operator, tool_name)

    @classmethod
    async def send_tool_result(
        cls,
        session_id: str,
        tool_call_id: str,
        ok: bool,
        result,
        runner_id: str | None = None,
        trigger_id: str | None = None,
    ):
        """Send a locally executed tool result back to the service."""
        serialized_result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        resp = await cls._http.post(
            f"{cls._server_addr}/tool_result",
            json={
                "session_id": session_id,
                "runner_id": runner_id,
                "tool_call_id": tool_call_id,
                "ok": ok,
                "result": serialized_result,
                "trigger_id": trigger_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def init_subagent(
        cls,
        session_id: str,
        parent_runner_id: str,
        name: str,
        setting: str,
        operators: list[dict],
        trigger_id: str | None = None,
    ) -> dict:
        resp = await cls._http.post(
            f"{cls._server_addr}/init_subagent",
            json={
                "session_id": session_id,
                "parent_runner_id": parent_runner_id,
                "name": name,
                "setting": setting,
                "operators": operators,
                "trigger_id": trigger_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def trigger_subagent(
        cls,
        session_id: str,
        parent_runner_id: str,
        parent_tool_call_id: str,
        runner_id: str,
        task: str,
        trigger_id: str | None = None,
    ) -> dict:
        resp = await cls._http.post(
            f"{cls._server_addr}/trigger_subagent",
            json={
                "session_id": session_id,
                "parent_runner_id": parent_runner_id,
                "parent_tool_call_id": parent_tool_call_id,
                "runner_id": runner_id,
                "task": task,
                "trigger_id": trigger_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def delete_session(cls, session_id: str) -> bool:
        """Delete a session's persisted chat messages via HTTP DELETE."""
        resp = await cls._http.delete(
            f"{cls._server_addr}/session/{session_id}",
        )
        resp.raise_for_status()
        data = resp.json()
        cls._clients.pop(session_id, None)
        return data.get("status") == "ok"

    @classmethod
    async def reconnect_session(cls, session_id: str):
        """Reconnect to existing session by session_id, returns websocket."""
        socket_url = f"{cls._server_addr.replace('http', 'ws')}/agent_session?session_id={session_id}"
        print(f"Connecting to: {socket_url}")
        ws = await asyncio.wait_for(websockets.connect(socket_url), timeout=5.0)
        print(f"WebSocket connected!")
        return ws

    @classmethod
    def unregister_client(cls, session_id: str, client_instance=None):
        """
        Unregister a client from the session.

        If client_instance is provided, only unregister if the current registered
        client matches it (prevents stale client from unregistering active client).
        """
        if client_instance is not None:
            current = cls._clients.get(session_id)
            if current is not client_instance:
                # Don't unregister - a different client instance has taken over
                return

        cls._clients.pop(session_id, None)

    @classmethod
    async def stop(cls):
        if cls._http:
            await cls._http.aclose()
            cls._http = None
        cls._clients.clear()
