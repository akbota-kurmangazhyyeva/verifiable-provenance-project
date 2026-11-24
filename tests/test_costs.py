import math

import pytest

from provenance.costs import fit_log2, latex_int, latex_usd, significant, usd


def test_usd_matches_hand_calculation():
    # 74,229 gas at 0.5 gwei and $2,300/ETH = 74,229 * 0.5e-9 * 2,300 dollars
    assert usd(74_229, 0.5, 2_300) == pytest.approx(0.08536335)
    assert usd(21_000, 1, 1_000) == pytest.approx(0.021)
    assert usd(0, 37, 2_300) == 0


def test_usd_rejects_negative_inputs():
    with pytest.raises(ValueError):
        usd(-1, 1, 1)


def test_fit_recovers_exact_line():
    sizes = [1, 2, 4, 8, 1024]
    gas = [25_000 + 1_200 * math.log2(n) for n in sizes]
    intercept, slope, r_squared = fit_log2(sizes, gas)
    assert intercept == pytest.approx(25_000)
    assert slope == pytest.approx(1_200)
    assert r_squared == pytest.approx(1)


def test_fit_on_paper_table_2_points():
    # The four rows of Table 2 give the coefficients quoted in the paper draft.
    intercept, slope, _ = fit_log2([1, 4, 64, 1024], [25_384, 26_980, 32_100, 37_130])
    assert round(intercept, -2) == 25_000
    assert round(slope, -2) == 1_200


def test_fit_needs_two_distinct_sizes():
    with pytest.raises(ValueError):
        fit_log2([4, 4], [1, 2])
    with pytest.raises(ValueError):
        fit_log2([4], [1])


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.08536, "0.085"), (0.0013339, "0.0013"), (6.3167, "6.3"), (74.49, "74"), (0.000083, "0.000083"), (0, "0")],
)
def test_significant(value, expected):
    assert significant(value) == expected


def test_latex_usd_switches_format_by_size():
    assert latex_usd(6.3167) == "6.32"
    assert latex_usd(0.0061689) == "0.0062"
    assert latex_usd(0.00000083) == "$8.3\\times10^{-7}$"


def test_latex_int_uses_thin_separators():
    assert latex_int(74_226.6) == "74{,}227"
    assert latex_int(72.49) == "72"
