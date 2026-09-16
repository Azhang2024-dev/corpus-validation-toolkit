"""stats —— 统计原语：分位数 / 直方图 / H_norm / Gini / Top10% 份额（纯 Python，无 numpy 依赖）。"""
from __future__ import annotations

import math


def quantiles(vals, ps=(0.1, 0.25, 0.5, 0.75, 0.9, 0.95)) -> dict:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return {p: 0.0 for p in ps}
    out = {}
    for p in ps:
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        out[p] = round(s[f] + (s[c] - s[f]) * (k - f), 1)
    return out


def summary(vals) -> dict:
    if not vals:
        return {"n": 0, "min": 0, "max": 0, "mean": 0.0, **{f"p{int(p*100)}": 0.0 for p in (10, 25, 50, 75, 90, 95)}}
    n = len(vals)
    q = quantiles(vals)
    return {
        "n": n,
        "min": min(vals),
        "max": max(vals),
        "mean": round(sum(vals) / n, 2),
        "p10": q[0.1],
        "p25": q[0.25],
        "p50": q[0.5],
        "p75": q[0.75],
        "p90": q[0.9],
        "p95": q[0.95],
    }


def histogram(vals, edges) -> list[int]:
    out = [0] * (len(edges) - 1)
    for v in vals:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                out[i] += 1
                break
    return out


def entropy_norm(counts: dict) -> float:
    """归一化信息熵 H_norm ∈ [0,1]。"""
    tot = sum(counts.values())
    if tot == 0:
        return 0.0
    H = -sum((c / tot) * math.log2(c / tot) for c in counts.values() if c > 0)
    V = len(counts)
    return round(H / math.log2(V), 4) if V > 1 else 1.0


def gini(counts: dict) -> float:
    """简化经济式 Gini ∈ [0,1]，0=完全均匀，1=完全集中。"""
    freqs = sorted(counts.values())  # 升序（标准 Gini：0=均匀，1=完全集中）
    V = len(freqs)
    tot = sum(freqs)
    if V == 0 or tot == 0:
        return 0.0
    gsum = sum((i + 1) * f for i, f in enumerate(freqs))
    G = 2 * gsum / (V * tot) - (V + 1) / V
    return round(max(0.0, min(1.0, G)), 4)


def top_share(counts: dict, pct: float = 0.1) -> float:
    """Top pct 型符占全部 token 的份额。"""
    tot = sum(counts.values())
    if tot == 0:
        return 0.0
    k = max(1, int(len(counts) * pct))
    top = sum(c for _, c in counts.most_common(k))
    return round(top / tot, 4)
