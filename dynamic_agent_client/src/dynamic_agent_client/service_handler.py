"""
Singleton that owns the shared webhook server and the connection to the service.
All clients go through ServiceHandler — one webhook port for all sessions.
"""
import asyncio
import json
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
    def call_tool(**arguments):
        return operator.execute(tool_name, arguments)

    call_tool.operator = operator

    return call_tool


class ServiceHandler:
    """
    Class-only singleton.
    1. Runs one webhook server shared across all sessions
    2. Maps session_id -> client for routing tool execution
    3. Handles connect (create_session + websocket) on behalf of client
    4. Handles add_operator on behalf of client
    """

    _server_addr: str = None
    _clients: dict = {}  # session_id -> DynamicAgentClient
    _http: httpx.AsyncClient = None

    @classmethod
    async def connect(cls, server_addr: str):
        """
        First-time setup: start webhook server and store the service address.
        Subsequent calls with same address are a no-op.
        """
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
        persist: bool = False,
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
                "persist": persist,
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
    async def trigger(cls, session_id: str, text: str, bucket_name: str = None):
        """Trigger agent with text input via HTTP POST."""
        resp = await cls._http.post(
            f"{cls._server_addr}/trigger",
            json={"session_id": session_id, "text": text, "bucket_name": bucket_name},
        )
        resp.raise_for_status()
        return resp.json()

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
    ) -> dict:
        resp = await cls._http.post(
            f"{cls._server_addr}/init_subagent",
            json={
                "session_id": session_id,
                "parent_runner_id": parent_runner_id,
                "name": name,
                "setting": setting,
                "operators": operators,
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
    ) -> dict:
        resp = await cls._http.post(
            f"{cls._server_addr}/trigger_subagent",
            json={
                "session_id": session_id,
                "parent_runner_id": parent_runner_id,
                "parent_tool_call_id": parent_tool_call_id,
                "runner_id": runner_id,
                "task": task,
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
    async def create_bucket(cls, name: str, description: str = ""):
        """Create a new bucket via HTTP POST."""
        resp = await cls._http.post(
            f"{cls._server_addr}/knowledge/bucket",
            json={
                "name": name,
                "description": description,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def check_bucket(cls, name: str):
        """Check if a bucket exists via HTTP GET."""
        resp = await cls._http.get(
            f"{cls._server_addr}/knowledge/bucket/{name}",
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def delete_bucket(cls, name: str):
        """Delete a bucket via HTTP DELETE."""
        resp = await cls._http.delete(
            f"{cls._server_addr}/knowledge/bucket/{name}",
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def retrieve(cls, query: str, bucket_name: str, top_k: int = 10):
        """Retrieve knowledge from a bucket via HTTP POST. Returns (results, analytics)."""
        resp = await cls._http.post(
            f"{cls._server_addr}/knowledge/retrieve",
            json={
                "query": query,
                "bucket_name": bucket_name,
                "top_k": top_k,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", data), data.get("analytics", {})

    @classmethod
    async def expand_node_ids(cls, bucket_name: str, node_ids: list[str]):
        """Expand knowledge node IDs via HTTP POST."""
        resp = await cls._http.post(
            f"{cls._server_addr}/knowledge/expand",
            json={
                "bucket_name": bucket_name,
                "node_ids": node_ids,
            },
        )
        resp.raise_for_status()
        return resp.json()

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
