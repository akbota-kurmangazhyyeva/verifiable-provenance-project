#!/usr/bin/env python3
"""Deploy the contracts to Sepolia and repeat the gas measurements there.

Sends the same transactions as measure_gas.py: the same commitments, drawn
from the same seeded generator, so every Sepolia transaction has the same
calldata as its Anvil counterpart in data/gas_single.csv and
data/gas_batch.csv, and the two can be compared row by row.

Needs a funded Sepolia account. Put its key and an RPC URL in a .env file in
the repository root (never commit it; .env is in .gitignore):

    SEPOLIA_RPC_URL=https://...
    SEPOLIA_PRIVATE_KEY=0x...

Use a fresh account that holds only test ether: its address and every
transaction hash end up in data/ and in the paper.

Writes:
  data/sepolia_txs.csv      every transaction: hash, block, gas used, price
  data/sepolia_batch.csv    Merkle-root transactions and inclusion-check gas
  data/sepolia_meta.json    addresses, deployment transactions, versions, totals
  tables/sepolia.tex        Anvil vs Sepolia table for the paper

With the defaults this sends 54 transactions. Since the Glamsterdam upgrade
reached Sepolia (6 Oct 2026), new storage and contract code cost much more
gas there than on mainnet or Anvil (Prague): expect about 12 million gas in
total, against about 3.5 million under Prague rules. The script prints the
current gas price and the expected cost and asks before sending anything.
"""

import argparse
import csv
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provenance.commitment import keccak256
from provenance.merkle import MerkleTree

DATA = ROOT / "data"
TABLES = ROOT / "tables"
SEPOLIA_CHAIN_ID = 11155111
EXPLORER = "https://sepolia.etherscan.io/tx/"
# Must match measure_gas.py so the commitments, and so the calldata, are identical.
SEED = 20261014
RUNS = 20
BATCH_SIZES = [2**power for power in range(11)]
MODEL_ID = "0x" + keccak256(b"measurement-model").hex()
EXPECTED_GAS = 12_000_000  # rough total on Sepolia after Glamsterdam, used only for the cost estimate


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def run(*arguments: str) -> str:
    completed = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        # Do not echo the command: it contains the private key.
        raise RuntimeError(f"{arguments[0]} {arguments[1]} failed: {completed.stderr.strip()[:500]}")
    return completed.stdout.strip()


def as_number(value: object) -> int:
    return int(value, 0) if isinstance(value, str) else int(value)


def full_hex(value: bytes) -> str:
    return "0x" + value.hex()


def measurement_commitments() -> tuple[list[str], list[str], dict[int, list[bytes]]]:
    """The commitments measure_gas.py sends, in the same order."""
    generator = random.Random(SEED)
    commitment = lambda: full_hex(keccak256(generator.randbytes(32)))
    registry = [commitment() for _ in range(RUNS + 1)]
    log = [commitment() for _ in range(RUNS)]
    batches = {size: [bytes.fromhex(commitment()[2:]) for _ in range(size)] for size in BATCH_SIZES}
    return registry, log, batches


class Chain:
    def __init__(self, rpc_url: str, private_key: str):
        self.rpc_url = rpc_url
        self.private_key = private_key

    def deploy(self, contract: str) -> dict:
        created = json.loads(run("forge", "create", "--broadcast", "--json", contract, "--rpc-url", self.rpc_url, "--private-key", self.private_key, "--timeout", "600"))
        receipt = json.loads(run("cast", "receipt", "--json", created["transactionHash"], "--rpc-url", self.rpc_url))
        return {"address": created["deployedTo"], "tx_hash": created["transactionHash"], "gas_used": as_number(receipt["gasUsed"]), "block_number": as_number(receipt["blockNumber"])}

    def send(self, address: str, signature: str, *arguments: str) -> dict:
        receipt = json.loads(run("cast", "send", "--json", "--timeout", "600", "--rpc-url", self.rpc_url, "--private-key", self.private_key, address, signature, *arguments))
        if as_number(receipt["status"]) != 1:
            raise RuntimeError(f"transaction {receipt['transactionHash']} reverted")
        return {
            "tx_hash": receipt["transactionHash"],
            "block_number": as_number(receipt["blockNumber"]),
            "gas_used": as_number(receipt["gasUsed"]),
            "effective_gas_price_wei": as_number(receipt["effectiveGasPrice"]),
        }

    def call(self, address: str, signature: str, *arguments: str) -> str:
        return run("cast", "call", "--rpc-url", self.rpc_url, address, signature, *arguments)

    def estimate(self, address: str, signature: str, *arguments: str) -> int:
        return as_number(run("cast", "estimate", "--rpc-url", self.rpc_url, address, signature, *arguments))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def latex_int(value: float) -> str:
    return f"{round(value):,}".replace(",", "{,}")


