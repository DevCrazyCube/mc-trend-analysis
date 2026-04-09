/**
 * API client — all requests go through here.
 * API key is stored in sessionStorage (set on first load or login prompt).
 */

const BASE = '/api'

function getApiKey(): string {
  return sessionStorage.getItem('api_key') || ''
}

export function setApiKey(key: string) {
  sessionStorage.setItem('api_key', key)
}

export function hasApiKey(): boolean {
  return !!sessionStorage.getItem('api_key')
}

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const key = getApiKey()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (key) headers['Authorization'] = `Bearer ${key}`

  const res = await fetch(`${BASE}${path}`, { ...options, headers })

  if (res.status === 401) {
    sessionStorage.removeItem('api_key')
    window.location.reload()
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }

  return res.json() as Promise<T>
}

export const api = {
  // Health
  health: () => req<any>('/health'),
  sources: () => req<any>('/health/sources'),

  // Tokens
  tokens: (status?: string, limit = 50) =>
    req<any>(`/tokens?${status ? `status=${status}&` : ''}limit=${limit}`),
  token: (id: string) => req<any>(`/tokens/${id}`),

  // Narratives
  narrativeBoard: (classification?: string, includeNoise = false) =>
    req<any>(
      `/narratives/board?include_noise=${includeNoise}` +
      (classification ? `&classification=${encodeURIComponent(classification)}` : '')
    ),
  narratives: (state?: string) =>
    req<any>(`/narratives${state ? `?state=${state}` : ''}`),
  narrative: (id: string) => req<any>(`/narratives/${id}`),

  // Alerts
  alerts: (status?: string, limit = 50) =>
    req<any>(`/alerts?${status ? `status=${status}&` : ''}limit=${limit}`),
  alert: (id: string) => req<any>(`/alerts/${id}`),

  // Config
  config: () => req<any>('/config'),
  weights: () => req<any>('/config/weights'),
  patchConfig: (field: string, value: any) =>
    req<any>('/config', {
      method: 'PATCH',
      body: JSON.stringify({ field, value }),
    }),

  // Holdings
  holdings: () => req<any>('/holdings'),
  createHolding: (body: any) =>
    req<any>('/holdings', { method: 'POST', body: JSON.stringify(body) }),
  updateHolding: (id: string, body: any) =>
    req<any>(`/holdings/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteHolding: (id: string) =>
    req<any>(`/holdings/${id}`, { method: 'DELETE' }),
  wallets: () => req<any>('/holdings/wallets/list'),
  addWallet: (body: any) =>
    req<any>('/holdings/wallets', { method: 'POST', body: JSON.stringify(body) }),
  deleteWallet: (id: string) =>
    req<any>(`/holdings/wallets/${id}`, { method: 'DELETE' }),

  // Notifications
  notifications: (unreadOnly = false) =>
    req<any>(`/notifications?unread_only=${unreadOnly}`),
  markRead: (id: string) =>
    req<any>(`/notifications/${id}/read`, { method: 'POST' }),
  markAllRead: () =>
    req<any>('/notifications/read-all', { method: 'POST' }),
  deliveryLogs: (limit = 100) =>
    req<any>(`/notifications/delivery-logs?limit=${limit}`),
}

/** Open SSE connection for live updates */
export function openEventStream(
  onEvent: (type: string, payload: any) => void
): EventSource {
  const key = getApiKey()
  const url = `${BASE}/events/stream${key ? `?key=${encodeURIComponent(key)}` : ''}`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    try {
      const { type, payload } = JSON.parse(e.data)
      onEvent(type, payload)
    } catch {}
  }
  return es
}
