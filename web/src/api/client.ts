import { useSettingsStore } from '@/stores/settings'
import { getAuthToken } from './authtoken'

export class ApiError extends Error {
  status: number
  body: any
  constructor(status: number, body: any) {
    super(typeof body === 'string' ? body : body?.detail || `HTTP ${status}`)
    this.status = status
    this.body = body
  }
}

function baseUrl(): string {
  const s = useSettingsStore()
  return s.backendUrl.replace(/\/$/, '')
}

function apiKey(): string {
  return useSettingsStore().apiKey
}

function authToken(): string {
  return getAuthToken()
}

async function request<T = any>(method: string, path: string, body?: any, query?: Record<string, any>): Promise<T> {
  const url = new URL(baseUrl() + path)
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
    }
  }
  const headers: Record<string, string> = { 'X-API-Key': apiKey() }
  const tk = authToken()
  if (tk) headers['X-Auth-Token'] = tk
  let payload: BodyInit | undefined
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const resp = await fetch(url.toString(), { method, headers, body: payload })
  const text = await resp.text()
  const data = text ? (text.startsWith('{') || text.startsWith('[') ? JSON.parse(text) : text) : null
  if (!resp.ok) throw new ApiError(resp.status, data)
  return data as T
}

export const api = {
  get: <T = any>(path: string, query?: Record<string, any>) => request<T>('GET', path, undefined, query),
  post: <T = any>(path: string, body?: any) => request<T>('POST', path, body),
  put: <T = any>(path: string, body?: any) => request<T>('PUT', path, body),
  patch: <T = any>(path: string, body?: any) => request<T>('PATCH', path, body),
  del: <T = any>(path: string) => request<T>('DELETE', path),
  upload: async <T = any>(path: string, file: File | string, field: string = 'file'): Promise<T> => {
    const form = new FormData()
    form.append(field, file)
    const uheaders: Record<string, string> = { 'X-API-Key': apiKey() }
    const utk = authToken()
    if (utk) uheaders['X-Auth-Token'] = utk
    const resp = await fetch(baseUrl() + path, {
      method: 'POST',
      headers: uheaders,
      body: form,
    })
    const text = await resp.text()
    const data = text ? (text.startsWith('{') ? JSON.parse(text) : text) : null
    if (!resp.ok) throw new ApiError(resp.status, data)
    return data as T
  },
  blob: async (path: string): Promise<Blob> => {
    const bheaders: Record<string, string> = { 'X-API-Key': apiKey() }
    const btk = authToken()
    if (btk) bheaders['X-Auth-Token'] = btk
    const resp = await fetch(baseUrl() + path, { method: 'GET', headers: bheaders })
    if (!resp.ok) {
      const text = await resp.text().catch(() => '')
      throw new ApiError(resp.status, text ? (text.startsWith('{') ? JSON.parse(text) : text) : `HTTP ${resp.status}`)
    }
    return resp.blob()
  },
}
