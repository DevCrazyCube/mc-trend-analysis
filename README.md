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

## Quick Navigation

| Question | Where to look |
|---|---|
| What is this system? | `docs/core/00-project-overview.md` |
| What are the design principles? | `docs/core/01-system-philosophy.md` |
| How does the scoring work? | `docs/intelligence/scoring-model.md` |
| What do the probabilities mean? | `docs/intelligence/probability-framework.md` |
| What are the alert types? | `docs/alerting/alert-types.md` |
| How is a token evaluated end to end? | `docs/architecture/event-flow.md` |
| What are we building in what order? | `docs/implementation/roadmap.md` |
| What tools are currently in use? | `docs/implementation/current-approach.md` |
| See a real scoring example | `docs/examples/scoring-walkthroughs.md` |
| See example alerts | `docs/examples/example-alerts.md` |
| Contributing / working in this repo | `CLAUDE.md` |

---

## Documentation Structure

```
docs/
  core/           Project overview, philosophy, success metrics, scope
  architecture/   System design, pipelines, components, event flow, trust
  intelligence/   Scoring model, probability framework, rug risk, narrative linking, OG resolution
  alerting/       Alert engine, alert types, signal philosophy, delivery
  ingestion/      Source types, token/event ingestion, normalization
  implementation/ Current tooling, agent strategy, data model, roadmap
  rules/          Engineering rules, decision rules, data quality, anti-overengineering
  skills/         Ingestion, scoring, alert, and entity resolution patterns
  research/       Source catalog, adversarial patterns
  examples/       Worked alerts, scenarios, scoring walkthroughs
```

The documentation is the source of truth. Code implements what the docs describe.

---

## System Output

Alerts include:
- Alert type (one of 8 defined types)
- Token identification (address, name, symbol)
- Linked narrative
- net_potential, P_potential, P_failure, confidence_score
- All six dimension scores
- Risk flags (explicit, always visible)
- Human-readable reasoning (traceable to specific score inputs)
- Expiry and re-evaluation logic

Alerts are not buy/sell signals. They are structured probability estimates with explicit uncertainty.

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

Pre-implementation. Documentation architecture complete. See `docs/implementation/roadmap.md` for the phased build plan.