def latex_table(single: list[dict], batch: list[dict]) -> str:
    def mean(rows: list[dict], key: str) -> float:
        return sum(row[key] for row in rows) / len(rows)

    def line(label: str, anvil: float, sepolia: float) -> str:
        return f"{label} & {latex_int(anvil)} & {latex_int(sepolia)} & {sepolia / anvil:.2f} \\\\"

    lines = [
        "% Generated by scripts/sepolia_run.py from data/sepolia_*.csv and data/gas_*.csv. Do not edit by hand.",
        "\\begin{tabular}{lrrr}",
        "\\toprule",
        "Transaction & Anvil & Sepolia & Ratio \\\\",
        "\\midrule",
    ]
    for design, label in (("registry_first", "Registry, first ever"), ("registry", "Registry"), ("log", "Event-only log")):
        rows = [row for row in single if row["design"] == design]
        lines.append(line(label, mean(rows, "anvil_gas_used"), mean(rows, "gas_used")))
    for row in batch:
        if row["batch_size"] in (1, 1024):
            lines.append(line(f"Root, $n={row['batch_size']}$", row["anvil_gas_used"], row["gas_used"]))
    last = batch[-1]
    lines.append(line(f"Check, $n={last['batch_size']}$", last["anvil_verification_gas"], last["verification_gas"]))
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rpc-url", help="default: $SEPOLIA_RPC_URL")
    parser.add_argument("--private-key-env", default="SEPOLIA_PRIVATE_KEY", help="name of the environment variable holding the key")
    parser.add_argument("--chain-id", type=int, default=SEPOLIA_CHAIN_ID, help="refuse to run on any other chain")
    parser.add_argument("--out-dir", type=Path, default=DATA, help="where to write the CSV and JSON files")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    rpc_url = args.rpc_url or os.environ.get("SEPOLIA_RPC_URL")
    private_key = os.environ.get(args.private_key_env)
    if not rpc_url or not private_key:
        sys.exit("Set SEPOLIA_RPC_URL and SEPOLIA_PRIVATE_KEY in .env (see the docstring).")
    chain = Chain(rpc_url, private_key)

    chain_id = as_number(run("cast", "chain-id", "--rpc-url", rpc_url))
    if chain_id != args.chain_id:
        sys.exit(f"Connected to chain {chain_id}, expected {args.chain_id}. Nothing was sent.")
    sender = run("cast", "wallet", "address", "--private-key", private_key)
    balance = as_number(run("cast", "balance", sender, "--rpc-url", rpc_url))
    gas_price = as_number(run("cast", "gas-price", "--rpc-url", rpc_url))
    estimate = EXPECTED_GAS * gas_price
    print(f"chain {chain_id}, sender {sender}")
    print(f"balance {balance / 1e18:.6f} ETH, gas price {gas_price / 1e9:.3f} gwei, expected cost about {estimate / 1e18:.6f} ETH")
    if balance < 2 * estimate:
        print("Warning: balance is less than twice the expected cost; the run may stop part way.")
    if not args.yes and input("Send the transactions? [y/N] ").strip().lower() != "y":
        sys.exit("Nothing was sent.")

    anvil_single = list(csv.DictReader((DATA / "gas_single.csv").open()))
    anvil_batch = {int(row["batch_size"]): row for row in csv.DictReader((DATA / "gas_batch.csv").open())}
    registry_commitments, log_commitments, batches = measurement_commitments()
    started = datetime.now(timezone.utc)

    registry = chain.deploy("src/contracts/ProvenanceRegistry.sol:ProvenanceRegistry")
    print(f"ProvenanceRegistry {registry['address']}  {EXPLORER}{registry['tx_hash']}")
    log = chain.deploy("src/contracts/ProvenanceLog.sol:ProvenanceLog")
    print(f"ProvenanceLog      {log['address']}  {EXPLORER}{log['tx_hash']}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    single: list[dict[str, object]] = []
    jobs = [("registry_first" if index == 0 else "registry", index, registry["address"], commitment) for index, commitment in enumerate(registry_commitments)]
    jobs += [("log", index + 1, log["address"], commitment) for index, commitment in enumerate(log_commitments)]
    for design, index, address, commitment in jobs:
        anvil_row = next(row for row in anvil_single if row["design"] == design and int(row["run"]) == index)
        sent = chain.send(address, "commit(bytes32,bytes32)", commitment, MODEL_ID)
        single.append({"design": design, "run": index, "commitment": commitment, **sent, "anvil_gas_used": int(anvil_row["gas_used"])})
        print(f"{design:>14} {index:>2}: {sent['gas_used']:>6} gas (Anvil {anvil_row['gas_used']})  {EXPLORER}{sent['tx_hash']}", flush=True)
        write_csv(args.out_dir / "sepolia_txs.csv", single)  # keep what we have if a later send fails

    batch: list[dict[str, object]] = []
    for size, commitments in batches.items():
        tree = MerkleTree(commitments)
        root = full_hex(tree.root)
        sent = chain.send(registry["address"], "commit(bytes32,bytes32)", root, MODEL_ID)
        proof = "[" + ",".join(full_hex(item) for item in tree.proof(0)) + "]"
        if int(chain.call(registry["address"], "verifyInclusion(bytes32,bytes32,bytes32[])", root, full_hex(commitments[0]), proof), 16) != 1:
            raise RuntimeError(f"inclusion check failed for batch size {size}")
        verification = chain.estimate(registry["address"], "verifyInclusion(bytes32,bytes32,bytes32[])", root, full_hex(commitments[0]), proof)
        batch.append({
            "batch_size": size, "root": root, **sent, "verification_gas": verification,
            "anvil_gas_used": int(anvil_batch[size]["root_gas_used"]), "anvil_verification_gas": int(anvil_batch[size]["verification_gas"]),
        })
        print(f"root n={size:>4}: {sent['gas_used']} gas (Anvil {anvil_batch[size]['root_gas_used']}), check {verification} (Anvil {anvil_batch[size]['verification_gas']})", flush=True)
        write_csv(args.out_dir / "sepolia_batch.csv", batch)

    spent = sum(row["gas_used"] * row["effective_gas_price_wei"] for row in single + batch)
    (args.out_dir / "sepolia_meta.json").write_text(json.dumps({
        "chain_id": chain_id,
        "sender": sender,
        "registry": registry,
        "log": log,
        "explorer": EXPLORER,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "transactions": 2 + len(single) + len(batch),
        "fees_paid_eth_excluding_deployments": spent / 1e18,
        "forge_version": run("forge", "--version").splitlines()[0],
        "git_commit": run("git", "rev-parse", "HEAD"),
        "seed": SEED,
    }, indent=2) + "\n")
    TABLES.mkdir(exist_ok=True)
    table_path = TABLES / "sepolia.tex" if args.out_dir == DATA else args.out_dir / "sepolia.tex"
    table_path.write_text(latex_table(single, batch), encoding="utf-8")

    differences = [row["gas_used"] - row["anvil_gas_used"] for row in single + batch]
    print(f"\n{len(differences)} commit transactions; gas differs from Anvil in {sum(d != 0 for d in differences)} "
          f"(min {min(differences):+}, max {max(differences):+}). Inclusion-check differences: "
          f"{sorted({row['verification_gas'] - row['anvil_verification_gas'] for row in batch})}")


if __name__ == "__main__":
    main()
