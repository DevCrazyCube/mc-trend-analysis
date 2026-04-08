# mc-trend-analysis

Real-time trend intelligence and alerting system for Pump.fun / Solana memecoins.

Detects newly launched tokens, connects them to real-world narratives, evaluates opportunity and failure probability, and produces structured alerts with explicit reasoning.

**This is an intelligence layer. It does not trade. It does not guarantee outcomes. It produces probability estimates.**

---

## What It Does

1. Monitors Pump.fun for new token launches in real time
2. Detects trending real-world narratives across news, search, and social sources
3. Matches tokens to narratives and identifies which is most likely the canonical token
4. Scores each token across six dimensions: narrative relevance, authenticity, rug risk, momentum quality, attention strength, timing quality
5. Computes P_potential, P_failure, net_potential, and confidence_score
6. Classifies tokens into alert tiers and delivers structured alerts with full reasoning

---

## Getting Started

### Prerequisites

- Python 3.11+
- pip (or uv)

### Installation

```bash
# Clone the repo
git clone https://github.com/devcrazycube/mc-trend-analysis.git
cd mc-trend-analysis

# Install dependencies
pip install -e ".[dev]"
```

### Configuration

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your keys. At minimum you need no keys for the demo mode. For live data:

| Variable | Required | Source |
|---|---|---|
| `NEWSAPI_KEY` | For news narratives | newsapi.org |
| `SERPAPI_KEY` | For Google Trends | serpapi.com |
| `TELEGRAM_BOT_TOKEN` | For Telegram alerts | @BotFather |
| `TELEGRAM_CHAT_ID` | For Telegram alerts | Telegram |

### Running

```bash
# Demo mode (synthetic data, no API keys needed)
python -m mctrend --demo --once

# Single polling cycle with live data
python -m mctrend --once

# Continuous monitoring loop
python -m mctrend

# Show system status
python -m mctrend --status
```

### Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/unit/ -v

# Integration tests only
python -m pytest tests/integration/ -v
```

---

## Architecture

```
src/mctrend/
  config/          Settings, weights, thresholds (all configurable)
  models/          Pydantic domain models
  ingestion/       Source adapters (PumpFun, NewsAPI, SerpAPI, Solana RPC)
  normalization/   Canonical record normalization
  correlation/     Name matching (4 layers), OG token resolution
  scoring/         6-dimension scoring engine, probability framework
  alerting/        Alert classification, lifecycle management, reasoning
  delivery/        Console, Telegram, webhook delivery with rate limiting
  persistence/     SQLite (WAL mode) with typed repositories
  utils/           Structured logging (structlog)
  pipeline.py      8-step orchestration pipeline
  runner.py        CLI entrypoint and system builder
```

### Pipeline Flow

```
Ingest -> Normalize -> Correlate -> OG Resolve -> Score -> Classify -> Deliver -> Expire
```

### Scoring Model

Six dimensions scored [0, 1]:

| Dimension | Measures | Weight in P_potential |
|---|---|---|
| Narrative Relevance | How well token matches a real narrative | 0.25 |
| OG Likelihood | Probability of being the canonical token | 0.20 |
| Momentum Quality | Organic vs manipulated trading patterns | 0.20 |
| Attention Strength | Real-world narrative attention | 0.20 |
| Timing Quality | Position in narrative lifecycle | 0.15 |
| Rug Risk | Probability of structural failure | (used in P_failure) |

Composite scores:
- **P_potential** = weighted sum of positive dimensions
- **P_failure** = weighted sum of failure indicators (rug risk, fakeout, exhaustion, copycat, liquidity)
- **net_potential** = P_potential * (1 - P_failure)
- **confidence_score** = evidence quality measure

### Alert Types

| Type | Criteria |
|---|---|
| possible_entry | net >= 0.60, P_failure < 0.30, confidence >= 0.65 |
| high_potential_watch | net >= 0.45, P_failure < 0.50, confidence >= 0.55 |
| take_profit_watch | Prior high-tier + narrative PEAKING/DECLINING |
| verify | net >= 0.35, confidence < 0.55 |
| watch | net >= 0.25 |
| exit_risk | P_failure >= 0.65 + prior alert |
| discard | P_failure >= 0.80 or net < 0.10 |

---

## Quick Navigation

| Question | Where to look |
|---|---|
| What is this system? | `docs/core/00-project-overview.md` |
| What are the design principles? | `docs/core/01-system-philosophy.md` |
| How does the scoring work? | `docs/intelligence/scoring-model.md` |
| What do the probabilities mean? | `docs/intelligence/probability-framework.md` |
| What are the alert types? | `docs/alerting/alert-types.md` |
| How is a token evaluated end to end? | `docs/architecture/event-flow.md` |
| Contributing / working in this repo | `CLAUDE.md` |

---

## Limitations

- **This is not financial advice.** Alerts are probability estimates with explicit uncertainty.
- **Data quality varies.** Missing data produces conservative (not zero) scores. Check `data_gaps` and `confidence_score`.
- **Social data is limited.** Twitter/social adapters are stubbed; momentum and attention scores rely on available sources.
- **No backtesting.** Scoring weights are based on documented reasoning, not historical validation.
- **Single chain.** Currently targets Solana/Pump.fun only.

---

## Critical Non-Goals

This system does not:
- Execute trades
- Manage positions
- Predict prices
- Guarantee safety
- Provide financial advice

See `docs/core/03-scope-and-non-goals.md` for the full boundary definition.

---

## Status

Implementation complete. Core pipeline functional with demo mode for testing without live API keys. 161 tests covering scoring, probability calculations, rug risk, OG resolution, alert classification, normalization, and end-to-end pipeline integration.
