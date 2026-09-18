# C8 — Verification Report: Remote Access, LAN Trust and First Run

Recorded: 2026-09-18 · Branch: `c8/remote-access-first-run` (from `c7/storage-backup-export` @ `52f0f3f`) · Authority: Meta Prompt §C8
Status: **C8 gate passed** for the backend described below. The Remote Access screens and the First Run wizard UI are C2.

## Commands and results

```sh
cd backend
.venv/bin/pytest          # → 728 passed (673 from C1–C7, 55 new in C8), no warnings
```

New dependency: `webauthn>=3.0.0` (py_webauthn 3.0.0, with `cbor2` and `pyasn1`), verified working on Python 3.14.7 and recorded in `pyproject.toml` and `requirements.lock`.

## Gate checklist (Meta Prompt §C8)

| Gate item | Evidence | Result |
|---|---|---|
| Genuine LAN versus forged forwarded headers | `test_a_lan_client_that_is_not_a_configured_proxy_cannot_forge_a_client_address` (the header is ignored entirely), `test_a_remote_client_cannot_enrol_itself_or_forge_lan_trust` (a remote peer sending `X-Forwarded-For: 192.168.1.50` stays remote), C1 `tests/unit/test_access.py` | Pass |
| Remote proxy cases | `test_a_trusted_proxy_never_lends_its_own_lan_trust_to_remote_visitors` — a reverse proxy *inside* the LAN is refused on its own connection, a forwarded internet visitor stays remote, a prepended chain (`203.0.113.9, 192.168.1.5`) cannot climb in, and only a genuinely forwarded LAN address becomes `lan` | Pass |
| Passkey authentication and revocation | `tests/integration/auth/test_passkeys.py` (register → authenticate, single-use challenges, expiry, wrong origin, wrong RP ID, unknown credential, cloned-authenticator sign-counter detection, list/delete), API `test_lan_is_trusted_and_can_enrol_a_passkey_that_remote_then_uses` | Pass |
| Registration is never anonymous | `test_a_remote_client_cannot_register_a_passkey_on_its_own`, `test_registration_from_a_signed_in_remote_session_is_allowed_but_never_anonymously` — LAN, a valid Recovery Code, or an existing session; nothing else | Pass |
| Recovery regeneration invalidates old codes | `test_regeneration_invalidates_the_previous_code`, `test_a_recovery_code_authorizes_a_new_passkey_and_regeneration_invalidates_it`, API `test_recovery_code_can_be_regenerated_from_the_lan`; the code is stored only as a scrypt verifier (`test_generated_code_is_readable_and_stored_only_as_a_verifier`) | Pass |
| Correct session defaults | `test_default_lifetime_is_thirty_days`, `test_configurable_lifetimes` (7 d / 30 d / 90 d / 1 y), `test_manual_lifetime_never_expires_on_its_own`, `test_listing_marks_the_current_session_without_fingerprinting`, `test_revoke_and_revoke_all_other_sessions`, API `test_sessions_can_be_listed_and_revoked`, `test_sign_out_only_ends_the_current_session` | Pass |
| No tokens in Web Storage | `test_cookies_are_httponly_samesite_and_secure_only_on_https`, the API assertion that the sign-in body carries no token and the cookie is `HttpOnly; SameSite=lax`, plus the source guard `tests/unit/test_no_token_storage.py` (scans web files for Web Storage token writes, `document.cookie` writes and the cookie name; verified against a planted violation) | Pass |
| Remote CSRF / Origin rejection | `test_cross_site_requests_are_refused` (403 `CROSS_ORIGIN_REQUEST`), C3 `tests/unit/test_request_guard.py` (Host allowlist, `Sec-Fetch-Site`, Origin mismatch on every unsafe method) | Pass |
| Recovery's limited scope | `test_lan_recovery_resets_remote_auth_only` — works, shelf entries, reading state, download jobs, plugins, source sessions, assets and follows are counted before and after and are identical; only passkeys, sessions and the recovery verifier go. API `test_lan_recovery_resets_remote_auth_and_says_so` asserts the confirmation says so in words | Pass |
| LAN recovery is LAN-only | `test_lan_recovery_is_refused_from_anywhere_but_a_genuine_lan_or_loopback`; a signed-in remote client still gets 403 `LAN_RECOVERY_UNAVAILABLE` | Pass |
| Canonical HTTPS hostname | `test_remote_access_needs_a_canonical_hostname` (stored as a bare host, URLs normalized, rubbish refused), `test_options_name_the_canonical_hostname_and_never_expose_an_account`, `test_the_configured_canonical_hostname_is_accepted_without_extra_configuration` (the Host allowlist follows the setting) | Pass |
| No account or profile | `test_options_name_the_canonical_hostname_and_never_expose_an_account` — one fixed internal WebAuthn identity (`oneshelf` / "OneShelf"); no username, password or profile exists anywhere in the API | Pass |
| First run is short and never blocks Home | `test_first_run_is_short_and_never_blocks_home` (health, storage, access mode, finish; every request works while first run is pending), `test_first_run_remote_mode_needs_a_hostname_and_a_passkey` (409 until remote setup is real) | Pass |
| Trusted networks come from configuration | `tests/unit/auth/test_policy.py` (loopback only before first run, configured private ranges become LAN, public ranges refused, environment and configured ranges merge, forwarded headers need a configured proxy, single-gateway warning) | Pass |
| First-run Arabic/English and mobile usability | Carried forward to C2 with the wizard UI (EB-2) | Carried |

