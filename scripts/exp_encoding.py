#!/usr/bin/env python3
"""Encoding experiment: does the same text in a different form still verify?

Each output from data/exp1_generations.jsonl is committed once, with its true
model label, on a fresh local Anvil chain. Then the receipt is rewritten in
each of the forms below and checked with `provenance.cli verify`.

Text variants change the characters of the output; a reader would usually
call the result "the same text":
  nfd               Unicode NFD instead of NFC (e.g. e + combining accent)
  crlf              Windows line endings (CR LF) instead of LF
  trailing_space    one space appended
  trailing_newline  one newline appended, as many editors do on save
  nbsp              the first space replaced by a no-break space (U+00A0)

Receipt variants keep every string and number but write the JSON differently:
  keys_reordered    all object keys in reverse order
  compact_json      no indentation or spaces
  ascii_escaped     non-ASCII characters written as \\uXXXX escapes
  ints_as_floats    integer parameters written as floats (20 -> 20.0)

For each (output, variant) we record whether the variant changes the bytes of
the canonical record (a variant can be a no-op, e.g. NFD on ASCII text), whether `verify` accepts it, and whether a verifier that
normalised text before hashing (NFC, LF line endings, trailing whitespace
removed) would have matched it.

Writes data/encoding_results.csv and data/encoding_summary.csv.
"""

import csv
import io
import json
import sys
import tempfile
import unicodedata
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_chain import ANVIL_KEY, anvil, deploy
from provenance import cli
from provenance.record import GenerationRecord

DATA = ROOT / "data"


