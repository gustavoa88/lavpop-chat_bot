BEGIN;

ALTER TABLE chatbot.webhook_event_dedup
  DROP CONSTRAINT IF EXISTS webhook_event_dedup_pkey;

ALTER TABLE chatbot.webhook_event_dedup
  ADD COLUMN IF NOT EXISTS event_key VARCHAR(255),
  ADD COLUMN IF NOT EXISTS payload_hash CHAR(64),
  ADD COLUMN IF NOT EXISTS source VARCHAR(60) DEFAULT 'meta_webhook';

UPDATE chatbot.webhook_event_dedup
   SET event_key = COALESCE(event_key, provider || ':' || event_id),
       payload_hash = COALESCE(payload_hash, repeat('0', 64)),
       source = COALESCE(source, provider, 'meta_webhook')
 WHERE event_key IS NULL
    OR payload_hash IS NULL
    OR source IS NULL;

ALTER TABLE chatbot.webhook_event_dedup
  ALTER COLUMN event_key SET NOT NULL,
  ALTER COLUMN payload_hash SET NOT NULL,
  ALTER COLUMN source SET NOT NULL;

ALTER TABLE chatbot.webhook_event_dedup
  DROP COLUMN IF EXISTS provider,
  DROP COLUMN IF EXISTS event_id;

ALTER TABLE chatbot.webhook_event_dedup
  ADD CONSTRAINT webhook_event_dedup_pkey PRIMARY KEY (event_key);

DROP INDEX IF EXISTS chatbot.idx_webhook_event_processed_at;

CREATE INDEX IF NOT EXISTS idx_webhook_event_dedup_processed_at
  ON chatbot.webhook_event_dedup (processed_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA chatbot TO chatbot_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA chatbot TO chatbot_user;

COMMIT;
