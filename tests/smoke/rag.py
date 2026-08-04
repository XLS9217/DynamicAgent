"""Smoke test RAG retrieval through the client-side RagOperator.

Prerequisite: populate ``claude_mythos_blog`` with
``python -m examples.knowledge_inbound``.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

from dynamic_agent_client import DynamicAgentClient, RagOperator
from dynamic_agent_client.service_handler import ServiceHandler


load_dotenv()


SESSION_ID = "smoke-rag-operator"
BUCKET_NAME = "claude_mythos_blog"
QUESTION = "What cybersecurity capabilities does Claude Mythos Preview demonstrate?"


async def main() -> None:
    client = None
    session_created = False
    tool_calls = []
    tool_results = []

    try:
        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        bucket = await DynamicAgentClient.check_bucket(BUCKET_NAME)
        assert bucket["exists"], (
            f"RAG smoke prerequisite missing: populate {BUCKET_NAME!r} with "
            "`python -m examples.knowledge_inbound`"
        )

        # Remove state left by an interrupted previous smoke run.
        await DynamicAgentClient.delete_session(SESSION_ID)

        client = await DynamicAgentClient.create(
            setting=(
                "Answer from the configured knowledge bucket. Always call the RAG "
                "retrieve tool before answering knowledge questions."
            ),
            session_id=SESSION_ID,
            persist=False,
        )
        session_created = True
        assert client.messages == [], "fresh RAG smoke session should start empty"

        client.on_tool_call(lambda name, arguments: tool_calls.append((name, arguments)))
        client.on_tool_result(
            lambda name, arguments, result: tool_results.append((name, arguments, result))
        )

        registration = await client.add_operator(
            RagOperator(bucket_name=BUCKET_NAME, top_k=5)
        )
        print(f"operator registered: {registration}")

        response = await client.trigger(QUESTION)

        assert tool_calls, "expected the RAG retrieve tool to be called"
        assert tool_calls[0][0] == "RagOperator_retrieve"
        assert tool_results, "expected a RAG tool result"
        assert tool_results[0][0] == "RagOperator_retrieve"
        assert tool_results[0][2], "expected non-empty retrieved knowledge"
        assert response.strip(), "expected a non-empty grounded response"

        print(f"tool: {tool_calls[0][0]}")
        print(f"retrieval result items: {len(tool_results[0][2])}")
        print(f"response: {response}")
        print("ALL PASSED")
    finally:
        if client is not None:
            await client.close()
        if session_created:
            await DynamicAgentClient.delete_session(SESSION_ID)
        await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
