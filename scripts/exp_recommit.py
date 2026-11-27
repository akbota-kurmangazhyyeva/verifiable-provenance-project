#!/usr/bin/env python3
"""Copy-and-recommit: a third party commits someone else's published output.

The copier never sees the author's salt, so it cannot copy the author's
commitment. Instead it builds its own record from the published prompt and
output, with its own model label and a fresh salt, and commits that.

Two scenarios, on all three registries:
  committed_first: the author commits, then publishes; the copier recommits later.
  never_committed: the author publishes without committing; the copier commits.

Writes data/exp_recommit.csv and data/exp_recommit_meta.json. Run `forge build` first.
"""

import csv
import json
import random
from datetime import datetime, timezone

from chain import AUTHOR, CONTRACTS, COPIER, HARD_FORK, ROOT, anvil, anvil_version, commit_as, deploy, entry
from provenance.commitment import commit, model_id, verify_opening
from provenance.record import GenerationRecord

DATA = ROOT / "data"
SEED = 20261127
RUNS = 10
SCENARIOS = ["committed_first", "never_committed"]


def main() -> None:
    DATA.mkdir(exist_ok=True)
    generator = random.Random(SEED)
    rows: list[dict] = []

    with anvil():
        registries = {design: deploy(name) for design, name in CONTRACTS.items()}
        for scenario in SCENARIOS:
            for design, registry in registries.items():
                for run in range(1, RUNS + 1):
                    prompt = f"Prompt {scenario} {design} {run}"
                    output = f"Output {generator.getrandbits(64):016x}"

                    original = GenerationRecord(model="model-A", prompt=prompt, output=output, created_at="2026-11-27T10:00:00Z")
                    original_salt = generator.randbytes(32)
                    original_commitment = commit(original, original_salt)
                    if scenario == "committed_first":
                        commit_as(design, registry, AUTHOR, original_commitment, model_id(original.model))

                    # Only prompt and output are published. The copier relabels and re-salts them.
                    claimed = GenerationRecord(model="model-B", prompt=prompt, output=output, created_at="2026-11-27T12:00:00Z")
                    claimed_salt = generator.randbytes(32)
                    claimed_commitment = commit(claimed, claimed_salt)
                    commit_as(design, registry, COPIER, claimed_commitment, model_id(claimed.model))

                    author_entry = entry(design, registry, AUTHOR, original_commitment)
                    copier_entry = entry(design, registry, COPIER, claimed_commitment)
                    if author_entry and copier_entry:
                        earliest = "author" if author_entry[1] < copier_entry[1] else "copier"
                    else:
                        earliest = "author" if author_entry else "copier" if copier_entry else "none"

                    rows.append({
                        "scenario": scenario,
                        "design": design,
                        "run": run,
                        "same_prompt_and_output": original.prompt == claimed.prompt and original.output == claimed.output,
                        "commitments_differ": original_commitment != claimed_commitment,
                        "copier_commit_accepted": copier_entry is not None,
                        "copier_receipt_opens": verify_opening(claimed, claimed_salt, claimed_commitment),
                        "author_entry_exists": author_entry is not None,
                        "author_block": author_entry[1] if author_entry else "",
                        "copier_block": copier_entry[1] if copier_entry else "",
                        "earliest_entry_for_this_output": earliest,
                    })

    with (DATA / "exp_recommit.csv").open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (DATA / "exp_recommit_meta.json").write_text(json.dumps({
        "anvil_version": anvil_version(),
        "hardfork": HARD_FORK,
        "seed": SEED,
        "runs_per_scenario_and_design": RUNS,
        "scenarios": SCENARIOS,
        "date": datetime.now(timezone.utc).date().isoformat(),
    }, indent=2) + "\n")

    for scenario in SCENARIOS:
        for design in CONTRACTS:
            group = [r for r in rows if r["scenario"] == scenario and r["design"] == design]
            accepted = sum(r["copier_commit_accepted"] for r in group)
            opens = sum(r["copier_receipt_opens"] for r in group)
            earliest = sorted({r["earliest_entry_for_this_output"] for r in group})
            print(f"{scenario:16} {design:9} copier accepted {accepted}/{len(group)}, "
                  f"copier receipt opens {opens}/{len(group)}, earliest entry: {earliest}")


if __name__ == "__main__":
    main()
