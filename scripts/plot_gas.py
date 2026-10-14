#!/usr/bin/env python3
"""Plot gas measurements written by measure_gas.py."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLOURS = {"registry": "#2a78d6", "log": "#eb6834", "batch": "#1baf7a"}


def main() -> None:
    single = pd.read_csv(ROOT / "data/gas_single.csv")
    batch = pd.read_csv(ROOT / "data/gas_batch.csv")
    registry = single.loc[single.design == "registry", "gas_used"].mean()
    log = single.loc[single.design == "log", "gas_used"].mean()

    figure, (per_record, verification) = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)
    per_record.plot(batch.batch_size, batch.gas_per_record, color=COLOURS["batch"], linestyle="-", marker="o")
    per_record.axhline(registry, color=COLOURS["registry"], linestyle="--")
    per_record.axhline(log, color=COLOURS["log"], linestyle=":")
    per_record.set(xscale="log", yscale="log", xlabel="Batch size", ylabel="Gas per record")
    per_record.text(batch.batch_size.iloc[-1], batch.gas_per_record.iloc[-1], "Merkle root", color=COLOURS["batch"], ha="right", va="bottom")
    per_record.text(batch.batch_size.iloc[0], registry, "Registry", color=COLOURS["registry"], va="bottom")
    per_record.text(batch.batch_size.iloc[0], log, "Log", color=COLOURS["log"], va="bottom")

    verification.plot(batch.batch_size, batch.verification_gas, color=COLOURS["batch"], linestyle="-.", marker="s")
    verification.set(xscale="log", xlabel="Batch size", ylabel="Verification gas")
    verification.text(batch.batch_size.iloc[-1], batch.verification_gas.iloc[-1], "verifyInclusion", color=COLOURS["batch"], ha="right", va="bottom")
    for axis in (per_record, verification):
        axis.grid(True, which="both", alpha=0.25)
    (ROOT / "figures").mkdir(exist_ok=True)
    figure.savefig(ROOT / "figures/gas_per_record.pdf", bbox_inches="tight")


if __name__ == "__main__":
    main()
