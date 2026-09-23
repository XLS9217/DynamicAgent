"""Script name: test_media_storage.py. Verify filesystem media references and model input."""

import base64
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import UploadFile
from starlette.datastructures import Headers

from dynamic_agent_service.service.media_storage import MediaStorage
from dynamic_agent_service.service.service_structs import MessageItem


class MediaStorageTest(unittest.IsolatedAsyncioTestCase):
    """Keep bytes on disk while storage documents retain references only."""

    async def test_upload_reference_materialization_and_delete(self):
        """Store raw bytes, materialize once, and remove the referenced file."""
        image = b"\x89PNG\r\n\x1a\n" + b"unit-image-body"
        upload = UploadFile(
            BytesIO(image),
            filename="sample.png",
            headers=Headers({"content-type": "image/png"}),
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"MEDIA_DIR": directory},
        ):
            stored = await MediaStorage.save_uploads([upload])
            message = MessageItem.from_user("Describe it", stored)

            public = message.public_message()
            self.assertNotIn("relative_path", str(public))
            self.assertNotIn("sha256", str(public))
            self.assertNotIn("base64", message.model_dump_json())

            provider = await MediaStorage.materialize(message)
            image_url = provider["content"][1]["image_url"]["url"]
            self.assertEqual(base64.b64decode(image_url.split(",", 1)[1]), image)
            path = MediaStorage._resolve(stored[0].relative_path)
            self.assertTrue(path.is_file())

            await MediaStorage.delete(stored)
            self.assertFalse(path.exists())
