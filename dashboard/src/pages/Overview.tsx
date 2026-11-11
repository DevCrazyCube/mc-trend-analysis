import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Card,
  ErrorMsg,
  Loading,
  SectionTitle,
  StatTile,
  Badge,
  fmtDate,
} from '../components/ui'

export function Overview() {
  const [health, setHealth] = useState<any>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const h = await api.health()
      setHealth(h)
      setErr('')
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const lc = health.last_cycle || {}
  const ws = health.ws_discovery || {}
  const tc = health.token_counts || {}
  const nc = health.narrative_counts || {}

  const uptime = health.uptime_seconds != null
    ? `${Math.floor(health.uptime_seconds / 3600)}h ${Math.floor((health.uptime_seconds % 3600) / 60)}m`
    : '—'

  return (
    <div>
      <SectionTitle>System Overview</SectionTitle>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
        <StatTile label="Uptime" value={uptime} />
        <StatTile
          label="Active Alerts"
          value={health.active_alerts ?? 0}
          color={health.active_alerts > 0 ? '#f0883e' : '#3fb950'}
        />
        <StatTile
          label="Open Source Gaps"
          value={health.open_source_gaps ?? 0}
          color={health.open_source_gaps > 0 ? '#f85149' : '#3fb950'}
        />
        <StatTile
          label="DB Size"
          value={`${health.db_size_mb ?? 0} MB`}
        />
      </div>

      {/* Token counts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
        <Card>
          <SectionTitle>Token Pipeline</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {Object.entries(tc).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #21262d' }}>
                <span style={{ color: '#6e7681' }}>{k}</span>
                <span style={{ color: '#c9d1d9', fontWeight: 600 }}>{String(v)}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle>Narratives by State</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {Object.entries(nc).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #21262d' }}>
                <span style={{ color: '#6e7681', textTransform: 'capitalize', fontSize: 11 }}>{k}</span>
                <span style={{ color: '#c9d1d9', fontWeight: 600 }}>{String(v)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* WS Discovery health */}
      <Card style={{ marginBottom: 20 }}>
        <SectionTitle>Token Discovery — PumpPortal WebSocket</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
          <div>
            <div style={{ color: '#6e7681', fontSize: 11, marginBottom: 4 }}>Status</div>
            <Badge variant={ws.ws_connected ? 'green' : 'red'}>
              {ws.ws_connected ? 'Connected' : 'Disconnected'}
            </Badge>
            {ws.last_error && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#f85149' }}>
                {ws.last_error}
              </div>
            )}
          </div>
          <div>
            <div style={{ color: '#6e7681', fontSize: 11, marginBottom: 4 }}>Events received</div>
            <div style={{ color: '#c9d1d9', fontWeight: 600 }}>{ws.total_events_received ?? 0}</div>
            {ws.reconnect_count > 0 && (
              <div style={{ fontSize: 11, color: '#d2a317', marginTop: 2 }}>
                {ws.reconnect_count} reconnect(s)
              </div>
            )}
          </div>
          <div>
            <div style={{ color: '#6e7681', fontSize: 11, marginBottom: 4 }}>Queue depth</div>
            <div style={{ color: '#c9d1d9', fontWeight: 600 }}>{ws.queue_depth ?? 0}</div>
            {ws.seconds_since_last_message != null && (
              <div style={{ fontSize: 11, color: '#6e7681', marginTop: 2 }}>
                Last msg: {ws.seconds_since_last_message}s ago
              </div>
            )}
          </div>
        </div>
        {!ws.ws_connected && (
          <div style={{ marginTop: 12, padding: '8px 12px', background: 'rgba(248,81,73,0.08)', borderRadius: 6, fontSize: 11, color: '#8b949e' }}>
            WebSocket discovery is not active. Set <code style={{ background: '#21262d', padding: '1px 4px', borderRadius: 3 }}>PUMPPORTAL_WS_ENABLED=true</code> in your .env and restart. Token discovery will remain at 0 until a working source is configured.
          </div>
        )}
      </Card>

      {/* Last cycle */}
      <Card style={{ marginBottom: 20 }}>
        <SectionTitle>Last Pipeline Cycle</SectionTitle>
        {Object.keys(lc).length === 0 ? (
          <div style={{ color: '#6e7681', fontSize: 12 }}>No cycle data yet. Run a cycle first.</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8 }}>
            {['tokens_ingested','events_ingested','links_created','tokens_scored',
              'alerts_created','alerts_delivered','alerts_expired','elapsed_seconds'].map(k => (
              <div key={k} style={{ padding: '4px 0', borderBottom: '1px solid #21262d' }}>
                <div style={{ color: '#6e7681', fontSize: 10 }}>{k.replace(/_/g, ' ')}</div>
                <div style={{ color: '#c9d1d9', fontWeight: 600 }}>{lc[k] ?? '—'}</div>
              </div>
            ))}
          </div>
        )}
        {lc.errors?.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ color: '#f85149', fontSize: 11, marginBottom: 4 }}>Cycle errors:</div>
            {lc.errors.map((e: string, i: number) => (
              <div key={i} style={{ fontSize: 11, color: '#8b949e', padding: '2px 0' }}>{e}</div>
            ))}
          </div>
        )}
      </Card>

      {/* Source gaps */}
      {health.source_gaps?.length > 0 && (
        <Card>
          <SectionTitle>Open Source Gaps</SectionTitle>
          {health.source_gaps.map((g: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 12, padding: '6px 0', borderBottom: '1px solid #21262d', fontSize: 12 }}>
              <Badge variant="red">{g.source}</Badge>
              <span style={{ color: '#8b949e' }}>since {fmtDate(g.since)}</span>
              {g.notes && <span style={{ color: '#6e7681' }}>{g.notes}</span>}
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
