# `app/core/security.py`

> Last updated: 2026-10-21

## Purpose

Every cryptographic operation behind holder sign-in: password hashing,
OTP codes, reset tokens, and the JWTs the wallet sends. The auth feature
and the `CurrentHolder` dependency are its only callers.

## Public API

### Passwords

- `hash_password(password) -> str` — Argon2id hash, run in a thread.
- `verify_password(password, password_hash) -> PasswordCheck` —
  constant-time check; `updated_hash` is set when the stored hash uses
  outdated parameters and should be replaced.
- `burn_password_check_time(password)` — spends the time of a real
  check when the account does not exist, so response time does not
  reveal registered emails.

### One-time secrets

- `generate_otp_code() -> str` — six random digits from `secrets`.
- `generate_url_token() -> str` — 256-bit URL-safe token for reset links.
- `hash_secret_value(value, settings) -> str` and
  `is_secret_value_valid(value, stored_hash, settings) -> bool` — HMAC-SHA256
  keyed with `TOKEN_HASH_SECRET`; only the hash is stored.

### Tokens

- `create_access_token(holder_id, session_id, expires_at, settings)` —
  signs a token with `typ=access` and `sid=<session id>`.
- `create_email_verification_token(holder_id, expires_at, settings)` —
  signs a token with `typ=email_verification` and no session, for
  `/v1/holder/email/verify`. `decode_token` refuses it as an access
  token and an access token as it, because the `typ` must match.
- `create_recovery_token(holder_id, settings) -> str` and
  `read_recovery_token(token, settings) -> UUID` — the token login
  returns for a recently deleted account. It is a base64url payload
  `{holder_id, type: "holder_recovery", exp}` plus an HMAC keyed with
  `TOKEN_HASH_SECRET`, valid `RECOVERY_TOKEN_TTL_SECONDS`.
  `read_recovery_token` raises `RecoveryTokenError` (`is_expired` set
  for a genuine but old token).
- `decode_token(token, expected_type, settings) -> TokenClaims` —
  verifies signature, issuer, audience, expiry, required claims, and the
  `typ`; raises `AuthenticationError` with one generic message.

```python
from app.core.security import TokenType, decode_token

claims = decode_token(raw_token, TokenType.ACCESS, settings)
holder_session_id = claims.session_id
```

## How it works

1. Argon2id is slow on purpose; `run_in_threadpool` keeps the event loop
   free while it runs.
2. OTPs and reset tokens are short-lived and random, so a keyed fast
   hash is enough. The key means a leaked database cannot be used to
   confirm a code offline.
3. JWTs are HS256 by default with the algorithm list pinned on decode,
   which blocks `alg: none` and algorithm-confusion attacks. The audience
   is `everycred-holder-service`, so tokens from other EveryCRED services
   are rejected even if a key were shared by mistake.
4. Recovery tokens are not JWTs, so they can never pass as access
   tokens; their HMAC message starts with a type label, so OTP and reset
   hashes made with the same key cannot be replayed as one.
5. An access token is only half the check: `CurrentHolder` also loads the
   session named by `sid` and rejects ended or expired sessions. That is
   what makes logout immediate without a token blacklist.

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `JWT_SECRET_KEY` | required, 32+ chars | Signs all tokens |
| `JWT_ALGORITHM` | `HS256` | HMAC algorithm |
| `SESSION_LIFETIME_DAYS` | `30` | Access token and session lifetime |
| `RECOVERY_TOKEN_TTL_SECONDS` | `120` | Recovery token lifetime |
| `TOKEN_HASH_SECRET` | required, 32+ chars | Keys OTP and reset token hashes and recovery tokens |

## Failure modes

| Situation | Behaviour |
|-----------|-----------|
| Expired, tampered, wrong-audience, or wrong-type token | `AuthenticationError` (401, "Invalid token") |

## Changing this module

- Never log tokens, codes, or passwords.
- Changing `TOKEN_AUDIENCE` or the issuer invalidates every token.

## Tests

`tests/features/auth/test_auth.py` covers the flows end to end,
including that a recovery token is refused as an access token
(`test_delete_then_recover_account`).
