from __future__ import annotations

from typing import Any


def _score_holder_distribution(metrics: dict[str, Any], flags: list[str]) -> int:
    top10 = metrics["top10_pct_ex_labeled"]
    largest = metrics["largest_unlabeled_holder_pct"]
    if largest is not None:
        if largest > 20:
            flags.append("single_unlabeled_holder_gt_20pct")
        elif largest > 10:
            flags.append("single_unlabeled_holder_gt_10pct")
    if top10 is None:
        return 5
    if top10 < 20:
        score = 30
    elif top10 <= 35:
        score = 20
    elif top10 <= 50:
        score = 10
    else:
        flags.append("top10_holders_gt_50pct")
        score = 0
    if largest is not None and largest > 10:
        score = min(score, 10)
    if largest is not None and largest > 20:
        score = min(score, 5)
    return score


def score_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    market_cap = metrics["market_cap_usd"] or 0
    volume = metrics["volume_24h_usd"] or 0
    liquidity = metrics["liquidity_usd"] or 0
    holders = metrics["holders"]
    locked = metrics["lp_locked_pct"]

    volume_ratio = volume / market_cap if market_cap else None
    liquidity_ratio = liquidity / market_cap if market_cap else None
    if locked is not None and locked < 50:
        flags.append("lp_lock_lt_50pct")
    elif locked is None:
        flags.append("lp_lock_unknown")

    if volume_ratio is None:
        volume_score = 0
    elif metrics["buys_24h"] is None or metrics["sells_24h"] is None:
        volume_score = 2 if volume_ratio < 0.03 else 7
    elif volume_ratio >= 0.50 and metrics["buys_24h"] + metrics["sells_24h"] >= 500:
        volume_score = 20
    elif volume_ratio >= 0.10 and metrics["buys_24h"] + metrics["sells_24h"] >= 250:
        volume_score = 12
    elif volume_ratio >= 0.03:
        volume_score = 7
    else:
        volume_score = 2
    if metrics["bundled_buy_suspected"]:
        flags.append("bundled_buy_suspected")
        volume_score = 3

    if liquidity_ratio is None:
        liquidity_score = 0
    elif locked is not None and locked >= 95 and 0.03 <= liquidity_ratio <= 0.10:
        liquidity_score = 15
    elif locked is not None and locked >= 95:
        liquidity_score = 10
    elif 0.03 <= liquidity_ratio <= 0.10:
        liquidity_score = 8
    else:
        liquidity_score = 4

    mentions = metrics["social_mentions_1h"] or 0
    kol_mentions = metrics["kol_mentions_1h"] or 0
    if mentions >= 25 and kol_mentions <= max(5, mentions * 0.25):
        social_score = 15
    elif mentions >= 10:
        social_score = 8
    elif mentions > 0:
        social_score = 3
    else:
        social_score = 0
    holder_score = 0 if holders is None else 20 if holders >= 5000 else 12 if holders >= 1000 else 5 if holders >= 250 else 0
    components = {
        "holder_distribution": _score_holder_distribution(metrics, flags),
        "holder_growth": holder_score,
        "volume_quality": volume_score,
        "liquidity_safety": liquidity_score,
        "social_reflexivity": social_score,
    }
    total = sum(components.values())
    if "single_unlabeled_holder_gt_20pct" in flags:
        total = min(total, 55)
    elif "top10_holders_gt_50pct" in flags:
        total = min(total, 59)

    if "single_unlabeled_holder_gt_20pct" in flags or "top10_holders_gt_50pct" in flags:
        verdict = "risk_review"
    elif total >= 75:
        verdict = "watchlist"
    elif total >= 60:
        verdict = "monitor"
    else:
        verdict = "ignore"
    return {"score": total, "verdict": verdict, "components": components, "risk_flags": list(dict.fromkeys(flags))}
