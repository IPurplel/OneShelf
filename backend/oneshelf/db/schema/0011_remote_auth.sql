-- Remote Web UI authentication (Master §28) and First Run state (§29).
--
-- Passkeys use one fixed internal identity; it is never exposed as an account or profile (§28.4).
-- Nothing here is library state: resetting it affects remote Web UI authentication only (§28.5).

CREATE TABLE remote_credentials (
    credential_id TEXT PRIMARY KEY,          -- base64url, as sent by the authenticator
    public_key BLOB NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    label TEXT NOT NULL,
    transports TEXT,
    backed_up INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE remote_sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,         -- sha256 of the cookie token; the token itself is never stored
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    expires_at TEXT,                         -- NULL means "until manually revoked" (§28.6)
    revoked_at TEXT
);

CREATE INDEX remote_sessions_active ON remote_sessions(revoked_at, expires_at);

-- Single row: the Recovery Code is stored only as a verifier (§28.5).
CREATE TABLE remote_recovery (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    verifier TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT
);

-- Short-lived WebAuthn ceremony challenges; one row per pending ceremony.
CREATE TABLE webauthn_challenges (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('registration', 'authentication')),
    challenge BLOB NOT NULL,
    authorized_by TEXT,                      -- 'lan', 'recovery' or 'session' for registration ceremonies
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE first_run (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL CHECK (state IN ('pending', 'completed')),
    access_mode TEXT CHECK (access_mode IN ('local', 'lan', 'remote')),
    canonical_hostname TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
