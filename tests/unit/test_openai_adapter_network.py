"""Script name: test_openai_adapter_network.py. Verify LAN-only proxy bypass."""

import unittest
from unittest.mock import patch

from dynamic_agent_service.external_service.openai_adapter import OpenAIAdapter, _is_local_endpoint


class OpenAIAdapterNetworkTest(unittest.TestCase):
    """Check local routing while preserving public endpoint defaults."""

    def test_only_local_addresses_bypass_proxies(self):
        """Cover private IPv4, local IPv6, localhost, and public destinations."""
        for url in [
            "http://172.16.40.98:8091/api/v1", "http://10.1.2.3/v1",
            "https://192.168.1.2/v1", "http://127.0.0.1:8000/v1",
            "http://localhost:8000", "http://[::1]/v1", "http://[fd00::1]/v1",
        ]:
            with self.subTest(url=url):
                self.assertTrue(_is_local_endpoint(url))
        for url in ["https://openrouter.ai/api/v1", "https://dashscope.aliyuncs.com", "https://8.8.8.8", "https://localhost.example.com"]:
            with self.subTest(url=url):
                self.assertFalse(_is_local_endpoint(url))

    def test_lan_client_disables_environment_proxies(self):
        """A LAN model gets the SDK transport with trust_env disabled."""
        with (
            patch("dynamic_agent_service.external_service.openai_adapter.DefaultAsyncHttpxClient") as transport,
            patch("dynamic_agent_service.external_service.openai_adapter.AsyncOpenAI") as sdk,
        ):
            OpenAIAdapter("test-key", "http://172.16.40.98:8091/api/v1", "test-model")
        transport.assert_called_once_with(trust_env=False)
        self.assertIs(sdk.call_args.kwargs["http_client"], transport.return_value)

    def test_public_client_uses_default_proxy_behavior(self):
        """Public model endpoints retain the OpenAI SDK's default transport."""
        with (
            patch("dynamic_agent_service.external_service.openai_adapter.DefaultAsyncHttpxClient") as transport,
            patch("dynamic_agent_service.external_service.openai_adapter.AsyncOpenAI") as sdk,
        ):
            OpenAIAdapter("test-key", "https://openrouter.ai/api/v1", "test-model")
        transport.assert_not_called()
        self.assertIsNone(sdk.call_args.kwargs["http_client"])
