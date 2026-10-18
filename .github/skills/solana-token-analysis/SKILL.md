---
name: solana-token-analysis
description: "Analyze a single Solana token by ticker or mint with this repository's CLI. Use when asked to inspect a Solana token, get its market or holder metrics, assess risk, or produce JSON analysis."
---

# Solana Token Analysis

Use the repository's `solana-token-analyzer` CLI to look up and report one
Solana token. Do not substitute guessed figures, another analyzer, or a broad
token scan.

## Procedure

1. Get the requested ticker or mint from the user request. If it is missing,
   ask which token to analyze.
2. Run the command from the repository root using the project environment:

   ```bash
   .venv/bin/solana-token-analyzer <ticker-or-mint>
   ```

   Add `--json` if the user asks for JSON, structured data, or a machine-readable
   result. If the environment is not installed, follow the setup in the root
   README (`uv venv .venv`, activate it, then `uv pip install -e .`).
3. Show the CLI's result and briefly explain that it is a public-data snapshot,
   not investment advice. Preserve source warnings and unknown values.
4. If a ticker resolves to multiple mints, do not select a candidate. Show the
   candidate addresses from the CLI error and ask the user to choose a mint.
5. If the lookup fails, report the error rather than inventing or silently
   omitting metrics.

The command makes read-only requests to public DexScreener and RugCheck APIs.
It does not require wallet credentials or submit transactions.
