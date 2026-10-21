# `app/core/storage.py`

> Last updated: 2026-10-21

## Purpose

Store holder files: profile images, DID QR codes, DID profile documents,
and verifiable presentations. The database keeps object keys only;
URLs are produced when a response needs one.

## Public API

### `ObjectStorage` (protocol)

- `await put(key, content, content_type)` — store or replace an object.
- `await url_for(key) -> str` — a URL the wallet can fetch.

### `Storage`

`Annotated[ObjectStorage, Depends(get_storage)]`; the instance is built
once in the lifespan by `create_storage(settings)`.

```python
async def replace_image(storage: Storage, key: str, png: bytes) -> str:
    await storage.put(key, png, "image/png")
    return await storage.url_for(key)
```

### Backends

- `S3Storage` — private bucket, server-side encryption (`AES256`),
  presigned GET URLs valid for `STORAGE_URL_TTL_SECONDS`. boto3 calls run
  in a thread. AWS credentials come from the standard chain.
- `LocalStorage` — files under `STORAGE_LOCAL_DIR`, served by `app.main`
  at `/media`. URLs do not expire, so it is refused in production.

## How it works

1. Keys are built by services (`holders/<holder id>/...`) and never
   taken from requests. `_check_key` still rejects absolute paths and
   `..` so a future mistake cannot write outside the root.
2. `S3Storage` prefixes every key with `S3_PREFIX`.

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `STORAGE_BACKEND` | `local` | `local` or `s3` (required in production) |
| `STORAGE_LOCAL_DIR` | `media` | Local root |
| `STORAGE_PUBLIC_BASE_URL` | `http://127.0.0.1:8040/media` | Local URL base |
| `STORAGE_URL_TTL_SECONDS` | `900` | Presigned URL lifetime |
| `AWS_REGION`, `S3_BUCKET`, `S3_PREFIX` | — | S3 location |

## Failure modes

| Situation | Behaviour |
|-----------|-----------|
| Invalid key | `InvalidObjectKeyError` (a bug; surfaces as 500) |
| S3 unavailable or access denied | botocore error propagates; the request fails with 500 and the traceback is logged |

## Changing this module

- A new backend must implement both protocol methods.
- The S3 bucket must block public access; files are only reachable via
  presigned URLs.

## Tests

`tests/core/test_storage.py`; feature tests swap in an in-memory
storage through `app.dependency_overrides[get_storage]`.
