import hashlib
import os
from importlib.metadata import metadata, version
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse


router = APIRouter(prefix="/sdk", tags=["sdk"])

CLIENT_PACKAGE = "dynamic-agent-client"
SERVICE_PACKAGE = "dynamic-agent-service"
PROTOCOL_VERSION = "1"
SDK_DIST_DIR = Path(
    os.getenv("DYNAMIC_AGENT_SDK_DIST_DIR")
    or Path(__file__).resolve().parents[2] / "sdk_dist"
).resolve()


def _client_wheel() -> Path:
    client_version = version(CLIENT_PACKAGE)
    wheels = sorted(SDK_DIST_DIR.glob(f"dynamic_agent_client-{client_version}-*.whl"))
    if not wheels:
        raise HTTPException(
            status_code=503,
            detail=(
                f"DynamicAgent client wheel {client_version} is not available. "
                "Build it with: uv build --package dynamic-agent-client "
                "--out-dir sdk_dist"
            ),
        )
    if len(wheels) > 1:
        raise HTTPException(
            status_code=500,
            detail=f"Multiple client wheels found for version {client_version}",
        )
    return wheels[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@router.get("/manifest.json")
async def sdk_manifest() -> dict:
    wheel = _client_wheel()
    client_metadata = metadata(CLIENT_PACKAGE)
    client_version = version(CLIENT_PACKAGE)
    return {
        "service_version": version(SERVICE_PACKAGE),
        "protocol_version": PROTOCOL_VERSION,
        "python_sdk": {
            "package": CLIENT_PACKAGE,
            "version": client_version,
            "requires_python": client_metadata.get("Requires-Python"),
            "filename": wheel.name,
            "url": f"/sdk/python/{wheel.name}",
            "sha256": _sha256(wheel),
        },
    }


@router.get("/python", include_in_schema=False)
async def latest_python_sdk() -> RedirectResponse:
    wheel = _client_wheel()
    return RedirectResponse(url=f"/sdk/python/{wheel.name}", status_code=307)


@router.get("/python/{filename}")
async def download_python_sdk(filename: str) -> FileResponse:
    wheel = _client_wheel()
    if filename != wheel.name:
        raise HTTPException(status_code=404, detail="SDK wheel not found")
    return FileResponse(
        path=wheel,
        filename=wheel.name,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{_sha256(wheel)}"',
        },
    )
