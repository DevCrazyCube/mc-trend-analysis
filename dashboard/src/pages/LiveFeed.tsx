import { useEffect, useRef, useState } from 'react'
import { openEventStream, api } from '../api/client'
import {
  Badge,
  Card,
  SectionTitle,
  alertTypeBadge,
  fmtDate,
  shortAddr,
  Loading,
  ErrorMsg,
} from '../components/ui'

interface FeedItem {
  id: string
  type: 'token' | 'narrative' | 'alert' | 'system'
  ts: string
  label: string
  sub?: string
  badge?: string
  badgeVariant?: string
}

function feedItem(raw: any, type: string): FeedItem {
  if (type === 'token')
    return {
      id: raw.token_id || raw.address,
      type: 'token',
      ts: raw.first_seen_by_system || new Date().toISOString(),
      label: `${raw.name} (${raw.symbol})`,
      sub: shortAddr(raw.address),
      badge: raw.launch_platform || 'unknown',
      badgeVariant: 'blue',
    }
  if (type === 'narrative')
    return {
      id: raw.narrative_id,
      type: 'narrative',
      ts: raw.first_detected || new Date().toISOString(),
      label: raw.description || raw.anchor_terms?.join(' '),
      sub: `state: ${raw.state}`,
      badge: raw.state,
      badgeVariant: raw.state === 'EMERGING' ? 'green' : raw.state === 'PEAKING' ? 'orange' : 'gray',
    }
  if (type === 'alert')
    return {
      id: raw.alert_id,
      type: 'alert',
      ts: raw.created_at || new Date().toISOString(),
      label: `[${raw.alert_type}] ${raw.token_name}`,
      sub: `net_potential: ${raw.net_potential != null ? (raw.net_potential * 100).toFixed(1) + '%' : '—'}`,
      badge: raw.alert_type,
      badgeVariant: alertTypeBadge(raw.alert_type),
    }
  return {
    id: String(Math.random()),
    type: 'system',
    ts: new Date().toISOString(),
    label: String(raw),
    badgeVariant: 'gray',
  }
}

export function LiveFeed() {
  const [items, setItems] = useState<FeedItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [paused, setPaused] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  // Load recent items on mount
  useEffect(() => {
    const loadInitial = async () => {
      try {
        const [tokensRes, narrativesRes, alertsRes] = await Promise.all([
          api.tokens(undefined, 20),
          api.narratives(),
          api.alerts(undefined, 20),
        ])
        const tokenItems = (tokensRes.tokens || []).map((t: any) => feedItem(t, 'token'))
        const narItems = (narrativesRes.narratives || []).map((n: any) => feedItem(n, 'narrative'))
        const alertItems = (alertsRes.alerts || []).map((a: any) => feedItem(a, 'alert'))
        const all = [...tokenItems, ...narItems, ...alertItems]
          .sort((a, b) => b.ts.localeCompare(a.ts))
          .slice(0, 80)
        setItems(all)
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    loadInitial()
  }, [])

  // SSE for live updates
  useEffect(() => {
    const es = openEventStream((type, payload) => {
      if (pausedRef.current) return
      if (type === 'new_token') {
        setItems(prev => [feedItem(payload, 'token'), ...prev].slice(0, 200))
      } else if (type === 'new_alert') {
        setItems(prev => [feedItem(payload, 'alert'), ...prev].slice(0, 200))
      } else if (type === 'cycle_complete') {
        // silent refresh hint — handled by other pages
      }
    })
    return () => es.close()
  }, [])

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const TYPE_COLORS: Record<string, string> = {
    token: '#58a6ff',
    narrative: '#3fb950',
    alert: '#f0883e',
    system: '#6e7681',
  }

  return (
    <div>
      <SectionTitle
        right={
          <button
            onClick={() => setPaused(p => !p)}
            style={{
              background: paused ? 'rgba(63,185,80,0.15)' : 'rgba(248,81,73,0.15)',
              color: paused ? '#3fb950' : '#f85149',
              border: 'none',
              borderRadius: 4,
              padding: '4px 12px',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
        }
      >
        Live Feed
      </SectionTitle>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {['token', 'narrative', 'alert'].map(t => (
          <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: TYPE_COLORS[t], display: 'inline-block' }} />
            <span style={{ fontSize: 11, color: '#6e7681', textTransform: 'capitalize' }}>{t}</span>
          </div>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#6e7681' }}>
          {items.length} events
          {paused && ' — paused'}
        </span>
      </div>

      <Card style={{ padding: 0, maxHeight: 'calc(100vh - 180px)', overflowY: 'auto' }}>
        {items.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#6e7681' }}>
            No events yet. Events will appear here as the pipeline runs.
          </div>
        ) : (
          items.map((item, i) => (
            <div
              key={item.id + i}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 12,
                padding: '10px 16px',
                borderBottom: '1px solid #21262d',
                fontSize: 12,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: TYPE_COLORS[item.type],
                  marginTop: 4,
                  flexShrink: 0,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: '#c9d1d9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.label}
                </div>
                {item.sub && (
                  <div style={{ color: '#6e7681', fontSize: 11 }}>{item.sub}</div>
                )}
              </div>
              {item.badge && (
                <Badge variant={(item.badgeVariant as any) || 'gray'}>
                  {item.badge}
                </Badge>
              )}
              <span style={{ fontSize: 11, color: '#484f58', flexShrink: 0 }}>
                {fmtDate(item.ts)}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </Card>
    </div>
  )
}
