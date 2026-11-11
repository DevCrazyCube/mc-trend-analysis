/**
 * React hook for audio alert playback.
 *
 * Responsibilities:
 * - Maintain a per-session Set of seen alert IDs (cleared on page load — no replay on refresh)
 * - Enforce burst-protection cooldown between sounds
 * - Generate tones via Web Audio API (no audio files required)
 * - Persist and expose settings (enable/disable, volume, type map, cooldown)
 */

import { useCallback, useRef, useState } from 'react'
import {
  loadSettings,
  saveSettings,
  shouldPlaySound,
} from './audioAlerts'
import type { AudioSettings, SoundType } from './audioAlerts'

// ---------------------------------------------------------------------------
// Tone generators
// ---------------------------------------------------------------------------

/**
 * Buy sound: ascending two-note chime (C5 → E5), warm sine wave.
 * Conveys opportunity / positive signal.
 */
function playBuyTone(ctx: AudioContext, volume: number): void {
  const gain = ctx.createGain()
  gain.connect(ctx.destination)
  const now = ctx.currentTime
  gain.gain.setValueAtTime(volume * 0.28, now)
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.5)

  const osc = ctx.createOscillator()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(523.25, now)        // C5
  osc.frequency.setValueAtTime(659.25, now + 0.14) // E5
  osc.connect(gain)
  osc.start(now)
  osc.stop(now + 0.5)
}

/**
 * Sell sound: descending two-note alert (A5 → F4), sharper sawtooth wave.
 * Conveys urgency / risk signal.
 */
function playSellTone(ctx: AudioContext, volume: number): void {
  const gain = ctx.createGain()
  gain.connect(ctx.destination)
  const now = ctx.currentTime
  gain.gain.setValueAtTime(volume * 0.22, now)
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.4)

  const osc = ctx.createOscillator()
  osc.type = 'sawtooth'
  osc.frequency.setValueAtTime(880.0, now)         // A5
  osc.frequency.setValueAtTime(349.23, now + 0.15) // F4
  osc.connect(gain)
  osc.start(now)
  osc.stop(now + 0.4)
}

function playTone(ctx: AudioContext, soundType: SoundType, volume: number): void {
  if (soundType === 'buy') playBuyTone(ctx, volume)
  else if (soundType === 'sell') playSellTone(ctx, volume)
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseAudioAlertsReturn {
  settings: AudioSettings
  updateSettings: (patch: Partial<AudioSettings>) => void
  /** Call this for every new_alert SSE event. Handles dedup and cooldown internally. */
  onAlert: (alertId: string, alertType: string) => void
  /** Play a test tone immediately (bypasses dedup and cooldown). */
  testSound: (soundType: SoundType) => void
}

export function useAudioAlerts(): UseAudioAlertsReturn {
  const [settings, setSettingsState] = useState<AudioSettings>(() => loadSettings())

  // Per-session dedup: cleared on every page load — no replay on refresh.
  const seenIds = useRef<Set<string>>(new Set())
  const lastPlayedAtMs = useRef<number>(0)
  const audioCtxRef = useRef<AudioContext | null>(null)

  const getOrCreateCtx = useCallback((): AudioContext | null => {
    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new AudioContext()
      }
      if (audioCtxRef.current.state === 'suspended') {
        // Best-effort resume — may be blocked until a user gesture
        audioCtxRef.current.resume().catch(() => undefined)
      }
      return audioCtxRef.current
    } catch {
      return null
    }
  }, [])

  const updateSettings = useCallback((patch: Partial<AudioSettings>) => {
    setSettingsState(prev => {
      const next = { ...prev, ...patch }
      saveSettings(next)
      return next
    })
  }, [])

  const onAlert = useCallback(
    (alertId: string, alertType: string) => {
      const nowMs = Date.now()
      const soundType = shouldPlaySound(
        alertId,
        alertType,
        settings,
        seenIds.current,
        nowMs,
        lastPlayedAtMs.current,
      )

      // Always register the ID so repeated delivery doesn't replay after cooldown lifts
      if (settings.enabled && !seenIds.current.has(alertId)) {
        seenIds.current.add(alertId)
      }

      if (soundType === 'none') return

      lastPlayedAtMs.current = nowMs

      const ctx = getOrCreateCtx()
      if (!ctx) return
      try {
        playTone(ctx, soundType, settings.volume)
      } catch {
        // AudioContext failure — silent
      }
    },
    [settings, getOrCreateCtx],
  )

  const testSound = useCallback(
    (soundType: SoundType) => {
      const ctx = getOrCreateCtx()
      if (!ctx) return
      try {
        playTone(ctx, soundType, settings.volume)
      } catch {
        // silent
      }
    },
    [settings.volume, getOrCreateCtx],
  )

  return { settings, updateSettings, onAlert, testSound }
}
