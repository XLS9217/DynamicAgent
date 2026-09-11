"""Script name: test_sdk_router.py. Verify backend client package discovery."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dynamic_agent_service.service import sdk_router


class SDKRouterTest(unittest.TestCase):
    """Check index links, version selection, and missing artifacts."""

    def test_index_tracks_bundled_version_and_download_hash(self):
        """Advertise and serve only the installed client's wheel after an upgrade."""
        app = FastAPI()
        app.include_router(sdk_router.router)
        with tempfile.TemporaryDirectory() as directory, TestClient(app) as client:
            with (
                patch.object(sdk_router, "SDK_DIST_DIR", Path(directory)),
                patch.object(sdk_router, "metadata", return_value={"Requires-Python": ">=3.11"}),
                patch.object(sdk_router, "version") as installed_version,
            ):
                for current_version in ("0.3.1", "0.3.2"):
                    installed_version.return_value = current_version
                    filename = f"dynamic_agent_client-{current_version}-py3-none-any.whl"
                    payload = current_version.encode()
                    (Path(directory) / filename).write_bytes(payload)
                    response = client.get("/sdk/simple/dynamic-agent-client/")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertIn(f'../../python/{filename}#sha256={hashlib.sha256(payload).hexdigest()}', response.text)
                    self.assertIn('data-requires-python="&gt;=3.11"', response.text)
                    self.assertNotIn(f"dynamic_agent_client-{'0.3.2' if current_version == '0.3.1' else '0.3.1'}-", response.text)
                    self.assertEqual(client.get(f"/sdk/python/{filename}").content, payload)
                    redirect = client.get("/sdk/python", follow_redirects=False)
                    self.assertEqual(redirect.headers["location"], f"/sdk/python/{filename}")
                    self.assertEqual(redirect.headers["cache-control"], "no-store")
                self.assertEqual(client.get("/sdk/simple/unknown-package/").status_code, 404)
                self.assertIn('href="dynamic-agent-client/"', client.get("/sdk/simple/").text)

    def test_missing_wheel_returns_service_unavailable(self):
        """Do not advertise an artifact that the backend cannot serve."""
        app = FastAPI()
        app.include_router(sdk_router.router)
        with tempfile.TemporaryDirectory() as directory, TestClient(app) as client:
            with patch.object(sdk_router, "SDK_DIST_DIR", Path(directory)):
                self.assertEqual(client.get("/sdk/simple/dynamic-agent-client/").status_code, 503)
