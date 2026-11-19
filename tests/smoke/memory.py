"""Script name: memory.py. Exercise memory against an isolated service and real model."""
import asyncio
import json
import os
import socket
from pathlib import Path
from uuid import uuid4

import asyncpg
import uvicorn
from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentChatClient
from dynamic_agent_client.operator import AgentOperator, agent_tool
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.__main__ import app
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.memory_accessor import MemoryAccessor
from dynamic_agent_service.service.session_management import SessionManager


class EvidenceOperator(AgentOperator):
    """Provide a stable result that must survive a later trigger."""
    @agent_tool(description="Read the test evidence before answering.")
    async def read(self):
        """Return the test value and expendable context."""
        return {"code":"silver-heron", "notes":"redundant background " * 900}


async def main():
    """Use a temporary PostgreSQL schema, unique session and ephemeral HTTP port."""
    root=Path(__file__).resolve().parents[2]
    load_dotenv(root/'.env')
    admin=await asyncpg.connect(os.environ['POSTGRES_DSN'])
    schema='smoke_memory_'+uuid4().hex
    session_id='smoke-memory-'+uuid4().hex
    client=None; server=None; serving=None
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        PgInstance._pool=await asyncpg.create_pool(os.environ['POSTGRES_DSN'],min_size=1,max_size=4,
            server_settings={'search_path':f'{schema},public'})
        # Rehearse the upgrade against the old table, entirely inside the temporary schema.
        async with PgInstance._pool.acquire() as conn:
            await conn.execute('CREATE TABLE session_message (message_id UUID PRIMARY KEY, create_at TIMESTAMPTZ NOT NULL DEFAULT now(), session_id TEXT NOT NULL, content JSONB NOT NULL)')
            await conn.execute((root/'migrations/memory_history.sql').read_text())
        server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
        serving=asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(100):
            if server.started:break
            await asyncio.sleep(.1)
        assert server.started
        await DynamicAgentChatClient.connect(f'http://127.0.0.1:{port}')
        client=await DynamicAgentChatClient.create(
            setting='Use tools when asked. Preserve the evidence code in memory. Keep compacted under 120 words. Answer briefly.',
            session_id=session_id,soft_limit_count=1600,hard_limit_count=2400)
        await client.add_operator(EvidenceOperator())
        await asyncio.wait_for(client.trigger('Call EvidenceOperator_read, remember its code, then reply with only that code.'),120)
        all_messages=await SessionAccessor.load_messages(session_id)
        calls=[c['function']['name'] for m in all_messages for c in (m.tool_calls or [])]
        assert 'EvidenceOperator_read' in calls
        checkpoints=await MemoryAccessor.all(session_id); assert checkpoints
        restored=await SessionManager.get(session_id).load_model_messages()
        assert restored[0]['role']=='user' and restored[0]['content'].startswith('Previous conversation has been compacted.')
        # Force a PostgreSQL reload instead of relying on Redis.
        await SessionAccessor.delete_cached_messages(session_id)
        restored=await SessionManager.get(session_id).load_model_messages()
        assert restored[0]['role']=='user' and restored[0]['content'].startswith('Previous conversation has been compacted.')
        before=len(checkpoints)
        await asyncio.wait_for(client.trigger('Call MemoryOperator_compact now, with no arguments, then reply briefly.'),120)
        assert len(await MemoryAccessor.all(session_id)) > before
        reply=await asyncio.wait_for(client.trigger('Use MemoryOperator_list, then check the checkpoint returned, and tell me the evidence code.'),120)
        assert 'silver-heron' in reply.lower(),reply
        final=await SessionAccessor.load_messages(session_id)
        calls=[c['function']['name'] for m in final for c in (m.tool_calls or [])]
        assert 'MemoryOperator_list' in calls and 'MemoryOperator_check' in calls and 'MemoryOperator_compact' in calls
        report={'status':'passed','soft_limit':1600,'hard_limit':2400,'tool_calls':calls,
                'checkpoints':len(await MemoryAccessor.all(session_id)),
                'postgres_reload':True,'recall':reply}
        output=root/'cache'/'memory-smoke.json';output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        if client:
            await client.stop()
            await client.close()
            await client.delete_session(session_id)
        await ServiceHandler.stop()
        if server:
            server.should_exit=True
        if serving:
            await serving
        elif PgInstance._pool:
            await PgInstance.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()
        sock.close()


if __name__=='__main__':
    asyncio.run(main())
