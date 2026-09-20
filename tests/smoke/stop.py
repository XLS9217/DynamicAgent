"""Script name: stop.py. Stop live text and tool turns, then reuse the session."""

import asyncio
import os
import re
import time
from uuid import uuid4

from dotenv import load_dotenv

from dynamic_agent_client import (
    AgentOperator, DynamicAgentClient, SubagentOperator, agent_tool, description,
)
from dynamic_agent_client.service_handler import ServiceHandler

load_dotenv()


class SlowAsyncOperator(AgentOperator):
    """Provide a cancellable tool for the live stop check."""

    @description
    def describe(self):
        """Describe the slow tool."""
        return "Runs a slow check when asked."

    @agent_tool(description="Run the slow check")
    async def check(self) -> str:
        """Wait long enough to stop the turn during execution."""
        await asyncio.sleep(30)
        return "ASYNC_LATE_RESULT"


async def stop_and_measure(client, pending):
    """Require stop acknowledgement and the original trigger to resolve promptly."""
    started = time.monotonic()
    await asyncio.wait_for(client.stop(), 5)
    partial = await asyncio.wait_for(pending, 1)
    elapsed = time.monotonic() - started
    print(f"stop acknowledged in {elapsed:.3f}s; partial: {partial!r}")
    assert elapsed < 3, f"stop was too slow: {elapsed:.3f}s"
    return partial


async def text_case(client):
    """Interrupt shortly after text starts, then ask the model what it said."""
    first_line = asyncio.Event()
    chunks = []
    terminals = []

    def on_chunk(chunk):
        """Wait for the opening phrase and collect the terminal update."""
        if chunk.finished:
            terminals.append(chunk)
        elif chunk.text:
            chunks.append(chunk.text)
            text = "".join(chunks)
            if "\n" in text and len(text.strip()) >= 15:
                first_line.set()

    pending = asyncio.create_task(client.trigger(
        "Say hello, then count to 50.",
        on_chunk=on_chunk,
    ))
    await asyncio.wait_for(first_line.wait(), 60)
    await asyncio.sleep(0.05)
    assert not pending.done(), "model finished before it could be interrupted"
    partial = await stop_and_measure(client, pending)
    assert partial.strip(), "expected partial text"
    assert len(terminals) == 1 and terminals[0].cancelled
    title_words = re.findall(r"[a-z]+", partial.splitlines()[0].lower())
    assert title_words, partial
    answer = await asyncio.wait_for(client.trigger(
        "What did you say just before I stopped you? Repeat your greeting and "
        "briefly describe only the text you actually wrote, including the last number. "
        "Use digits for numbers. Do not continue counting.",
    ), 60)
    print(f"recall: {answer}")
    assert all(word in answer.lower() for word in title_words), (partial, answer)
    numbers = re.findall(r"\b\d+\b", partial)
    assert numbers and numbers[-1] in re.findall(r"\b\d+\b", answer), (partial, answer)
    await client.stop()
    print("TEXT STOP + RECALL PASSED")


async def tool_case(client, operator, subagent=False):
    """Stop during a tool, then verify a new turn and ignore a late result."""
    if subagent:
        await client.add_operator(SubagentOperator(candidate_operators=[operator]))
    else:
        await client.add_operator(operator)
    started = asyncio.Event()
    events = []

    def on_event(event):
        """Observe the actual slow tool, including when a subagent calls it."""
        events.append(event)
        if getattr(event, "name", "").endswith("_check") and getattr(event, "status", "") == "started":
            started.set()

    request = "Use the slow check tool now. Report its result when it finishes."
    if subagent:
        request = "Create a subagent with SlowAsyncOperator and ask it to run the slow check tool."
    pending = asyncio.create_task(client.trigger(request, on_event=on_event))
    await asyncio.wait_for(started.wait(), 90)
    await asyncio.sleep(0.05)
    old_turn = client._trigger_id
    old_tool = next(event for event in events if getattr(event, "name", "").endswith("_check"))
    await stop_and_measure(client, pending)
    assert any(getattr(event, "status", "") == "cancelled" for event in events)
    new_events = []
    next_turn = asyncio.create_task(client.trigger("Do not use tools. Say pong only.", on_event=new_events.append))
    await asyncio.sleep(0.05)
    late = await ServiceHandler.send_tool_result(
        session_id=client.session_id, runner_id=old_tool.runner_id,
        tool_call_id=old_tool.tool_call_id, ok=True, result="INJECTED_LATE_RESULT", trigger_id=old_turn,
    )
    assert late["status"] == "ignored"
    answer = await asyncio.wait_for(next_turn, 60)
    assert "pong" in answer.lower(), answer
    await asyncio.sleep(2.1)
    assert not any(getattr(event, "name", "").endswith("_check") for event in new_events)
    print(f"{'SUBAGENT' if subagent else type(operator).__name__} STOP + NEXT TURN PASSED")


async def main():
    """Run independent live stop scenarios against the configured backend."""
    await DynamicAgentClient.connect(f"http://localhost:{os.getenv('PORT', '7777')}")
    try:
        for case in ("text", "async", "subagent"):
            client = await DynamicAgentClient.create(
                setting="Reply in English. Follow the user's instructions precisely.",
                session_id=f"smoke-stop-{case}-{uuid4().hex[:8]}",
            )
            try:
                print(f"CASE {case}: {client.session_id}", flush=True)
                if case == "text":
                    await text_case(client)
                else:
                    operator = SlowAsyncOperator()
                    await tool_case(client, operator, subagent=case == "subagent")
            finally:
                session_id = client.session_id
                try:
                    await asyncio.wait_for(client.stop(), 5)
                finally:
                    await client.close()
                    await DynamicAgentClient.delete_session(session_id)
    finally:
        await ServiceHandler.stop()
    print("ALL STOP SMOKES PASSED")


if __name__ == "__main__":
    asyncio.run(main())
