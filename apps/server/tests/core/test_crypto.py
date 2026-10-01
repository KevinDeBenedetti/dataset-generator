import pytest

from server.core.crypto import (
    CryptoError,
    SecretBox,
    aad_for,
    build_box,
    generate_key,
    parse_ring,
)


def _ring(*ids):
    return ",".join(f"{i}:{generate_key()}" for i in ids)


def test_roundtrip_and_ciphertext_hides_the_value():
    box = build_box(_ring("k1"))
    ciphertext, key_id = box.encrypt("sk-secret-value", aad_for("u1", "openai_api_key"))

    assert key_id == "k1"
    assert "sk-secret-value" not in ciphertext
    assert (
        box.decrypt(ciphertext, key_id, aad_for("u1", "openai_api_key"))
        == "sk-secret-value"
    )


def test_two_encryptions_of_the_same_value_differ():
    box = build_box(_ring("k1"))
    aad = aad_for("u1", "hf_token")
    assert box.encrypt("v", aad)[0] != box.encrypt("v", aad)[0]


def test_a_ciphertext_is_bound_to_its_owner_and_kind():
    box = build_box(_ring("k1"))
    ciphertext, key_id = box.encrypt("value", aad_for("alice", "openai_api_key"))

    with pytest.raises(CryptoError):
        box.decrypt(ciphertext, key_id, aad_for("bob", "openai_api_key"))
    with pytest.raises(CryptoError):
        box.decrypt(ciphertext, key_id, aad_for("alice", "hf_token"))


def test_tampering_is_detected():
    box = build_box(_ring("k1"))
    aad = aad_for("u", "k")
    ciphertext, key_id = box.encrypt("value", aad)
    flipped = ciphertext[:-4] + ("AAAA" if not ciphertext.endswith("AAAA") else "BBBB")
    with pytest.raises(CryptoError):
        box.decrypt(flipped, key_id, aad)
    with pytest.raises(CryptoError):
        box.decrypt("not base64 !!", key_id, aad)


def test_rotation_new_key_encrypts_old_key_still_decrypts():
    old = _ring("k1")
    old_box = build_box(old)
    ciphertext, key_id = old_box.encrypt("value", aad_for("u", "k"))

    rotated = build_box(f"k2:{generate_key()},{old}")
    assert rotated.primary_id == "k2"
    assert rotated.decrypt(ciphertext, key_id, aad_for("u", "k")) == "value"
    assert rotated.encrypt("x", aad_for("u", "k"))[1] == "k2"

    # Without the old key the old ciphertext is unreadable.
    with pytest.raises(CryptoError, match="not in the key ring"):
        build_box(_ring("k2")).decrypt(ciphertext, key_id, aad_for("u", "k"))


@pytest.mark.parametrize(
    "raw",
    [
        "k1",
        "k1:",
        ":abc",
        "k1:short",
        f"a:{generate_key()},a:{generate_key()}",
        "k1:!!!",
    ],
)
def test_malformed_rings_are_refused(raw):
    with pytest.raises(CryptoError):
        parse_ring(raw)


def test_dev_fallback_is_derived_and_stable_but_needs_a_secret():
    a = build_box("", "auth-secret")
    b = build_box("", "auth-secret")
    ciphertext, key_id = a.encrypt("v", aad_for("u", "k"))
    assert b.decrypt(ciphertext, key_id, aad_for("u", "k")) == "v"
    assert isinstance(a, SecretBox)
    with pytest.raises(CryptoError, match="not configured"):
        build_box("", "")
