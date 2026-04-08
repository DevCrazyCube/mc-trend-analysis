# Event Ingestion

This document defines how external events, news, and cultural trends are ingested, processed, and maintained as active narratives.

---

## What an Event Record Represents

An `EventRecord` in this system represents a detected real-world narrative or trend moment — not just a single article or post. Multiple source signals pointing to the same topic are grouped into a single event record.

Think of it as: "the world is talking about X" — and the event record is the system's representation of that fact, backed by citations from multiple sources.

---

## Event Sources

Events enter the system from several source types (see `docs/ingestion/source-types.md` for full detail):

| Source | Signal Type | Polling Cadence |
|---|---|---|
| Search trend APIs | Trending search terms + volume | Every 15–30 min |
| News aggregator APIs | Published articles + entity extraction | Every 5–10 min |
| Mainstream news feeds | Major event coverage | Every 5–10 min |
| Crypto-native news | Crypto-specific events | Every 5 min |
| Public social platforms | Trending topics, viral content | Every 2–5 min |

---

## Event Detection Pipeline

### Step 1: Raw Signal Collection

Each source adapter polls or streams its source and produces raw signal records. These are not yet events — they are raw signals.

A raw signal from search trends looks like:
```
{
  source: "google-trends",
  term: "deepmind",
  relative_volume: 89,  // on a 0-100 scale
  region: "US",
  sampled_at: "2024-10-15T14:30:00Z"
}
```

A raw signal from a news API looks like:
```
{
  source: "newsapi",
  headline: "Google DeepMind announces Gemini Ultra 2",
  entities: ["Google", "DeepMind", "Gemini", "AI"],
  url: "...",
  published_at: "2024-10-15T14:12:00Z",
  outlet_trust_tier: 2
}
```

---

### Step 2: Term and Entity Extraction

Key terms and named entities are extracted from each raw signal. The extraction goal is to produce a set of **anchor terms** — the words that will be matched against token names.

**Extraction priority:**
1. Named entities (proper nouns: people, companies, products)
2. Capitalized unique terms (event-specific jargon)
3. High-frequency context terms (supporting context, lower weight)

**Extraction methods:**
- For news/text: NLP entity recognition (specific tool is implementation detail)
- For search trends: the trending term itself is the anchor
- For social: hashtags and high-frequency terms in the signal

**Extraction quality:**
- Each extracted term is assigned an extraction confidence score
- Low-confidence extractions are included but marked with `low_confidence: true`
- Ambiguous terms that match many possible narratives are flagged with `ambiguous: true`

---

### Step 3: Event Deduplication and Grouping

Multiple signals about the same topic should produce one event record, not many.

**Grouping criteria:**
- If two signals share anchor terms AND fall within a 2-hour time window → same event
- If the same story appears across multiple news outlets → same event (different sources)
- If a trending search term is a subset of an existing event's terms → potentially merge (with confidence threshold)

**Deduplication keys:**
- Primary: exact anchor term match
- Secondary: entity co-occurrence (two signals share 2+ of the same named entities)

When signals are grouped into an event, the event record's `sources[]` array is extended. Confidence and attention scores are recalculated based on the combined signal.

---

### Step 4: Narrative Strength Scoring

The freshly created or updated event record receives an attention strength score based on:

- Number of independent source types reporting (more types = higher score)
- Volume/magnitude of each source's signal
- Recency of the signals (weighted toward most recent)

See `docs/intelligence/scoring-model.md` Dimension 5 (Attention Strength) for the full scoring definition.

---

## Event Record Schema

```
EventRecord {
  // Identity
  narrative_id: string (internal UUID),
  anchor_terms: [string],  // primary matching terms
  related_terms: [string], // secondary matching terms
  entities: [{ name: string, type: string, confidence: float }],
  description: string,  // human-readable summary of the narrative

  // Source tracking
  sources: [
    {
      source_id: string,
      source_type: string,
      source_name: string,
      signal_strength: float,
      first_seen: timestamp,
      last_updated: timestamp,
      raw_reference: string  // URL or identifier for audit
    }
  ],

  // Scoring state
  attention_score: float,  // current computed attention strength
  narrative_velocity: float,  // rate of change in attention (positive = growing)
  source_type_count: int,   // number of distinct source types

  // Lifecycle
  state: "EMERGING" | "PEAKING" | "DECLINING" | "DEAD",
  first_detected: timestamp,
  peaked_at: timestamp | null,
  dead_at: timestamp | null,
  updated_at: timestamp,

  // Data quality
  extraction_confidence: float,  // average confidence of term extractions
  ambiguous: bool,  // true if terms could match multiple distinct narratives
  data_gaps: [string]
}
```

---

## Narrative Lifecycle Management

Events are not static. The system tracks their lifecycle and updates state:

**EMERGING:** Narrative first detected within last 2 hours. Attention velocity is positive. New signals still arriving.

**PEAKING:** Attention magnitude at or near maximum. Velocity has slowed or turned flat. The narrative is at peak attention but not yet decaying.

**DECLINING:** Attention is measurably below peak (> 20% drop). New sources no longer mentioning the topic. Velocity is negative.

**DEAD:** Attention below minimum threshold across all sources. No new signals in the last N hours (configurable; default: 3 hours for fast-moving narratives).

**State transition logic:**
```
if velocity > 0 and age < EMERGING_WINDOW:
    state = EMERGING
elif velocity <= 0 and attention > PEAK_THRESHOLD:
    state = PEAKING
elif attention < peak_attention * 0.8:
    state = DECLINING
elif last_signal_age > DEAD_THRESHOLD:
    state = DEAD
```

Thresholds are configurable. Initial values are heuristics and should be calibrated against observed narrative behavior.

---

## Handling Fast-Decaying Narratives

Some narratives peak and die within 2–4 hours (viral social moments). Others sustain for days (major news events).

The system does not distinguish types upfront. Lifecycle state is tracked reactively.

**Implication for scoring:** A narrative in DECLINING state still exists as an event record. Tokens linked to it receive low timing quality scores, reflecting that the narrative window may be closing. The event record is not deleted — it is retained for calibration and historical analysis.

---

## Handling Duplicate / Near-Duplicate Narratives

Sometimes multiple events have overlapping anchor terms that are genuinely distinct:

Example: "GEMINI" → could be Google's AI model, the Gemini DEX, or the Gemini zodiac sign.

**Handling:**
- Create separate event records for each distinct semantic topic
- Mark anchor terms that appear in multiple records as `collision_risk: true`
- The correlation engine handles token matching to specific event records; it is not the event ingestion pipeline's job to resolve which narrative a token belongs to

---

## Event Ingestion Rate and Volume

Expect: dozens of potential narrative signals per hour on average, with spikes of hundreds per hour during major global events.

Most raw signals will not produce new event records — they will update existing ones (adding a new source, updating attention scores).

Genuinely new events (new narrative detected) are expected at a rate of 5–30 per day depending on the global news cycle.
