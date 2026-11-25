#!/usr/bin/env python3
"""Experiment 1: a false model label verifies just as well as the true one.

For every output in data/exp1_generations.jsonl (written by exp1_generate.py)
we commit three records that differ only in the model field:

  true      the model that actually produced the text
  other     a different, real model that did not produce it
  fake      a model id that does not exist

Each record gets its own salt and its own transaction on a fresh local Anvil
chain, through the same `provenance.cli commit` and `verify` commands a user
would run. We then check that every receipt verifies and that the registry's
modelId is whatever label was submitted. As a negative control, each true
receipt is also verified once more with one character of the output changed,
which must fail.

Writes data/exp1_results.csv and data/exp1_summary.json.
"""

import csv
import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_chain import ANVIL_KEY, anvil, call, deploy
from provenance import cli
from provenance.commitment import model_id

DATA = ROOT / "data"
LABELS = {
    "other": "meta-llama/Llama-3.1-8B-Instruct",
    "fake": "example/model-that-does-not-exist",
}


def run_cli(arguments: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(arguments)
    return code, out.getvalue() + err.getvalue()


def commit(record: dict, label: str, registry: str, rpc_url: str, workdir: Path, name: str) -> Path:
    prompt, output, receipt = workdir / f"{name}.prompt", workdir / f"{name}.output", workdir / f"{name}.json"
    prompt.write_bytes(record["prompt"].encode("utf-8"))
    output.write_bytes(record["output"].encode("utf-8"))
    code, printed = run_cli([
        "commit", str(prompt), str(output), label, "--registry", registry, "--receipt", str(receipt),
        "--rpc-url", rpc_url, "--private-key", ANVIL_KEY,
        "--params", json.dumps(record["params"]), "--created-at", record["created_at"],
    ])
    if code != 0:
        raise RuntimeError(f"commit failed for {name}: {printed}")
    return receipt


def main() -> None:
    generations = [json.loads(line) for line in (DATA / "exp1_generations.jsonl").read_text(encoding="utf-8").splitlines()]
    rows: list[dict[str, object]] = []
    with anvil() as rpc_url, tempfile.TemporaryDirectory() as temporary:
        workdir = Path(temporary)
        registry = deploy("src/contracts/ProvenanceRegistry.sol:ProvenanceRegistry", rpc_url)
        for generation in generations:
            record = generation["record"]
            labels = {"true": record["model"], **LABELS}
            for kind, label in labels.items():
                receipt_path = commit(record, label, registry, rpc_url, workdir, f"{generation['id']}-{kind}")
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                code, printed = run_cli(["verify", str(receipt_path)])
                stored = call(registry, "getRecord(bytes32)", receipt["commitment"], rpc_url=rpc_url).removeprefix("0x")
                rows.append({
                    "id": generation["id"],
                    "label_kind": kind,
                    "model_label": label,
                    "commitment": receipt["commitment"],
                    "tx_hash": receipt["tx_hash"],
                    "verify_passed": code == 0,
                    "label_printed_as_claim": f"not checked: model {label!r}" in printed,
                    "onchain_model_id_is_label": stored[192:256] == model_id(label).hex(),
                    "tampered_verify_passed": "",
                })
                if kind == "true":
                    # Negative control: change the first character of the output.
                    output = receipt["record"]["output"]
                    receipt["record"]["output"] = ("X" if output[:1] != "X" else "Y") + output[1:]
                    tampered = workdir / f"{generation['id']}-tampered.json"
                    tampered.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
                    rows[-1]["tampered_verify_passed"] = run_cli(["verify", str(tampered)])[0] == 0
            print(f"{generation['id']}: " + ", ".join(f"{row['label_kind']}={'pass' if row['verify_passed'] else 'FAIL'}" for row in rows[-3:]), flush=True)

    with (DATA / "exp1_results.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary: dict[str, object] = {"outputs": len(generations), "registry_transactions": len(rows)}
    for kind in ("true", "other", "fake"):
        selected = [row for row in rows if row["label_kind"] == kind]
        summary[kind] = {
            "label": selected[0]["model_label"],
            "committed": len(selected),
            "verified": sum(bool(row["verify_passed"]) for row in selected),
            "label_printed_as_claim": sum(bool(row["label_printed_as_claim"]) for row in selected),
            "onchain_model_id_is_label": sum(bool(row["onchain_model_id_is_label"]) for row in selected),
        }
    true_rows = [row for row in rows if row["label_kind"] == "true"]
    summary["tampered_control"] = {"checked": len(true_rows), "verified": sum(row["tampered_verify_passed"] is True for row in true_rows)}
    (DATA / "exp1_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
