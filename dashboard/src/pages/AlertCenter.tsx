/**
 * Alert Center — narrative-grouped view.
 *
 * Primary table: one row per narrative cluster (grouped by narrative_id).
 * Each row: narrative name, dominant alert type, confidence, token_count,
 *   alert_count, last_seen.
 *
 * Detail panel: narrative board data (live, from /api/narratives/board) +
 *   child token alerts (from the group's alerts list).
 *
 * Confidence shown here is max(confidence_score) within the group, which
 * varies once the pipeline's _build_narrative_data fix is in effect. For
 * legacy rows still showing ~47.5%, the board's narrative_score (labeled
 * "Narrative Score") is shown alongside as the more discriminative metric.
 */

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

function tierBadge(tier: string) {
  if (tier === 'T1') return <Badge variant="green">T1</Badge>
  if (tier === 'T2') return <Badge variant="blue">T2</Badge>
  if (tier === 'T3') return <Badge variant="yellow">T3</Badge>
  if (tier === 'T4') return <Badge variant="gray">T4</Badge>
  return null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function alertTypeBadgeVariant(type: string) {
  return alertTypeBadge(type)
}

function dominantBadge(type: string) {
  return <Badge variant={alertTypeBadgeVariant(type)}>{type.replace(/_/g, ' ')}</Badge>
}

function statusBadge(s: string) {
  return <Badge variant={s === 'active' ? 'green' : 'gray'}>{s}</Badge>
}

// Find the best matching board entry for a narrative group.
// Match on: narrative_name contains a board term OR a token name in the group
// appears in the board entry's token list.
function findBoardEntry(group: any, board: any[]): any | null {
  const name = (group.narrative_name || '').toUpperCase()
  const tokenNames = new Set(
    (group.token_names || []).map((n: string) => n.toUpperCase())
  )
  for (const entry of board) {
    const term = (entry.term || '').toUpperCase()
    if (name.includes(term) || term.includes(name)) return entry
    const boardTokens = (entry.tokens || []).map((t: any) => (t.name || '').toUpperCase())
    if (boardTokens.some((bt: string) => tokenNames.has(bt))) return entry
  }
  return null
}

// ---------------------------------------------------------------------------
// Narrative group detail panel
// ---------------------------------------------------------------------------

function NarrativeGroupDetail({
  group,
  boardEntry,
}: {
  group: any
  boardEntry: any | null
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Board entry card — live discovery data */}
      {boardEntry ? (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>
            Live narrative intelligence
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: '#c9d1d9' }}>
              {boardEntry.term}
            </span>
            {boardEntry.tier && tierBadge(boardEntry.tier)}
            {boardEntry.classification === 'STRONG' && <Badge variant="green">STRONG</Badge>}
            {boardEntry.classification === 'EMERGING' && <Badge variant="blue">EMERGING</Badge>}
            {boardEntry.classification === 'WEAK' && <Badge variant="yellow">WEAK</Badge>}
            {boardEntry.corroboration?.x_confirmed && (
              <span style={{ fontSize: 10, color: '#bc8cff' }}>
                X ({boardEntry.corroboration?.x_authors || 0} authors)
              </span>
            )}
            {boardEntry.corroboration?.news_confirmed && (
              <span style={{ fontSize: 10, color: '#58a6ff' }}>
                news ({boardEntry.corroboration?.news_articles || 0})
              </span>
            )}
          </div>
          <ScoreBar label="Narrative score" value={boardEntry.narrative_score} />
          <ScoreBar label="Quality" value={boardEntry.quality_score} />
          <ScoreBar label="Confidence" value={boardEntry.confidence} />
          <div style={{ marginTop: 8, fontSize: 11, color: '#8b949e', display: 'flex', gap: 12 }}>
            <span>
              5m: <strong style={{ color: '#c9d1d9' }}>{boardEntry.velocity?.tokens_last_5m}</strong>
            </span>
            <span>
              15m: <strong style={{ color: '#c9d1d9' }}>{boardEntry.velocity?.tokens_last_15m}</strong>
            </span>
            <span>
              accel:{' '}
              <strong
                style={{
                  color:
                    boardEntry.velocity?.acceleration === 'increasing'
                      ? '#3fb950'
                      : boardEntry.velocity?.acceleration === 'decreasing'
                      ? '#f85149'
                      : '#8b949e',
                }}
              >
                {boardEntry.velocity?.acceleration}
              </strong>
            </span>
          </div>
          {boardEntry.pattern_flags?.length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {boardEntry.pattern_flags.map((f: string) => (
                <span
                  key={f}
                  style={{
                    fontSize: 10,
                    color: '#8b949e',
                    background: 'rgba(139,148,158,0.1)',
                    borderRadius: 3,
                    padding: '1px 5px',
                  }}
                >
                  {f === 'repeated' ? '🔁 repeated' : f === 'rapid_spawn' ? '⚡ rapid spawn' : f === 'converging' ? '🧠 converging' : f}
                </span>
              ))}
            </div>
          )}
          <div style={{ marginTop: 8, fontSize: 11, color: '#6e7681', lineHeight: 1.5 }}>
            {boardEntry.reason}
          </div>
        </Card>
      ) : (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681' }}>
            No live board entry for this narrative yet.
          </div>
        </Card>
      )}

      {/* Child alerts */}
      {group.alerts?.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>
            Scored token alerts ({group.alerts.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {group.alerts.slice(0, 15).map((a: any, i: number) => (
              <div
                key={i}
                style={{
                  padding: '8px 0',
                  borderBottom: '1px solid #21262d',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                }}
              >
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Badge variant={alertTypeBadgeVariant(a.alert_type)}>
                    {a.alert_type?.replace(/_/g, ' ')}
                  </Badge>
                  <span style={{ fontSize: 12, color: '#c9d1d9', flex: 1 }}>
                    {a.token_name || shortAddr(a.token_address)}
                  </span>
                  <Badge variant={a.status === 'active' ? 'green' : 'gray'}>
                    {a.status}
                  </Badge>
                </div>
                <div
                  style={{
                    display: 'flex',
                    gap: 16,
                    fontSize: 11,
                    color: '#8b949e',
                  }}
                >
                  <span>
                    Net:{' '}
                    <strong style={{ color: scoreColor(a.net_potential) }}>
                      {fmtPct(a.net_potential)}
                    </strong>
                  </span>
                  <span>
                    P_fail:{' '}
                    <strong style={{ color: riskColor(a.p_failure) }}>
                      {fmtPct(a.p_failure)}
                    </strong>
                  </span>
                  <span>
                    Conf:{' '}
                    <strong>{fmtPct(a.confidence_score)}</strong>
                  </span>
                  <span style={{ color: '#484f58' }}>{fmtDate(a.created_at)}</span>
                </div>
                {a.risk_flags?.length > 0 && (
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {a.risk_flags.slice(0, 3).map((f: string, fi: number) => (
                      <Badge key={fi} variant="red">{f}</Badge>
                    ))}
                    {a.risk_flags.length > 3 && (
                      <span style={{ fontSize: 10, color: '#6e7681' }}>
                        +{a.risk_flags.length - 3} more
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
            {group.alerts.length > 15 && (
              <div style={{ fontSize: 11, color: '#6e7681', textAlign: 'center' }}>
                +{group.alerts.length - 15} more alerts
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AlertCenter() {
  const [groups, setGroups] = useState<any[]>([])
  const [board, setBoard] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState<'all' | 'active' | 'retired'>('all')
  const [selected, setSelected] = useState<any>(null)

  const load = async () => {
    try {
      const s = filter === 'all' ? undefined : filter
      const [groupRes, boardRes] = await Promise.all([
        api.narrativeAlerts(s, 100),
        api.narrativeBoard(undefined, false).catch(() => ({ board: [] })),
      ])
      setGroups(groupRes.groups || [])
      setBoard(boardRes.board || [])
      setLoading(false)
    } catch (e: any) {
      setErr(e.message)
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const totalAlerts = groups.reduce((s, g) => s + g.alert_count, 0)

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: selected ? '1fr 1fr' : '1fr',
        gap: 16,
      }}
    >
      <div>
        <SectionTitle
          right={
            <div style={{ display: 'flex', gap: 6 }}>
              {(['all', 'active', 'retired'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  style={{
                    background: filter === f ? 'rgba(88,166,255,0.15)' : 'transparent',
                    color: filter === f ? '#58a6ff' : '#6e7681',
                    border: '1px solid',
                    borderColor: filter === f ? 'rgba(88,166,255,0.3)' : '#30363d',
                    borderRadius: 4,
                    padding: '3px 10px',
                    fontSize: 11,
                    cursor: 'pointer',
                    textTransform: 'capitalize',
                  }}
                >
                  {f}
                </button>
              ))}
            </div>
          }
        >
          Alerts — {groups.length} narrative{groups.length !== 1 ? 's' : ''} ({totalAlerts} signals)
        </SectionTitle>

        {groups.length === 0 ? (
          <div style={{ padding: 32, color: '#6e7681', textAlign: 'center', fontSize: 13 }}>
            No alerts yet. Waiting for pipeline to score tokens.
          </div>
        ) : (
          <Card style={{ padding: 0 }}>
            <Table
              headers={['Narrative', 'Type', 'Confidence', 'Quality', 'Tokens', 'Alerts', 'Status', 'Last']}
              emptyMsg="No alerts found."
              rows={groups.map(g => {
                const boardEntry = findBoardEntry(g, board)
                const conf = g.max_confidence
                return [
                  <div>
                    <span
                      style={{ color: '#58a6ff', cursor: 'pointer', fontWeight: 600 }}
                      onClick={() => setSelected(selected?.narrative_id === g.narrative_id ? null : g)}
                    >
                      {g.narrative_name}
                    </span>
                    {boardEntry && (
                      <span style={{ marginLeft: 6, fontSize: 10, display: 'inline-flex', gap: 4 }}>
                        {boardEntry.tier && tierBadge(boardEntry.tier)}
                        {boardEntry.classification === 'STRONG' && <Badge variant="green">STRONG</Badge>}
                        {boardEntry.classification === 'EMERGING' && <Badge variant="blue">EMERGING</Badge>}
                        {boardEntry.classification === 'WEAK' && <Badge variant="yellow">WEAK</Badge>}
                      </span>
                    )}
                  </div>,
                  dominantBadge(g.dominant_alert_type),
                  <div style={{ minWidth: 70 }}>
                    <div style={{ color: scoreColor(conf), fontWeight: 600, fontSize: 12 }}>
                      {fmtPct(conf)}
                    </div>
                    {boardEntry && (
                      <div style={{ fontSize: 10, color: '#6e7681' }}>
                        score: {fmtPct(boardEntry.narrative_score)}
                      </div>
                    )}
                  </div>,
                  boardEntry ? (
                    <span style={{ color: scoreColor(boardEntry.quality_score || 0), fontWeight: 600, fontSize: 12 }}>
                      {fmtPct(boardEntry.quality_score)}
                    </span>
                  ) : (
                    <span style={{ color: '#484f58', fontSize: 11 }}>—</span>
                  ),
                  <span style={{ color: '#c9d1d9' }}>{g.token_count}</span>,
                  <span style={{ color: '#c9d1d9' }}>{g.alert_count}</span>,
                  statusBadge(g.status),
                  <span style={{ fontSize: 11, color: '#484f58' }}>
                    {fmtDate(g.latest_created_at)}
                  </span>,
                ]
              })}
            />
          </Card>
        )}
      </div>

      {selected && (
        <div>
          <SectionTitle
            right={
              <button
                onClick={() => setSelected(null)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#6e7681',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                ✕ Close
              </button>
            }
          >
            {selected.narrative_name}
          </SectionTitle>
          <NarrativeGroupDetail
            group={selected}
            boardEntry={findBoardEntry(selected, board)}
          />
        </div>
      )}
    </div>
  )
}
