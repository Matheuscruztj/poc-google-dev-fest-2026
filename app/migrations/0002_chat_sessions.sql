CREATE INDEX IF NOT EXISTS demo_sessions_by_expiry ON demo_sessions(expires_at);
CREATE TABLE IF NOT EXISTS demo_chat_messages (
  demo_session_hash TEXT NOT NULL REFERENCES demo_sessions(token_hash) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK(position >= 0 AND position < 8),
  content TEXT NOT NULL, PRIMARY KEY(demo_session_hash, position)
);
CREATE TABLE IF NOT EXISTS demo_chat_leases (
  demo_session_hash TEXT PRIMARY KEY REFERENCES demo_sessions(token_hash) ON DELETE CASCADE,
  owner TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL
);
UPDATE schema_meta SET version=3;
