CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, track TEXT NOT NULL DEFAULT '',
  level TEXT NOT NULL DEFAULT '', starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity > 0)
);
CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
INSERT INTO schema_meta(version)
SELECT 2 WHERE NOT EXISTS (SELECT 1 FROM schema_meta);
CREATE TABLE IF NOT EXISTS catalog_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1), content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
  expires_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  expires_at DOUBLE PRECISION NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reservations (
  receipt_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  created_at DOUBLE PRECISION NOT NULL, UNIQUE(user_id, session_id)
);
CREATE TABLE IF NOT EXISTS idempotency (
  user_id TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
  receipt_id TEXT NOT NULL REFERENCES reservations(receipt_id), PRIMARY KEY(user_id, key)
);
CREATE INDEX IF NOT EXISTS reservations_by_session ON reservations(session_id);
