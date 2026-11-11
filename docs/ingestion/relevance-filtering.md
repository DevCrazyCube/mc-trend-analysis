# Narrative Relevance Filtering

Relevance filtering is a quality gate applied at two points in the ingestion pipeline. Its purpose is to prevent irrelevant articles (sports, politics, entertainment, generic culture) from becoming narratives, and to prevent weak or off-topic narratives from contaminating the token linking and scoring steps.

**This is not content moderation.** It is signal triage — keeping the intelligence system focused on the space it was built to reason about: crypto tokens, market activity, and community-driven narratives.

---

## Why This Exists

NewsAPI returns a broad mix of content when queried with terms like "viral" or "trending." A single query cycle can return articles about sports championships, celebrity gossip, political events, and generic pop culture — none of which are meaningful signals for Pump.fun token trends. Without filtering:

- Spurious narratives fill the DB (e.g., "Super Bowl", "Oscars")
- These narratives accumulate sources from unrelated articles
- Tokens get linked to irrelevant narratives
- Scores are corrupted by meaningless narrative_relevance signals
- The competition layer has to suppress more noise, which means legitimate winners may not form

---

## Architecture

```
fetch_events()          → raw_events[]
    ↓
[Article Gate]          → score_article_relevance(title, description, source_name)
    ↓ reject if below articles_min_relevance_score
    ↓ count: articles_rejected_irrelevant
normalize_event()       → narrative dict in DB (state=WEAK)
    ↓
[Narrative Gate]        → score_narrative_relevance(anchor_terms, description)
    ↓ reject if below narratives_min_relevance_score
    ↓ count: narratives_blocked_low_relevance
correlate_token()       → token-narrative links
```

---

## Scoring Logic

Both gates use the same underlying scoring function. The score is a float in [0.0, 1.0].

### Positive Signals

The article/narrative text is scanned for terms that indicate crypto/market relevance. Terms are weighted by category:

| Category | Weight | Examples |
|----------|--------|---------|
| Token launch platform | 1.0 | pump.fun, pumpfun, pumpportal |
| Core crypto | 0.8 | crypto, cryptocurrency, bitcoin, ethereum, solana, sol, defi, nft, web3, blockchain |
| Token/market activity | 0.7 | token, coin, memecoin, meme, pump, dump, rug, mint, launch, liquidity, holder, wallet, exchange, trading, market, ath, moonshot |
| Community/degen | 0.5 | degen, ape, moonshot, pepe, wif, bonk, shib, doge, altcoin, shill |

Score is computed as: `min(sum_of_weighted_hits / positive_saturation, 1.0)` where `positive_saturation` is the minimum total weight needed to reach score 1.0 (configurable, default 1.5).

### Veto Categories

If the article primarily discusses a known off-topic domain with no crypto context, it is vetoed. A veto applies when:
- One or more veto category terms are present in the text, **and**
- The crypto signal score is below `veto_override_threshold` (default 0.15)

| Veto Category | Example terms |
|---------------|--------------|
| Sports | nba, nfl, mlb, fifa, championship, super bowl, world cup, touchdown, home run, playoffs |
| Politics | election, senate, congress, president, white house, democrat, republican, supreme court, legislation |
| Entertainment | oscars, grammys, emmys, box office, album release, concert tour, red carpet |
| Generic culture | recipe, cooking, food festival, fashion week |

A veto reduces the score to a fixed low value (default 0.02) rather than 0.0. This allows the threshold to distinguish a vetoed article from a structurally empty one.

### Final Score

```
score = positive_score(text)
if veto_hit(text) and score < veto_override_threshold:
    score = veto_penalized_score  # default 0.02
return min(max(score, 0.0), 1.0)
```

### Determinism

The scoring function is purely deterministic: same inputs → same output. No LLM, no API call. Configurable vocabulary lists are loaded from settings at startup.

---

## Configuration

All thresholds live in `settings.narrative_intelligence` (via `NarrativeIntelligenceConfig`) — no hardcoded values in scoring code.

| Setting | Default | Meaning |
|---------|---------|---------|
| `articles_min_relevance_score` | 0.20 | Minimum score for a raw article to pass the article gate |
| `narratives_min_relevance_score` | 0.15 | Minimum score for a narrative to pass the narrative gate (lower because narratives may have accumulated from multiple sources) |
| `relevance_positive_saturation` | 1.5 | Sum of positive term weights that yields score 1.0 |
| `relevance_veto_override_threshold` | 0.15 | Crypto signal above this prevents a veto from applying |

These defaults are deliberately conservative — they will block clear sports/politics articles while allowing borderline crypto-culture overlap.

---

## NewsAPI Rate Limit Cooldown

When NewsAPI returns HTTP 429 (Too Many Requests), the adapter enters a per-source cooldown:

1. Each 429 response increments a consecutive-429 counter
2. After `newsapi_rate_limit_cooldown_after` consecutive 429s (default 2), the adapter enters cooldown
3. During cooldown, `fetch()` returns an empty list immediately without making network calls
4. Cooldown duration follows exponential backoff: `base * 2^n` where n = cooldown episodes so far
5. Base duration is `newsapi_rate_limit_cooldown_seconds` (default 60.0 seconds)
6. Maximum cooldown duration is `newsapi_rate_limit_max_cooldown_seconds` (default 900.0 = 15 minutes)
7. A source gap is opened when cooldown starts and closed when the next successful fetch occurs
8. The cooldown state is observable via `GET /api/health` (`last_cycle.source_cooldown_active`)

This prevents the system from hammering a 429 source every pipeline cycle. A source in cooldown is silent but not broken — it will recover automatically.

---

## Tightened Query Strategy

Default NewsAPI query terms are changed from broad single words to compound, market-specific queries:

**Old defaults** (too broad):
- `"crypto"`, `"meme"`, `"viral"`, `"trending"`

**New defaults** (narrower):
- `"solana token launch"`
- `"memecoin crypto"`
- `"pump.fun token"`
- `"crypto market token"`

These produce fewer, more relevant articles per cycle. The `news_query_terms` setting in settings.py is still fully overridable.

Operators can also configure `newsapi_domains` (comma-separated list of domains like `"coindesk.com,cointelegraph.com"`) to restrict results to known crypto news sources. This is empty by default.

---

## Observability

The pipeline summary dict exposes the following relevance-related counters:

| Key | Meaning |
|-----|---------|
| `articles_fetched` | Total raw articles returned by event adapters before any gating |
| `articles_rejected_irrelevant` | Articles that failed the article gate (below `articles_min_relevance_score`) |
| `narratives_blocked_low_relevance` | Existing narratives blocked from token linking by the narrative gate |
| `source_cooldown_active` | Number of sources currently in rate-limit cooldown |

These counters are included in `GET /api/health` (`last_cycle`) and broadcast via SSE on `cycle_complete`.

---

## What This Does Not Do

- **Does not replace narrative strength gating.** Relevance is a separate signal from narrative lifecycle state. An article can be highly relevant but still produce a WEAK narrative that the intelligence engine correctly keeps off alert lists.
- **Does not score token quality.** Tokens are still evaluated through the full 6-dimension scoring pipeline.
- **Does not use an LLM.** All decisions are deterministic. This is intentional — per `docs/rules/engineering-rules.md`.
- **Does not block legitimate crypto-adjacent content.** If a sports figure (e.g., an athlete) launches a Solana token, that article will have sufficient crypto signal to pass the gate, and the veto override threshold prevents the sports veto from applying.
