"""Script name: media_storage.py. Store session images and materialize model input."""

import base64
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import UploadFile

from dynamic_agent_service.service.service_structs import MessageItem, StoredImagePart, TextPart


_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _detected_mime(header: bytes) -> str | None:
    """Detect supported image formats from their file signatures."""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


class MediaStorage:
    """Own filesystem-backed session media below MEDIA_DIR."""

    @staticmethod
    def root() -> Path:
        """Return the configured absolute media directory."""
        configured = os.getenv("MEDIA_DIR")
        if not configured:
            raise RuntimeError("MEDIA_DIR is required for image input")
        root = Path(configured).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def _resolve(cls, relative_path: str) -> Path:
        """Resolve a stored relative path without allowing directory escape."""
        root = cls.root()
        path = (root / relative_path).resolve()
        if path != root and root not in path.parents:
            raise ValueError("Media path escapes MEDIA_DIR")
        return path

    @classmethod
    async def save_uploads(cls, uploads: list[UploadFile]) -> list[StoredImagePart]:
        """Validate uploads and atomically move them into their final paths."""
        maximum = int(os.getenv("MEDIA_MAX_BYTES", str(10 * 1024 * 1024)))
        if len(uploads) > int(os.getenv("MEDIA_MAX_FILES", "8")):
            raise ValueError("Too many images in one trigger")
        root = cls.root()
        staging = root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        stored: list[StoredImagePart] = []
        temporary: list[Path] = []
        try:
            for upload in uploads:
                media_id = uuid4()
                temporary_path = staging / f"{media_id}.upload"
                temporary.append(temporary_path)
                digest = hashlib.sha256()
                size = 0
                header = b""
                async with aiofiles.open(temporary_path, "wb") as target:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        if size > maximum:
                            raise ValueError(f"Image exceeds {maximum} bytes")
                        if len(header) < 16:
                            header = (header + chunk)[:16]
                        digest.update(chunk)
                        await target.write(chunk)
                mime_type = _detected_mime(header)
                if mime_type is None or mime_type != upload.content_type:
                    raise ValueError("Image content does not match its supported MIME type")
                relative_path = f"{media_id.hex[:2]}/{media_id}{_EXTENSIONS[mime_type]}"
                final_path = cls._resolve(relative_path)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary_path, final_path)
                temporary.remove(temporary_path)
                stored.append(StoredImagePart(
                    media_id=media_id,
                    relative_path=relative_path,
                    mime_type=mime_type,
                    byte_size=size,
                    sha256=digest.hexdigest(),
                ))
        except BaseException:
            await cls.delete(stored)
            for path in temporary:
                path.unlink(missing_ok=True)
            raise
        finally:
            for upload in uploads:
                await upload.close()
        return stored

    @classmethod
    async def delete(cls, images: list[StoredImagePart]) -> None:
        """Delete media files while tolerating already-removed files."""
        for image in images:
            cls._resolve(image.relative_path).unlink(missing_ok=True)

    @classmethod
    async def materialize(cls, message: MessageItem) -> dict:
        """Convert stored references into OpenAI-compatible content blocks."""
        if len(message.parts) == 1 and isinstance(message.parts[0], TextPart):
            return {"role": message.role, "content": message.parts[0].text}
        content = []
        for part in message.parts:
            if isinstance(part, TextPart):
                content.append({"type": "text", "text": part.text})
                continue
            path = cls._resolve(part.relative_path)
            async with aiofiles.open(path, "rb") as source:
                data = await source.read()
            if len(data) != part.byte_size or hashlib.sha256(data).hexdigest() != part.sha256:
                raise ValueError(f"Stored media failed integrity check: {part.media_id}")
            encoded = base64.b64encode(data).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{part.mime_type};base64,{encoded}",
                    "detail": part.detail,
                },
            })
        return {"role": message.role, "content": content}
