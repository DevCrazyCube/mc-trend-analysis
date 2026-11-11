import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Badge,
  Card,
  ErrorMsg,
  Loading,
  ScoreBar,
  SectionTitle,
  fmtDate,
  fmtPct,
  scoreColor,
} from '../components/ui'

// ---------------------------------------------------------------------------
// Tier badge
// ---------------------------------------------------------------------------

function tierBadge(tier: string) {
  if (tier === 'T1') return <Badge variant="green">T1 External</Badge>
  if (tier === 'T2') return <Badge variant="blue">T2 Social</Badge>
  if (tier === 'T3') return <Badge variant="yellow">T3 Echo</Badge>
  if (tier === 'T4') return <Badge variant="gray">T4 Noise</Badge>
  return <Badge variant="gray">{tier}</Badge>
}

// ---------------------------------------------------------------------------
// Classification badge
// ---------------------------------------------------------------------------

function clsBadge(cls: string) {
  if (cls === 'STRONG')   return <Badge variant="green">STRONG</Badge>
  if (cls === 'EMERGING') return <Badge variant="blue">EMERGING</Badge>
  if (cls === 'WEAK')     return <Badge variant="yellow">WEAK</Badge>
  if (cls === 'NOISE')    return <Badge variant="gray">NOISE</Badge>
  return <Badge variant="gray">{cls}</Badge>
}

// ---------------------------------------------------------------------------
// Pattern flag display
// ---------------------------------------------------------------------------

const FLAG_LABEL: Record<string, string> = {
  repeated:    '🔁 repeated',
  rapid_spawn: '⚡ rapid spawn',
  converging:  '🧠 converging',
}

