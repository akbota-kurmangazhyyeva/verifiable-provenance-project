#!/usr/bin/env python3
"""Derive the gas prices and the ETH price used for the dollar-cost table.

Gas prices are read from block data, not from a gas-tracker website, so anyone
can recompute them: for every sampled block we take the base fee plus the
median priority fee paid in that block (eth_feeHistory, 50th reward
percentile). This is the price per gas that a transaction paying a typical tip
would have paid in that block.

- Ethereum mainnet: every block in the period is used.
- Base: blocks are far more frequent, so `--base-windows-per-day` evenly
  spaced windows of 100 consecutive blocks are sampled per day.

The ETH price is the mean of CoinGecko's hourly prices on `--eth-date` (UTC).

Writes data/fee_daily.csv (per-day statistics) and data/fee_summary.json
(period statistics). The scenarios used in the paper are chosen from these in
data/prices.json, which scripts/usd_costs.py reads.

Uses only public endpoints, no API keys. Override them with --mainnet-rpc and
--base-rpc if they rate-limit you.
"""

import argparse
import csv
import http.client
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
USER_AGENT = "verifiable-provenance-fee-sampler"
COINGECKO_RANGE = "https://api.coingecko.com/api/v3/coins/ethereum/market_chart/range?vs_currency=usd&from={start}&to={end}"


class Rpc:
    def __init__(self, url: str):
        self.url = url
        self.calls = 0

    def __call__(self, method: str, params: list) -> object:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        for attempt in range(8):
            try:
                request = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response:
                    result = json.load(response)
                self.calls += 1
                if "error" in result:
                    raise RuntimeError(f"{method}: {result['error']}")
                return result["result"]
            except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as error:
                if isinstance(error, urllib.error.HTTPError) and error.code not in (429, 500, 502, 503, 504):
                    raise
                time.sleep(min(60, 2**attempt))
        raise RuntimeError(f"{method}: gave up after repeated network errors")

    def timestamp(self, number: int) -> int:
        return int(self("eth_getBlockByNumber", [hex(number), False])["timestamp"], 16)

    def first_block_at_or_after(self, unix_time: int) -> int:
        low, high = 1, int(self("eth_blockNumber", []), 16)
        while low < high:
            middle = (low + high) // 2
            if self.timestamp(middle) < unix_time:
                low = middle + 1
            else:
                high = middle
        return low

    def fees(self, first: int, count: int) -> list[tuple[int, int, int]]:
        """(block, base fee, median priority fee) in wei for `count` blocks from `first`."""
        history = self("eth_feeHistory", [hex(count), hex(first + count - 1), [50]])
        base = [int(value, 16) for value in history["baseFeePerGas"][:count]]
        tips = [int(row[0], 16) if row else 0 for row in history["reward"]]
        start = int(history["oldestBlock"], 16)
        return [(start + index, base[index], tips[index]) for index in range(count)]


def unix(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def sample_chain(rpc: Rpc, days: list[date], windows_per_day: int | None) -> dict[date, list[tuple[int, int, int]]]:
    boundaries = [rpc.first_block_at_or_after(unix(day)) for day in [*days, days[-1] + timedelta(days=1)]]
    samples: dict[date, list[tuple[int, int, int]]] = {}
    for day, first, end in zip(days, boundaries, boundaries[1:]):
        rows: list[tuple[int, int, int]] = []
        if windows_per_day is None:  # every block
            for start in range(first, end, 1024):
                rows += rpc.fees(start, min(1024, end - start))
        else:
            stride = (end - first) // windows_per_day
            for index in range(windows_per_day):
                rows += rpc.fees(first + index * stride, min(100, end - first - index * stride))
        samples[day] = rows
        print(f"  {day}: blocks {first}-{end - 1}, {len(rows)} sampled", file=sys.stderr)
    return samples


def gwei(wei: int) -> float:
    return wei / 1e9


def percentile(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(fraction * len(sorted_values)))]


def summarise(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "p95": percentile(ordered, 0.95),
        "p99": percentile(ordered, 0.99),
        "max": ordered[-1],
    }


def eth_price(day: date) -> dict[str, object]:
    url = COINGECKO_RANGE.format(start=unix(day), end=unix(day + timedelta(days=1)) - 1)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        prices = [price for _, price in json.load(response)["prices"]]
    return {"mean": statistics.fmean(prices), "min": min(prices), "max": max(prices), "hourly_points": len(prices), "url": url}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 20))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 30), help="last day, inclusive")
    parser.add_argument("--eth-date", type=date.fromisoformat, default=date(2026, 10, 30))
    parser.add_argument("--mainnet-rpc", default="https://eth.drpc.org")
    parser.add_argument("--base-rpc", default="https://base.drpc.org")
    parser.add_argument("--base-windows-per-day", type=int, default=24)
    args = parser.parse_args()

    days = [args.start + timedelta(days=offset) for offset in range((args.end - args.start).days + 1)]
    chains = {
        "ethereum": (Rpc(args.mainnet_rpc), None),
        "base": (Rpc(args.base_rpc), args.base_windows_per_day),
    }
    daily_rows: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "period": f"{args.start.isoformat()}/{args.end.isoformat()}",
        "method": "per block: base fee + median priority fee (eth_feeHistory, reward percentile 50), in gwei",
        "retrieved": datetime.now(timezone.utc).date().isoformat(),
        "chains": {},
    }
    for chain, (rpc, windows) in chains.items():
        print(f"{chain} ({rpc.url})", file=sys.stderr)
        samples = sample_chain(rpc, days, windows)
        every = [(block, gwei(base + tip)) for rows in samples.values() for block, base, tip in rows]
        for day, rows in samples.items():
            stats = summarise([gwei(base + tip) for _, base, tip in rows])
            daily_rows.append({"chain": chain, "date": day.isoformat(), "blocks_sampled": len(rows), "first_block": rows[0][0], "last_block": rows[-1][0], **{key: f"{value:.6g}" for key, value in stats.items()}})
        peak_block, peak = max(every, key=lambda item: item[1])
        summary["chains"][chain] = {
            "rpc": rpc.url,
            "sampling": "every block" if windows is None else f"{windows} windows of 100 consecutive blocks per day",
            "blocks_sampled": len(every),
            "first_block": samples[days[0]][0][0],
            "last_block": samples[days[-1]][-1][0],
            "gwei": summarise([value for _, value in every]),
            "peak_block": peak_block,
            "peak_block_time": datetime.fromtimestamp(rpc.timestamp(peak_block), timezone.utc).isoformat(),
            "peak_gwei": peak,
        }
    summary["eth_usd"] = {"date": args.eth_date.isoformat(), "source": "CoinGecko market_chart/range, hourly", **eth_price(args.eth_date)}

    DATA.mkdir(exist_ok=True)
    with (DATA / "fee_daily.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(daily_rows[0]))
        writer.writeheader()
        writer.writerows(daily_rows)
    (DATA / "fee_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
