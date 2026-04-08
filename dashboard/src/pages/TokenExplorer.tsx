import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Badge,
  Card,
  ErrorMsg,
  Loading,
  ScoreBar,
  SectionTitle,
  Table,
  alertTypeBadge,
  fmtDate,
  fmtPct,
  riskColor,
  scoreColor,
  shortAddr,
} from '../components/ui'

function statusBadge(s: string) {
  if (s === 'new') return <Badge variant="blue">new</Badge>
  if (s === 'linked') return <Badge variant="purple">linked</Badge>
  if (s === 'scored') return <Badge variant="orange">scored</Badge>
  if (s === 'alerted') return <Badge variant="green">alerted</Badge>
  if (s === 'expired') return <Badge variant="gray">expired</Badge>
  if (s === 'discarded') return <Badge variant="red">discarded</Badge>
  return <Badge variant="gray">{s}</Badge>
}

export function TokenExplorer() {
  const [tokens, setTokens] = useState<any[]>([])
  const [filter, setFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [selected, setSelected] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.tokens(filter || undefined, 100)
        setTokens(res.tokens || [])
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    load()
  }, [filter])

  const openDetail = async (token: any) => {
    setSelected(token)
    setDetailLoading(true)
    try {
      const d = await api.token(token.token_id)
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
      {/* Token list */}
      <div>
        <SectionTitle
          right={
            <select
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{ background: '#21262d', color: '#c9d1d9', border: '1px solid #30363d', borderRadius: 4, padding: '4px 8px', fontSize: 12 }}
            >
              <option value="">All statuses</option>
              {['new','linked','scored','alerted','expired','discarded'].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          }
        >
          Tokens ({tokens.length})
        </SectionTitle>

        <Card style={{ padding: 0 }}>
          <Table
            headers={['Name', 'Symbol', 'Status', 'Platform', 'Launched']}
            emptyMsg="No tokens found. Run the pipeline or inject demo data."
            rows={tokens.map(t => [
              <span
                style={{ color: '#58a6ff', cursor: 'pointer' }}
                onClick={() => openDetail(t)}
              >
                {t.name}
              </span>,
              <code style={{ background: '#21262d', padding: '1px 5px', borderRadius: 3, fontSize: 11 }}>{t.symbol}</code>,
              statusBadge(t.status),
              <span style={{ fontSize: 11, color: '#6e7681' }}>{t.launch_platform || '—'}</span>,
              <span style={{ fontSize: 11, color: '#484f58' }}>{fmtDate(t.launch_time)}</span>,
            ])}
          />
        </Card>
      </div>

      {/* Token detail */}
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
            {selected.name}
          </SectionTitle>

          {detailLoading ? (
            <Loading />
          ) : detail?.error ? (
            <ErrorMsg msg={detail.error} />
          ) : detail ? (
            <TokenDetail detail={detail} />
          ) : null}
        </div>
      )}
    </div>
  )
}

