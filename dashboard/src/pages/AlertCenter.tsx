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

export function AlertCenter() {
  const [alerts, setAlerts] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState<'all' | 'active' | 'retired'>('all')
  const [selected, setSelected] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const s = filter === 'all' ? undefined : filter
        const res = await api.alerts(s, 100)
        setAlerts(res.alerts || [])
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [filter])

  const openDetail = async (alert: any) => {
    setSelected(alert)
    setDetailLoading(true)
    try {
      const d = await api.alert(alert.alert_id)
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
          Alerts ({alerts.length})
        </SectionTitle>

        <Card style={{ padding: 0 }}>
          <Table
            headers={['Type', 'Token', 'Net Pot.', 'P_failure', 'Confidence', 'Status', 'Created']}
            emptyMsg="No alerts found."
            rows={alerts.map(a => [
              <Badge variant={alertTypeBadge(a.alert_type)}>{a.alert_type}</Badge>,
              <span
                style={{ color: '#58a6ff', cursor: 'pointer' }}
                onClick={() => openDetail(a)}
              >
                {a.token_name || shortAddr(a.token_address)}
              </span>,
              <span style={{ color: scoreColor(a.net_potential) }}>{fmtPct(a.net_potential)}</span>,
              <span style={{ color: riskColor(a.p_failure) }}>{fmtPct(a.p_failure)}</span>,
              <span>{fmtPct(a.confidence_score)}</span>,
              <Badge variant={a.status === 'active' ? 'green' : 'gray'}>{a.status}</Badge>,
              <span style={{ fontSize: 11, color: '#484f58' }}>{fmtDate(a.created_at)}</span>,
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
            Alert Detail
          </SectionTitle>

          {detailLoading ? (
            <Loading />
          ) : detail?.error ? (
            <ErrorMsg msg={detail.error} />
          ) : detail ? (
            <AlertDetail detail={detail} />
          ) : null}
        </div>
      )}
    </div>
  )
}

function AlertDetail({ detail }: { detail: any }) {
  const { alert, deliveries } = detail

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Header */}
      <Card>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
          <Badge variant={alertTypeBadge(alert.alert_type)}>{alert.alert_type}</Badge>
          <Badge variant={alert.status === 'active' ? 'green' : 'gray'}>{alert.status}</Badge>
        </div>
        <div style={{ fontSize: 14, color: '#c9d1d9', marginBottom: 8 }}>
          {alert.token_name} ({alert.token_symbol})
          {alert.narrative_name && (
            <span style={{ color: '#6e7681', fontSize: 12 }}> — {alert.narrative_name}</span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          <div>
            <div style={{ color: '#6e7681', fontSize: 10 }}>Net Potential</div>
            <div style={{ fontWeight: 700, color: scoreColor(alert.net_potential), fontSize: 16 }}>
              {fmtPct(alert.net_potential)}
            </div>
          </div>
          <div>
            <div style={{ color: '#6e7681', fontSize: 10 }}>P_failure</div>
            <div style={{ fontWeight: 700, color: riskColor(alert.p_failure), fontSize: 16 }}>
              {fmtPct(alert.p_failure)}
            </div>
          </div>
          <div>
            <div style={{ color: '#6e7681', fontSize: 10 }}>Confidence</div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{fmtPct(alert.confidence_score)}</div>
          </div>
        </div>
      </Card>

      {/* Reasoning */}
      {alert.reasoning && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Why this alert?</div>
          <div style={{ fontSize: 12, color: '#8b949e', lineHeight: 1.6 }}>{alert.reasoning}</div>
        </Card>
      )}

      {/* Scores */}
      {alert.dimension_scores && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 10 }}>Dimension Scores</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {Object.entries(alert.dimension_scores).map(([k, v]: [string, any]) => (
              <ScoreBar key={k} label={k.replace(/_/g, ' ')} value={v} />
            ))}
          </div>
        </Card>
      )}

      {/* Risk flags */}
      {alert.risk_flags?.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Risk Flags</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {alert.risk_flags.map((f: string, i: number) => (
              <Badge key={i} variant="red">{f}</Badge>
            ))}
          </div>
        </Card>
      )}

      {/* Delivery logs */}
      {deliveries?.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>Delivery Log</div>
          {deliveries.map((d: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 10, padding: '5px 0', borderBottom: '1px solid #21262d', fontSize: 11 }}>
              <Badge variant={d.status === 'delivered' ? 'green' : 'red'}>{d.status}</Badge>
              <span style={{ color: '#8b949e' }}>{d.channel_type}</span>
              <span style={{ color: '#484f58' }}>{fmtDate(d.attempted_at)}</span>
              {d.failure_reason && <span style={{ color: '#f85149' }}>{d.failure_reason}</span>}
            </div>
          ))}
        </Card>
      )}

      {/* History */}
      {alert.history?.length > 0 && (
        <Card>
          <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 8 }}>State History</div>
          {alert.history.map((h: any, i: number) => (
            <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid #21262d', fontSize: 11 }}>
              <div style={{ color: '#8b949e' }}>
                {h.previous_type ? `${h.previous_type} → ` : ''}{h.new_type}
                <span style={{ color: '#484f58', marginLeft: 8 }}>{fmtDate(h.timestamp)}</span>
              </div>
              {h.reason && <div style={{ color: '#6e7681' }}>{h.reason}</div>}
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
