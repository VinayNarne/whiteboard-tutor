"""Small statistics for the eval reports: Wilson intervals, Fisher exact comparison, run-count planning, Cohen's kappa."""
import math

from scipy.stats import fisher_exact, norm

LEGEND = "p < 0.05: unlikely to be chance"


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def compare(k1, n1, k2, n2):
    p = fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])[1] if n1 and n2 else 1.0
    return {"p": p, "ci1": wilson(k1, n1), "ci2": wilson(k2, n2), "diff": (k2 / n2 if n2 else 0) - (k1 / n1 if n1 else 0)}


def runs_needed(p1, p2, alpha=0.05, power=0.8):
    """Runs per side to tell two proportions apart (normal approximation)."""
    if p1 == p2:
        return math.inf
    pbar = (p1 + p2) / 2
    za, zb = norm.ppf(1 - alpha / 2), norm.ppf(power)
    num = za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(num ** 2 / (p1 - p2) ** 2)


def fmt(k, n):
    if n == 0:
        return "0/0"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({lo * 100:.0f}–{hi * 100:.0f}%)"


def fmt_p(p):
    return f"{p:.3f}" if p >= 0.001 else "<0.001"


def cohen_kappa(a, b):
    """a, b: equal-length lists of yes/no labels (bool, or 'YES'/'NO' strings)."""
    a, b = [str(x).upper() in ("YES", "TRUE", "1") for x in a], [str(x).upper() in ("YES", "TRUE", "1") for x in b]
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


if __name__ == "__main__":
    assert abs(compare(0, 10, 8, 10)["p"] - 0.0007) < 0.0002
    assert abs(compare(2, 5, 5, 6)["p"] - 0.24) < 0.02
    lo, hi = wilson(5, 6)
    assert abs(lo - 0.436) < 0.01 and abs(hi - 0.974) < 0.01, (lo, hi)
    assert fmt(5, 6) == "5/6 (44–97%)", fmt(5, 6)
    assert runs_needed(0.3, 0.7) == 24
    assert abs(cohen_kappa(["YES", "NO", "YES", "NO"], ["YES", "NO", "NO", "NO"]) - 0.5) < 1e-9
    print("eval_stats ok")
