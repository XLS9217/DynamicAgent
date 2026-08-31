# Downstream Support Recommendations

This document defines the features DynamicAgent should provide to support
downstream projects such as `market_platform` through stable public contracts
instead of downstream overrides of client internals.

## Feature 1: Typed Invocation Event Stream

DynamicAgent should expose a public typed event stream for every trigger. A
downstream consumer should not need to override `DynamicAgentClient._listen()`
or parse raw WebSocket messages to observe an execution.

The API may use an async iterator:

```python
async for event in client.trigger_events(prompt):
    await invocation_log.write(event)
```

It may also support callbacks when an iterator is inconvenient, but both forms
should use the same exported event models.

Each invocation event should include:

- `session_id`, `trigger_id`, and `invocation_id`
- `runner_id`, `parent_runner_id`, and `parent_tool_call_id`
- runner name and runner role
- invocation type, operator name, and tool name when applicable
- start and completion timestamps, duration, and status
- provider and model when available
- input, output, and total token usage when applicable
- structured error information for failed invocations

IDs must remain stable across streaming chunks so concurrent subagent
invocations can be correlated without relying on arrival order. Event models
should be exported from the client package and versioned as part of the public
protocol.

Acceptance criteria:

- A consumer can record main-agent and subagent invocations without subclassing
  the client.
- Parallel subagent events can be reconstructed into the correct runner tree.
- Token usage can be associated with a specific invocation rather than a local
  sequence counter.

## Feature 2: Structured Trigger Completion, Failure, and Cancellation

Every trigger should finish with one typed terminal event. Server exceptions
must not be represented as ordinary assistant text with `finished=True`.

The terminal event should contain:

```text
status: completed | failed | cancelled | timed_out
error_code
error_message
retryable
```

`DynamicAgentClient.trigger()` should return the assistant result only for a
completed trigger. It should raise documented client exceptions for failure,
cancellation, timeout, connection loss, and protocol incompatibility.

The trigger API should accept an explicit timeout and provide cancellation. A
lost WebSocket terminal message must not leave the caller waiting indefinitely.
Cancellation should propagate to the service and its active main or subagent
runner where possible.

Acceptance criteria:

- Exactly one terminal event is emitted for every accepted trigger.
- Server failures cannot be logged by a consumer as successful completions.
- Callers can bound trigger execution time and cancel active work.
- Exceptions expose stable error codes suitable for retry policy decisions.

## Feature 3: Context-Rich Tool Execution Events

Tool callbacks should expose a typed context object rather than only tool name,
arguments, and result. This allows downstream systems to record tool execution
within the same invocation tree as model calls.

A tool event should include:

- session, trigger, invocation, runner, and parent identifiers
- operator name, tool name, and `tool_call_id`
- normalized arguments or an explicit redacted marker
- start and completion timestamps and duration
- status and structured error information
- a result reference, result summary, or explicit redacted marker

The SDK should offer start and terminal tool events. Tool calls that have no
independent token usage should use `null` token fields instead of fabricated
zero values.

Acceptance criteria:

- A downstream logger can correlate a tool call and result without maintaining
  private maps from raw protocol messages.
- Tool activity can be assigned to the correct main runner or subagent.
- Sensitive arguments and results can be omitted without losing execution
  identity or status.

## Feature 4: Versioned Protocol and Capability Handshake

The service should advertise compatibility information before a client starts a
session. The create-session response, or a dedicated capabilities endpoint,
should include:

- service version
- protocol schema version
- minimum supported client version
- maximum supported client version, preferably as an exclusive bound
- supported capabilities such as invocation events, token usage, subagent
  streams, cancellation, and resumable triggers

The client should expose its own package version and validate compatibility
before registering operators or triggering work. Incompatibility should produce
an actionable exception that identifies the client version, service version,
and supported range.

Additive protocol changes should remain backward compatible within a declared
protocol version. Breaking field or semantic changes require a new protocol
version and migration notes.

Acceptance criteria:

- Incompatible clients fail before beginning agent work.
- Downstream lineage can record both client and service versions.
- Consumers can feature-detect optional capabilities without inspecting raw
  messages or guessing from versions.

## Feature 5: Service-Hosted, Reproducible SDK Distribution

The running service should provide the exact Python SDK artifact compatible
with it. The initial design should expose a machine-readable manifest and one
immutable wheel:

```text
GET /sdk/manifest.json
GET /sdk/python/<wheel-filename>
```

The manifest should advertise the SDK version, Python requirement, protocol
compatibility, artifact URL, and SHA-256. The wheel should be built during CI or
service image construction and bundled with the service. It must never be built
dynamically in response to a download request.

Downstream projects should pin the immutable wheel URL and record its version
and hash instead of using a machine-specific editable filesystem dependency. A
PEP 503 package index can be added later if the service intentionally retains
and supports multiple SDK versions.

The complete endpoint, build, caching, security, and rollout design is specified
in `SDK_DISTRIBUTION_RECOMMENDATION.md`.

Acceptance criteria:

- A clean Python environment can discover and install the compatible SDK using
  only the service URL.
- The downloaded artifact matches the manifest hash and advertised version.
- Installing the SDK requires neither Git nor local build tooling.

## Feature 6: Consumer-Driven Protocol Contract Tests

DynamicAgent should maintain an SDK-focused contract test suite using recorded
or deterministic service-to-client event fixtures. Service unit tests alone do
not protect the behavior consumed through the published SDK.

The suite should cover:

- main-runner text, invocation, usage, and completion events
- multiple and parallel subagents
- successful and failed local tools
- reconnect during idle and active triggers
- timeout and cancellation
- malformed, unknown, and forward-compatible event fields
- server-side exceptions
- exactly one terminal event per accepted trigger
- compatibility handshake failures

At least one release-gate smoke test should install the built wheel into a clean
environment, connect to the service, register an operator, perform a trigger,
and validate the resulting event sequence. A compact scenario based on the
needs of `market_platform` should be retained as a consumer contract fixture.

Tests must use isolated sessions and storage so they do not affect a running
service or persistent user data.

Acceptance criteria:

- Breaking a documented SDK event or lifecycle contract fails CI.
- The built wheel, rather than only editable source, is exercised before a
  release.
- Main-runner and subagent behavior are verified through the public SDK.

## Feature 7: Supported Collector Integration Recipe

The client documentation should provide a complete collector-oriented example
that demonstrates the supported composition used by downstream data pipelines.
It should cover:

- connecting to a configured service without hidden environment fallbacks
- creating one DynamicAgent session per collector worker
- registering the coordinator and candidate subagent operators
- consuming typed invocation and tool events
- writing data-lineage metadata without storing complete prompts or sensitive
  tool results
- setting trigger timeouts and applying retry policy from structured errors
- reconnecting safely and closing all client and local-tool resources
- recording client, service, protocol, and configuration versions

The example should be executable as a smoke test and should use only public SDK
interfaces. Documentation should also include a migration example that replaces
a custom `_listen()` override with the supported event API.

Acceptance criteria:

- A downstream collector can adopt DynamicAgent without copying transport or
  listener code.
- The example produces enough metadata to reconstruct runner and invocation
  relationships.
- The documented shutdown path leaves no active sessions, tool processes, or
  background listener tasks.
