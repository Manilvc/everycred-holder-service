from app.core.signatures import is_signature_valid, sign

SECRET = "s" * 40
BODY = b'{"id":"1"}'


def test_valid_signature_is_accepted() -> None:
    header = sign(SECRET, 1_000, BODY)

    assert is_signature_valid(SECRET, header, BODY, 300, now=1_100)


def test_signature_outside_tolerance_is_rejected() -> None:
    header = sign(SECRET, 1_000, BODY)

    assert not is_signature_valid(SECRET, header, BODY, 300, now=2_000)


def test_signature_over_other_body_is_rejected() -> None:
    header = sign(SECRET, 1_000, BODY)

    assert not is_signature_valid(SECRET, header, b"{}", 300, now=1_000)


def test_malformed_header_is_rejected() -> None:
    assert not is_signature_valid(SECRET, "garbage", BODY, 300, now=1_000)
