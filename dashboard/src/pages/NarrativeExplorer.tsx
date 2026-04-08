import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Badge,
  Card,
  ErrorMsg,
  Loading,
  SectionTitle,
  Table,
  fmtDate,
  fmtPct,
  shortAddr,
} from '../components/ui'

function stateBadge(state: string) {
  if (state === 'EMERGING') return <Badge variant="green">EMERGING</Badge>
  if (state === 'PEAKING') return <Badge variant="orange">PEAKING</Badge>
  if (state === 'DECLINING') return <Badge variant="yellow">DECLINING</Badge>
  if (state === 'DEAD') return <Badge variant="gray">DEAD</Badge>
  return <Badge variant="gray">{state}</Badge>
}

export function NarrativeExplorer() {
  const [narratives, setNarratives] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.narratives(filter || undefined)
        setNarratives(res.narratives || [])
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    load()
  }, [filter])

  const openDetail = async (n: any) => {
    setSelected(n)
    setDetailLoading(true)
    try {
      const d = await api.narrative(n.narrative_id)
      setDetail(d)
    } catch (e: any) {
      setDetail({ error: e.message })
    } finally {
      setDetailLoading(false)
    }
  }

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  return (
    <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 1fr' : '1fr', gap: 16 }}>
      <div>
        <SectionTitle
          right={
            <select
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{ background: '#21262d', color: '#c9d1d9', border: '1px solid #30363d', borderRadius: 4, padding: '4px 8px', fontSize: 12 }}
            >
              <option value="">All states</option>
              {['EMERGING','PEAKING','DECLINING','DEAD'].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          }
        >
          Narratives ({narratives.length})
        </SectionTitle>

        <Card style={{ padding: 0 }}>
          <Table
            headers={['Description', 'State', 'Attention', 'Sources', 'Detected']}
            emptyMsg="No narratives found."
            rows={narratives.map(n => [
              <span
                style={{ color: '#58a6ff', cursor: 'pointer' }}
                onClick={() => openDetail(n)}
              >
                {n.description || n.anchor_terms?.join(' ')}
              </span>,
              stateBadge(n.state),
              <span style={{ color: '#c9d1d9' }}>{fmtPct(n.attention_score)}</span>,
              <span style={{ fontSize: 11, color: '#6e7681' }}>{n.source_type_count ?? 1}</span>,
              <span style={{ fontSize: 11, color: '#484f58' }}>{fmtDate(n.first_detected)}</span>,
            ])}
          />
        </Card>
      </div>

      {selected && (
        <div>
          <SectionTitle
            right={
              <button
                onClick={() => { setSelected(null); setDetail(null) }}
                style={{ background: 'none', border: 'none', color: '#6e7681', cursor: 'pointer', fontSize: 12 }}
              >
                ✕ Close
              </button>
            }
          >
            Narrative Detail
          </SectionTitle>

          {detailLoading ? (
            <Loading />
          ) : detail?.error ? (
            <ErrorMsg msg={detail.error} />
          ) : detail ? (
            <NarrativeDetail detail={detail} />
          ) : null}
        </div>
      )}
    </div>
  )
}

function NarrativeDetail({ detail }: { detail: any }) {
  const { narrative, linked_tokens } = detail

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card>
        <div style={{ fontSize: 13, color: '#c9d1d9', marginBottom: 12 }}>
          {narrative.description}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
          {(narrative.anchor_terms || []).map((t: string) => (
            <Badge key={t} variant="blue">{t}</Badge>
          ))}
        </div>
        {narrative.related_terms?.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {narrative.related_terms.map((t: string) => (
              <Badge key={t} variant="gray">{t}</Badge>
            ))}
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
          <div><span style={{ color: '#6e7681' }}>State: </span>{narrative.state}</div>
          <div><span style={{ color: '#6e7681' }}>Attention: </span>{fmtPct(narrative.attention_score)}</div>
          <div><span style={{ color: '#6e7681' }}>Velocity: </span>{(narrative.narrative_velocity || 0).toFixed(2)}</div>
          <div><span style={{ color: '#6e7681' }}>Sources: </span>{narrative.source_type_count ?? 1}</div>
          <div><span style={{ color: '#6e7681' }}>First detected: </span>{fmtDate(narrative.first_detected)}</div>
          <div><span style={{ color: '#6e7681' }}>Updated: </span>{fmtDate(narrative.updated_at)}</div>
        </div>
      </Card>

      {/* Sources */}
      {narrative.sources?.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Source Evidence</div>
          {narrative.sources.map((s: any, i: number) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: 12 }}>
              <div style={{ color: '#c9d1d9' }}>{s.source_name} ({s.source_type})</div>
              <div style={{ color: '#6e7681', fontSize: 11 }}>
                signal: {fmtPct(s.signal_strength)} — {fmtDate(s.first_seen)}
              </div>
            </div>
          ))}
        </Card>
      )}

      {/* Linked tokens (OG ranking) */}
      {linked_tokens?.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>
            Linked Tokens — OG Ranking
          </div>
          {linked_tokens.map((l: any, i: number) => (
            <div
              key={i}
              style={{
                padding: '7px 0',
                borderBottom: '1px solid #21262d',
                fontSize: 12,
                display: 'flex',
                gap: 10,
                alignItems: 'center',
              }}
            >
              {l.og_rank != null && (
                <span
                  style={{
                    minWidth: 24,
                    textAlign: 'center',
                    fontWeight: 700,
                    color: l.og_rank === 1 ? '#f0883e' : '#6e7681',
                  }}
                >
                  #{l.og_rank}
                </span>
              )}
              <div style={{ flex: 1 }}>
                <div style={{ color: '#c9d1d9' }}>{l.token_name} ({l.token_symbol})</div>
                <div style={{ fontSize: 11, color: '#6e7681' }}>
                  {shortAddr(l.token_address)} — match: {fmtPct(l.match_confidence)}
                  {l.og_score != null && ` — OG score: ${fmtPct(l.og_score)}`}
                </div>
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
