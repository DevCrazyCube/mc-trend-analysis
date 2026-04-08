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
} from '../components/ui'

export function Notifications() {
  const [notifications, setNotifications] = useState<any[]>([])
  const [deliveryLogs, setDeliveryLogs] = useState<any[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [tab, setTab] = useState<'notifications' | 'delivery'>('notifications')

  const load = async () => {
    try {
      const [nRes, dRes] = await Promise.all([
        api.notifications(unreadOnly),
        api.deliveryLogs(100),
      ])
      setNotifications(nRes.notifications || [])
      setUnreadCount(nRes.unread_count ?? 0)
      setDeliveryLogs(dRes.delivery_logs || [])
      setLoading(false)
    } catch (e: any) {
      setErr(e.message)
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [unreadOnly])

  const markRead = async (id: string) => {
    try { await api.markRead(id); load() } catch {}
  }

  const markAllRead = async () => {
    try { await api.markAllRead(); load() } catch {}
  }

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const severityVariant = (s: string) => {
    if (s === 'error') return 'red'
    if (s === 'warning') return 'yellow'
    if (s === 'success') return 'green'
    return 'gray'
  }

  return (
    <div>
      <SectionTitle
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                style={{ background: 'none', color: '#58a6ff', border: '1px solid rgba(88,166,255,0.3)', borderRadius: 4, padding: '4px 10px', cursor: 'pointer', fontSize: 11 }}
              >
                Mark all read
              </button>
            )}
          </div>
        }
      >
        Notifications {unreadCount > 0 && <Badge variant="red">{unreadCount}</Badge>}
      </SectionTitle>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 16 }}>
        {(['notifications', 'delivery'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: tab === t ? 'rgba(88,166,255,0.1)' : 'transparent',
              color: tab === t ? '#58a6ff' : '#6e7681',
              border: '1px solid',
              borderColor: tab === t ? 'rgba(88,166,255,0.3)' : '#30363d',
              borderRadius: t === 'notifications' ? '4px 0 0 4px' : '0 4px 4px 0',
              padding: '5px 14px',
              cursor: 'pointer',
              fontSize: 12,
              textTransform: 'capitalize',
            }}
          >
            {t === 'notifications' ? 'System Notifications' : 'Delivery Logs'}
          </button>
        ))}
        <button
          onClick={() => setUnreadOnly(u => !u)}
          style={{
            marginLeft: 'auto',
            background: unreadOnly ? 'rgba(63,185,80,0.1)' : 'transparent',
            color: unreadOnly ? '#3fb950' : '#6e7681',
            border: '1px solid',
            borderColor: unreadOnly ? 'rgba(63,185,80,0.3)' : '#30363d',
            borderRadius: 4,
            padding: '5px 12px',
            cursor: 'pointer',
            fontSize: 11,
          }}
        >
          {unreadOnly ? '● Unread only' : '○ All'}
        </button>
      </div>

      {tab === 'notifications' && (
        <Card style={{ padding: 0 }}>
          {notifications.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: '#6e7681' }}>
              No notifications.
            </div>
          ) : (
            notifications.map((n) => (
              <div
                key={n.notification_id}
                style={{
                  display: 'flex',
                  gap: 12,
                  padding: '10px 16px',
                  borderBottom: '1px solid #21262d',
                  background: n.read ? 'transparent' : 'rgba(88,166,255,0.03)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, flex: 1 }}>
                  {!n.read && (
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#58a6ff', marginTop: 5, flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
                      <span style={{ color: '#c9d1d9', fontSize: 12, fontWeight: n.read ? 400 : 600 }}>
                        {n.title}
                      </span>
                      <Badge variant={severityVariant(n.severity) as any}>{n.severity}</Badge>
                    </div>
                    {n.body && <div style={{ fontSize: 11, color: '#6e7681' }}>{n.body}</div>}
                    <div style={{ fontSize: 11, color: '#484f58', marginTop: 2 }}>
                      {fmtDate(n.created_at)}
                      {n.source_name && ` — ${n.source_name}`}
                    </div>
                  </div>
                </div>
                {!n.read && (
                  <button
                    onClick={() => markRead(n.notification_id)}
                    style={{ background: 'none', color: '#6e7681', border: 'none', cursor: 'pointer', fontSize: 11, flexShrink: 0 }}
                  >
                    Mark read
                  </button>
                )}
              </div>
            ))
          )}
        </Card>
      )}

      {tab === 'delivery' && (
        <Card style={{ padding: 0 }}>
          <Table
            headers={['Status', 'Channel', 'Token', 'Type', 'Time', 'Reason']}
            emptyMsg="No delivery logs yet."
            rows={deliveryLogs.map(d => [
              <Badge variant={d.status === 'delivered' ? 'green' : 'red'}>{d.status}</Badge>,
              <span style={{ color: '#8b949e', fontSize: 11 }}>{d.channel_type}</span>,
              <span style={{ color: '#c9d1d9' }}>{d.token_name || d.alert_id?.slice(0, 8)}</span>,
              d.alert_type ? <Badge variant="gray">{d.alert_type}</Badge> : <span>—</span>,
              <span style={{ fontSize: 11, color: '#484f58' }}>{fmtDate(d.attempted_at)}</span>,
              <span style={{ fontSize: 11, color: '#f85149' }}>{d.failure_reason || '—'}</span>,
            ])}
          />
        </Card>
      )}
    </div>
  )
}
