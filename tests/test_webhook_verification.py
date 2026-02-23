import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from omniclaw.webhooks.parser import InvalidSignatureError, WebhookParser


@pytest.fixture
def key_pair():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def parser(key_pair):
    _, public_key = key_pair
    # Use hex format for default parser
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return WebhookParser(verification_key=pub_bytes.hex())


def sign_payload(private_key, payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")

    signature = private_key.sign(payload)
    return base64.b64encode(signature).decode("utf-8")


def test_verify_signature_valid(parser, key_pair):
    private_key, _ = key_pair
    payload = '{"test": "data"}'
    signature = sign_payload(private_key, payload)
    headers = {"x-circle-signature": signature}

    assert parser.verify_signature(payload, headers) is True


def test_verify_signature_invalid_signature(parser, key_pair):
    _, _ = key_pair
    payload = '{"test": "data"}'
    # Random signature
    signature = base64.b64encode(b"0" * 64).decode("utf-8")
    headers = {"x-circle-signature": signature}

    with pytest.raises(InvalidSignatureError, match="Signature mismatch"):
        parser.verify_signature(payload, headers)


def test_verify_signature_tampered_payload(parser, key_pair):
    private_key, _ = key_pair
    payload = '{"test": "data"}'
    signature = sign_payload(private_key, payload)
    headers = {"x-circle-signature": signature}

    # Verify with modified payload
    with pytest.raises(InvalidSignatureError, match="Signature mismatch"):
        parser.verify_signature('{"test": "hacked"}', headers)


def test_verify_signature_missing_header(parser):
    payload = '{"test": "data"}'
    headers = {}

    with pytest.raises(InvalidSignatureError, match="Missing x-circle-signature header"):
        parser.verify_signature(payload, headers)


def test_verify_signature_base64_key(key_pair):
    private_key, public_key = key_pair
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    b64_key = base64.b64encode(pub_bytes).decode("utf-8")

    parser = WebhookParser(verification_key=b64_key)
    payload = "data"
    signature = sign_payload(private_key, payload)
    headers = {"x-circle-signature": signature}

    assert parser.verify_signature(payload, headers) is True


def test_verify_signature_pem_key(key_pair):
    private_key, public_key = key_pair
    pem_key = public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")

    parser = WebhookParser(verification_key=pem_key)
    payload = "data"
    signature = sign_payload(private_key, payload)
    headers = {"x-circle-signature": signature}

    assert parser.verify_signature(payload, headers) is True


def test_no_verification_key():
    parser = WebhookParser(verification_key=None)
    payload = "data"
    headers = {}  # No header needed
    assert parser.verify_signature(payload, headers) is True
