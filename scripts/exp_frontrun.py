#!/usr/bin/env python3
"""Experiment 2: copy a pending commitment from the mempool and get it mined first.

Runs the same attack against ProvenanceRegistry and KeyedProvenanceRegistry on a
local Anvil node with automatic mining off, so transactions wait in the pool until
we mine a block. Writes data/exp_frontrun.csv and data/exp_frontrun_meta.json.

Run `forge build` first (the script deploys the compiled contracts from out/).
"""

import csv
import json
import random
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provenance.commitment import commit, keccak256, model_id, verify_opening
from provenance.record import GenerationRecord

DATA = ROOT / "data"
PORT = 8545
RPC_URL = f"http://127.0.0.1:{PORT}"
HARD_FORK = "prague"
SEED = 20261120
RUNS = 10
GWEI = 10**9
# Fee cap = BASE_CAP + tip. Anvil's default "fees" ordering compares the fee cap
# (maxFeePerGas), so a sender who only raises the tip but keeps the same cap is
# NOT moved ahead (equal caps are mined in arrival order). Raising both, as a real
# front-runner would, puts the higher bidder first.
BASE_CAP = 100 * GWEI

# Anvil's first two default accounts (unlocked, so eth_sendTransaction needs no signing)
AUTHOR = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
COPIER = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"

# (scenario, author priority fee, copier priority fee) in gwei.
# "attack": the copier outbids the author, as a front-runner would.
# "control": the copier pays less, to check that the fee decides the order.
SCENARIOS = [("attack", 1, 2), ("control", 2, 1)]

CONTRACTS = {
    "original": "ProvenanceRegistry",
    "keyed": "KeyedProvenanceRegistry",
}


