"""Backtest metrics: PF, WR, bootstrap CI, Holm-Bonferroni multiple comparison correction."""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np


def compute_metrics(returns: List[float], bootstrap_iters: int = 1000, seed: int = 42) -> Dict:
    """Compute trade-level metrics from list of trade returns (decimal, e.g. 0.05 = +5%).

    Returns dict with: N, PF, WR, mean, std, t_stat, p_value (one-tailed bootstrap),
    ci_low, ci_high (95% bootstrap CI on PF).
    """
    if not returns:
        return {
            "N": 0, "PF": float("nan"), "WR": float("nan"),
            "mean": float("nan"), "std": float("nan"),
            "t_stat": float("nan"), "p_value": float("nan"),
            "ci_low": float("nan"), "ci_high": float("nan"),
        }

    arr = np.array(returns, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]

    if len(losses) == 0 or losses.sum() == 0:
        pf = float("inf") if len(wins) > 0 else float("nan")
    else:
        pf = float(wins.sum() / abs(losses.sum()))

    wr = float(len(wins) / len(arr))
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    t_stat = float(mean / (std / np.sqrt(len(arr)))) if std > 0 else float("nan")

    rng = np.random.default_rng(seed)
    pf_samples = []
    boot_means = []
    for _ in range(bootstrap_iters):
        sample = rng.choice(arr, size=len(arr), replace=True)
        s_wins = sample[sample > 0].sum()
        s_losses = abs(sample[sample <= 0].sum())
        if s_losses > 0:
            pf_samples.append(s_wins / s_losses)
        boot_means.append(sample.mean())

    if pf_samples:
        ci_low = float(np.percentile(pf_samples, 2.5))
        ci_high = float(np.percentile(pf_samples, 97.5))
    else:
        ci_low = float("nan")
        ci_high = float("nan")

    p_value = float(sum(1 for m in boot_means if m <= 0) / bootstrap_iters)

    return {
        "N": len(arr), "PF": pf, "WR": wr,
        "mean": mean, "std": std,
        "t_stat": t_stat, "p_value": p_value,
        "ci_low": ci_low, "ci_high": ci_high,
    }


def bootstrap_pf_ci(
    returns: List[float],
    iterations: int = 1000,
    seed: int = 42,
    confidence: float = 0.95,
) -> Tuple[float, float]:
    """Standalone bootstrap CI helper for PF."""
    if not returns or all(r <= 0 for r in returns):
        return (float("nan"), float("nan"))
    arr = np.array(returns, dtype=float)
    rng = np.random.default_rng(seed)
    pf_samples = []
    for _ in range(iterations):
        sample = rng.choice(arr, size=len(arr), replace=True)
        s_wins = sample[sample > 0].sum()
        s_losses = abs(sample[sample <= 0].sum())
        if s_losses > 0:
            pf_samples.append(s_wins / s_losses)
    if not pf_samples:
        return (float("nan"), float("nan"))
    alpha = (1 - confidence) / 2
    return (
        float(np.percentile(pf_samples, alpha * 100)),
        float(np.percentile(pf_samples, (1 - alpha) * 100)),
    )


def holm_bonferroni(p_values: Dict, alpha: float = 0.05) -> Dict:
    """Apply Holm-Bonferroni step-down correction.

    Args:
        p_values: dict {test_id: p_value}
        alpha: family-wise error rate

    Returns:
        dict {test_id: is_significant_after_correction}
    """
    if not p_values:
        return {}

    sorted_p = sorted(p_values.items(), key=lambda x: x[1])
    m = len(sorted_p)
    significance = {tid: False for tid in p_values}

    for rank, (tid, p) in enumerate(sorted_p):
        threshold = alpha / (m - rank)
        if p <= threshold:
            significance[tid] = True
        else:
            break  # step-down: remaining tests stay False

    return significance
