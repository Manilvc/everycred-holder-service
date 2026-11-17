"""Read the issuer's chain links from a credential document.

An issuer can link credentials into a chain (an employment verification
followed by an experience letter, for example). Each linked credential
carries a signed ``linkedCredentialData`` block whose
``firstCredentialLinkedList`` has exactly one key: the id of the chain's
first credential. Every credential of a chain shares that key, so it is
the chain id.

The wallet app parses the same block (``src/features/credentials/
linked.ts``); both sides must agree on how ids are normalised.
"""

import base64
import binascii
import json
from typing import Any

from app.core.connector import NormalizedCredential

SD_JWT_FORMAT = "vc+ld+sd_jwt"
_URN_UUID_PREFIX = "urn:uuid:"


def normalize_credential_id(value: object) -> str | None:
    """Return ``value`` without an ``urn:uuid:`` prefix, lower-cased."""
    if not isinstance(value, str):
        return None
    bare = value.strip()
    if bare.lower().startswith(_URN_UUID_PREFIX):
        bare = bare[len(_URN_UUID_PREFIX) :]
    return bare.lower() or None


def _jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    segment = parts[1]
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        payload = json.loads(decoded)
    except (binascii.Error, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _claims_of(document: object) -> dict[str, Any] | None:
    # An SD-JWT credential arrives as an envelope; the chain block and the
    # id sit in its JWT payload, not in the envelope itself.
    if not isinstance(document, dict):
        return None
    token = document.get("credential")
    if document.get("format") == SD_JWT_FORMAT and isinstance(token, str):
        return _jwt_payload(token)
    return document


def document_of(credential: NormalizedCredential) -> dict[str, Any] | None:
    """Return the credential document as issued, parsed."""
    if credential.credential_json_content:
        try:
            parsed = json.loads(credential.credential_json_content)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return credential.credential_json


def document_id_of(document: object) -> str | None:
    """Return the credential's own id (``id``, else ``jti``), normalised."""
    claims = _claims_of(document)
    if claims is None:
        return None
    own_id = normalize_credential_id(claims.get("id"))
    return own_id or normalize_credential_id(claims.get("jti"))


def _linked_block(document: object) -> dict[str, Any] | None:
    claims = _claims_of(document)
    block = claims.get("linkedCredentialData") if claims else None
    return block if isinstance(block, dict) else None


def _ids_of(id_map: object) -> list[str]:
    # The block maps ``urn:uuid:<id>`` to a URL; only the keys matter.
    if not isinstance(id_map, dict):
        return []
    return [
        normalized
        for key in id_map
        if (normalized := normalize_credential_id(key)) is not None
    ]


def previous_ids_of(document: object) -> list[str]:
    """Return the ids of the credentials this one directly follows.

    Reads both predecessor maps of the signed block: the holder's own
    earlier credential and the previous owner's credential.

    Returns:
        Normalised ids in block order without duplicates; empty for a
        chain's first credential or a standalone one.
    """
    block = _linked_block(document)
    if block is None:
        return []
    ids = _ids_of(block.get("previousCredentialsId"))
    ids += _ids_of(block.get("previousOwnershipCredentialId"))
    return list(dict.fromkeys(ids))


def chain_id_of(document: object) -> str | None:
    """Return the id of the chain the credential belongs to.

    Returns:
        The normalised id of the chain's first credential, or None for a
        standalone credential or a block too damaged to use.
    """
    block = _linked_block(document)
    if block is None:
        return None
    first = block.get("firstCredentialLinkedList")
    # One key names the chain; zero or several is malformed.
    if not isinstance(first, dict) or len(first) != 1:
        return None
    return normalize_credential_id(next(iter(first)))
