# Scope and Non-Goals

This document defines the hard boundary of the system. Anything outside this boundary is explicitly not built, not implied, and not supported.

---

## In Scope

### Token Discovery
- Detecting newly launched tokens on Pump.fun and related Solana token launchpads
- Tracking tokens that have moved from launch to active trading
- Ingesting basic on-chain metadata: address, name, symbol, deployer, launch time, holder count, liquidity

### Narrative Matching
- Matching token names and metadata to current real-world events, trends, and cultural moments
- Scoring the strength and relevance of that match
- Tracking narrative decay over time as attention moves elsewhere

### OG / Authenticity Resolution
- Estimating which token in a namespace (shared name/theme) is most likely the original, canonical token
- Flagging likely copycats with explicit uncertainty

### Risk Assessment
- Evaluating structural risk signals: deployer history, holder concentration, wallet clustering, liquidity quality
- Outputting risk tiers with explicit reasoning

### Momentum Analysis
- Distinguishing organic momentum patterns from coordinated/manipulated movement
- Tracking volume, holder growth, and social signal growth rates

### Alert Generation
- Producing structured, typed alerts with all reasoning included
- Managing alert lifecycle: creation, expiry, re-evaluation, retirement
- Delivering alerts via configured channels

### Attention Source Monitoring
- Ingesting signals from social platforms, news, search trends, and community channels
- Normalizing and scoring attention strength across sources

---

## Out of Scope

These are not ambiguities. These are explicit exclusions.

### Trade Execution
The system does not submit, suggest, or simulate trades. It does not generate order sizes, entry prices, or execution strategies. Any downstream system that executes trades is entirely separate and outside this codebase.

### Position Management
No tracking of open positions, portfolio allocation, P&L, drawdown, or exit management.

### Price Prediction
The system does not predict token prices. Probability estimates are about opportunity window existence, not price targets.

### Financial Advice
The system does not provide investment advice. Outputs are analytical signals, not recommendations. The system must never use language that implies it is recommending action.

### Token Creation or Deployment
The system observes the Pump.fun ecosystem. It does not create tokens, participate in launches, or interact with launch contracts.

### Historical Backtesting Engine
The system is not a backtesting framework. While historical data will inform calibration, building a full backtesting engine is not in scope. Retrospective analysis is done manually or through separate tooling.

### Multi-Chain Coverage (Initially)
Scope is Solana/Pump.fun. Other chains (Base, Ethereum, etc.) are out of scope until explicitly added and documented.

### Exchange Integration
No CEX or DEX integration for price feed dependency. On-chain data is the source. No order books, no CEX APIs.

### User Account System
No user authentication, user profiles, watchlists, or personalized alert configuration. Alerts are delivered to configured channels, not to user accounts.

### Regulatory Compliance Tooling
The system does not assess whether holding, trading, or alerting about specific tokens violates any regulatory requirement. Compliance is the user's responsibility.

---

## Boundary Cases (Explicit Decisions)

| Scenario | Decision |
|---|---|
| Token on Solana not on Pump.fun | Out of scope unless explicitly extended |
| Token with no narrative match | Evaluated as low narrative score, not excluded — still goes through full scoring pipeline |
| Token previously rugged, relaunched | Treated as new token; deployer history is a risk signal |
| Same narrative, many tokens | All evaluated; OG resolution determines which is surfaced |
| Narrative is ambiguous or debatable | Marked with low confidence, not suppressed |
| News event that drives multiple tokens | All tokens correlated to event are evaluated independently |
| User asks "should I buy this?" | System does not answer this question. |

---

## Why These Boundaries Exist

**Speed over breadth.** Covering Solana/Pump.fun well is harder than it looks. Adding chains before the core works creates surface area without benefit.

**Separation of concerns.** Trade execution, position sizing, and portfolio management are separate domains with separate risk profiles. Mixing them into this system would make it dangerous (automated financial decisions) and fragile (two unrelated problems coupled together).

**Liability surface.** The more this system looks like financial advice, the more problematic it becomes to operate. Strict scoping keeps it clearly in the "analytical tool" category.

**Complexity budget.** Every in-scope feature competes for engineering attention. Non-goals protect the complexity budget.
