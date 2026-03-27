import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// ── Profiles ──────────────────────────────────────────────────────────────
export const fetchProfiles    = ()           => api.get('/profiles').then(r => r.data)
export const createProfile    = (data)       => api.post('/profiles', data).then(r => r.data)
export const updateProfile    = (id, data)   => api.patch(`/profiles/${id}`, data).then(r => r.data)
export const deleteProfile    = (id)         => api.delete(`/profiles/${id}`)
export const scrapeProfile    = (id)         => api.post(`/scrape/profile/${id}`).then(r => r.data)

// ── Posts ─────────────────────────────────────────────────────────────────
export const fetchPosts       = (profileId)  =>
  api.get('/posts', { params: { profile_id: profileId, limit: 30 } }).then(r => r.data)

// ── Scrape ────────────────────────────────────────────────────────────────
export const triggerScrape    = ()           => api.post('/scrape/trigger').then(r => r.data)

// ── Settings ──────────────────────────────────────────────────────────────
export const fetchSettings    = ()           => api.get('/settings').then(r => r.data)
export const updateSettings   = (data)       => api.patch('/settings', data).then(r => r.data)

// ── RAG ───────────────────────────────────────────────────────────────────
export const ragQuery         = (question, only_active = true) =>
  api.post('/rag/query', { question, only_active }).then(r => r.data)

// ── Stats ─────────────────────────────────────────────────────────────────
export const fetchStats       = ()           => api.get('/stats').then(r => r.data)
