# `app/core/models.py`

> Last updated: 2026-10-21

## Purpose

Column types and mixins every ORM model can reuse, so ids and
timestamps behave the same in every table.

## Public API

### `UUIDPrimaryKeyMixin`

Adds `id: uuid.UUID`, generated with `uuid4()` in Python. On MySQL the
column is `CHAR(32)`. Random ids do not leak record counts and can be
referenced before the row is flushed.

### `TimestampMixin`

Adds `created_at` and `updated_at`, both `UTCDateTime`. `updated_at`
changes on every ORM update.

### `UTCDateTime`

A `TypeDecorator` over `DateTime`:

- **Saving** — requires a timezone-aware datetime, converts it to UTC,
  and stores it naive. Passing a naive datetime raises `ValueError`
  rather than guessing its zone.
- **Loading** — marks the naive value as UTC.

### `utc_now() -> datetime`

`datetime.now(UTC)`. Use it everywhere instead of `datetime.now()` or
`datetime.utcnow()` (which returns a naive value).

### `to_naive_iso(value) -> str | None`

Formats a datetime as naive UTC ISO-8601 (`2026-10-22T10:00:00`), the
format the DCS returned and the wallet app parses.

### `generate_public_id() -> int`

A random positive integer below 2^52, used for the integer ids the
wallet app expects (`holders.numeric_id`, `credential_refs.numeric_id`).
It is JavaScript-safe and reveals nothing about row counts.

## Usage

```python
class HolderSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "holder_sessions"

    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
```

Mixins go before `Base` in the class bases.

## How it works

MySQL `DATETIME` has no time zone, and aiomysql returns naive values.
Comparing those with `utc_now()` raises `TypeError`, and mixing local
and UTC times would give wrong lockout and expiry decisions. Converting
at the column boundary means the rest of the code only ever sees aware
UTC datetimes.

## Changing this module

- Migrations render `UTCDateTime` as `sa.DateTime()` (see
  `_render_item` in `migrations/env.py`), so changing this class does
  not require editing old migrations.
