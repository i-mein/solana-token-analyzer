from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import quote

from .scoring import score_metrics
from .sources import (
    RUGCHECK_REPORT_URL,
    SourceError,
    fetch_rugcheck_report,
    holder_metrics,
    liquidity_usd,
    pair_metrics,
    search_solana_pairs,
    utc_now,
)

METRIC_FIELDS = (
    "market_cap_usd",
    "liquidity_usd",
    "volume_24h_usd",
    "volume_to_mcap",
    "liquidity_to_mcap",
    "pool_age_hours",
    "buys_24h",
    "sells_24h",
    "holders",
    "top10_pct_ex_labeled",
    "top20_pct_ex_labeled",
    "largest_unlabeled_holder_pct",
    "creator_balance_pct",
    "lp_locked_pct",
    "social_mentions_1h",
    "kol_mentions_1h",
    "bundled_buy_suspected",
    "social_links",
)


class SelectionError(Exception):
    pass


def select_token(pairs: list[dict[str, Any]], query: str) -> dict[str, Any]:
    exact_mint = [pair for pair in pairs if pair_metrics(pair)["token_address"] == query]
    exact_symbol = [
        pair for pair in pairs
        if str((pair.get("baseToken") or {}).get("symbol") or "").casefold() == query.casefold()
    ]
    candidates = exact_mint or exact_symbol
    if not candidates:
        raise SelectionError(f"No Solana token found for {query!r}. Check the ticker or mint address.")

    by_mint: dict[str, dict[str, Any]] = {}
    for pair in candidates:
        mint = pair_metrics(pair)["token_address"]
        if not mint:
            continue
        if mint not in by_mint or liquidity_usd(pair) > liquidity_usd(by_mint[mint]):
            by_mint[mint] = pair

    if len(by_mint) > 1:
        choices = sorted(
            by_mint.values(),
            key=lambda pair: liquidity_usd(pair),
            reverse=True,
        )
        details = "; ".join(
            f"{(pair.get('baseToken') or {}).get('symbol', '?')}: "
            f"{(pair.get('baseToken') or {}).get('address', '?')} "
            f"(liquidity ${liquidity_usd(pair):,.0f})"
            for pair in choices
        )
        raise SelectionError(
            f"Ticker {query!r} matches multiple Solana mints. Use a mint address: {details}"
        )
    if not by_mint:
        raise SelectionError(f"DexScreener returned no usable token address for {query!r}.")
    return next(iter(by_mint.values()))


def analyze(query: str) -> dict[str, Any]:
    pair = select_token(search_solana_pairs(query.strip()), query.strip())
    metrics = pair_metrics(pair)
    warnings: list[str] = []
    mint = metrics["token_address"]
    warnings.append("Social-mention data is unavailable; the social score component is zero.")
    try:
        metrics.update(holder_metrics(fetch_rugcheck_report(mint)))
        sources = ["DexScreener", "RugCheck"]
    except SourceError as exc:
        warnings.append(f"RugCheck enrichment unavailable: {exc}")
        sources = ["DexScreener"]

    metrics["bundled_buy_suspected"] = None
    metrics["social_links"] = metrics.get("social_links") or 0
    metrics["social_mentions_1h"] = None
    metrics["kol_mentions_1h"] = None
    for field in METRIC_FIELDS:
        metrics.setdefault(field, None)
    market_cap = metrics["market_cap_usd"]
    metrics["volume_to_mcap"] = (
        metrics["volume_24h_usd"] / market_cap
        if market_cap and metrics["volume_24h_usd"] is not None
        else None
    )
    metrics["liquidity_to_mcap"] = (
        metrics["liquidity_usd"] / market_cap
        if market_cap and metrics["liquidity_usd"] is not None
        else None
    )

    observed_at = utc_now()
    created_at = metrics.pop("pool_created_at", None)
    if created_at is not None:
        age_hours = max(0, (observed_at - created_at).total_seconds() / 3600)
        metrics["pool_age_hours"] = round(age_hours, 2)
    else:
        metrics["pool_age_hours"] = None

    analysis = score_metrics(metrics)
    coverage = [metrics[field] is not None for field in METRIC_FIELDS]
    public_metrics = {
        key: value for key, value in metrics.items()
        if key not in {
            "top10_pct_ex_labeled",
            "top20_pct_ex_labeled",
            "largest_unlabeled_holder_pct",
        }
    }
    base_token = pair.get("baseToken") or {}
    result = {
        "input": query,
        "token": {
            "symbol": base_token.get("symbol"),
            "name": base_token.get("name"),
            "mint": mint,
            "pair_address": pair.get("pairAddress"),
            "dex_id": pair.get("dexId"),
            "pair_url": pair.get("url"),
            "observed_at": observed_at.isoformat(),
        },
        "metrics": public_metrics,
        "analysis": analysis,
        "sources": sources,
        "source_urls": {
            "dexscreener": pair.get("url"),
            "rugcheck": RUGCHECK_REPORT_URL.format(mint=quote(mint, safe="")),
        },
        "data_coverage": {
            "available": sum(coverage),
            "total": len(coverage),
        },
        "warnings": warnings,
    }
    return result


