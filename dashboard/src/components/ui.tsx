/** Shared UI primitives — no external component library required. */

import type { ReactNode } from 'react'

// ---- Card ----------------------------------------------------------------

export function Card({
  children,
  style,
}: {
  children: ReactNode
  style?: React.CSSProperties
}) {
  return (
    <div
      style={{
        background: '#161b22',
        border: '1px solid #21262d',
        borderRadius: 8,
        padding: '16px 20px',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// ---- Section heading -------------------------------------------------------

export function SectionTitle({
  children,
  right,
}: {
  children: ReactNode
  right?: ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 16,
      }}
    >
      <h2
        style={{
          color: '#c9d1d9',
          fontSize: 15,
          fontWeight: 600,
          margin: 0,
        }}
      >
        {children}
      </h2>
      {right}
    </div>
  )
}

// ---- Status badge ----------------------------------------------------------

type BadgeVariant =
  | 'green'
  | 'yellow'
  | 'red'
  | 'blue'
  | 'gray'
  | 'orange'
  | 'purple'

const BADGE_COLORS: Record<BadgeVariant, { bg: string; color: string }> = {
  green:  { bg: 'rgba(63,185,80,0.15)',  color: '#3fb950' },
  yellow: { bg: 'rgba(210,153,34,0.15)', color: '#d2a317' },
  red:    { bg: 'rgba(248,81,73,0.15)',  color: '#f85149' },
  blue:   { bg: 'rgba(88,166,255,0.15)', color: '#58a6ff' },
  gray:   { bg: 'rgba(139,148,158,0.15)', color: '#8b949e' },
  orange: { bg: 'rgba(240,136,62,0.15)', color: '#f0883e' },
  purple: { bg: 'rgba(188,140,255,0.15)', color: '#bc8cff' },
}

export function Badge({
  variant = 'gray',
  children,
}: {
  variant?: BadgeVariant
  children: ReactNode
}) {
  const { bg, color } = BADGE_COLORS[variant]
  return (
    <span
      style={{
        background: bg,
        color,
        borderRadius: 4,
        padding: '2px 7px',
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: '0.02em',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

// ---- Score bar -------------------------------------------------------------

export function ScoreBar({
  value,
  max = 1,
  color,
  label,
}: {
  value: number | null | undefined
  max?: number
  color?: string
  label?: string
}) {
  const pct = value != null ? Math.min(100, (value / max) * 100) : 0
  const barColor = color || (pct > 65 ? '#3fb950' : pct > 35 ? '#d2a317' : '#f85149')
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {label && (
        <span style={{ fontSize: 11, color: '#8b949e', minWidth: 120 }}>{label}</span>
      )}
      <div
        style={{
          flex: 1,
          height: 6,
          background: '#21262d',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: barColor,
            transition: 'width 0.3s',
          }}
        />
      </div>
      {value != null && (
        <span style={{ fontSize: 11, color: '#8b949e', minWidth: 36, textAlign: 'right' }}>
          {(value * 100).toFixed(0)}%
        </span>
      )}
    </div>
  )
}

// ---- Table -----------------------------------------------------------------

export function Table({
  headers,
  rows,
  emptyMsg = 'No data',
}: {
  headers: string[]
  rows: ReactNode[][]
  emptyMsg?: string
}) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            {headers.map((h) => (
              <th
                key={h}
                style={{
                  textAlign: 'left',
                  padding: '6px 10px',
                  color: '#6e7681',
                  borderBottom: '1px solid #21262d',
                  fontWeight: 500,
                  whiteSpace: 'nowrap',
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={headers.length}
                style={{ padding: '20px 10px', color: '#6e7681', textAlign: 'center' }}
              >
                {emptyMsg}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={i}
                style={{
                  borderBottom: '1px solid #161b22',
                }}
              >
                {row.map((cell, j) => (
                  <td
                    key={j}
                    style={{
                      padding: '7px 10px',
                      color: '#c9d1d9',
                      verticalAlign: 'middle',
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

// ---- Stat tile -------------------------------------------------------------

export function StatTile({
  label,
  value,
  sub,
  color,
}: {
  label: string
  value: string | number
  sub?: string
  color?: string
}) {
  return (
    <Card>
      <div style={{ fontSize: 11, color: '#6e7681', marginBottom: 4 }}>{label}</div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: color || '#c9d1d9',
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>{sub}</div>
      )}
    </Card>
  )
}

// ---- Loading / Error -------------------------------------------------------

export function Loading() {
  return (
    <div style={{ padding: 32, color: '#6e7681', textAlign: 'center' }}>
      Loading…
    </div>
  )
}

export function ErrorMsg({ msg }: { msg: string }) {
  return (
    <div
      style={{
        padding: 16,
        background: 'rgba(248,81,73,0.1)',
        border: '1px solid rgba(248,81,73,0.3)',
        borderRadius: 6,
        color: '#f85149',
        fontSize: 12,
      }}
    >
      {msg}
    </div>
  )
}

// ---- Util: alert type badge variant ----------------------------------------

export function alertTypeBadge(
  type: string
): BadgeVariant {
  if (type === 'possible_entry') return 'green'
  if (type === 'high_potential_watch') return 'blue'
  if (type === 'take_profit_watch') return 'orange'
  if (type === 'exit_risk') return 'red'
  if (type === 'verify') return 'yellow'
  if (type === 'watch') return 'gray'
  return 'gray'
}

export function riskColor(value: number | null | undefined): string {
  if (value == null) return '#6e7681'
  if (value > 0.65) return '#f85149'
  if (value > 0.4) return '#d2a317'
  return '#3fb950'
}

export function scoreColor(value: number | null | undefined): string {
  if (value == null) return '#6e7681'
  if (value > 0.65) return '#3fb950'
  if (value > 0.35) return '#d2a317'
  return '#f85149'
}

export function fmtDate(iso: string | undefined | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

export function shortAddr(addr: string | undefined | null): string {
  if (!addr) return '—'
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}
