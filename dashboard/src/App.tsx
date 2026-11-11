import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api, hasApiKey, setApiKey } from './api/client'
import { Layout } from './components/Layout'
import { Overview } from './pages/Overview'
import { LiveFeed } from './pages/LiveFeed'
import { TokenExplorer } from './pages/TokenExplorer'
import { NarrativeExplorer } from './pages/NarrativeExplorer'
import { AlertCenter } from './pages/AlertCenter'
import { Configuration } from './pages/Configuration'
import { Holdings } from './pages/Holdings'
import { Notifications } from './pages/Notifications'

// ---- Login screen ----------------------------------------------------------

function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [key, setKey] = useState('')
  const [err, setErr] = useState('')
  const [checking, setChecking] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setChecking(true)
    setApiKey(key)
    try {
      await api.health()
      onLogin()
    } catch {
      setErr('Invalid API key or server unreachable.')
      sessionStorage.removeItem('api_key')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        width: '100vw',
        background: '#0a0b0e',
      }}
    >
      <div
        style={{
          background: '#161b22',
          border: '1px solid #21262d',
          borderRadius: 10,
          padding: '40px 48px',
          width: 400,
          textAlign: 'center',
        }}
      >
        <div style={{ color: '#f0883e', fontWeight: 700, fontSize: 16, marginBottom: 8 }}>
          MC Trend Analysis
        </div>
        <div style={{ color: '#6e7681', fontSize: 12, marginBottom: 28 }}>
          Operator Dashboard
        </div>
        <form onSubmit={submit}>
          <input
            type="password"
            placeholder="API Key (leave empty if not configured)"
            value={key}
            onChange={e => setKey(e.target.value)}
            style={{
              width: '100%',
              background: '#21262d',
              color: '#c9d1d9',
              border: '1px solid #30363d',
              borderRadius: 6,
              padding: '10px 12px',
              fontSize: 13,
              fontFamily: 'monospace',
              boxSizing: 'border-box',
              marginBottom: 12,
            }}
          />
          {err && (
            <div style={{ color: '#f85149', fontSize: 12, marginBottom: 10 }}>{err}</div>
          )}
          <button
            type="submit"
            disabled={checking}
            style={{
              width: '100%',
              background: '#238636',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '10px',
              fontSize: 13,
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {checking ? 'Connecting…' : 'Connect'}
          </button>
        </form>
        <div style={{ marginTop: 16, fontSize: 11, color: '#484f58', lineHeight: 1.6 }}>
          Intelligence layer only. Not a trading system.<br />
          Access this dashboard only on trusted networks.
        </div>
      </div>
    </div>
  )
}

// ---- Root app --------------------------------------------------------------

function AppInner() {
  const [authed, setAuthed] = useState(false)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    // If key exists in session, verify it still works
    if (hasApiKey()) {
      api.health()
        .then(() => setAuthed(true))
        .catch(() => {
          sessionStorage.removeItem('api_key')
          setAuthed(false)
        })
        .finally(() => setChecking(false))
    } else {
      // Try unauthenticated access first (no key configured on server)
      api.health()
        .then(() => { setAuthed(true); setChecking(false) })
        .catch(() => setChecking(false))
    }
  }, [])

  if (checking) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#0a0b0e', color: '#6e7681', fontSize: 12 }}>
        Connecting to backend…
      </div>
    )
  }

  if (!authed) {
    return <LoginScreen onLogin={() => setAuthed(true)} />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/feed" element={<LiveFeed />} />
        <Route path="/tokens" element={<TokenExplorer />} />
        <Route path="/narratives" element={<NarrativeExplorer />} />
        <Route path="/alerts" element={<AlertCenter />} />
        <Route path="/holdings" element={<Holdings />} />
        <Route path="/notifications" element={<Notifications />} />
        <Route path="/config" element={<Configuration />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  )
}
