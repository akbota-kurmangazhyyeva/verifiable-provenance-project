#!/usr/bin/env python3
"""Gas cost of the two front-running fixes against the original registry.

For each registry (original, keyed, signed): RUNS commits of fresh commitments
from the same account, and the gas of verifyInclusion for a 64-record batch.
Writes data/gas_fixes.csv (every commit), data/gas_fixes_summary.csv and
data/gas_fixes_meta.json. Run `forge build` first.
"""

import csv
import json
import random
import statistics
from datetime import datetime, timezone

from chain import AUTHOR, CONTRACTS, HARD_FORK, ROOT, anvil, anvil_version, commit_as, deploy, estimate, inclusion_calldata, rpc
from provenance.commitment import model_id
from provenance.merkle import MerkleTree

DATA = ROOT / "data"
SEED = 20261127
RUNS = 20
BATCH = 64
MODEL = model_id("example/model")


def calldata_bytes(receipt: dict) -> int:
    tx = rpc("eth_getTransactionByHash", [receipt["transactionHash"]])
    return (len(tx["input"]) - 2) // 2


def main() -> None:
    DATA.mkdir(exist_ok=True)
    generator = random.Random(SEED)
    rows: list[dict] = []
    summary: list[dict] = []

    with anvil():
        for design, name in CONTRACTS.items():
            registry = deploy(name)
            gas = []
            size = 0
            for run in range(1, RUNS + 1):
                receipt = commit_as(design, registry, AUTHOR, generator.randbytes(32), MODEL)
                gas.append(int(receipt["gasUsed"], 16))
                size = calldata_bytes(receipt)
                rows.append({"design": design, "run": run, "gas_used": gas[-1], "calldata_bytes": size})

            commitments = [generator.randbytes(32) for _ in range(BATCH)]
            tree = MerkleTree(commitments)
            commit_as(design, registry, AUTHOR, tree.root, MODEL)
            verify_gas = estimate(registry, inclusion_calldata(design, AUTHOR, tree.root, commitments[0], tree.proof(0)))

            summary.append({
                "design": design,
                "first_commit_gas": gas[0],
                "mean_commit_gas_runs_2_on": round(statistics.mean(gas[1:]), 1),
                "min_commit_gas": min(gas[1:]),
                "max_commit_gas": max(gas[1:]),
                "calldata_bytes": size,
                f"verify_inclusion_gas_n{BATCH}": verify_gas,
            })

    base = summary[0]["mean_commit_gas_runs_2_on"]
    for row in summary:
        extra = row["mean_commit_gas_runs_2_on"] - base
        row["extra_gas_vs_original"] = round(extra, 1)
        row["extra_percent_vs_original"] = round(100 * extra / base, 2)

    with (DATA / "gas_fixes.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (DATA / "gas_fixes_summary.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (DATA / "gas_fixes_meta.json").write_text(json.dumps({
        "anvil_version": anvil_version(),
        "hardfork": HARD_FORK,
        "seed": SEED,
        "runs_per_design": RUNS,
        "batch_size_for_inclusion_check": BATCH,
        "note": "run 1 is reported separately: it changes the count slot from zero",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }, indent=2) + "\n")

    for row in summary:
        print(f"{row['design']:9} commit {row['mean_commit_gas_runs_2_on']:>9,.1f} gas "
              f"({row['extra_percent_vs_original']:+.2f}% vs original), calldata {row['calldata_bytes']} B, "
              f"verify n={BATCH}: {row[f'verify_inclusion_gas_n{BATCH}']:,} gas")


if __name__ == "__main__":
    main()