## What C8 delivers (backend)

| Area | Modules |
|---|---|
| Passkey ceremonies, fixed internal identity, challenge lifecycle | `auth/passkeys.py`, migration `0011_remote_auth.sql` |
| Recovery Code verifier lifecycle | `auth/recovery.py` |
| Remote UI sessions, cookies, revocation | `auth/sessions.py` |
| Trust rules, LAN Recovery, remote state | `auth/service.py` |
| Runtime trusted networks, proxies, gateway warning | `auth/policy.py` |
| Access boundary with session authentication and dynamic configuration | `api/middleware.py`, `api/guard.py`, `api/app.py` |
| HTTP surface | `api/auth.py`, `api/firstrun.py` |

## Notes and decisions

- **Sign-in routes are reachable while signed out.** The access boundary lets exactly `POST /api/auth/sign-in/options` and `POST /api/auth/sign-in` through for remote clients; everything else needs a valid session cookie. Both routes only verify a passkey.
- **Trusted networks are hot.** The middleware resolves the effective `AccessConfig` per request from `AccessPolicy`, so First Run and Settings change trust without a restart. Environment-provided networks are merged, never replaced.
- **The gateway warning is real, not cosmetic.** `AccessPolicy` counts the distinct client addresses actually seen; if the first 20 non-loopback requests all arrive from one address, `gateway_warning()` explains that a router or proxy is probably forwarding and that everyone behind it would count as LAN.
- **A trusted proxy is not a LAN device.** Being listed as a trusted proxy means its forwarded address is read; the proxy's own connection is classified from the forwarded client, so an internet visitor never inherits LAN trust.
- **Passkey re-auth for sensitive operations** (§28.6 "may") is not implemented in v1; LAN Recovery and session revocation already require either genuine LAN or the session itself.

## Open items for review (ledger §13)

| ID | Item |
|---|---|
| D-C8-01 | Session lifetime options are exactly 7 d / 30 d / 90 d / 1 y / manual, with 30 d default; "shorter" in §28.6 is read as 7 days. |
| D-C8-04 | A trusted LAN device may register a passkey without any further proof, matching §28.1's trusted-LAN model. |
| D-C8-06 | First Run refuses to finish in Remote mode until a hostname and one passkey exist (409), rather than completing a setup that cannot be used. |