def _format_usd(value: Any) -> str:
    return "unknown" if value is None else f"${value:,.2f}"


def print_report(report: dict[str, Any]) -> None:
    token = report["token"]
    metrics = report["metrics"]
    analysis = report["analysis"]
    print(f"{token['symbol']} — {token['name'] or 'Unknown name'}")
    print(f"Mint: {token['mint']}")
    print(f"Pair: {token['dex_id'] or 'unknown'} | {token['pair_url'] or 'URL unavailable'}")
    print(f"Observed: {token['observed_at']}")
    print()
    print("MARKET")
    valuation_label = {
        "market_cap": "Market cap",
        "fdv": "FDV",
        None: "Valuation",
    }[metrics["valuation_basis"]]
    print(f"  {valuation_label}: {_format_usd(metrics['market_cap_usd'])}")
    print(f"  Liquidity: {_format_usd(metrics['liquidity_usd'])}")
    print(f"  24h volume: {_format_usd(metrics['volume_24h_usd'])}")
    print(f"  Volume / market cap: {metrics['volume_to_mcap'] if metrics['volume_to_mcap'] is not None else 'unknown'}")
    print(f"  Liquidity / market cap: {metrics['liquidity_to_mcap'] if metrics['liquidity_to_mcap'] is not None else 'unknown'}")
    print(f"  24h buys / sells: {metrics['buys_24h'] if metrics['buys_24h'] is not None else 'unknown'} / "
          f"{metrics['sells_24h'] if metrics['sells_24h'] is not None else 'unknown'}")
    age = metrics["pool_age_hours"]
    print(f"  Pool age: {age:,.2f} hours" if age is not None else "  Pool age: unknown")
    print()
    print("RISK & HOLDERS")
    for label, field, suffix in (
        ("Holders", "holders", ""),
        ("Creator balance", "creator_balance_pct", "%"),
        ("LP locked", "lp_locked_pct", "%"),
        ("Social links", "social_links", ""),
    ):
        value = metrics[field]
        shown = "unknown" if value is None else f"{value}{suffix}"
        print(f"  {label}: {shown}")
    print(f"  Score: {analysis['score']}/100 ({analysis['verdict']})")
    for component, score in analysis["components"].items():
        print(f"    {component.replace('_', ' ')}: {score}")
    print(f"  Risk flags: {', '.join(analysis['risk_flags']) or 'none detected'}")
    print(f"  Sources: {', '.join(report['sources'])}")
    coverage = report["data_coverage"]
    print(f"  Data coverage: {coverage['available']}/{coverage['total']} key metrics")
    print(f"  RugCheck report: {report['source_urls']['rugcheck']}")
    for warning in report["warnings"]:
        print(f"  Warning: {warning}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solana-token-analyzer",
        description="Analyze one Solana token by exact ticker or mint address.",
    )
    parser.add_argument("token", help="Solana ticker (for example PUMP) or token mint address")
    parser.add_argument("--json", action="store_true", help="Write a machine-readable JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = args.token.strip()
    if not query:
        print("Error: token ticker or mint address cannot be empty.", file=sys.stderr)
        return 2
    try:
        report = analyze(query)
    except SelectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, allow_nan=False))
        for warning in report["warnings"]:
            print(f"Warning: {warning}", file=sys.stderr)
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
