this will be the md for learning from different industry lead

# Claude Code

## Tool Handling

Claude Code uses a **3-tier dynamic tool discovery system** instead of sending all tools to every LLM call.

### Architecture

**Tool Categories:**
- **Non-deferred tools**: Core tools always sent (Read, Write, Bash, Edit, etc.)
- **Deferred tools**: Specialized/MCP tools sent only after discovery
- **ToolSearchTool**: Meta-tool that discovers deferred tools on-demand

**Filtering Logic** (`src/services/api/claude.ts:1154-1172`):
```typescript
if (useToolSearch) {
  const discoveredToolNames = extractDiscoveredToolNames(messages)
  
  filteredTools = tools.filter(tool => {
    if (!deferredToolNames.has(tool.name)) return true  // Core tools
    if (toolMatchesName(tool, TOOL_SEARCH_TOOL_NAME)) return true  // Search tool
    return discoveredToolNames.has(tool.name)  // Only discovered deferred
  })
}
```

### Discovery Flow

1. LLM receives core tools + ToolSearchTool
2. When LLM needs specialized tool, calls `ToolSearchTool` with query (e.g., "find GitHub tools")
3. ToolSearchTool returns `tool_reference` blocks (lightweight references, not full schemas)
4. API expands `tool_reference` into full tool definitions in model context
5. `extractDiscoveredToolNames()` scans message history for these references
6. Next LLM call includes discovered tools in filtered list

### Tool Metadata for Search

Each tool has metadata that ToolSearchTool uses for keyword matching:

**Tool Definition** (`Tool.ts:378`):
```typescript
{
  name: string              // e.g., "mcp__github__create_issue", "NotebookEdit"
  searchHint?: string       // One-line capability phrase (3-10 words)
  prompt: () => string      // Full tool description
  // ... other fields
}
```

**Search Scoring** (`ToolSearchTool.ts:259-295`):
- **Tool name parts** (highest weight): Splits by `__` for MCP tools, CamelCase for regular tools
  - `mcp__slack__send_message` → ["slack", "send", "message"]
  - `NotebookEdit` → ["notebook", "edit"]
  - Exact part match: +12 (MCP) or +10 (regular)
  - Partial part match: +6 (MCP) or +5 (regular)
- **searchHint** (high signal): +4 per keyword match
  - Example: `WebSearchTool.searchHint = "search the web for current information"`
- **Tool description** (lower signal): +2 per keyword match (word boundary)
- **Required terms**: Use `+` prefix (e.g., "+slack send") to filter candidates first

**Query Examples**:
- `"select:Read,Edit,Grep"` → Direct selection by name
- `"notebook jupyter"` → Keyword search, returns top 5 matches
- `"+slack send"` → Require "slack" in name/desc, rank by "send"
- `"github"` → Matches `mcp__github__*` tools by server name

### Auto-Enable Logic

Tool search auto-enables when:
- MCP tools exceed 10% of context window (configurable via `ENABLE_TOOL_SEARCH=auto:N`)
- Model supports `tool_reference` (Sonnet 4+, Opus 4+; Haiku does NOT)
- ToolSearchTool is available

### Benefits

- **Token efficiency**: Don't send 100 tool schemas when only 3 are needed
- **Scalable**: No hard limit on total tools
- **Smart discovery**: LLM discovers tools as needed, not all upfront
- **Context preservation**: More room for actual conversation/code

### Key Files

- `src/tools.ts`: Tool registration with feature flags
- `src/services/api/claude.ts`: Dynamic filtering logic
- `src/utils/toolSearch.ts`: Discovery extraction and auto-enable logic
- `src/tools/ToolSearchTool/`: Meta-tool implementation

### Comparison to Basic Approach

**Basic (our current)**: `tools = get_all_operator_tools()` → send to every LLM call

**Claude Code**: `tools = core_tools + [ToolSearchTool]` → discover deferred tools on-demand → filter by discovered set

## Tool Execution

Claude Code uses **async generators with streaming** for tool execution, not simple async-await or message queues.

### Core Pattern: Async Generator (`toolExecution.ts`)

```typescript
// NOT: result = await tool.call(args)
// Instead:
async function* runToolUse(...): AsyncGenerator<MessageUpdate> {
  // yields progress updates as they happen
  yield { type: 'progress', output: '...' }
  // yields final result
  yield { type: 'result', content: '...' }
}
```

**Benefits**:
- Stream output back to user in real-time
- Don't block waiting for completion
- UI shows progress immediately

### Concurrency: Smart Batching (`toolOrchestration.ts`)

**Partitioning Strategy**:
- **Read-only tools** (Read, Grep, Glob, WebFetch): run concurrently (up to 10, configurable via `CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY`)
- **Write tools** (Bash, Edit, Write): run serially, one at a time
- Consecutive read-only tools are batched together
- Each non-read-only tool gets its own batch

**Concurrency Check** (`StreamingToolExecutor.ts:129-150`):
```typescript
private canExecuteTool(isConcurrencySafe: boolean): boolean {
  const executingTools = this.tools.filter(t => t.status === 'executing')
  return (
    executingTools.length === 0 ||
    (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe))
  )
}
```

### Long-Running Commands (`BashTool.tsx`, `Shell.ts`)

**Auto-Backgrounding**:
- Commands exceeding `ASSISTANT_BLOCKING_BUDGET_MS` (15 seconds) → auto-backgrounded
- User can explicitly set `run_in_background: true`
- Background tasks: child process spawned via Node.js `spawn()`, output written to file
- Default timeout: 30 minutes

**Stall Detection** (`LocalShellTask.tsx`):
- Polls output file every 5 seconds
- If no growth for 45 seconds and output looks like a prompt → notifies user
- Prevents silent hangs on interactive commands (e.g., `vim`, `python` REPL)

