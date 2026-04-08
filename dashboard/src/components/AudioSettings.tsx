/**
 * Audio notification settings panel.
 * Rendered inline on the LiveFeed page when the user opens the audio settings toggle.
 */

import type { AudioSettings, SoundType } from '../hooks/audioAlerts'
import { DEFAULT_ALERT_TYPE_MAP } from '../hooks/audioAlerts'

interface AudioSettingsProps {
  settings: AudioSettings
  onUpdate: (patch: Partial<AudioSettings>) => void
  onTest: (soundType: SoundType) => void
}

const ALERT_TYPE_LABELS: Record<string, string> = {
  possible_entry: 'Possible Entry',
  high_potential_watch: 'High Potential Watch',
  exit_risk: 'Exit Risk',
  take_profit_watch: 'Take Profit Watch',
  discard: 'Discard',
}

const SOUND_OPTIONS: { value: SoundType; label: string }[] = [
  { value: 'buy', label: 'Buy (ascending chime)' },
  { value: 'sell', label: 'Sell (descending alert)' },
  { value: 'none', label: 'Off' },
]

const row: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '5px 0',
}

const label: React.CSSProperties = {
  fontSize: 11,
  color: '#8b949e',
  minWidth: 160,
}

const select: React.CSSProperties = {
  background: '#21262d',
  color: '#c9d1d9',
  border: '1px solid #30363d',
  borderRadius: 4,
  padding: '3px 6px',
  fontSize: 11,
  cursor: 'pointer',
}

const btnStyle = (variant: 'green' | 'blue' | 'gray'): React.CSSProperties => {
  const colors = {
    green: { bg: 'rgba(63,185,80,0.15)', color: '#3fb950', border: 'rgba(63,185,80,0.3)' },
    blue:  { bg: 'rgba(88,166,255,0.15)', color: '#58a6ff', border: 'rgba(88,166,255,0.3)' },
    gray:  { bg: 'transparent', color: '#6e7681', border: '#30363d' },
  }[variant]
  return {
    background: colors.bg,
    color: colors.color,
    border: `1px solid ${colors.border}`,
    borderRadius: 4,
    padding: '3px 10px',
    cursor: 'pointer',
    fontSize: 11,
  }
}

export function AudioSettingsPanel({ settings, onUpdate, onTest }: AudioSettingsProps) {
  const toggleEnabled = () => onUpdate({ enabled: !settings.enabled })

  const setVolume = (e: React.ChangeEvent<HTMLInputElement>) =>
    onUpdate({ volume: parseFloat(e.target.value) })

  const setTypeMap = (alertType: string, soundType: SoundType) =>
    onUpdate({ alertTypeMap: { ...settings.alertTypeMap, [alertType]: soundType } })

  const resetDefaults = () =>
    onUpdate({ alertTypeMap: { ...DEFAULT_ALERT_TYPE_MAP } })

  return (
    <div
      style={{
        background: '#0d1117',
        border: '1px solid #21262d',
        borderRadius: 8,
        padding: '14px 18px',
        marginBottom: 16,
        fontSize: 12,
      }}
    >
      <div style={{ fontSize: 11, color: '#6e7681', fontWeight: 600, marginBottom: 12 }}>
        Audio Notifications
      </div>

      {/* Master toggle */}
      <div style={row}>
        <span style={label}>Enable audio alerts</span>
        <button onClick={toggleEnabled} style={btnStyle(settings.enabled ? 'green' : 'gray')}>
          {settings.enabled ? 'Enabled' : 'Disabled'}
        </button>
      </div>

      {settings.enabled && (
        <>
          {/* Volume */}
          <div style={row}>
            <span style={label}>Volume</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.volume}
              onChange={setVolume}
              style={{ flex: 1, maxWidth: 120, accentColor: '#58a6ff' }}
            />
            <span style={{ fontSize: 11, color: '#6e7681', minWidth: 32 }}>
              {Math.round(settings.volume * 100)}%
            </span>
          </div>

          {/* Per-type mapping */}
          <div style={{ marginTop: 10, marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#484f58' }}>Alert type → sound</span>
          </div>

          {Object.keys(DEFAULT_ALERT_TYPE_MAP).map(alertType => (
            <div key={alertType} style={row}>
              <span style={label}>{ALERT_TYPE_LABELS[alertType] ?? alertType}</span>
              <select
                value={settings.alertTypeMap[alertType] ?? 'none'}
                onChange={e => setTypeMap(alertType, e.target.value as SoundType)}
                style={select}
              >
                {SOUND_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          ))}

          {/* Test buttons */}
          <div style={{ ...row, marginTop: 12, gap: 8 }}>
            <span style={label}>Test sounds</span>
            <button onClick={() => onTest('buy')} style={btnStyle('green')}>
              ▶ Buy
            </button>
            <button onClick={() => onTest('sell')} style={btnStyle('blue')}>
              ▶ Sell
            </button>
            <button onClick={resetDefaults} style={{ ...btnStyle('gray'), marginLeft: 'auto' }}>
              Reset defaults
            </button>
          </div>
        </>
      )}
    </div>
  )
}
