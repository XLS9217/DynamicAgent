# LLM invoke schema with JSONB usage

```sql
CREATE TABLE llm_invoke (
    invoke_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seq                    BIGSERIAL UNIQUE NOT NULL,

    trigger_id             UUID NOT NULL
                           REFERENCES agent_trigger(trigger_id)
                           ON DELETE CASCADE,

    session_id             TEXT NOT NULL,
    runner_id              TEXT NOT NULL,
    runner_name            TEXT NOT NULL,
    parent_runner_id       TEXT,
    parent_tool_call_id    TEXT,

    provider_generation_id TEXT,
    provider               TEXT,
    model                  TEXT NOT NULL,

    status                 TEXT NOT NULL DEFAULT 'running'
                           CHECK (status IN (
                               'running',
                               'completed',
                               'failed',
                               'cancelled'
                           )),

    finish_reason          TEXT,
    native_finish_reason   TEXT,

    started_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at           TIMESTAMPTZ,
    duration_ms            BIGINT,

    completion_text        TEXT,
    tool_calls             JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- Entire provider usage object, including tokens and costs.
    usage                  JSONB,

    raw_completion         JSONB,
    error                  JSONB,
    metadata               JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX idx_llm_invoke_trigger_seq
    ON llm_invoke (trigger_id, seq);

CREATE INDEX idx_llm_invoke_session_started
    ON llm_invoke (session_id, started_at DESC);

CREATE INDEX idx_llm_invoke_runner_started
    ON llm_invoke (runner_id, started_at DESC);
```

## Example `usage` value

```json
{
  "prompt_tokens": 11,
  "completion_tokens": 162,
  "total_tokens": 173,
  "completion_tokens_details": {
    "accepted_prediction_tokens": null,
    "audio_tokens": 0,
    "reasoning_tokens": 148,
    "rejected_prediction_tokens": null,
    "image_tokens": 0
  },
  "prompt_tokens_details": {
    "audio_tokens": 0,
    "cached_tokens": 0,
    "cache_write_tokens": 0,
    "video_tokens": 0
  },
  "cost": 0.000733075,
  "is_byok": false,
  "cost_details": {
    "upstream_inference_cost": 0.000733075,
    "upstream_inference_prompt_cost": 0.000016225,
    "upstream_inference_completions_cost": 0.00071685
  }
}
```

## Aggregate usage by trigger

```sql
SELECT
    trigger_id,
    COUNT(*) AS invoke_count,
    SUM(COALESCE((usage->>'prompt_tokens')::BIGINT, 0)) AS prompt_tokens,
    SUM(COALESCE((usage->>'completion_tokens')::BIGINT, 0)) AS completion_tokens,
    SUM(COALESCE((usage->>'total_tokens')::BIGINT, 0)) AS total_tokens,
    SUM(COALESCE((usage->>'cost')::NUMERIC, 0)) AS cost
FROM llm_invoke
GROUP BY trigger_id;
```

## Read nested token details

```sql
SELECT
    invoke_id,
    COALESCE(
        (usage->'completion_tokens_details'->>'reasoning_tokens')::BIGINT,
        0
    ) AS reasoning_tokens,
    COALESCE(
        (usage->'prompt_tokens_details'->>'cached_tokens')::BIGINT,
        0
    ) AS cached_tokens
FROM llm_invoke;
```

## Optional expression indexes

Add these only if token or cost aggregation becomes a frequent query.

```sql
CREATE INDEX idx_llm_invoke_total_tokens
    ON llm_invoke (((usage->>'total_tokens')::BIGINT));

CREATE INDEX idx_llm_invoke_usage_cost
    ON llm_invoke (((usage->>'cost')::NUMERIC));
```
