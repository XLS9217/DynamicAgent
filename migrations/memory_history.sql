-- Run once against existing installations; fresh installs use init_storage.
BEGIN;
LOCK TABLE session_message IN ACCESS EXCLUSIVE MODE;
ALTER TABLE session_message ADD COLUMN IF NOT EXISTS sequence_no BIGINT;
WITH ordered AS (
 SELECT message_id, row_number() OVER (ORDER BY create_at, message_id) AS seq
 FROM session_message
)
UPDATE session_message m SET sequence_no = ordered.seq FROM ordered
WHERE m.message_id = ordered.message_id AND m.sequence_no IS NULL;
CREATE SEQUENCE IF NOT EXISTS session_message_sequence_no_seq;
SELECT setval('session_message_sequence_no_seq', COALESCE(MAX(sequence_no), 0) + 1, false)
FROM session_message;
ALTER TABLE session_message ALTER COLUMN sequence_no SET DEFAULT nextval('session_message_sequence_no_seq');
ALTER TABLE session_message ALTER COLUMN sequence_no SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS session_message_session_identity ON session_message(session_id, message_id);
CREATE INDEX IF NOT EXISTS session_message_sequence ON session_message(session_id, sequence_no);
CREATE TABLE IF NOT EXISTS session_memory_checkpoint (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL CHECK (btrim(summary) <> ''),
    compacted TEXT NOT NULL CHECK (btrim(compacted) <> ''),
    last_message_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, last_message_id),
    FOREIGN KEY (session_id, last_message_id)
        REFERENCES session_message (session_id, message_id) ON DELETE CASCADE
);
COMMIT;