function PatternFlags({ flags }: { flags: string[] }) {
  if (!flags || flags.length === 0) return null
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
      {flags.map(f => (
        <span
          key={f}
          style={{
            fontSize: 10,
            color: '#8b949e',
            background: 'rgba(139,148,158,0.1)',
            borderRadius: 3,
            padding: '1px 5px',
            whiteSpace: 'nowrap',
          }}
        >
          {FLAG_LABEL[f] ?? f}
        </span>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Token list (collapsed by default)
// ---------------------------------------------------------------------------

function TokenList({ tokens, clusters }: { tokens: any[]; clusters: any[] }) {
  const [open, setOpen] = useState(false)

  // Prefer cluster names if available
  const displayNames: string[] =
    clusters && clusters.length > 0
      ? clusters.flatMap((c: any) => c.names || [c.canonical_name])
      : (tokens || []).map((t: any) => t.name).filter(Boolean)

  if (displayNames.length === 0) return null

  return (
    <div style={{ marginTop: 6 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          background: 'none',
          border: 'none',
          color: '#58a6ff',
          cursor: 'pointer',
          fontSize: 11,
          padding: 0,
        }}
      >
        {open ? '▾' : '▸'} {displayNames.length} token{displayNames.length !== 1 ? 's' : ''}
      </button>
      {open && (
        <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {displayNames.slice(0, 20).map((name, i) => (
            <span
              key={i}
              style={{
                fontSize: 10,
                color: '#c9d1d9',
                background: '#21262d',
                borderRadius: 3,
                padding: '1px 5px',
              }}
            >
              {name}
            </span>
          ))}
          {displayNames.length > 20 && (
            <span style={{ fontSize: 10, color: '#6e7681' }}>
              +{displayNames.length - 20} more
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Velocity bar
// ---------------------------------------------------------------------------

function VelocityMini({ vel }: { vel: any }) {
  if (!vel) return null
  const accelColor =
    vel.acceleration === 'increasing' ? '#3fb950' :
    vel.acceleration === 'decreasing' ? '#f85149' : '#8b949e'

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, color: '#8b949e' }}>
      <span>5m: <strong style={{ color: '#c9d1d9' }}>{vel.tokens_last_5m}</strong></span>
      <span>15m: <strong style={{ color: '#c9d1d9' }}>{vel.tokens_last_15m}</strong></span>
      <span>60m: <strong style={{ color: '#c9d1d9' }}>{vel.tokens_last_60m}</strong></span>
      <span style={{ color: accelColor }}>
        {vel.acceleration === 'increasing' ? '▲' : vel.acceleration === 'decreasing' ? '▼' : '—'}
        {' '}{vel.acceleration}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Quality breakdown (collapsed by default)
// ---------------------------------------------------------------------------

function QualityDetail({ breakdown }: { breakdown: any }) {
  const [open, setOpen] = useState(false)
  if (!breakdown) return null

  const items = [
    { label: 'Source gravity', value: breakdown.source_gravity },
    { label: 'Source diversity', value: breakdown.source_diversity },
    { label: 'Social scale', value: breakdown.social_scale },
    { label: 'Velocity', value: breakdown.velocity },
    { label: 'Semantic gravity', value: breakdown.semantic_gravity },
    { label: 'Anti-spam', value: breakdown.anti_spam },
  ]

  return (
    <div style={{ marginTop: 4 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          background: 'none',
          border: 'none',
          color: '#58a6ff',
          cursor: 'pointer',
          fontSize: 11,
          padding: 0,
        }}
      >
        {open ? '▾' : '▸'} quality breakdown
      </button>
      {open && (
        <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {items.map(({ label, value }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
              <span style={{ color: '#8b949e', minWidth: 100 }}>{label}</span>
              <div style={{
                flex: 1,
                height: 6,
                background: '#21262d',
                borderRadius: 3,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${(value ?? 0) * 100}%`,
                  background: scoreColor(value ?? 0),
                  borderRadius: 3,
                }} />
              </div>
              <span style={{ color: '#c9d1d9', fontSize: 10, minWidth: 30, textAlign: 'right' }}>
                {fmtPct(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Narrative card
// ---------------------------------------------------------------------------

function NarrativeCard({ entry }: { entry: any }) {
  const vel = entry.velocity || {}
  const corr = entry.corroboration || {}
  const score = entry.narrative_score ?? 0
  const quality = entry.quality_score ?? 0

  return (
    <Card style={{ marginBottom: 10 }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#c9d1d9' }}>{entry.term}</span>
        {entry.tier && tierBadge(entry.tier)}
        {clsBadge(entry.classification)}
        {corr.x_confirmed && (
          <span style={{ fontSize: 10, color: '#bc8cff' }}>
            X ({corr.x_authors || 0} authors)
          </span>
        )}
        {corr.news_confirmed && (
          <span style={{ fontSize: 10, color: '#58a6ff' }}>
            news ({corr.news_articles || 0})
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: scoreColor(score), fontWeight: 600 }}>
          {(score * 100).toFixed(0)}
        </span>
      </div>

      {/* Score + Quality bars */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
        <div style={{ flex: 1 }}>
          <ScoreBar label="Score" value={score} />
        </div>
        <div style={{ flex: 1 }}>
          <ScoreBar label="Quality" value={quality} />
        </div>
      </div>

      {/* Tier reason */}
      {entry.tier_reason && (
        <div style={{ fontSize: 10, color: '#6e7681', marginBottom: 4, fontStyle: 'italic' }}>
          {entry.tier_reason}
        </div>
      )}

      {/* Velocity */}
      <VelocityMini vel={vel} />

      {/* Pattern flags */}
      <PatternFlags flags={entry.pattern_flags || []} />

      {/* Token list (collapsed) */}
      <TokenList tokens={entry.tokens || []} clusters={entry.token_clusters || []} />

      {/* Quality breakdown (collapsed) */}
      <QualityDetail breakdown={entry.quality_breakdown} />

      {/* Reason */}
      <div style={{ marginTop: 8, fontSize: 11, color: '#6e7681', lineHeight: 1.5 }}>
        {entry.reason}
      </div>

      {/* Meta row */}
      <div style={{ marginTop: 6, fontSize: 10, color: '#484f58', display: 'flex', gap: 12 }}>
        <span>first: {fmtDate(entry.first_seen)}</span>
        <span>last: {fmtDate(entry.last_seen)}</span>
        <span>{entry.token_count} tokens total</span>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function NarrativeExplorer() {
  const [board, setBoard] = useState<any[]>([])
  const [meta, setMeta] = useState<any>({})
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [classFilter, setClassFilter] = useState('')
  const [tierFilter, setTierFilter] = useState('')
  const [includeNoise, setIncludeNoise] = useState(false)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const res = await api.narrativeBoard(
          classFilter || undefined,
          includeNoise,
          tierFilter || undefined,
        )
        setBoard(res.board || [])
        setMeta({
          count: res.count,
          total: res.total_candidates,
          counts: res.classification_counts || {},
          tierCounts: res.tier_counts || {},
        })
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    load()
  }, [classFilter, tierFilter, includeNoise])

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const counts = meta.counts || {}
  const tierCounts = meta.tierCounts || {}

  return (
    <div>
      <SectionTitle
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 11, color: '#8b949e', display: 'flex', gap: 4, alignItems: 'center' }}>
              <input
                type="checkbox"
                checked={includeNoise}
                onChange={e => setIncludeNoise(e.target.checked)}
                style={{ accentColor: '#58a6ff' }}
              />
              show noise
            </label>
            <select
              value={tierFilter}
              onChange={e => setTierFilter(e.target.value)}
              style={{
                background: '#21262d', color: '#c9d1d9',
                border: '1px solid #30363d', borderRadius: 4,
                padding: '4px 8px', fontSize: 12,
              }}
            >
              <option value="">All tiers</option>
              {['T1', 'T2', 'T3', 'T4'].map(t => (
                <option key={t} value={t}>
                  {t} {tierCounts[t] ? `(${tierCounts[t]})` : ''}
                </option>
              ))}
            </select>
            <select
              value={classFilter}
              onChange={e => setClassFilter(e.target.value)}
              style={{
                background: '#21262d', color: '#c9d1d9',
                border: '1px solid #30363d', borderRadius: 4,
                padding: '4px 8px', fontSize: 12,
              }}
            >
              <option value="">All classes</option>
              {['STRONG', 'EMERGING', 'WEAK', 'NOISE'].map(c => (
                <option key={c} value={c}>
                  {c} {counts[c] ? `(${counts[c]})` : ''}
                </option>
              ))}
            </select>
          </div>
        }
      >
        Narrative Board ({meta.count ?? board.length})
      </SectionTitle>

      {/* Tier + classification summary bar */}
      {meta.total > 0 && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, fontSize: 11, color: '#8b949e', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 8 }}>
            {tierCounts.T1 > 0 && <span><strong style={{ color: '#3fb950' }}>{tierCounts.T1}</strong> T1</span>}
            {tierCounts.T2 > 0 && <span><strong style={{ color: '#58a6ff' }}>{tierCounts.T2}</strong> T2</span>}
            {tierCounts.T3 > 0 && <span><strong style={{ color: '#d2a317' }}>{tierCounts.T3}</strong> T3</span>}
            {tierCounts.T4 > 0 && <span><strong style={{ color: '#484f58' }}>{tierCounts.T4}</strong> T4</span>}
          </div>
          <span style={{ color: '#30363d' }}>|</span>
          <div style={{ display: 'flex', gap: 8 }}>
            {counts.STRONG > 0 && <span><strong style={{ color: '#3fb950' }}>{counts.STRONG}</strong> STRONG</span>}
            {counts.EMERGING > 0 && <span><strong style={{ color: '#58a6ff' }}>{counts.EMERGING}</strong> EMERGING</span>}
            {counts.WEAK > 0 && <span><strong style={{ color: '#d2a317' }}>{counts.WEAK}</strong> WEAK</span>}
            {counts.NOISE > 0 && <span><strong style={{ color: '#484f58' }}>{counts.NOISE}</strong> NOISE</span>}
          </div>
          <span style={{ marginLeft: 'auto' }}>{meta.total} candidates total</span>
        </div>
      )}

      {board.length === 0 ? (
        <div style={{ padding: 32, color: '#6e7681', textAlign: 'center', fontSize: 13 }}>
          No narratives detected yet. Waiting for token stream data.
        </div>
      ) : (
        board.map((entry: any) => (
          <NarrativeCard key={entry.candidate_id} entry={entry} />
        ))
      )}
    </div>
  )
}
