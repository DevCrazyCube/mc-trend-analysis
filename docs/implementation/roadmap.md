# Roadmap

This document defines the phased build order with rationale. It contains no dates. Phases are sequenced by dependency, value, and risk, not by calendar.

---

## Guiding Principle

Build the simplest version of each layer that works before adding complexity. Each phase should produce a usable (if limited) system before the next phase begins. This prevents the system from being "almost done" indefinitely.

---

## Phase 1: Token Discovery + Basic Rug Screening

**Goal:** Can we see new tokens being launched and immediately flag the obvious rugs?

**Deliverables:**

1. Token ingestion pipeline: real-time detection of new Pump.fun tokens
2. Token registry with basic deduplication
3. TokenChainSnapshot fetcher (deployer, holder concentration, liquidity)
4. Rug risk assessor: deployer risk + holder concentration + liquidity risk (categories 1, 2, 4 from the rug risk framework)
5. Basic alert: `discard` for critical rug signals, `watch` for everything else
6. Delivery: Telegram delivery of discard/watch alerts

**Success condition:** The system ingests tokens in real time, detects obvious rug patterns, and delivers basic alerts to a Telegram channel.

**What's not in Phase 1:**
- Narrative linking
- Probability scoring
- Social signals
- Any LLM usage

**Why start here:** Rug detection is the most critical safety function. Starting with it establishes the core ingestion and delivery infrastructure while providing immediate utility.

---

## Phase 2: Narrative Detection + Basic Correlation

**Goal:** Can we detect what's trending and link tokens to trends?

**Deliverables:**

1. Event ingestion: at least two source types operational (search trends + one news API)
2. Narrative registry with lifecycle tracking
3. Correlation engine: Layer 1 (exact match) and Layer 2 (abbreviation match)
4. TokenNarrativeLink creation
5. Basic narrative relevance score (from correlation confidence only)
6. Alert upgrade: distinguish tokens with narrative links from those without

**Success condition:** Tokens with obvious narrative links (e.g., exact-match names to trending terms) are identified and elevated above non-linked tokens in alerts.

**What's not in Phase 2:**
- Semantic matching (Layer 4)
- OG resolution
- Full probability scoring
- Social signal ingestion

---

## Phase 3: Full Scoring Model

**Goal:** Compute all six dimension scores and derived probability values.

**Deliverables:**

1. Momentum analyzer (on-chain volume patterns, trade diversity)
2. Attention strength computation from available event sources
3. Timing quality computation
4. OG resolver (for namespaces with multiple tokens)
5. Scoring aggregator: P_potential, P_failure, net_potential, confidence_score
6. Full alert type taxonomy operational (all eight types)
7. Alert expiry and re-evaluation logic

**Success condition:** Every token with a narrative link receives a full score. Alert types reflect the full classification model. Expiry and re-evaluation work.

**What's not in Phase 3:**
- Social source integration
- Semantic narrative matching
- Wallet clustering analysis (deferred to Phase 4)

---

## Phase 4: Social Signal Integration + Wallet Clustering

**Goal:** Complete the evidence base with social signals and improve manipulation detection.

**Deliverables:**

1. Social signal ingestion (Twitter/X or alternative)
2. Momentum quality improvement: social-chain alignment scoring
3. Attention strength improvement: multi-source with social included
4. Wallet clustering analysis (Category 3 of rug risk framework)
5. Bot detection basic heuristics for social signal discounting
6. Cross-source token mention detection for OG resolution

**Success condition:** Social signals meaningfully contribute to scoring. Confidence scores reflect social data availability. Wallet clustering catches additional rug risk patterns.

---

## Phase 5: Semantic Matching + LLM Integration

**Goal:** Catch narrative connections that deterministic matching misses.

**Deliverables:**

1. Layer 4 semantic matching using LLM
2. Prompt templates, versioning, and validation
3. LLM call logging and monitoring
4. Fallback mechanisms for LLM failures
5. Calibration: measure false positive/negative rate of semantic matching vs. deterministic-only

**Success condition:** Semantic matching adds measurable signal (more true positive narrative links) without adding noise (false positive rate stays acceptable).

**Why this is Phase 5:** LLM integration adds complexity and fragility. Do it after the core deterministic model is proven to work and calibrated. Otherwise you can't distinguish LLM errors from model errors.

---

## Phase 6: Calibration Infrastructure

**Goal:** Can we measure whether the system is working?

**Deliverables:**

1. Outcome logging: track what happened to each alerted token after alert delivery
2. Calibration analysis: compare predicted probability bands to observed outcomes
3. Alert quality dashboard
4. Source performance tracking (which sources contribute most signal quality)
5. Dimension weight tuning workflow

**Success condition:** The team can look at a dashboard and understand whether the probability estimates are well-calibrated. Specific dimensions that over- or under-predict are identifiable.

**Why this is Phase 6:** Calibration requires a body of outcomes to analyze. You can't calibrate before you have data. But it's critical to do before Phase 7.

---

## Phase 7: Operational Hardening

**Goal:** Make the system production-grade.

**Deliverables:**

1. Monitoring and alerting for system health (source downtime, error rates, pipeline latency)
2. Retry logic and backoff for all external dependencies
3. Rate limit management for all API sources
4. Graceful degradation when sources are unavailable
5. Database performance tuning (indices, query optimization)
6. Automated testing: integration tests for all pipelines

**Why this is Phase 7:** Start with a working system, then make it robust. Building all the reliability infrastructure before proving the system works is premature.

---

## Not On the Roadmap (Explicit Non-Starters)

These are features explicitly not planned and not to be added without re-evaluating the non-goals:

- Trade execution engine
- Portfolio management
- Mobile app
- Multi-chain support (before Solana/Pump.fun is fully working)
- Full backtesting framework
- User account system / personalization

---

## Roadmap Maintenance

This roadmap should be updated when:
- A phase is completed (mark it complete, note what was actually built)
- Scope within a phase changes (document the change and why)
- A new phase needs to be added (append to the end; do not restructure earlier phases unless unavoidable)

Phase completion order is a recommendation, not a law. If Phase 3 dependencies resolve before Phase 2, re-evaluate the sequence. But don't skip phases — each phase provides necessary validation for the next.
