"""A single LLM generation and the exact bytes we hash for it."""

import json
from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GenerationRecord:
    model: str  # provider/model identifier, e.g. "anthropic/claude-sonnet-5-5"
    prompt: str
    output: str
    params: dict = field(default_factory=dict)  # temperature, max_tokens, seed, ...
    created_at: str = ""  # ISO 8601 UTC time reported by the generating client

    def canonical_bytes(self) -> bytes:
        """Deterministic UTF-8 JSON encoding of the record.

        Keys are sorted and there is no whitespace, so the same record always
        gives the same bytes regardless of dict order. The text is NOT
        normalised (no Unicode NFC, no strip): the hash is over the exact
        characters, so any edit, even one character, changes it.

        Floats in `params` use Python's repr, which other languages may format
        differently. A verifier written in another language should either use
        the same formatting or the params should be stored as strings.
        """
        obj = {
            "v": SCHEMA_VERSION,
            "model": self.model,
            "prompt": self.prompt,
            "output": self.output,
            "params": self.params,
            "created_at": self.created_at,
        }
        text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return text.encode("utf-8")

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_json(cls, text: str) -> "GenerationRecord":
        obj = json.loads(text)
        if obj.get("v") != SCHEMA_VERSION:
            raise ValueError(f"unsupported record version {obj.get('v')!r}")
        return cls(
            model=obj["model"],
            prompt=obj["prompt"],
            output=obj["output"],
            params=obj["params"],
            created_at=obj["created_at"],
        )
