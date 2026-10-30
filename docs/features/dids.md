# DIDs

> Package: `app/features/dids/`
> Owner: EveryCRED backend team
> Last updated: 2026-10-21

## Overview

Each holder gets a DID at registration. The wallet generates key pairs
on the device and registers the public keys here; they are published in
the holder's DID document, which verifiers resolve to check signed
presentations. Private keys never leave the device.

## Endpoints

| Method | Path | Summary | Auth |
|--------|------|---------|------|
| POST | `/v1/holders/me/keys` | Register a public key | bearer |
| GET | `/v1/holders/me/keys` | List active keys | bearer |
| DELETE | `/v1/holders/me/keys/{key_id}` | Revoke a key | bearer |
| GET | `/v1/dids/{did}` | Resolve a DID document | public |

### `POST /v1/holders/me/keys`

```json
{
  "public_jwk": {
    "kty": "OKP",
    "crv": "Ed25519",
    "x": "<base64url, 32 bytes>"
  }
}
```

P-256 keys use `{"kty": "EC", "crv": "P-256", "x": "...", "y": "..."}`.

Response `201 Created`:

```json
{
  "key_id": "key-0123456789abcdef",
  "verification_method_id": "did:evrc:holder:...#key-0123456789abcdef",
  "algorithm": "EdDSA",
  "public_jwk": {"kty": "OKP", "crv": "Ed25519", "x": "..."},
  "created_at": "2026-10-21T10:00:00Z"
}
```

### `GET /v1/dids/{did}`

`application/did+json`:

```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/suites/jws-2020/v1"
  ],
  "id": "did:evrc:holder:...",
  "verificationMethod": [
    {
      "id": "did:evrc:holder:...#key-0123456789abcdef",
      "type": "JsonWebKey2020",
      "controller": "did:evrc:holder:...",
      "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": "..."}
    }
  ],
  "authentication": ["did:evrc:holder:...#key-0123456789abcdef"],
  "assertionMethod": ["did:evrc:holder:...#key-0123456789abcdef"]
}
```

Errors:

Errors use the DCS envelope `{"status", "data", "message"}`.

| Status | `message` | When |
|--------|-----------|------|
| 404 | The DID was not found. | No active holder owns the DID |
| 404 | Key `<key_id>` does not exist. | Revoking an unknown or revoked key |
| 409 | Revoke an existing key before registering another. | `MAX_KEYS_PER_HOLDER` active keys already |
| 422 | `<field> <reason>` | Private members (`d`, ...), wrong curve, point not on curve |

## Flow

At registration `DidProvisioner.provision` creates
`<DID_PREFIX>:<uuid4>`, renders a QR PNG of it, and writes a JSON-LD
profile document (`HolderProfile`, no personal data) to storage.

`PublicJwk` validation, in order: reject any private member, check
`kty`/`crv` combination, decode coordinates (32 bytes each), and build
the key with `cryptography` to prove it is valid.

## Data model

`holder_keys`: `holder_id`, `key_id` (unique per holder), `algorithm`
(`EdDSA` or `ES256`), `public_jwk` (JSON), `revoked_at`.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `DID_PREFIX` | `did:evrc:holder` | DID method and namespace |
| `MAX_KEYS_PER_HOLDER` | `10` | Active keys per holder |

## Design decisions

- The DID format matches DCS (`did:evrc:holder:<uuid4>`), so existing
  verifier tooling recognises it.
- Revoked keys are kept, so audit entries and old presentations can
  still be explained.

## Known limitations

- Existing DCS holders get a new DID here; migrating DCS holder DIDs is
  a separate task.
- The `did:evrc` universal resolver driver must be pointed at
  `GET /v1/dids/{did}` for holder DIDs.

## Testing

`tests/features/dids/test_keys_and_did_document.py`.
