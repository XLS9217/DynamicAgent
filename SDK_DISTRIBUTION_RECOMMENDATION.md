# Service-Hosted Python SDK Distribution

## Recommendation

DynamicAgent should make the Python SDK version that is compatible with the
running service available for download from that service. The first version
should use one immutable wheel and a machine-readable manifest rather than a
full package index.

This gives downstream projects a reproducible installation source without
requiring a machine-specific editable path. It also makes the compatibility
relationship explicit: consumers can install the SDK advertised by the same
service instance they will call.

## Proposed HTTP API

Expose two unauthenticated or deployment-authenticated read-only endpoints:

```text
GET /sdk/manifest.json
GET /sdk/python/<wheel-filename>
```

Example manifest:

```json
{
  "service_version": "0.1.0",
  "protocol_version": "1",
  "generated_at": "2026-08-31T08:00:00Z",
  "python_sdk": {
    "package": "dynamic-agent-client",
    "version": "0.2.6",
    "requires_python": ">=3.11",
    "filename": "dynamic_agent_client-0.2.6-py3-none-any.whl",
    "url": "/sdk/python/dynamic_agent_client-0.2.6-py3-none-any.whl",
    "sha256": "<wheel-sha256>"
  },
  "compatibility": {
    "minimum_client_version": "0.2.6",
    "maximum_client_version_exclusive": "0.3.0"
  }
}
```

The URL may be absolute when the service is deployed behind a gateway. The
service should derive it from trusted deployment configuration instead of
blindly trusting forwarded request headers.

## Installation

Consumers can install the advertised wheel directly:

```powershell
uv add "http://dynamic-agent-host:7777/sdk/python/dynamic_agent_client-0.2.6-py3-none-any.whl"
```

or:

```powershell
pip install "http://dynamic-agent-host:7777/sdk/python/dynamic_agent_client-0.2.6-py3-none-any.whl"
```

Production consumers should pin the complete wheel URL and verify its SHA-256.
Installing from a mutable URL such as `/sdk/python/latest` should not be the
documented reproducible workflow.

## Build and Packaging Flow

1. Build the client wheel as part of CI or the service image build.
2. Calculate the wheel SHA-256 and generate `manifest.json` from package
   metadata.
3. Copy both immutable artifacts into the service image.
4. Fail the image build if the manifest version, wheel metadata, service
   compatibility declaration, or hash disagree.
5. Serve the artifacts as static files with correct content types and cache
   headers.

The service must not build packages in response to HTTP requests. Runtime
package builds would introduce latency, mutable results, additional build tools,
and a larger security surface.

Suggested cache behavior:

- Wheel: `Cache-Control: public, max-age=31536000, immutable`
- Manifest: `Cache-Control: no-cache`

Suggested response headers for the wheel:

```text
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="dynamic_agent_client-0.2.6-py3-none-any.whl"
ETag: "<wheel-sha256>"
```

## Compatibility Enforcement

SDK distribution and runtime compatibility checks should use the same metadata.
The create-session response should include at least:

```json
{
  "service_version": "0.1.0",
  "protocol_version": "1",
  "minimum_client_version": "0.2.6",
  "maximum_client_version_exclusive": "0.3.0"
}
```

The client should expose `dynamic_agent_client.__version__` and reject an
incompatible service with a clear exception before creating a session. The
service-hosted wheel is the recommended compatible build, but tagged source
releases should remain available as an alternative installation source.

## Security and Operations

- Serve the wheel only over HTTPS outside a trusted development network.
- Apply the deployment's normal authentication policy when the SDK should not
  be publicly downloadable.
- Never place credentials or environment-specific configuration in the wheel.
- Verify the wheel hash during image construction and in deployment smoke tests.
- Record the client version, service version, protocol version, and wheel hash
  in downstream data-lineage manifests.
- Keep old immutable wheels only when the service intentionally supports those
  client versions.

## Future Package Index

If the service needs to host multiple SDK versions, add a PEP 503-compatible
index:

```text
GET /simple/dynamic-agent-client/
```

That would support conventional package resolution. It is unnecessary for the
initial single-compatible-wheel design and introduces more version-retention and
index-management responsibilities.

## Rollout Plan

### Phase 1: Metadata

- Export the client package version through `__version__`.
- Define the protocol version and compatibility range.
- Add a build check that compares service and client metadata.

### Phase 2: Artifact Hosting

- Build and bundle the wheel in the service image.
- Implement the manifest and wheel endpoints.
- Add hash, cache-header, and download tests.

### Phase 3: Downstream Adoption

- Replace machine-specific editable dependencies with a pinned wheel URL.
- Store SDK and service metadata in downstream lineage manifests.
- Add a smoke test that downloads the wheel, installs it in a clean environment,
  creates a session, and performs one trigger.

## Acceptance Criteria

- A clean Python environment can discover and install the compatible SDK using
  only the running service URL.
- The downloaded artifact hash matches the manifest.
- The installed package exposes the advertised version.
- An incompatible SDK receives an actionable compatibility error.
- Rebuilding the same release does not silently replace an artifact at an
  existing immutable URL.
- The SDK download path does not require source code, Git, or build tooling on
  the consumer machine.
