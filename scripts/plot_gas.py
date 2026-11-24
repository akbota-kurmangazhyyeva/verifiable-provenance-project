#!/usr/bin/env python3
"""Plot gas measurements written by measure_gas.py."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLOURS = {"registry": "#2a78d6", "log": "#eb6834", "batch": "#1baf7a"}

# Sized for the full text width of an IEEE two-column page (7.16 in), so the
# figure is not scaled down and 8 pt text stays 8 pt. TrueType (Type 42) fonts
# are embedded because IEEE PDF checks reject matplotlib's default Type 3.
plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42, "ps.fonttype": 42})


def main() -> None:
    single = pd.read_csv(ROOT / "data/gas_single.csv")
    batch = pd.read_csv(ROOT / "data/gas_batch.csv")
    registry = single.loc[single.design == "registry", "gas_used"].mean()
    log = single.loc[single.design == "log", "gas_used"].mean()

    figure, (per_record, verification) = plt.subplots(1, 2, figsize=(7.0, 2.6), constrained_layout=True)
    per_record.plot(batch.batch_size, batch.gas_per_record, color=COLOURS["batch"], linestyle="-", marker="o", markersize=4)
    per_record.axhline(registry, color=COLOURS["registry"], linestyle="--")
    per_record.axhline(log, color=COLOURS["log"], linestyle=":")
    per_record.set(yscale="log", ylabel="Gas per record", ylim=(40, 4e5))
    # Labels sit at the right-hand end of each line, away from the data points.
    right = batch.batch_size.iloc[-1]
    per_record.text(right, registry * 1.15, "Registry, one tx per record", color=COLOURS["registry"], ha="right", va="bottom")
    per_record.text(right, log * 1.15, "Log, one tx per record", color=COLOURS["log"], ha="right", va="bottom")
    per_record.annotate("Merkle root, one tx per batch", (batch.batch_size.iloc[3], batch.gas_per_record.iloc[3]), xytext=(10, 2), textcoords="offset points", color=COLOURS["batch"])

    verification.plot(batch.batch_size, batch.verification_gas, color=COLOURS["batch"], linestyle="-.", marker="s", markersize=4)
    verification.set(ylabel="Gas of one inclusion check")
    verification.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    verification.text(batch.batch_size.iloc[0], batch.verification_gas.iloc[-1], "verifyInclusion (paid per check)", color=COLOURS["batch"], ha="left", va="top")
    for axis in (per_record, verification):
        # Batch sizes are powers of two, so label them as such.
        axis.set_xscale("log", base=2)
        axis.set_xticks([4**power for power in range(6)], [str(4**power) for power in range(6)])
        axis.set_xlabel("Batch size $n$")
        axis.grid(True, which="major", alpha=0.25)
    (ROOT / "figures").mkdir(exist_ok=True)
    figure.savefig(ROOT / "figures/gas_per_record.pdf", bbox_inches="tight")


if __name__ == "__main__":
    main()
