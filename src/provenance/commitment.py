"""Salted commitments to generation records, compatible with ProvenanceRegistry.

commitment = keccak256(salt || keccak256(canonical_bytes(record)))

The salt is 32 random bytes kept by the owner. Without it, anyone could test
guesses: an output such as "Yes." or a prompt from a known list can be hashed
and compared with what is on chain. With the salt, the on-chain value reveals
nothing until the owner publishes the record and the salt together.
"""

import hmac
import secrets

from Crypto.Hash import keccak

from .record import GenerationRecord

SALT_BYTES = 32


def keccak256(data: bytes) -> bytes:
    # Ethereum uses the original Keccak padding. hashlib.sha3_256 is the NIST
    # SHA3-256 standard, which pads differently and gives different digests.
    return keccak.new(digest_bits=256, data=data).digest()


def new_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def content_hash(record: GenerationRecord) -> bytes:
    return keccak256(record.canonical_bytes())


def commit(record: GenerationRecord, salt: bytes) -> bytes:
    """Same as Solidity keccak256(abi.encodePacked(salt, contentHash))."""
    if len(salt) != SALT_BYTES:
        raise ValueError(f"salt must be {SALT_BYTES} bytes, got {len(salt)}")
    return keccak256(salt + content_hash(record))


def model_id(model: str) -> bytes:
    """The modelId stored next to a commitment. It is only a label chosen by the
    submitter; nothing on chain checks that this model produced the output."""
    return keccak256(model.encode("utf-8"))


def verify_opening(record: GenerationRecord, salt: bytes, commitment: bytes) -> bool:
    """True if (record, salt) is an opening of `commitment`."""
    try:
        return hmac.compare_digest(commit(record, salt), commitment)
    except ValueError:
        return False
