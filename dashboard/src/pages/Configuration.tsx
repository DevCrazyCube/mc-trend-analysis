import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Badge,
  Card,
  ErrorMsg,
  Loading,
  SectionTitle,
} from '../components/ui'

export function Configuration() {
  const [config, setConfig] = useState<Record<string, any>>({})
  const [weights, setWeights] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saveMsg, setSaveMsg] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        const [cfgRes, wRes] = await Promise.all([api.config(), api.weights()])
        setConfig(cfgRes.config || {})
        setWeights(wRes)
        setLoading(false)
      } catch (e: any) {
        setErr(e.message)
        setLoading(false)
      }
    }
    load()
  }, [])

  const startEdit = (field: string, currentValue: any) => {
    setEditing(field)
    setEditValue(String(currentValue?.value ?? ''))
    setSaveMsg('')
  }

  const saveEdit = async () => {
    if (!editing) return
    try {
      await api.patchConfig(editing, editValue)
      const res = await api.config()
      setConfig(res.config || {})
      setSaveMsg(`✓ Updated ${editing}`)
      setEditing(null)
    } catch (e: any) {
      setSaveMsg(`Error: ${e.message}`)
    }
  }

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  // Group fields
  const groups: Record<string, string[]> = {
    'Ingestion / Polling': [
      'polling_interval_tokens', 'polling_interval_events',
      'pumpfun_fetch_limit', 'news_page_size', 'news_signal_strength',
    ],
    'Source URLs': [
      'solana_rpc_url', 'pumpfun_api_url', 'pumpportal_ws_url',
    ],
    'Alert / Scoring': [
      'alert_rate_limit_per_10min', 'max_token_age_hours',
      'confidence_floor_for_alert',
    ],
    'Infrastructure': [
      'environment', 'database_path', 'log_level', 'log_format',
      'dashboard_port', 'dashboard_host',
    ],
    'Delivery (secrets)': [
      'telegram_bot_token', 'telegram_chat_id', 'webhook_url',
      'webhook_secret', 'newsapi_key', 'serpapi_key',
    ],
  }

  return (
    <div>
      <SectionTitle>Configuration</SectionTitle>

      {saveMsg && (
        <div
          style={{
            padding: '8px 12px',
            marginBottom: 16,
            borderRadius: 6,
            background: saveMsg.startsWith('✓')
              ? 'rgba(63,185,80,0.1)'
              : 'rgba(248,81,73,0.1)',
            color: saveMsg.startsWith('✓') ? '#3fb950' : '#f85149',
            border: `1px solid ${saveMsg.startsWith('✓') ? 'rgba(63,185,80,0.3)' : 'rgba(248,81,73,0.3)'}`,
            fontSize: 12,
          }}
        >
          {saveMsg}
        </div>
      )}

      <div
        style={{
          padding: '10px 14px',
          background: 'rgba(88,166,255,0.08)',
          border: '1px solid rgba(88,166,255,0.2)',
          borderRadius: 6,
          fontSize: 11,
          color: '#8b949e',
          marginBottom: 20,
        }}
      >
        Dynamic fields can be updated here and take effect immediately in the running process.
        Restart-required fields must be changed in your .env file and the system restarted.
        Secrets are masked and can only be set in .env.
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {Object.entries(groups).map(([group, fields]) => {
          const fieldsInGroup = fields.filter(f => config[f] !== undefined)
          if (fieldsInGroup.length === 0) return null
          return (
            <Card key={group}>
              <div style={{ fontSize: 12, color: '#6e7681', fontWeight: 600, marginBottom: 10 }}>{group}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {fieldsInGroup.map(field => {
                  const meta = config[field] || {}
                  const isEditing = editing === field
                  return (
                    <div
                      key={field}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '6px 8px',
                        borderRadius: 4,
                        background: isEditing ? 'rgba(88,166,255,0.05)' : 'transparent',
                        border: isEditing ? '1px solid rgba(88,166,255,0.2)' : '1px solid transparent',
                      }}
                    >
                      <span style={{ fontSize: 11, color: '#6e7681', minWidth: 200, flexShrink: 0 }}>
                        {field}
                      </span>
                      {isEditing ? (
                        <>
                          <input
                            value={editValue}
                            onChange={e => setEditValue(e.target.value)}
                            style={{
                              flex: 1,
                              background: '#21262d',
                              color: '#c9d1d9',
                              border: '1px solid #30363d',
                              borderRadius: 4,
                              padding: '3px 8px',
                              fontSize: 12,
                              fontFamily: 'monospace',
                            }}
                            onKeyDown={e => e.key === 'Enter' && saveEdit()}
                            autoFocus
                          />
                          <button
                            onClick={saveEdit}
                            style={{ background: '#238636', color: '#fff', border: 'none', borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontSize: 11 }}
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditing(null)}
                            style={{ background: 'none', color: '#6e7681', border: '1px solid #30363d', borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontSize: 11 }}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <span
                            style={{
                              flex: 1,
                              fontFamily: 'monospace',
                              fontSize: 12,
                              color: meta.secret ? '#6e7681' : '#c9d1d9',
                            }}
                          >
                            {meta.secret ? '••••••' : String(meta.value ?? '—')}
                          </span>
                          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                            {meta.dynamic && !meta.secret && (
                              <Badge variant="green">dynamic</Badge>
                            )}
                            {meta.restart_required && (
                              <Badge variant="yellow">restart required</Badge>
                            )}
                            {meta.secret && (
                              <Badge variant="gray">secret — .env only</Badge>
                            )}
                          </div>
                          {meta.dynamic && !meta.secret && (
                            <button
                              onClick={() => startEdit(field, meta)}
                              style={{
                                background: 'none',
                                color: '#58a6ff',
                                border: '1px solid rgba(88,166,255,0.3)',
                                borderRadius: 4,
                                padding: '2px 8px',
                                cursor: 'pointer',
                                fontSize: 11,
                              }}
                            >
                              Edit
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
            </Card>
          )
        })}

        {/* Scoring weights (read-only) */}
        {weights && (
          <Card>
            <div style={{ fontSize: 12, color: '#6e7681', fontWeight: 600, marginBottom: 10 }}>
              Scoring Weights (read-only — change via environment or code)
            </div>
            {['potential_weights', 'failure_weights', 'rug_risk_category_weights', 'confidence_weights'].map(wk => (
              weights[wk] && (
                <div key={wk} style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: '#484f58', marginBottom: 4 }}>{wk.replace(/_/g, ' ')}</div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {Object.entries(weights[wk]).map(([k, v]) => (
                      <div key={k} style={{ background: '#21262d', borderRadius: 4, padding: '3px 8px', fontSize: 11 }}>
                        <span style={{ color: '#6e7681' }}>{k}: </span>
                        <span style={{ color: '#c9d1d9' }}>{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            ))}
          </Card>
        )}
      </div>
    </div>
  )
}
