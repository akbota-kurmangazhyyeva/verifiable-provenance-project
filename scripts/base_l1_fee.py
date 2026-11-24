#!/usr/bin/env python3
"""Measure the L1 data fee that Base charged for transactions shaped like ours.

On Base, as on other OP Stack rollups, a transaction pays its L2 execution fee
plus an L1 data fee for posting its data to Ethereum; the receipt reports the
latter as `l1Fee`. The data fee depends on the transaction's (compressed)
size, so we sample real Base transactions whose calldata is exactly as long
as a registry commit: 68 bytes (4-byte selector + two 32-byte words).

From blocks evenly spaced over the period of data/prices.json, the first such
transaction per block is taken. Writes data/base_l1_fee.json with every
sampled transaction hash (checkable on basescan.org), the fee statistics in
wei and in US dollars at the ETH price in data/prices.json.
"""

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_prices import Rpc

DATA = ROOT / "data"
CALLDATA_BYTES = 68  # commit(bytes32,bytes32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rpc", default="https://mainnet.base.org")
    parser.add_argument("--blocks", type=int, default=200, help="number of evenly spaced blocks to look at")
    args = parser.parse_args()

    summary = json.loads((DATA / "fee_summary.json").read_text())["chains"]["base"]
    eth_usd = json.loads((DATA / "prices.json").read_text())["eth_usd"]["value"]
    first, last = summary["first_block"], summary["last_block"]
    rpc = Rpc(args.rpc)
    samples = []
    for index in range(args.blocks):
        number = first + index * (last - first) // args.blocks
        block = rpc("eth_getBlockByNumber", [hex(number), True])
        for transaction in block["transactions"]:
            if transaction.get("to") and len(transaction["input"]) == 2 + 2 * CALLDATA_BYTES:
                receipt = rpc("eth_getTransactionReceipt", [transaction["hash"]])
                if "l1Fee" in receipt:
                    samples.append({
                        "block": number,
                        "tx_hash": transaction["hash"],
                        "l1_fee_wei": int(receipt["l1Fee"], 16),
                        "execution_fee_wei": int(receipt["gasUsed"], 16) * int(receipt["effectiveGasPrice"], 16),
                    })
                break
        print(f"\r{index + 1}/{args.blocks} blocks, {len(samples)} samples", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    fees = sorted(sample["l1_fee_wei"] for sample in samples)
    result = {
        "description": f"L1 data fee (receipt field l1Fee) of Base transactions with {CALLDATA_BYTES}-byte calldata, like a registry commit",
        "rpc": args.rpc,
        "blocks": f"{args.blocks} evenly spaced in {first}-{last}",
        "retrieved": datetime.now(timezone.utc).date().isoformat(),
        "samples": len(samples),
        "l1_fee_wei": {"median": statistics.median(fees), "p95": fees[int(0.95 * (len(fees) - 1))], "min": fees[0], "max": fees[-1]},
        "eth_usd": eth_usd,
        "l1_fee_usd_median": statistics.median(fees) / 1e18 * eth_usd,
        "transactions": samples,
    }
    (DATA / "base_l1_fee.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "transactions"}, indent=2))


if __name__ == "__main__":
    main()
