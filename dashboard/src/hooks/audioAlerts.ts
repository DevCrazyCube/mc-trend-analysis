/**
 * Pure logic for audio alert deduplication, type mapping, and settings persistence.
 * No browser APIs or React — fully unit-testable.
 */

export type SoundType = 'buy' | 'sell' | 'none'

export interface AudioSettings {
  /** Master enable/disable toggle. */
  enabled: boolean
  /** Playback volume, 0.0–1.0. */
  volume: number
  /** Per-alert-type sound assignment. */
  alertTypeMap: Record<string, SoundType>
  /** Minimum milliseconds between any two sounds (burst protection). */
  cooldownMs: number
}

/** Default alert-type → sound mapping. */
export const DEFAULT_ALERT_TYPE_MAP: Record<string, SoundType> = {
  possible_entry: 'buy',
  high_potential_watch: 'buy',
  exit_risk: 'sell',
  take_profit_watch: 'sell',
  discard: 'none',
}

export const DEFAULT_SETTINGS: AudioSettings = {
  enabled: true,
  volume: 0.5,
  alertTypeMap: { ...DEFAULT_ALERT_TYPE_MAP },
  cooldownMs: 2000,
}

const STORAGE_KEY = 'mc_audio_settings'

/** Load settings from localStorage, falling back to defaults on any error. */
export function loadSettings(): AudioSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS, alertTypeMap: { ...DEFAULT_SETTINGS.alertTypeMap } }
    const parsed = JSON.parse(raw) as Partial<AudioSettings>
    return {
      ...DEFAULT_SETTINGS,
      ...parsed,
      // Merge alertTypeMap so new defaults aren't lost on a partial saved value
      alertTypeMap: { ...DEFAULT_ALERT_TYPE_MAP, ...(parsed.alertTypeMap ?? {}) },
    }
  } catch {
    return { ...DEFAULT_SETTINGS, alertTypeMap: { ...DEFAULT_SETTINGS.alertTypeMap } }
  }
}

/** Persist settings to localStorage. */
export function saveSettings(settings: AudioSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

/**
 * Resolve which sound to play for a given alert type.
 * Returns 'none' for any type not present in the mapping.
 */
export function getSoundType(alertType: string, mapping: Record<string, SoundType>): SoundType {
  return mapping[alertType] ?? 'none'
}

/**
 * Decide whether to play a sound for an incoming alert.
 *
 * Pure function — callers are responsible for updating seenIds and lastPlayedAt.
 *
 * Returns the SoundType to play, or 'none' to suppress.
 */
export function shouldPlaySound(
  alertId: string,
  alertType: string,
  settings: AudioSettings,
  seenIds: Set<string>,
  nowMs: number,
  lastPlayedAtMs: number,
): SoundType {
  if (!settings.enabled) return 'none'
  if (seenIds.has(alertId)) return 'none'

  const soundType = getSoundType(alertType, settings.alertTypeMap)
  if (soundType === 'none') return 'none'

  if (nowMs - lastPlayedAtMs < settings.cooldownMs) return 'none'

  return soundType
}
