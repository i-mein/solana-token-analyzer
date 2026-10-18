from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest.mock import patch

from solana_token_analyzer import cli
from solana_token_analyzer.scoring import score_metrics
from solana_token_analyzer.sources import SourceError, holder_metrics, pair_metrics


def make_pair(
    mint: str = "MintOne",
    symbol: str = "TEST",
    liquidity: float = 100_000,
) -> dict:
    return {
        "chainId": "solana",
        "dexId": "raydium",
        "pairAddress": f"pair-{mint}",
        "url": f"https://dexscreener.com/solana/pair-{mint}",
        "pairCreatedAt": 1_777_000_000_000,
        "baseToken": {"address": mint, "symbol": symbol, "name": "Test Token"},
        "marketCap": 1_000_000,
        "fdv": 1_100_000,
        "liquidity": {"usd": liquidity},
        "volume": {"h24": 200_000},
        "txns": {"h24": {"buys": 400, "sells": 300}},
    }


class TokenSelectionTests(unittest.TestCase):
    def test_ticker_selects_exact_symbol_and_highest_liquidity_pool(self) -> None:
        selected = cli.select_token(
            [make_pair(liquidity=10), make_pair(liquidity=100), make_pair(mint="Other", symbol="TEST2")],
            "test",
        )
        self.assertEqual(selected["baseToken"]["address"], "MintOne")
        self.assertEqual(selected["liquidity"]["usd"], 100)

    def test_ticker_refuses_to_guess_between_mints(self) -> None:
        with self.assertRaisesRegex(cli.SelectionError, "multiple Solana mints"):
            cli.select_token(
                [make_pair(), make_pair(mint="MintTwo")],
                "TEST",
            )

    def test_mint_selects_matching_address(self) -> None:
        selected = cli.select_token([make_pair(), make_pair(mint="MintTwo")], "MintTwo")
        self.assertEqual(selected["baseToken"]["address"], "MintTwo")


class MetricsTests(unittest.TestCase):
    def test_market_cap_falls_back_to_fdv_and_keeps_basis(self) -> None:
        pair = make_pair()
        pair.pop("marketCap")
        metrics = pair_metrics(pair)
        self.assertEqual(metrics["market_cap_usd"], 1_100_000)
        self.assertEqual(metrics["valuation_basis"], "fdv")

    def test_holder_metrics_exclude_liquidity_accounts_and_keep_unknowns(self) -> None:
        metrics = holder_metrics({
            "totalHolders": 25,
            "topHolders": [
                {"address": "pool", "pct": 70},
                {"address": "wallet-a", "pct": 8},
                {"address": "wallet-b", "pct": 7},
            ],
            "markets": [{"liquidityA": "pool", "lp": {"lpLockedPct": 99}}],
        })
        self.assertEqual(metrics["top10_pct_ex_labeled"], 15)
        self.assertIsNone(metrics["creator_balance_pct"])
        self.assertEqual(metrics["lp_locked_pct"], 99)

    def test_concentration_risk_caps_score(self) -> None:
        metrics = {
            "market_cap_usd": 1_000_000,
            "volume_24h_usd": 500_000,
            "liquidity_usd": 60_000,
            "buys_24h": 500,
            "sells_24h": 500,
            "holders": 5_000,
            "top10_pct_ex_labeled": 55,
            "largest_unlabeled_holder_pct": 21,
            "lp_locked_pct": 99,
            "bundled_buy_suspected": False,
            "social_links": 5,
            "social_mentions_1h": None,
            "kol_mentions_1h": None,
        }
        score = score_metrics(metrics)
        self.assertEqual(score["verdict"], "risk_review")
        self.assertLessEqual(score["score"], 55)
        self.assertIn("single_unlabeled_holder_gt_20pct", score["risk_flags"])

    def test_social_links_do_not_masquerade_as_mentions(self) -> None:
        metrics = {
            "market_cap_usd": 1_000_000,
            "volume_24h_usd": 200_000,
            "liquidity_usd": 50_000,
            "buys_24h": 100,
            "sells_24h": 100,
            "holders": None,
            "top10_pct_ex_labeled": None,
            "largest_unlabeled_holder_pct": None,
            "lp_locked_pct": None,
            "bundled_buy_suspected": False,
            "social_links": 100,
            "social_mentions_1h": None,
            "kol_mentions_1h": None,
        }
        self.assertEqual(score_metrics(metrics)["components"]["social_reflexivity"], 0)

    def test_analyze_returns_market_snapshot_when_rugcheck_is_unavailable(self) -> None:
        with (
            patch.object(cli, "search_solana_pairs", return_value=[make_pair()]),
            patch.object(cli, "fetch_rugcheck_report", side_effect=SourceError("offline")),
        ):
            report = cli.analyze("TEST")
        self.assertEqual(report["sources"], ["DexScreener"])
        self.assertIsNone(report["metrics"]["holders"])
        self.assertIsNone(report["metrics"]["bundled_buy_suspected"])
        self.assertIn("RugCheck enrichment unavailable", report["warnings"][1])
        self.assertIn("rugcheck", report["source_urls"])

    def test_concentration_metrics_are_not_in_public_report(self) -> None:
        with (
            patch.object(cli, "search_solana_pairs", return_value=[make_pair()]),
            patch.object(cli, "fetch_rugcheck_report", return_value={
                "totalHolders": 25,
                "topHolders": [{"address": "holder", "pct": 22}],
            }),
        ):
            report = cli.analyze("TEST")
        self.assertNotIn("top10_pct_ex_labeled", report["metrics"])
        self.assertNotIn("top20_pct_ex_labeled", report["metrics"])
        self.assertNotIn("largest_unlabeled_holder_pct", report["metrics"])
        self.assertEqual(report["data_coverage"]["total"], 18)
        output = StringIO()
        with patch("sys.stdout", output), patch("sys.stderr", StringIO()):
            cli.print_report(report)
        self.assertNotIn("Top 10 excluding labeled", output.getvalue())
        self.assertNotIn("Top 20 excluding labeled", output.getvalue())
        self.assertNotIn("Largest unlabeled holder", output.getvalue())

    def test_json_output_is_valid(self) -> None:
        with patch.object(cli, "analyze", return_value={"metric": None, "warnings": []}):
            output = StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(cli.main(["TEST", "--json"]), 0)
            self.assertIsNone(json.loads(output.getvalue())["metric"])


if __name__ == "__main__":
    unittest.main()
