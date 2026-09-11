import inspect
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dynamic_agent_client
from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_service.service.service_router import TriggerRequest, router


class ServiceSurfaceTest(unittest.TestCase):
    def test_application_keeps_health_and_chat_without_monitoring_routes(self):
        # Import the real application without configuring filesystem log handlers.
        with patch("dynamic_agent_service.logging.setup_logging.my_logger_setup"):
            from dynamic_agent_service.__main__ import app

        paths = {route.path for route in app.routes}
        self.assertIn("/agent_session", paths)
        self.assertIn("/trigger", paths)
        self.assertFalse(any(path.startswith("/monitor") for path in paths))
        # No lifespan context: external services and the running app are untouched.
        client = TestClient(app)
        try:
            self.assertEqual(client.get("/health").json(), {"status": "healthy"})
            for path in ["/monitor/sessions", "/monitor/openai-resources", "/monitor/logs"]:
                self.assertEqual(client.get(path).status_code, 404)
        finally:
            client.close()

    def test_chat_routes_remain_and_old_knowledge_routes_are_absent(self):
        app = FastAPI()
        app.include_router(router)
        paths = app.openapi()["paths"]
        self.assertIn("/trigger", paths)
        self.assertIn("/create_session", paths)
        self.assertEqual(set(TriggerRequest.model_fields), {"session_id", "text"})
        with TestClient(app) as client:
            for path in ["/knowledge/bucket/test", "/buckets", "/blueprints/test/instances", "/session/test/rag"]:
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.post("/knowledge/retrieve", json={}).status_code, 404)
        self.assertFalse(hasattr(dynamic_agent_client, "RagOperator"))
        self.assertNotIn("bucket_name", inspect.signature(DynamicAgentClient.trigger).parameters)
