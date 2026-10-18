from __future__ import annotations

import json
import http.client
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q={query}"
RUGCHECK_REPORT_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
USER_AGENT = "solana-token-analyzer/0.1.0"


class SourceError(Exception):
    """A public data provider returned an unusable response."""


def _get_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except (
        urllib.error.URLError,
        TimeoutError,
        http.client.HTTPException,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise SourceError(f"Request failed for {urllib.parse.urlparse(url).netloc}: {exc}") from exc


def search_solana_pairs(query: str) -> list[dict[str, Any]]:
    url = DEX_SEARCH_URL.format(query=urllib.parse.quote(query, safe=""))
    data = _get_json(url)
    if not isinstance(data, dict):
        raise SourceError("DexScreener returned an unexpected search response.")
    pairs = data.get("pairs")
    if pairs is None:
        return []
    if not isinstance(pairs, list):
        raise SourceError("DexScreener returned an unexpected search response.")
    return [
        pair for pair in pairs
        if isinstance(pair, dict) and str(pair.get("chainId", "")).lower() == "solana"
    ]


def fetch_rugcheck_report(mint: str) -> dict[str, Any]:
    url = RUGCHECK_REPORT_URL.format(mint=urllib.parse.quote(mint, safe=""))
    data = _get_json(url)
    if not isinstance(data, dict):
        raise SourceError("RugCheck returned an unexpected token report.")
    return data


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _parse_created_at(value: Any) -> datetime | None:
    milliseconds = _number(value)
    if milliseconds is None:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def liquidity_usd(pair: dict[str, Any]) -> float:
    liquidity = pair.get("liquidity") or {}
    return _number(liquidity.get("usd")) or 0.0


def pair_metrics(pair: dict[str, Any]) -> dict[str, Any]:
    market_cap = _number(pair.get("marketCap"))
    fdv = _number(pair.get("fdv"))
    if market_cap is None or market_cap <= 0:
        market_cap = None
    if fdv is None or fdv <= 0:
        fdv = None
    valuation = market_cap if market_cap is not None else fdv
    volume = pair.get("volume") or {}
    txns = (pair.get("txns") or {}).get("h24") or {}
    base_token = pair.get("baseToken") or {}
    buys = _number(txns.get("buys"))
    sells = _number(txns.get("sells"))
    return {
        "market_cap_usd": valuation,
        "valuation_basis": "market_cap" if market_cap is not None else "fdv" if fdv is not None else None,
        "liquidity_usd": _number((pair.get("liquidity") or {}).get("usd")),
        "volume_24h_usd": _number(volume.get("h24")),
        "buys_24h": int(buys) if buys is not None else None,
        "sells_24h": int(sells) if sells is not None else None,
        "pool_created_at": _parse_created_at(pair.get("pairCreatedAt")),
        "social_links": _social_link_count(pair),
        "token_address": base_token.get("address"),
    }


def _social_link_count(pair: dict[str, Any]) -> int:
    info = pair.get("info") or {}
    socials = info.get("socials") or []
    websites = info.get("websites") or []
    return sum(
        len([item for item in entries if item])
        for entries in (socials, websites)
        if isinstance(entries, list)
    )


def holder_metrics(report: dict[str, Any]) -> dict[str, Any]:
    markets = report.get("markets") or []
    liquidity_addresses: set[str] = set()
    for market in markets:
        if not isinstance(market, dict):
            continue
        for key in ("liquidityA", "liquidityB", "pubkey", "market"):
            address = market.get(key)
            if isinstance(address, str):
                liquidity_addresses.add(address)

    holders = report.get("topHolders") or []
    unlabeled: list[float] = []
    for holder in holders:
        if not isinstance(holder, dict) or str(holder.get("address", "")) in liquidity_addresses:
            continue
        percentage = _number(holder.get("pct"))
        if percentage is not None:
            unlabeled.append(percentage)

    lock_values: list[float] = []
    for market in markets:
        if isinstance(market, dict):
            lp = market.get("lp") or {}
            if isinstance(lp, dict):
                locked = _number(lp.get("lpLockedPct"))
                if locked is not None:
                    lock_values.append(locked)

    creator_percentage = _number(report.get("creatorPercentage"))
    if creator_percentage is None and report.get("creatorBalance") in (0, "0"):
        creator_percentage = 0.0
    total_holders = _number(report.get("totalHolders"))
    return {
        "holders": int(total_holders) if total_holders is not None else None,
        "top10_pct_ex_labeled": round(sum(unlabeled[:10]), 4) if unlabeled else None,
        "top20_pct_ex_labeled": round(sum(unlabeled[:20]), 4) if unlabeled else None,
        "largest_unlabeled_holder_pct": round(max(unlabeled), 4) if unlabeled else None,
        "creator_balance_pct": creator_percentage,
        "lp_locked_pct": max(lock_values) if lock_values else None,
        "labels_applied": ["liquidity_accounts_excluded"] if liquidity_addresses else [],
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