def rpc(method: str, params: list) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(RPC_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        reply = json.load(response)
    if "error" in reply:
        raise RuntimeError(f"{method} failed: {reply['error']}")
    return reply["result"]


def selector(signature: str) -> bytes:
    return keccak256(signature.encode())[:4]


def word(value: bytes | str) -> bytes:
    """One 32-byte ABI word: a bytes32 as is, an address left-padded with zeros."""
    if isinstance(value, str):
        return bytes(12) + bytes.fromhex(value.removeprefix("0x"))
    return value


def calldata(signature: str, *arguments: bytes | str) -> str:
    return "0x" + (selector(signature) + b"".join(word(a) for a in arguments)).hex()


def send(sender: str, to: str | None, data: str, priority_gwei: int) -> str:
    transaction = {
        "from": sender,
        "data": data,
        "gas": hex(3_000_000),
        "maxFeePerGas": hex(BASE_CAP + priority_gwei * GWEI),
        "maxPriorityFeePerGas": hex(priority_gwei * GWEI),
    }
    if to is not None:
        transaction["to"] = to
    return rpc("eth_sendTransaction", [transaction])


def call(to: str, data: str) -> bytes:
    return bytes.fromhex(rpc("eth_call", [{"to": to, "data": data}, "latest"])[2:])


def deploy(name: str) -> str:
    artifact = json.loads((ROOT / "out" / f"{name}.sol" / f"{name}.json").read_text())
    tx = send(AUTHOR, None, artifact["bytecode"]["object"], 1)
    rpc("evm_mine", [])
    return rpc("eth_getTransactionReceipt", [tx])["contractAddress"]


def submitter_of(design: str, registry: str, who: str, commitment: bytes) -> str | None:
    """The submitter stored for this commitment, or None if there is no entry."""
    if design == "original":
        raw = call(registry, calldata("getRecord(bytes32)", commitment))
    else:
        raw = call(registry, calldata("getRecord(address,bytes32)", who, commitment))
    address = "0x" + raw[12:32].hex()
    return None if int(address, 16) == 0 else address


def name_of(address: str | None) -> str:
    return {AUTHOR: "author", COPIER: "copier", None: "none"}[address]


def wait_for_anvil(node: subprocess.Popen) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if node.poll() is not None:
            raise RuntimeError("anvil exited before becoming ready")
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("anvil did not start within ten seconds")


def one_run(design: str, registry: str, record: GenerationRecord, salt: bytes, author_fee: int, copier_fee: int) -> dict:
    commitment = commit(record, salt)
    data = calldata("commit(bytes32,bytes32)", commitment, model_id(record.model))

    # 1. The author sends the commitment. It waits in the pool, not yet mined.
    author_tx = send(AUTHOR, registry, data, author_fee)

    # 2. The copier reads the pending pool, finds the author's transaction and
    #    resends its calldata unchanged from its own account with its own fee.
    pool = rpc("txpool_content", [])["pending"]
    pending = next(iter(pool[next(k for k in pool if k.lower() == AUTHOR)].values()))
    copied = pending["input"]
    copier_tx = send(COPIER, registry, copied, copier_fee)

    # 3. One block is mined. Anvil orders pending transactions by fee.
    rpc("evm_mine", [])
    author_receipt = rpc("eth_getTransactionReceipt", [author_tx])
    copier_receipt = rpc("eth_getTransactionReceipt", [copier_tx])
    assert author_receipt["blockNumber"] == copier_receipt["blockNumber"], "not mined in one block"

    copier_index = int(copier_receipt["transactionIndex"], 16)
    author_index = int(author_receipt["transactionIndex"], 16)

    # 4. What the chain says now, and what the author's receipt proves against it.
    if design == "original":
        recorded = name_of(submitter_of(design, registry, AUTHOR, commitment))
        entries = recorded
        author_entry = recorded
    else:
        names = [n for who, n in ((COPIER, "copier"), (AUTHOR, "author")) if submitter_of(design, registry, who, commitment)]
        entries = "+".join(names) or "none"
        author_entry = name_of(submitter_of(design, registry, AUTHOR, commitment))

    return {
        "design": design,
        "copied_calldata_identical": copied.lower() == data.lower(),
        "author_priority_gwei": author_fee,
        "copier_priority_gwei": copier_fee,
        "mined_first": "copier" if copier_index < author_index else "author",
        "author_tx": "success" if author_receipt["status"] == "0x1" else "reverted",
        "copier_tx": "success" if copier_receipt["status"] == "0x1" else "reverted",
        "entries_for_commitment": entries,
        "author_receipt_opens": verify_opening(record, salt, commitment),
        "entry_names_on_author_lookup": author_entry,
        "author_gas": int(author_receipt["gasUsed"], 16),
        "copier_gas": int(copier_receipt["gasUsed"], 16),
    }


def main() -> None:
    DATA.mkdir(exist_ok=True)
    with socket.socket() as probe:
        # SO_REUSEADDR: closed connections from a previous run may still hold the
        # port for a minute; that is fine, only a live listener should stop us.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", PORT))  # fails early if something already uses the port
    node = subprocess.Popen(
        ["anvil", "--port", str(PORT), "--hardfork", HARD_FORK, "--no-mining"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_anvil(node)
        registries = {design: deploy(name) for design, name in CONTRACTS.items()}
        generator = random.Random(SEED)

        rows: list[dict] = []
        for scenario, author_fee, copier_fee in SCENARIOS:
            for design, registry in registries.items():
                for run in range(1, RUNS + 1):
                    record = GenerationRecord(
                        model="example/model",
                        prompt=f"Prompt {scenario} {design} {run}",
                        output=f"Output {generator.getrandbits(64):016x}",
                        created_at="2026-11-20T00:00:00Z",
                    )
                    salt = generator.randbytes(32)
                    row = one_run(design, registry, record, salt, author_fee, copier_fee)
                    rows.append({"scenario": scenario, "run": run, **row})

        with (DATA / "exp_frontrun.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        (DATA / "exp_frontrun_meta.json").write_text(json.dumps({
            "anvil_version": subprocess.run(["anvil", "--version"], capture_output=True, text=True).stdout.strip(),
            "hardfork": HARD_FORK,
            "mining": "--no-mining, one evm_mine per run",
            "seed": SEED,
            "runs_per_scenario_and_design": RUNS,
            "scenarios": [{"name": s, "author_priority_gwei": a, "copier_priority_gwei": c} for s, a, c in SCENARIOS],
            "date": datetime.now(timezone.utc).date().isoformat(),
        }, indent=2) + "\n")
    finally:
        node.terminate()
        node.wait(timeout=5)

    summary: dict[tuple, list] = {}
    for row in rows:
        summary.setdefault((row["scenario"], row["design"]), []).append(row)
    for (scenario, design), group in summary.items():
        first = sorted({r["mined_first"] for r in group})
        author = sorted({r["author_tx"] for r in group})
        entry = sorted({r["entry_names_on_author_lookup"] for r in group})
        print(f"{scenario:8} {design:9} mined first: {first}  author tx: {author}  author lookup names: {entry}")


if __name__ == "__main__":
    main()
