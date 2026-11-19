"""Script name: test_memory.py. Check memory boundaries and tool persistence offline."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from dynamic_agent_client.operator import MemoryOperator
from dynamic_agent_service.agent.agent_runner import AgentRunner
from dynamic_agent_service.service.service_structs import MessageItem
from dynamic_agent_client.session_struct import ChatSessionRequest, TaskSessionRequest
from dynamic_agent_service.service.session_management import AgentSessionBase, ChatAgentSession, SessionManager, TaskAgentSession
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.memory_accessor import MemoryAccessor
from dynamic_agent_service.service.media_storage import MediaStorage


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercise schema, session scope and context without external services."""

    async def test_session_factory_and_expiration_policies(self):
        """Select the concrete session and release only its temporary storage."""
        with self.assertRaises(TypeError):
            AgentSessionBase("test")
        with (
            patch.object(SessionManager, "_sessions", {}),
            patch.object(SessionManager, "_ensure_cleanup_task"),
            patch.object(SessionAccessor, "save_meta", new_callable=AsyncMock),
            patch.object(SessionAccessor, "delete_cached_messages", new_callable=AsyncMock) as delete,
        ):
            task = await SessionManager.create(TaskSessionRequest(setting="test"))
            self.assertIsInstance(task, TaskAgentSession)
            self.assertFalse(hasattr(task, "perform_compaction"))
            await task.append_message("user", "first turn")
            await SessionManager.mark_disconnected(task)
            resumed = await SessionManager.create(TaskSessionRequest(setting="test", session_id=task.session_id))
            self.assertIs(task, resumed)
            self.assertEqual(await resumed.load_model_messages(), [{"role": "user", "content": "first turn"}])
            task.disconnect_time = 0
            await SessionManager.cleanup_expired()
            self.assertEqual(await task.load_messages(), [])
            with self.assertRaisesRegex(ValueError, "expired or unavailable"):
                await SessionManager.create(TaskSessionRequest(setting="test", session_id=task.session_id))
            SessionAccessor.save_meta.assert_not_awaited()
            delete.assert_not_awaited()

            chat = await SessionManager.create(ChatSessionRequest(
                setting="test", session_type="chat", compact_prompt="Keep decisions",
            ))
            self.assertIsInstance(chat, ChatAgentSession)
            self.assertEqual(chat.meta().compact_prompt, "Keep decisions")
            await chat.expire_cache()
            delete.assert_awaited_with(chat.session_id, delete_media=False, keep_meta=True)

    async def test_short_lived_image_cache(self):
        """Store raw bytes with expiry and resolve references only for model input."""
        import io
        from unittest.mock import MagicMock
        from starlette.datastructures import Headers, UploadFile
        from dynamic_agent_service.external_service.redis_instance import RedisInstance
        data = b"GIF89a-\xff"
        upload = UploadFile(io.BytesIO(data), headers=Headers({"content-type": "image/gif"}))
        task = TaskAgentSession("test")
        redis = MagicMock(set=AsyncMock(), delete=AsyncMock(), execute_command=AsyncMock(return_value=data))
        pipe = redis.pipeline.return_value.__aenter__.return_value
        pipe.expire = MagicMock()
        with patch.object(RedisInstance, "get_client", return_value=redis):
            images = await task.cache_images([upload])
            key = f"task:{task.session_id}:image:{images[0].media_id}"
            redis.set.assert_awaited_once_with(key, data, ex=300)
            await task.append_message("user", MessageItem.from_user("inspect", images))
            self.assertEqual((await task.read_context())[0].parts[1].image_path, key)
            model = await task.load_model_messages()
            redis.execute_command.assert_awaited_once_with("GET", key, NEVER_DECODE=True)
            self.assertTrue(model[0]["content"][1]["image_url"]["url"].startswith("data:image/gif;base64,"))
            self.assertEqual((await task.load_messages())[0]["content"][1]["type"], "image")
            task._next_refresh = 0
            await task.refresh_images()
            pipe.expire.assert_called_once_with(key, 300)
            await task.expire_cache()
            redis.delete.assert_awaited_once_with(key)

    def test_tools_and_limits(self):
        """Expose agent-written arguments without a separate summarizer prompt."""
        tools = {t['function']['name']:t['function'] for t in MemoryOperator().get_serialized_operator().tools}
        self.assertEqual(set(tools), {'MemoryOperator_list','MemoryOperator_check','MemoryOperator_compact'})
        self.assertEqual(tools['MemoryOperator_compact']['parameters'].get('properties', {}), {})
        with self.assertRaises(ValueError):
            ChatSessionRequest(setting='x', session_type='chat', soft_limit_count=800000)

    async def test_message_roundtrip(self):
        """Retain provider call IDs and arguments through typed storage."""
        for original in [
            {'role':'assistant','content':'','tool_calls':[{'id':'call-1','type':'function','function':{'name':'x','arguments':'{}'}}]},
            {'role':'tool','content':'result','tool_call_id':'call-1'},
        ]:
            item=MessageItem.model_validate_json(MessageItem.from_model(original).model_dump_json())
            self.assertEqual(await MediaStorage.materialize(item), original)

    async def test_latest_boundary_inclusive_and_interrupted_pair(self):
        """Retain the newest compact call and repair an interrupted result."""
        session=ChatAgentSession('test')
        messages=[MessageItem.from_text('user','old'),
                  MessageItem.from_model({'role':'assistant','tool_calls':[{'id':'c','function':{'name':'MemoryOperator_compact','arguments':'{}'}}]}),
                  MessageItem.from_text('user','new')]
        for i,m in enumerate(messages):m.message_id=str(i)
        with patch.object(SessionAccessor,'load_context',AsyncMock(return_value=messages[1:])):
            restored=await session.load_model_messages()
        self.assertEqual(restored[0]['tool_calls'][0]['id'],'c')
        self.assertEqual(restored[1]['role'],'tool')
        self.assertEqual(restored[-1]['content'],'new')
        self.assertNotIn('old',str(restored))

    async def test_runner_persists_call_result_and_final_once(self):
        """Commit calls before dispatch and results before continuation."""
        from dynamic_agent_service.agent.agent_structs import AgentToolCall
        call=AgentToolCall(id='c',name='Example_read',arguments='{}')
        handler=SimpleNamespace(invoke=AsyncMock(side_effect=[
            SimpleNamespace(full_text='checking',tool_calls=[call],total_tokens=10),
            SimpleNamespace(full_text='done',tool_calls=[],total_tokens=20)]))
        stored=[]
        async def persist(messages):stored.extend(messages)
        async def send(calls):self.assertEqual(stored[0]['tool_calls'][0]['id'],'c')
        runner=AgentRunner('main','runner',handler,send_tool_calls=send)
        runner.on_messages=persist
        await runner.trigger([{'role':'system','content':'test'},{'role':'user','content':'go'}])
        await runner.append_tool_result('c',True,'evidence')
        await runner._continuation_task
        self.assertEqual([m['role'] for m in stored],['assistant','tool','assistant'])
        self.assertEqual(stored[-1]['content'],'done')

    async def test_soft_hint_and_direct_hard_compaction(self):
        """Soft prompts the agent; hard invokes the service without forced tools."""
        for count,hard in [(150,False),(250,True)]:
            handler=SimpleNamespace(invoke=AsyncMock(return_value=SimpleNamespace(full_text='done',tool_calls=[],total_tokens=1)))
            runner=AgentRunner('main','runner',handler)
            runner.soft_limit_count=100;runner.hard_limit_count=200;runner._last_total_tokens=count
            runner.on_compact=AsyncMock(return_value=[{'role':'user','content':'compacted'}])
            await runner.trigger([{'role':'system','content':'test'}],MemoryOperator().get_serialized_operator().tools)
            self.assertEqual(runner.on_compact.await_count,int(hard))
            self.assertFalse(hasattr(handler,'tool_choice'))
            if not hard:
                self.assertIn('soft limit reached',handler.invoke.call_args.kwargs['messages'][0]['content'])

    async def test_submission_validation_and_idempotence(self):
        """Reject empty or conflicting results; accept identical resubmission."""
        from dynamic_agent_client.operator import CompactionSubmitOperator
        op=CompactionSubmitOperator()
        with self.assertRaises(ValueError):await op.submit(' ', 'detail')
        with self.assertRaises(ValueError):await op.submit(1, 'detail')
        self.assertEqual(await op.submit('brief','detail'), {'status':'accepted'})
        await op.submit('brief','detail')
        with self.assertRaises(ValueError):await op.submit('other','detail')

    async def test_compact_task_uses_only_submission_and_retries_text(self):
        """A task requires valid submission and receives no main system prompt."""
        from dynamic_agent_service.agent.compact_agent import CompactTaskAgent
        from dynamic_agent_service.agent.agent_structs import AgentToolCall
        agent=CompactTaskAgent(object())
        agent.handler.invoke=AsyncMock(side_effect=[
            SimpleNamespace(full_text='not a submission',tool_calls=[]),
            SimpleNamespace(full_text='',tool_calls=[AgentToolCall(id='s',name='CompactionSubmitOperator_submit',arguments='{"summary":"brief","compacted":"detail"}')])])
        result=await agent.run([{'role':'system','content':'private main instructions'},{'role':'user','content':'do work'}],'do work')
        self.assertEqual(result.compacted,'detail')
        messages,tools,_=agent.handler.invoke.call_args.args
        self.assertNotIn('private main instructions',str(messages))
        self.assertEqual([t['function']['name'] for t in tools],['CompactionSubmitOperator_submit'])

    async def test_compact_task_missing_submission_fails(self):
        """Plain text cannot be mistaken for accepted memory."""
        from dynamic_agent_service.agent.compact_agent import CompactTaskAgent
        agent=CompactTaskAgent(object())
        agent.handler.invoke=AsyncMock(return_value=SimpleNamespace(full_text='text',tool_calls=[]))
        with self.assertRaises(ValueError):await agent.run([],'request')
        self.assertEqual(agent.handler.invoke.await_count,3)

    async def test_compaction_failure_does_not_save(self):
        """Keep original persistence when the compact task fails."""
        session=ChatAgentSession('test')
        session.agi=SimpleNamespace(openai_adapter=object())
        session.load_model_messages=AsyncMock(return_value=[{'role':'user','content':'work'}])
        with patch('dynamic_agent_service.service.session_management.chat_agent_session.CompactTaskAgent') as task, patch.object(MemoryAccessor,'save',AsyncMock()) as save:
            task.return_value.run=AsyncMock(side_effect=ValueError('invalid submission'))
            with self.assertRaises(ValueError):await session.perform_compaction()
            save.assert_not_awaited()

    async def test_check_is_scoped(self):
        """Reject checkpoint IDs absent from the active session."""
        session=ChatAgentSession('test')
        session.agi=SimpleNamespace(runner_id='r',validate_pending_tool_call=lambda *a:None,
            pending_tool_calls={'c':SimpleNamespace(name='MemoryOperator_check')})
        session._trigger_open=True;session.trigger_id='t'
        request=SimpleNamespace(action='check',runner_id='r',trigger_id='t',tool_call_id='c',checkpoint_id='other')
        with patch.object(MemoryAccessor,'all',AsyncMock(return_value=[])):
            with self.assertRaises(ValueError):await session.memory(request)
