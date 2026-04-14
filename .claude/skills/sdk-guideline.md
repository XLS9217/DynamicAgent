---
name: sdk-guideline
description: Guidelines for developing SDKs (Python, TS/JS, C++, etc.) for the DynamicAgent service
---

# SDK Development Guideline

You are helping develop an SDK for the DynamicAgent service.
Follow these guidelines strictly regardless of the target language.

## Core Concepts

Every SDK must expose these abstractions:

1. **Client** — connects to the service, manages sessions, sends/receives messages
2. **Operator** — a user-defined tool provider that groups related tools
3. **Tool** — a single callable function exposed to the agent, declared via decorator/attribute/macro depending on language
4. **Session** — a stateful conversation context created through the client

## Communication Contract

- The service exposes HTTP + WebSocket endpoints
- SDK connects via HTTP for session lifecycle (create, close)
- SDK connects via WebSocket for streaming (agent responses, tool invocations)
- Tool execution is callback-based: service calls back into the SDK when a tool is invoked
- The SDK runs a local webhook server to receive tool invocation requests

## SDK Must Implement

| Capability              | Description                                                  |
|-------------------------|--------------------------------------------------------------|
| `connect(addr)`        | Establish connection to the service                          |
| `create(setting, ...)`  | Create a new session with agent configuration                |
| `trigger(text, ...)`    | Send user message and stream back response                   |
| `add_operator(op)`      | Register an operator (tool provider) with the client         |
| `close()`               | Tear down session and clean up resources                     |
| Operator declaration     | Language-idiomatic way to define a group of tools            |
| Tool declaration         | Language-idiomatic way to mark a method/function as a tool   |
| Tool schema generation   | Auto-generate OpenAI function-call schema from tool signatures |

## Design Principles

1. **Language-idiomatic** — use decorators in Python, attributes in C++, decorators/types in TS. Don't force one language's patterns onto another.
2. **Minimal surface** — expose only what the user needs. Internal transport, serialization, and routing stay private.
3. **Schema from code** — tool parameter schemas must be derived from type annotations/hints, not hand-written JSON.
4. **Streaming-first** — all response handling is streaming by default via callbacks or async iterators.
5. **No cross-import** — the SDK package must NEVER import from `dynamic_agent_service`. It is a standalone dependency.

## Operator & Tool Convention

- An Operator groups related tools under a namespace
- Each Operator has a description (what it can do) and optionally a flow (step-by-step instructions)
- Each Tool has: name, description, parameters (with types + descriptions), and a handler
- Parameter descriptions come from docstrings / JSDoc / comments — not from a separate schema file

## Language-Specific Addendum

When working on a specific language SDK, also load the corresponding sub-guideline if it exists:

- Python: `.claude/skills/sdk-guideline-python.md`
- TypeScript/JavaScript: `.claude/skills/sdk-guideline-ts.md`
- C++: `.claude/skills/sdk-guideline-cpp.md`

If the sub-guideline doesn't exist yet, follow the core principles above and use the Python SDK (`packages/dynamic_agent_client/`) as the reference implementation.