def run_cli(arguments: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(arguments)
    return code, out.getvalue() + err.getvalue()


def with_output(receipt: dict, change: Callable[[str], str]) -> str:
    changed = json.loads(json.dumps(receipt))
    changed["record"]["output"] = change(changed["record"]["output"])
    return json.dumps(changed, indent=2, ensure_ascii=False)


def reverse_keys(value: object) -> object:
    if isinstance(value, dict):
        return {key: reverse_keys(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [reverse_keys(item) for item in value]
    return value


def ints_as_floats(receipt: dict) -> str:
    changed = json.loads(json.dumps(receipt))
    changed["record"]["params"] = {key: float(value) if isinstance(value, int) and not isinstance(value, bool) else value for key, value in changed["record"]["params"].items()}
    return json.dumps(changed, indent=2, ensure_ascii=False)


VARIANTS: dict[str, tuple[str, Callable[[dict], str]]] = {
    "nfd": ("text", lambda r: with_output(r, lambda text: unicodedata.normalize("NFD", text))),
    "crlf": ("text", lambda r: with_output(r, lambda text: text.replace("\r\n", "\n").replace("\n", "\r\n"))),
    "trailing_space": ("text", lambda r: with_output(r, lambda text: text + " ")),
    "trailing_newline": ("text", lambda r: with_output(r, lambda text: text + "\n")),
    "nbsp": ("text", lambda r: with_output(r, lambda text: text.replace(" ", " ", 1))),
    "keys_reordered": ("receipt", lambda r: json.dumps(reverse_keys(r), indent=2, ensure_ascii=False)),
    "compact_json": ("receipt", lambda r: json.dumps(r, separators=(",", ":"), ensure_ascii=False)),
    "ascii_escaped": ("receipt", lambda r: json.dumps(r, indent=2, ensure_ascii=True)),
    "ints_as_floats": ("receipt", ints_as_floats),
}


def normalise(text: str) -> str:
    """What a lenient verifier might do: NFC, LF line endings, no trailing whitespace."""
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").rstrip()


def canonical(receipt_text: str) -> bytes:
    return GenerationRecord.from_json(json.dumps(json.loads(receipt_text)["record"])).canonical_bytes()


def failure_stage(printed: str) -> str:
    if "do not open" in printed:
        return "opening"  # record and salt no longer hash to the committed value
    if "not recorded" in printed:
        return "chain"
    if printed.startswith("Error"):
        return "error"
    return ""


def main() -> None:
    generations = [json.loads(line) for line in (DATA / "exp1_generations.jsonl").read_text(encoding="utf-8").splitlines()]
    rows: list[dict[str, object]] = []
    with anvil() as rpc_url, tempfile.TemporaryDirectory() as temporary:
        workdir = Path(temporary)
        registry = deploy("src/contracts/ProvenanceRegistry.sol:ProvenanceRegistry", rpc_url)
        for generation in generations:
            record = generation["record"]
            prompt, output, receipt_path = (workdir / f"{generation['id']}.{suffix}" for suffix in ("prompt", "output", "json"))
            prompt.write_bytes(record["prompt"].encode("utf-8"))
            output.write_bytes(record["output"].encode("utf-8"))
            code, printed = run_cli([
                "commit", str(prompt), str(output), record["model"], "--registry", registry, "--receipt", str(receipt_path),
                "--rpc-url", rpc_url, "--private-key", ANVIL_KEY,
                "--params", json.dumps(record["params"]), "--created-at", record["created_at"],
            ])
            if code != 0:
                raise RuntimeError(f"commit failed for {generation['id']}: {printed}")
            original_text = receipt_path.read_text(encoding="utf-8")
            original = json.loads(original_text)
            if run_cli(["verify", str(receipt_path)])[0] != 0:
                raise RuntimeError(f"unchanged receipt did not verify for {generation['id']}")

            for name, (level, make) in VARIANTS.items():
                variant_text = make(original)
                variant_path = workdir / f"{generation['id']}-{name}.json"
                variant_path.write_text(variant_text, encoding="utf-8")
                code, printed = run_cli(["verify", str(variant_path)])
                variant_output = json.loads(variant_text)["record"]["output"]
                rows.append({
                    "id": generation["id"],
                    "kind": generation["kind"],
                    "variant": name,
                    "level": level,
                    "record_bytes_changed": canonical(variant_text) != canonical(original_text),
                    "verify_passed": code == 0,
                    "failure_stage": "" if code == 0 else failure_stage(printed),
                    # Only meaningful when the text itself was changed.
                    "match_after_normalising": normalise(variant_output) == normalise(original["record"]["output"]) if level == "text" else "",
                })
            print(f"{generation['id']}: " + " ".join(f"{row['variant']}={'pass' if row['verify_passed'] else 'fail'}" for row in rows[-len(VARIANTS):]), flush=True)

    with (DATA / "encoding_results.csv").open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = []
    for name, (level, _) in VARIANTS.items():
        selected = [row for row in rows if row["variant"] == name]
        changed = [row for row in selected if row["record_bytes_changed"]]
        unchanged = [row for row in selected if not row["record_bytes_changed"]]
        summary.append({
            "variant": name,
            "level": level,
            "outputs": len(selected),
            "record_changed": len(changed),
            "verified": sum(bool(row["verify_passed"]) for row in selected),
            "verified_when_record_changed": sum(bool(row["verify_passed"]) for row in changed),
            "verified_when_record_unchanged": sum(bool(row["verify_passed"]) for row in unchanged),
            "failure_stages": ";".join(sorted({row["failure_stage"] for row in selected if row["failure_stage"]})),
            "match_after_normalising": sum(row["match_after_normalising"] is True for row in changed) if level == "text" else "n/a",
        })
    with (DATA / "encoding_summary.csv").open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    for row in summary:
        print(row)
    nfc = sum(unicodedata.is_normalized("NFC", g["record"]["output"]) for g in generations)
    ascii_only = sum(g["record"]["output"].isascii() for g in generations)
    multiline = sum("\n" in g["record"]["output"] for g in generations)
    print(f"outputs already in NFC: {nfc}/{len(generations)}; ASCII only: {ascii_only}; multi-line: {multiline}")


if __name__ == "__main__":
    main()