function TokenDetail({ detail }: { detail: any }) {
  const { token, chain_snapshot, links, scores, alerts } = detail

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Identifiers */}
      <Card>
        <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Identifiers</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
          <div><span style={{ color: '#6e7681' }}>Address: </span>{shortAddr(token.address)}</div>
          <div><span style={{ color: '#6e7681' }}>Deployer: </span>{shortAddr(token.deployed_by)}</div>
          <div><span style={{ color: '#6e7681' }}>Platform: </span>{token.launch_platform || '—'}</div>
          <div><span style={{ color: '#6e7681' }}>Launched: </span>{fmtDate(token.launch_time)}</div>
          <div><span style={{ color: '#6e7681' }}>Mint auth: </span>{token.mint_authority_status || '—'}</div>
          <div><span style={{ color: '#6e7681' }}>Freeze auth: </span>{token.freeze_authority_status || '—'}</div>
        </div>
        {token.data_gaps?.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 11, color: '#d2a317' }}>
            Data gaps: {token.data_gaps.join(', ')}
          </div>
        )}
      </Card>

      {/* Chain snapshot */}
      {chain_snapshot && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>
            Chain Snapshot — {fmtDate(chain_snapshot.sampled_at)}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 12 }}>
            <div><span style={{ color: '#6e7681' }}>Holders: </span>{chain_snapshot.holder_count ?? '—'}</div>
            <div><span style={{ color: '#6e7681' }}>Liquidity: </span>${(chain_snapshot.liquidity_usd || 0).toLocaleString()}</div>
            <div><span style={{ color: '#6e7681' }}>Top 5 pct: </span>{fmtPct(chain_snapshot.top_5_holder_pct)}</div>
            <div><span style={{ color: '#6e7681' }}>Top 10 pct: </span>{fmtPct(chain_snapshot.top_10_holder_pct)}</div>
            <div><span style={{ color: '#6e7681' }}>Vol 1h: </span>${(chain_snapshot.volume_1h_usd || 0).toLocaleString()}</div>
            <div><span style={{ color: '#6e7681' }}>Liq locked: </span>{chain_snapshot.liquidity_locked ? 'Yes' : 'No'}</div>
          </div>
        </Card>
      )}

      {/* Scores */}
      {scores.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 10 }}>Score Breakdown</div>
          {scores.slice(0, 1).map((s: any) => (
            <div key={s.score_id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <ScoreBar label="Narrative relevance" value={s.narrative_relevance} />
              <ScoreBar label="OG score" value={s.og_score} />
              <ScoreBar label="Rug risk" value={s.rug_risk} color={riskColor(s.rug_risk)} />
              <ScoreBar label="Momentum" value={s.momentum_quality} />
              <ScoreBar label="Attention" value={s.attention_strength} />
              <ScoreBar label="Timing" value={s.timing_quality} />
              <div style={{ borderTop: '1px solid #21262d', marginTop: 4, paddingTop: 6 }}>
                <ScoreBar label="Net potential" value={s.net_potential} color={scoreColor(s.net_potential)} />
                <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11 }}>
                  <span style={{ color: '#6e7681' }}>P_potential: <span style={{ color: '#c9d1d9' }}>{fmtPct(s.p_potential)}</span></span>
                  <span style={{ color: '#6e7681' }}>P_failure: <span style={{ color: riskColor(s.p_failure) }}>{fmtPct(s.p_failure)}</span></span>
                  <span style={{ color: '#6e7681' }}>Confidence: <span style={{ color: '#c9d1d9' }}>{fmtPct(s.confidence_score)}</span></span>
                </div>
              </div>
              {s.risk_flags?.length > 0 && (
                <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {s.risk_flags.map((f: string, i: number) => (
                    <Badge key={i} variant="red">{f}</Badge>
                  ))}
                </div>
              )}
              {s.data_gaps?.length > 0 && (
                <div style={{ fontSize: 11, color: '#d2a317' }}>
                  Data gaps affecting score: {s.data_gaps.join(', ')}
                </div>
              )}
            </div>
          ))}
        </Card>
      )}

      {/* Links */}
      {links.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Narrative Links ({links.length})</div>
          {links.map((l: any, i: number) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: 12 }}>
              <div style={{ color: '#c9d1d9' }}>{l.narrative_description || l.narrative_id}</div>
              <div style={{ color: '#6e7681', fontSize: 11 }}>
                match: {fmtPct(l.match_confidence)} via {l.match_method}
                {l.og_rank != null && ` — OG rank #${l.og_rank} (${fmtPct(l.og_score)})`}
              </div>
            </div>
          ))}
        </Card>
      )}

      {/* Alerts */}
      {alerts.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Alert History ({alerts.length})</div>
          {alerts.map((a: any, i: number) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: 12, display: 'flex', gap: 10 }}>
              <Badge variant={alertTypeBadge(a.alert_type)}>{a.alert_type}</Badge>
              <span style={{ color: '#6e7681' }}>net: {fmtPct(a.net_potential)}</span>
              <span style={{ color: a.status === 'active' ? '#3fb950' : '#6e7681' }}>{a.status}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
