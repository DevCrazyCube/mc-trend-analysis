import { NavLink } from 'react-router-dom'
import {
  AlertTriangle,
  Bell,
  BookOpen,
  Coins,
  Home,
  Settings,
  TrendingUp,
  Wallet,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'

interface LayoutProps {
  children: React.ReactNode
}

const NAV = [
  { to: '/', icon: Home, label: 'Overview' },
  { to: '/feed', icon: Zap, label: 'Live Feed' },
  { to: '/tokens', icon: Coins, label: 'Tokens' },
  { to: '/narratives', icon: BookOpen, label: 'Narratives' },
  { to: '/alerts', icon: AlertTriangle, label: 'Alerts' },
  { to: '/holdings', icon: Wallet, label: 'Holdings' },
  { to: '/notifications', icon: Bell, label: 'Notifications' },
  { to: '/config', icon: Settings, label: 'Config' },
]

export function Layout({ children }: LayoutProps) {
  const [unread, setUnread] = useState(0)
  const [wsConnected, setWsConnected] = useState<boolean | null>(null)

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const health = await api.health()
        setWsConnected(health.ws_discovery?.ws_connected ?? false)
        const notifs = await api.notifications(true)
        setUnread(notifs.unread_count ?? 0)
      } catch {}
    }
    fetchStatus()
    const t = setInterval(fetchStatus, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Sidebar */}
      <aside
        style={{
          width: 220,
          minWidth: 220,
          background: '#0d1117',
          borderRight: '1px solid #21262d',
          display: 'flex',
          flexDirection: 'column',
          padding: '16px 0',
        }}
      >
        {/* Brand */}
        <div style={{ padding: '0 16px 16px', borderBottom: '1px solid #21262d' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <TrendingUp size={18} color="#f0883e" />
            <span style={{ color: '#f0883e', fontWeight: 600, fontSize: 13 }}>
              MC Trend Analysis
            </span>
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: '#6e7681' }}>
            Operator Console
          </div>
          {/* WS status pill */}
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: wsConnected === true
                  ? '#3fb950'
                  : wsConnected === false
                  ? '#f85149'
                  : '#6e7681',
                display: 'inline-block',
              }}
            />
            <span style={{ fontSize: 11, color: '#6e7681' }}>
              {wsConnected === true
                ? 'WS discovery live'
                : wsConnected === false
                ? 'WS discovery down'
                : 'Checking…'}
            </span>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '12px 0' }}>
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 16px',
                color: isActive ? '#58a6ff' : '#8b949e',
                background: isActive ? 'rgba(88,166,255,0.08)' : 'transparent',
                textDecoration: 'none',
                fontSize: 13,
                borderLeft: isActive ? '2px solid #58a6ff' : '2px solid transparent',
                transition: 'background 0.1s',
                position: 'relative',
              })}
            >
              <Icon size={15} />
              {label}
              {label === 'Notifications' && unread > 0 && (
                <span
                  style={{
                    marginLeft: 'auto',
                    background: '#f85149',
                    color: '#fff',
                    borderRadius: 10,
                    padding: '0 5px',
                    fontSize: 10,
                    minWidth: 16,
                    textAlign: 'center',
                  }}
                >
                  {unread}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid #21262d',
            fontSize: 11,
            color: '#6e7681',
          }}
        >
          Intelligence layer only.
          <br />
          Not a trading system.
        </div>
      </aside>

      {/* Main content */}
      <main
        style={{
          flex: 1,
          overflow: 'auto',
          background: '#0a0b0e',
          padding: 24,
        }}
      >
        {children}
      </main>
    </div>
  )
}
