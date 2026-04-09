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
  scoreColor,
} from '../components/ui'

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
// Narrative card
// ---------------------------------------------------------------------------

function NarrativeCard({ entry }: { entry: any }) {
  const vel = entry.velocity || {}
  const corr = entry.corroboration || {}
  const score = entry.narrative_score ?? 0

  return (
    <Card style={{ marginBottom: 10 }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#c9d1d9' }}>{entry.term}</span>
        {clsBadge(entry.classification)}
        {corr.x_confirmed && (
          <span style={{ fontSize: 10, color: '#bc8cff' }}>X corroborated</span>
        )}
        {corr.news_confirmed && (
          <span style={{ fontSize: 10, color: '#58a6ff' }}>news</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: scoreColor(score), fontWeight: 600 }}>
          {(score * 100).toFixed(0)}
        </span>
      </div>

      {/* Score bar */}
      <div style={{ marginBottom: 8 }}>
        <ScoreBar value={score} />
      </div>

      {/* Velocity */}
      <VelocityMini vel={vel} />

      {/* Pattern flags */}
      <PatternFlags flags={entry.pattern_flags || []} />

      {/* Token list (collapsed) */}
      <TokenList tokens={entry.tokens || []} clusters={entry.token_clusters || []} />

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
  const [includeNoise, setIncludeNoise] = useState(false)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const res = await api.narrativeBoard(classFilter || undefined, includeNoise)
        setBoard(res.board || [])
        setMeta({
          count: res.count,
          total: res.total_candidates,
          counts: res.classification_counts || {},
        })
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    load()
  }, [classFilter, includeNoise])

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const counts = meta.counts || {}

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
              value={classFilter}
              onChange={e => setClassFilter(e.target.value)}
              style={{
                background: '#21262d', color: '#c9d1d9',
                border: '1px solid #30363d', borderRadius: 4,
                padding: '4px 8px', fontSize: 12,
              }}
            >
              <option value="">All</option>
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

      {/* Classification summary bar */}
      {meta.total > 0 && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, fontSize: 11, color: '#8b949e' }}>
          {counts.STRONG > 0 && <span><strong style={{ color: '#3fb950' }}>{counts.STRONG}</strong> STRONG</span>}
          {counts.EMERGING > 0 && <span><strong style={{ color: '#58a6ff' }}>{counts.EMERGING}</strong> EMERGING</span>}
          {counts.WEAK > 0 && <span><strong style={{ color: '#d2a317' }}>{counts.WEAK}</strong> WEAK</span>}
          {counts.NOISE > 0 && <span><strong style={{ color: '#484f58' }}>{counts.NOISE}</strong> NOISE</span>}
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
