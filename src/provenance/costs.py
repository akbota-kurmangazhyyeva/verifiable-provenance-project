"""Dollar cost of gas and the fit for inclusion-check gas used in the paper.

USD = gas * gas_price_gwei * 1e-9 * eth_usd

Gas is what we measure; the gas price and the ETH price change daily, so the
dollar figures are always derived from gas with this one formula.
"""

import math
from collections.abc import Sequence

GWEI = 1e-9  # ETH per gwei


def usd(gas: float, gas_price_gwei: float, eth_usd: float) -> float:
    """Cost in US dollars of `gas` units at `gas_price_gwei` and `eth_usd` per ETH."""
    if gas < 0 or gas_price_gwei < 0 or eth_usd < 0:
        raise ValueError("gas, gas price and ETH price must be non-negative")
    return gas * gas_price_gwei * GWEI * eth_usd


def fit_log2(batch_sizes: Sequence[int], gas: Sequence[float]) -> tuple[float, float, float]:
    """Least-squares fit gas ~ a + b * log2(n).

    Returns (a, b, r_squared). Used for the inclusion-check gas, which grows by
    one proof element, and so by a roughly constant amount, per doubling of n.
    """
    if len(batch_sizes) != len(gas) or len(gas) < 2:
        raise ValueError("need at least two (batch size, gas) pairs of equal length")
    xs = [math.log2(n) for n in batch_sizes]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(gas) / len(gas)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("batch sizes must not all be equal")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, gas))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in gas)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, gas))
    r_squared = 1.0 if total == 0 else 1 - residual / total
    return intercept, slope, r_squared


def significant(value: float, digits: int = 2) -> str:
    """Plain decimal string with `digits` significant figures, e.g. 0.0013, 6.3, 74."""
    if value == 0:
        return "0"
    exponent = math.floor(math.log10(abs(value)))
    decimals = max(0, digits - 1 - exponent)
    return f"{round(value, decimals):.{decimals}f}"


def latex_usd(value: float) -> str:
    """Dollar value for a LaTeX table.

    Two decimals from $1 up, two significant figures between 1e-4 and 1, and
    scientific notation below that, where a decimal would be mostly zeros.
    """
    if value >= 1:
        return f"{value:.2f}"
    if value >= 1e-4:
        return significant(value)
    mantissa, exponent = f"{value:.1e}".split("e")
    return f"${mantissa}\\times10^{{{int(exponent)}}}$"


def latex_int(value: float) -> str:
    """Integer with LaTeX thousands separators: 74226.6 -> 74{,}227."""
    return f"{round(value):,}".replace(",", "{,}")
