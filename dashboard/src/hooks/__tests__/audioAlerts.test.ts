/**
 * Unit tests for audio alert pure logic.
 *
 * Covers:
 *   - Alert-type → sound-type mapping (getSoundType)
 *   - Deduplication via shouldPlaySound
 *   - Burst-protection cooldown via shouldPlaySound
 *   - Settings persistence (loadSettings / saveSettings)
 */

import { describe, it, expect, beforeEach } from 'vitest'
import {
  getSoundType,
  shouldPlaySound,
  loadSettings,
  saveSettings,
  DEFAULT_SETTINGS,
  DEFAULT_ALERT_TYPE_MAP,
} from '../audioAlerts'
import type { AudioSettings } from '../audioAlerts'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function freshSettings(overrides: Partial<AudioSettings> = {}): AudioSettings {
  return {
    ...DEFAULT_SETTINGS,
    alertTypeMap: { ...DEFAULT_ALERT_TYPE_MAP },
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Alert-type mapping
// ---------------------------------------------------------------------------

describe('getSoundType', () => {
  const mapping = { ...DEFAULT_ALERT_TYPE_MAP }

  it('maps possible_entry to buy', () => {
    expect(getSoundType('possible_entry', mapping)).toBe('buy')
  })

  it('maps high_potential_watch to buy', () => {
    expect(getSoundType('high_potential_watch', mapping)).toBe('buy')
  })

  it('maps exit_risk to sell', () => {
    expect(getSoundType('exit_risk', mapping)).toBe('sell')
  })

  it('maps take_profit_watch to sell', () => {
    expect(getSoundType('take_profit_watch', mapping)).toBe('sell')
  })

  it('maps discard to none', () => {
    expect(getSoundType('discard', mapping)).toBe('none')
  })

  it('returns none for unknown alert types', () => {
    expect(getSoundType('unknown_type', mapping)).toBe('none')
    expect(getSoundType('', mapping)).toBe('none')
    expect(getSoundType('verify', mapping)).toBe('none')
  })

  it('respects custom mapping overrides', () => {
    const custom = { ...mapping, discard: 'sell' as const }
    expect(getSoundType('discard', custom)).toBe('sell')
  })
})

// ---------------------------------------------------------------------------
// Deduplication
// ---------------------------------------------------------------------------

describe('shouldPlaySound — deduplication', () => {
  const settings = freshSettings({ cooldownMs: 0 })  // disable cooldown for dedup tests

  it('returns sound type on first occurrence', () => {
    const seen = new Set<string>()
    const result = shouldPlaySound('alert-1', 'possible_entry', settings, seen, 1000, 0)
    expect(result).toBe('buy')
  })

  it('returns none for a previously seen alert_id', () => {
    const seen = new Set<string>(['alert-1'])
    const result = shouldPlaySound('alert-1', 'possible_entry', settings, seen, 2000, 0)
    expect(result).toBe('none')
  })

  it('allows a different alert_id even when another was recently seen', () => {
    const seen = new Set<string>(['alert-1'])
    const result = shouldPlaySound('alert-2', 'exit_risk', settings, seen, 2000, 0)
    expect(result).toBe('sell')
  })

  it('returns none when audio is globally disabled', () => {
    const disabledSettings = freshSettings({ enabled: false, cooldownMs: 0 })
    const seen = new Set<string>()
    const result = shouldPlaySound('alert-1', 'possible_entry', disabledSettings, seen, 1000, 0)
    expect(result).toBe('none')
  })

  it('returns none for alert types mapped to none', () => {
    const seen = new Set<string>()
    const result = shouldPlaySound('alert-1', 'discard', settings, seen, 1000, 0)
    expect(result).toBe('none')
  })

  it('returns none for unknown alert types', () => {
    const seen = new Set<string>()
    const result = shouldPlaySound('alert-1', 'not_a_real_type', settings, seen, 1000, 0)
    expect(result).toBe('none')
  })
})

// ---------------------------------------------------------------------------
// Burst-protection cooldown
// ---------------------------------------------------------------------------

describe('shouldPlaySound — cooldown', () => {
  const settings = freshSettings({ cooldownMs: 2000 })

  it('allows sound when no previous play', () => {
    const seen = new Set<string>()
    const result = shouldPlaySound('alert-1', 'possible_entry', settings, seen, 5000, 0)
    expect(result).toBe('buy')
  })

  it('suppresses sound within cooldown window', () => {
    const seen = new Set<string>()
    // lastPlayedAt = 5000, now = 6000, cooldownMs = 2000 → within cooldown
    const result = shouldPlaySound('alert-2', 'possible_entry', settings, seen, 6000, 5000)
    expect(result).toBe('none')
  })

  it('allows sound after cooldown has passed', () => {
    const seen = new Set<string>()
    // lastPlayedAt = 5000, now = 7001, cooldownMs = 2000 → just past cooldown
    const result = shouldPlaySound('alert-2', 'possible_entry', settings, seen, 7001, 5000)
    expect(result).toBe('buy')
  })

  it('cooldown applies even to different alert types', () => {
    const seen = new Set<string>()
    const result = shouldPlaySound('alert-2', 'exit_risk', settings, seen, 6000, 5000)
    expect(result).toBe('none')
  })
})

// ---------------------------------------------------------------------------
// Settings persistence
// ---------------------------------------------------------------------------

describe('loadSettings / saveSettings', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns default settings when nothing is stored', () => {
    const loaded = loadSettings()
    expect(loaded.enabled).toBe(DEFAULT_SETTINGS.enabled)
    expect(loaded.volume).toBe(DEFAULT_SETTINGS.volume)
    expect(loaded.cooldownMs).toBe(DEFAULT_SETTINGS.cooldownMs)
    expect(loaded.alertTypeMap).toEqual(DEFAULT_ALERT_TYPE_MAP)
  })

  it('round-trips settings through localStorage', () => {
    const custom: AudioSettings = {
      enabled: false,
      volume: 0.8,
      cooldownMs: 5000,
      alertTypeMap: { ...DEFAULT_ALERT_TYPE_MAP, discard: 'sell' },
    }
    saveSettings(custom)
    const loaded = loadSettings()
    expect(loaded.enabled).toBe(false)
    expect(loaded.volume).toBe(0.8)
    expect(loaded.cooldownMs).toBe(5000)
    expect(loaded.alertTypeMap.discard).toBe('sell')
  })

  it('merges saved partial alertTypeMap with defaults', () => {
    // Simulate a save that only overrides one key
    const partial = {
      enabled: true,
      volume: 0.3,
      cooldownMs: 1000,
      alertTypeMap: { possible_entry: 'none' },
    }
    localStorage.setItem('mc_audio_settings', JSON.stringify(partial))
    const loaded = loadSettings()
    // Custom override respected
    expect(loaded.alertTypeMap.possible_entry).toBe('none')
    // Default for other keys preserved
    expect(loaded.alertTypeMap.exit_risk).toBe('sell')
    expect(loaded.alertTypeMap.take_profit_watch).toBe('sell')
  })

  it('returns defaults when stored JSON is invalid', () => {
    localStorage.setItem('mc_audio_settings', 'not-valid-json{{{')
    const loaded = loadSettings()
    expect(loaded).toEqual(expect.objectContaining({
      enabled: DEFAULT_SETTINGS.enabled,
      volume: DEFAULT_SETTINGS.volume,
    }))
  })

  it('persists enabled=false correctly', () => {
    saveSettings(freshSettings({ enabled: false }))
    const loaded = loadSettings()
    expect(loaded.enabled).toBe(false)
  })
})
