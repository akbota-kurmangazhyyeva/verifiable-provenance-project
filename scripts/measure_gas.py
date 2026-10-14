#!/usr/bin/env python3
"""Measure transaction and inclusion-check gas on a local Anvil chain."""

import csv
import json
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provenance.commitment import keccak256
from provenance.merkle import MerkleTree

DATA = ROOT / "data"
RPC_URL = "http://127.0.0.1:8545"
PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SEED = 20261014
RUNS = 20
HARD_FORK = "prague"
MODEL_ID = "0x" + keccak256(b"measurement-model").hex()


def run(*arguments: str) -> str:
    return subprocess.run(arguments, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def json_run(*arguments: str) -> object:
    return json.loads(run(*arguments))


def as_number(value: object) -> int:
    if isinstance(value, str):
        return int(value, 0)
    return int(value)


def deploy(contract: str) -> str:
    created = json_run("forge", "create", "--broadcast", "--json", contract, "--rpc-url", RPC_URL, "--private-key", PRIVATE_KEY)
    return created["deployedTo"]


def send(address: str, signature: str, *arguments: str) -> int:
    receipt = json_run("cast", "send", "--json", "--rpc-url", RPC_URL, "--private-key", PRIVATE_KEY, address, signature, *arguments)
    return as_number(receipt["gasUsed"])


def estimate(address: str, signature: str, *arguments: str) -> int:
    return as_number(run("cast", "estimate", "--rpc-url", RPC_URL, address, signature, *arguments))


def full_hex(value: bytes) -> str:
    return "0x" + value.hex()


def wait_for_anvil(node: subprocess.Popen) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if node.poll() is not None:
            raise RuntimeError("anvil exited before becoming ready")
        try:
            with socket.create_connection(("127.0.0.1", 8545), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("anvil did not start within ten seconds")


def main() -> None:
    DATA.mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8545))
    node = subprocess.Popen(["anvil", "--port", "8545", "--hardfork", HARD_FORK], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_anvil(node)
        registry = deploy("src/contracts/ProvenanceRegistry.sol:ProvenanceRegistry")
        log = deploy("src/contracts/ProvenanceLog.sol:ProvenanceLog")
        generator = random.Random(SEED)
        commitment = lambda: full_hex(keccak256(generator.randbytes(32)))

        single_rows: list[dict[str, object]] = []
        for index in range(RUNS + 1):
            gas = send(registry, "commit(bytes32,bytes32)", commitment(), MODEL_ID)
            single_rows.append({"design": "registry_first" if index == 0 else "registry", "run": index, "gas_used": gas})
        for index in range(RUNS):
            gas = send(log, "commit(bytes32,bytes32)", commitment(), MODEL_ID)
            single_rows.append({"design": "log", "run": index + 1, "gas_used": gas})
        with (DATA / "gas_single.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["design", "run", "gas_used"])
            writer.writeheader()
            writer.writerows(single_rows)

        batch_rows: list[dict[str, object]] = []
        for size in (2**power for power in range(11)):
            commitments = [bytes.fromhex(commitment()[2:]) for _ in range(size)]
            tree = MerkleTree(commitments)
            root = full_hex(tree.root)
            root_gas = send(registry, "commit(bytes32,bytes32)", root, MODEL_ID)
            proof = tree.proof(0)
            proof_argument = "[" + ",".join(full_hex(item) for item in proof) + "]"
            verified = run("cast", "call", "--rpc-url", RPC_URL, registry, "verifyInclusion(bytes32,bytes32,bytes32[])", root, full_hex(commitments[0]), proof_argument)
            if int(verified, 16) != 1:
                raise RuntimeError(f"inclusion check failed for batch size {size}")
            verification_gas = estimate(registry, "verifyInclusion(bytes32,bytes32,bytes32[])", root, full_hex(commitments[0]), proof_argument)
            batch_rows.append({"batch_size": size, "root_gas_used": root_gas, "gas_per_record": root_gas / size, "verification_gas": verification_gas, "proof_length": len(proof)})
        with (DATA / "gas_batch.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["batch_size", "root_gas_used", "gas_per_record", "verification_gas", "proof_length"])
            writer.writeheader()
            writer.writerows(batch_rows)

        (ROOT / "gas_meta.json").write_text(json.dumps({
            "forge_version": run("forge", "--version"),
            "anvil_version": run("anvil", "--version"),
            "hardfork": HARD_FORK,
            "seed": SEED,
            "date": datetime.now(timezone.utc).date().isoformat(),
        }, indent=2) + "\n")
    finally:
        node.terminate()
        node.wait(timeout=5)


if __name__ == "__main__":
    main()
