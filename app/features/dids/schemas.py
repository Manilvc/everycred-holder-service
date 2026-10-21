"""Request and response models for holder keys and DID documents."""

import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

# JWK members that only private or symmetric keys have (RFC 7518 §6).
_PRIVATE_JWK_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})
_COORDINATE_BYTES = 32


def _decode_coordinate(value: str, name: str) -> bytes:
    # JWK coordinates are base64url without padding; padding is added
    # back so the standard decoder accepts them.
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"'{name}' is not base64url") from exc
    if len(decoded) != _COORDINATE_BYTES:
        raise ValueError(f"'{name}' must decode to {_COORDINATE_BYTES} bytes")
    return decoded


class PublicJwk(BaseModel):
    """A public key as a JWK: Ed25519 (``OKP``) or P-256 (``EC``)."""

    model_config = ConfigDict(extra="forbid")

    kty: Literal["OKP", "EC"]
    crv: Literal["Ed25519", "P-256"]
    x: str = Field(max_length=64)
    y: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def reject_private_material(cls, values: Any) -> Any:
        """Refuse private key members before any other validation.

        A specific message here is clearer than the generic "extra field"
        error, and the rejected value is never echoed back.
        """
        if isinstance(values, dict) and _PRIVATE_JWK_MEMBERS & values.keys():
            raise ValueError(
                "private key material must never leave the device"
            )
        return values

    @model_validator(mode="after")
    def check_key(self) -> "PublicJwk":
        """Confirm the coordinates form a valid public key."""
        x_bytes = _decode_coordinate(self.x, "x")
        if self.kty == "OKP":
            if self.crv != "Ed25519" or self.y is not None:
                raise ValueError("OKP keys must be Ed25519 with no 'y'")
            Ed25519PublicKey.from_public_bytes(x_bytes)
            return self
        if self.crv != "P-256" or self.y is None:
            raise ValueError("EC keys must be P-256 with 'x' and 'y'")
        y_bytes = _decode_coordinate(self.y, "y")
        # Raises ValueError when the point is not on the curve.
        ec.EllipticCurvePublicNumbers(
            int.from_bytes(x_bytes, "big"),
            int.from_bytes(y_bytes, "big"),
            ec.SECP256R1(),
        ).public_key()
        return self

    @property
    def algorithm(self) -> str:
        """Return the JWS algorithm this key signs with."""
        return "EdDSA" if self.kty == "OKP" else "ES256"


class HolderKeyCreate(BaseModel):
    """Payload for registering a public key generated on the device."""

    model_config = ConfigDict(extra="forbid")

    public_jwk: PublicJwk


class HolderKeyResponse(BaseModel):
    """A registered key and the verification method it is published as."""

    model_config = ConfigDict(from_attributes=True)

    key_id: str
    verification_method_id: str
    algorithm: str
    public_jwk: dict[str, Any]
    created_at: datetime


class VerificationMethod(BaseModel):
    """A DID document verification method (JsonWebKey2020)."""

    id: str
    type: Literal["JsonWebKey2020"] = "JsonWebKey2020"
    controller: str
    public_key_jwk: dict[str, Any] = Field(serialization_alias="publicKeyJwk")


class DidDocument(BaseModel):
    """W3C DID document of a holder."""

    context: list[str] = Field(serialization_alias="@context")
    id: str
    verification_method: list[VerificationMethod] = Field(
        serialization_alias="verificationMethod"
    )
    authentication: list[str]
    assertion_method: list[str] = Field(serialization_alias="assertionMethod")
