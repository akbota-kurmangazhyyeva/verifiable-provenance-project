import hashlib

import pytest

from provenance import GenerationRecord, commit, content_hash, keccak256, model_id, new_salt, verify_opening


def make_record(**overrides):
    fields = dict(
        model="anthropic/claude-sonnet-5-5",
        prompt="Summarise the Haber-Stornetta paper in one sentence.",
        output="It links document hashes into a chain so timestamps cannot be backdated.",
        params={"temperature": 0, "max_tokens": 128},
        created_at="2026-10-14T09:00:00Z",
    )
    fields.update(overrides)
    return GenerationRecord(**fields)


SALT = bytes(range(32))


def test_keccak256_known_vector_and_not_sha3():
    empty = bytes.fromhex("c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
    assert keccak256(b"") == empty
    assert hashlib.sha3_256(b"").digest() != empty


def test_canonical_bytes_ignore_param_order():
    a = make_record(params={"temperature": 0, "max_tokens": 128})
    b = make_record(params={"max_tokens": 128, "temperature": 0})
    assert a.canonical_bytes() == b.canonical_bytes()


def test_json_round_trip():
    r = make_record(output="Unicode stays as is: ąžš — 你好")
    assert GenerationRecord.from_json(r.to_json()) == r


def test_rejects_unknown_version():
    with pytest.raises(ValueError):
        GenerationRecord.from_json('{"v": 2}')


@pytest.mark.parametrize(
    "change",
    [
        {"output": "It links document hashes into a chain so timestamps cannot be backdated!"},
        {"output": "It links document hashes into a chain so timestamps cannot be backdated. "},
        {"prompt": "Summarise the Haber-Stornetta paper in one sentence"},
        {"model": "anthropic/claude-haiku-5-5"},
        {"params": {"temperature": 0.7, "max_tokens": 128}},
        {"created_at": "2026-10-14T09:00:01Z"},
    ],
)
def test_any_edit_changes_commitment(change):
    assert commit(make_record(**change), SALT) != commit(make_record(), SALT)


def test_unicode_lookalike_changes_commitment():
    # "é" as one code point vs "e" + combining accent: same on screen, different bytes
    a = make_record(output="caf\u00e9")
    b = make_record(output="cafe\u0301")
    assert a.output != b.output
    assert commit(a, SALT) != commit(b, SALT)


def test_salt_hides_low_entropy_output():
    r = make_record(output="Yes.")
    assert commit(r, new_salt()) != commit(r, new_salt())
    # unsalted hash is the same for everyone who guesses the text
    assert content_hash(r) == content_hash(make_record(output="Yes."))


def test_commit_matches_solidity_encode_packed():
    r = make_record()
    assert commit(r, SALT) == keccak256(SALT + content_hash(r))


def test_verify_opening():
    r = make_record()
    c = commit(r, SALT)
    assert verify_opening(r, SALT, c)
    assert not verify_opening(r, bytes(32), c)
    assert not verify_opening(make_record(output="different"), SALT, c)
    assert not verify_opening(r, b"short", c)


def test_bad_salt_length():
    with pytest.raises(ValueError):
        commit(make_record(), b"\x00" * 31)


def test_model_id_is_just_a_label():
    assert model_id("anthropic/claude-sonnet-5-5") == keccak256(b"anthropic/claude-sonnet-5-5")