**Progress Streaming**:
```typescript
async function* runShellCommand(...): AsyncGenerator<{
  type: 'progress';
  output: string;
  fullOutput: string;
  elapsedTimeSeconds: number;
  totalLines: number;
  taskId?: string;
}, ExecResult>
```

**Background Task Lifecycle**:
1. Command starts, exceeds 15s → auto-backgrounded
2. Task ID assigned, output written to file
3. Stall watchdog monitors for hangs
4. On completion → notification enqueued
5. Next LLM turn → notification fed back as message

### Error Cascading (`StreamingToolExecutor.ts:353-363`)

**Cascade Behavior**:
- **Bash tool error** → aborts sibling tools (implicit dependencies)
- **Other tool errors** → don't cascade (independent operations)
- Synthetic error messages generated for cancelled tools

```typescript
if (isErrorResult && tool.block.name === BASH_TOOL_NAME) {
  this.hasErrored = true;
  this.siblingAbortController.abort('sibling_error');
}
```

### Abort Signal Propagation

**Abort Reasons**:
- `'interrupt'` - user typed new message
- `'sibling_error'` - bash tool failed
- `'user_interrupted'` - ESC to reject
- `'streaming_fallback'` - model streaming failed

Child abort controllers propagate signals to running tools for graceful cleanup.

### Dual Execution Paths

**Streaming Execution** (default):
- Tools executed as they stream in from model
- Uses `StreamingToolExecutor` class
- Concurrent-safe tools run in parallel while streaming
- Progress yielded immediately

**Batch Execution** (fallback):
- All tools collected first, then executed
- Uses `runTools()` generator
- Partitions into batches based on concurrency safety

### Comparison to Basic Approach

| | Our Current | Claude Code |
|---|---|---|
| Execution | `await tool_execute(tc)` sequential | Async generator, streaming |
| Concurrency | None (`parallel_tool_calls=False`) | Read-only parallel (10), writes serial |
| Long-running | Blocks until done | Auto-background after 15s |
| Progress | None | Real-time via generator yields |
| Output | Return string | Stream chunks + persist to file |
| Error handling | Return error string | Cascade bash errors, abort siblings |
| Stall detection | None | 45s watchdog, notify user |

### Key Files

- `src/services/tools/toolExecution.ts` - Core execution logic
- `src/services/tools/toolOrchestration.ts` - Batching and concurrency
- `src/services/tools/StreamingToolExecutor.ts` - Streaming execution path
- `src/tools/BashTool/BashTool.tsx` - Long-running command handling
- `src/utils/Shell.ts` - Process spawning and management
- `src/utils/ShellCommand.ts` - Timeout and background logic
- `src/tasks/LocalShellTask/LocalShellTask.tsx` - Background task monitoring

## Memory Management

Claude Code prevents conversation history from blowing up with a **3-layer system**:

### 1. Tool Result Offloading (`toolResultStorage.ts`)

**Problem**: Single tool result can be >50KB (large file reads, bash output)

**Solution**: Persist to disk, keep preview in memory
- Large results (>50KB default) saved to `projectDir/sessionId/tool-results/`
- Message contains only 2KB preview + file path reference
- On resume, `ContentReplacementRecord` ensures byte-identical re-application for prompt cache hits
- Per-message budget enforcement: aggregate limit across all tool results in one API round

### 2. Microcompact - Runs Before Every API Call (`microCompact.ts`)

**Problem**: Tool results accumulate in conversation history (tool_use + tool_result messages)

**Solution**: Delete old tool results, keep only last N

**Two Paths**:

**Cache Warm Path** (cached microcompact):
- Uses Claude's `cache_edits` API to surgically delete old tool_use_id references
- Tracks tool_use IDs in module-level `CachedMCState`
- Groups tool results by user message (API-round boundaries)
- Count-based thresholds (e.g., keep last 5 tool results)
- Deletes from cached prefix WITHOUT rewriting it → cache stays warm
- Only targets heavy tools: Read, Bash, Grep, Glob, WebFetch, Edit, Write

**Cache Cold Path** (time-based trigger):
- When gap since last assistant message exceeds threshold (configurable)
- Content-clears all but most recent N tool results
- Replaces content with `[Old tool result content cleared]` marker
- Resets cached MC state (cache is cold anyway)

**Key Insight**: Old tool results are disposable - LLM already processed them, keeping verbatim is waste

### 3. Auto-Compact - When Context Hits ~93% of Window (`autoCompact.ts`, `compact.ts`)

**Problem**: Overall conversation too large despite microcompact

**Solution**: Summarize conversation

**Strategy**:
1. First tries **session memory compaction**: Extract key facts to markdown
2. Falls back to **full conversation summarization** via forked agent
3. **Circuit breaker**: Stops after 3 consecutive failures to prevent API hammering

**Trigger**: When context exceeds threshold (13K tokens below effective window)

### Summary Table

| Problem | Solution | File |
|---------|----------|------|
| Single large tool result | Persist to disk, keep 2KB preview | `toolResultStorage.ts` |
| Accumulating old tool results | Microcompact deletes old ones each turn | `microCompact.ts` |
| Overall context too big | Auto-compact summarizes conversation | `autoCompact.ts`, `compact.ts` |

### Key Innovation: Prompt Cache Preservation

Every compaction decision optimizes for **prompt cache hits**:
- Cached MC uses `cache_edits` to delete without invalidating cache
- Decisions are frozen: same tool result never replaced twice
- Time-based trigger explicitly signals cache is cold
- Content replacement records ensure byte-identical re-application

### Comparison to Basic Approach

**Basic (our current)**: Append all tool_use + tool_result → context blows up → manual truncation

**Claude Code**: Microcompact every turn → offload large results → auto-compact at threshold → cache-aware