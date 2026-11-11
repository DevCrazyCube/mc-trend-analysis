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

const STATUS_OPTIONS = ['watching', 'entered', 'trimmed', 'exited', 'invalidated']
const CONVICTION_OPTIONS = ['low', 'medium', 'high', 'very_high']

function statusBadge(s: string) {
  if (s === 'watching') return <Badge variant="blue">watching</Badge>
  if (s === 'entered') return <Badge variant="green">entered</Badge>
  if (s === 'trimmed') return <Badge variant="yellow">trimmed</Badge>
  if (s === 'exited') return <Badge variant="gray">exited</Badge>
  if (s === 'invalidated') return <Badge variant="red">invalidated</Badge>
  return <Badge variant="gray">{s}</Badge>
}

interface NewHolding {
  token_address: string
  token_name: string
  token_symbol: string
  status: string
  size_sol: string
  avg_entry_price_sol: string
  conviction: string
  exit_plan: string
  notes: string
}

const EMPTY_FORM: NewHolding = {
  token_address: '',
  token_name: '',
  token_symbol: '',
  status: 'watching',
  size_sol: '',
  avg_entry_price_sol: '',
  conviction: '',
  exit_plan: '',
  notes: '',
}

export function Holdings() {
  const [holdings, setHoldings] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NewHolding>(EMPTY_FORM)
  const [formErr, setFormErr] = useState('')
  const [editId, setEditId] = useState<string | null>(null)
  const [editStatus, setEditStatus] = useState('')
  const [editNotes, setEditNotes] = useState('')

  const load = async () => {
    try {
      const res = await api.holdings()
      setHoldings(res.holdings || [])
      setLoading(false)
    } catch (e: any) {
      setErr(e.message)
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const submit = async () => {
    if (!form.token_address) { setFormErr('Token address is required'); return }
    try {
      await api.createHolding({
        token_address: form.token_address,
        token_name: form.token_name || null,
        token_symbol: form.token_symbol || null,
        status: form.status,
        size_sol: form.size_sol ? parseFloat(form.size_sol) : null,
        avg_entry_price_sol: form.avg_entry_price_sol ? parseFloat(form.avg_entry_price_sol) : null,
        conviction: form.conviction || null,
        exit_plan: form.exit_plan || null,
        notes: form.notes || null,
      })
      setShowForm(false)
      setForm(EMPTY_FORM)
      setFormErr('')
      load()
    } catch (e: any) {
      setFormErr(e.message)
    }
  }

  const saveEdit = async (id: string) => {
    try {
      await api.updateHolding(id, {
        status: editStatus || undefined,
        notes: editNotes || undefined,
      })
      setEditId(null)
      load()
    } catch {}
  }

  const del = async (id: string) => {
    if (!confirm('Delete this holding?')) return
    try { await api.deleteHolding(id); load() } catch {}
  }

  if (loading) return <Loading />
  if (err) return <ErrorMsg msg={err} />

  const InputStyle: React.CSSProperties = {
    background: '#21262d',
    color: '#c9d1d9',
    border: '1px solid #30363d',
    borderRadius: 4,
    padding: '5px 8px',
    fontSize: 12,
    width: '100%',
    fontFamily: 'monospace',
  }

  const SelectStyle: React.CSSProperties = { ...InputStyle }

  return (
    <div>
      <SectionTitle
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Badge variant="gray">Manual tracking — not broker-connected</Badge>
            <button
              onClick={() => { setShowForm(!showForm); setFormErr('') }}
              style={{ background: '#238636', color: '#fff', border: 'none', borderRadius: 4, padding: '5px 12px', cursor: 'pointer', fontSize: 12 }}
            >
              + Add Position
            </button>
          </div>
        }
      >
        Holdings &amp; Positions
      </SectionTitle>

      {/* Add form */}
      {showForm && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: '#6e7681', marginBottom: 12 }}>New Position (manual)</div>
          {formErr && <div style={{ color: '#f85149', fontSize: 12, marginBottom: 8 }}>{formErr}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Token Address *</div>
              <input style={InputStyle} value={form.token_address} onChange={e => setForm({ ...form, token_address: e.target.value })} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Token Name</div>
              <input style={InputStyle} value={form.token_name} onChange={e => setForm({ ...form, token_name: e.target.value })} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Symbol</div>
              <input style={InputStyle} value={form.token_symbol} onChange={e => setForm({ ...form, token_symbol: e.target.value })} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Status</div>
              <select style={SelectStyle} value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}>
                {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Size (SOL)</div>
              <input type="number" style={InputStyle} value={form.size_sol} onChange={e => setForm({ ...form, size_sol: e.target.value })} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Avg Entry (SOL)</div>
              <input type="number" style={InputStyle} value={form.avg_entry_price_sol} onChange={e => setForm({ ...form, avg_entry_price_sol: e.target.value })} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Conviction</div>
              <select style={SelectStyle} value={form.conviction} onChange={e => setForm({ ...form, conviction: e.target.value })}>
                <option value="">—</option>
                {CONVICTION_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Exit Plan</div>
              <input style={InputStyle} value={form.exit_plan} onChange={e => setForm({ ...form, exit_plan: e.target.value })} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>Notes</div>
              <input style={InputStyle} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={submit} style={{ background: '#238636', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 16px', cursor: 'pointer', fontSize: 12 }}>
              Save
            </button>
            <button onClick={() => { setShowForm(false); setFormErr('') }} style={{ background: 'none', color: '#6e7681', border: '1px solid #30363d', borderRadius: 4, padding: '6px 16px', cursor: 'pointer', fontSize: 12 }}>
              Cancel
            </button>
          </div>
        </Card>
      )}

      <Card style={{ padding: 0 }}>
        <Table
          headers={['Token', 'Status', 'Size (SOL)', 'Avg Entry', 'Conviction', 'Exit Plan', 'Notes', 'Added', 'Actions']}
          emptyMsg="No holdings yet. Add a position to start tracking."
          rows={holdings.map(h => [
            <div>
              <div style={{ color: '#c9d1d9' }}>{h.token_name || '—'}</div>
              <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace' }}>{h.token_address?.slice(0, 10)}…</div>
            </div>,
            editId === h.holding_id ? (
              <select
                value={editStatus}
                onChange={e => setEditStatus(e.target.value)}
                style={{ background: '#21262d', color: '#c9d1d9', border: '1px solid #30363d', borderRadius: 4, padding: '2px 4px', fontSize: 11 }}
              >
                {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            ) : statusBadge(h.status),
            <span style={{ color: '#c9d1d9' }}>{h.size_sol ?? '—'}</span>,
            <span style={{ color: '#6e7681' }}>{h.avg_entry_price_sol ?? '—'}</span>,
            h.conviction ? <Badge variant="blue">{h.conviction}</Badge> : <span style={{ color: '#6e7681' }}>—</span>,
            <span style={{ fontSize: 11, color: '#6e7681' }}>{h.exit_plan || '—'}</span>,
            editId === h.holding_id ? (
              <input
                value={editNotes}
                onChange={e => setEditNotes(e.target.value)}
                style={{ background: '#21262d', color: '#c9d1d9', border: '1px solid #30363d', borderRadius: 4, padding: '2px 6px', fontSize: 11 }}
              />
            ) : (
              <span style={{ fontSize: 11, color: '#6e7681' }}>{h.notes || '—'}</span>
            ),
            <span style={{ fontSize: 11, color: '#484f58' }}>{fmtDate(h.created_at)}</span>,
            editId === h.holding_id ? (
              <div style={{ display: 'flex', gap: 4 }}>
                <button onClick={() => saveEdit(h.holding_id)} style={{ background: '#238636', color: '#fff', border: 'none', borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 10 }}>Save</button>
                <button onClick={() => setEditId(null)} style={{ background: 'none', color: '#6e7681', border: '1px solid #30363d', borderRadius: 3, padding: '2px 6px', cursor: 'pointer', fontSize: 10 }}>✕</button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 4 }}>
                <button onClick={() => { setEditId(h.holding_id); setEditStatus(h.status); setEditNotes(h.notes || '') }} style={{ background: 'none', color: '#58a6ff', border: '1px solid rgba(88,166,255,0.3)', borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 10 }}>Edit</button>
                <button onClick={() => del(h.holding_id)} style={{ background: 'none', color: '#f85149', border: '1px solid rgba(248,81,73,0.3)', borderRadius: 3, padding: '2px 6px', cursor: 'pointer', fontSize: 10 }}>Del</button>
              </div>
            ),
          ])}
        />
      </Card>
    </div>
  )
}
