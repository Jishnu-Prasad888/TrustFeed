import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchProfiles, createProfile, updateProfile, deleteProfile, scrapeProfile } from '../api'
import { Plus, Trash2, RefreshCw, Pencil, Check, X, ToggleLeft, ToggleRight } from 'lucide-react'
import toast from 'react-hot-toast'

const PLATFORMS = ['rss', 'twitter', 'web']

function TrustBar({ value }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.7 ? '#22c55e' : value >= 0.4 ? '#f59e0b' : '#ef4444'
  return (
    <div className="trust-bar-wrap">
      <div className="trust-bar-track">
        <div className="trust-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="trust-bar-label" style={{ color }}>{pct}%</span>
    </div>
  )
}

function ProfileRow({ profile, onEdit, onDelete, onScrape }) {
  return (
    <div className={`profile-row ${profile.is_active ? '' : 'inactive'}`}>
      <div className="profile-row-main">
        <div className="profile-row-name">{profile.name}</div>
        <div className="profile-row-url">{profile.url}</div>
      </div>
      <span className="badge badge-platform">{profile.platform}</span>
      <div className="profile-row-trust">
        <TrustBar value={profile.trust} />
      </div>
      <div className="profile-row-status">
        {profile.is_active
          ? <span className="status-dot active">Active</span>
          : <span className="status-dot passive">Passive</span>}
      </div>
      <div className="profile-row-actions">
        <button className="icon-btn" title="Scrape now" onClick={() => onScrape(profile)}>
          <RefreshCw size={15} />
        </button>
        <button className="icon-btn" title="Edit" onClick={() => onEdit(profile)}>
          <Pencil size={15} />
        </button>
        <button className="icon-btn danger" title="Delete" onClick={() => onDelete(profile)}>
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  )
}

function ProfileModal({ profile, onClose, onSave }) {
  const isEdit = Boolean(profile?.id)
  const [form, setForm] = useState({
    name:      profile?.name      ?? '',
    url:       profile?.url       ?? '',
    platform:  profile?.platform  ?? 'rss',
    trust:     profile?.trust     ?? 0.5,
    is_active: profile?.is_active ?? true,
  })

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{isEdit ? 'Edit Profile' : 'Add Profile'}</h2>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="form-group">
          <label>Name</label>
          <input value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. OpenAI Blog" />
        </div>

        <div className="form-group">
          <label>URL</label>
          <input value={form.url} onChange={e => set('url', e.target.value)} placeholder="https://…" />
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Platform</label>
            <select value={form.platform} onChange={e => set('platform', e.target.value)}>
              {PLATFORMS.map(p => <option key={p}>{p}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Status</label>
            <div className="toggle-row">
              <button
                className={`toggle-btn ${form.is_active ? 'on' : 'off'}`}
                onClick={() => set('is_active', !form.is_active)}
              >
                {form.is_active ? <ToggleRight size={22} /> : <ToggleLeft size={22} />}
                {form.is_active ? 'Active' : 'Passive'}
              </button>
            </div>
          </div>
        </div>

        <div className="form-group">
          <label>Trust Rating — <strong>{(form.trust * 100).toFixed(0)}%</strong></label>
          <input
            type="range" min="0" max="1" step="0.01"
            value={form.trust}
            onChange={e => set('trust', parseFloat(e.target.value))}
            className="trust-slider"
          />
          <div className="slider-labels"><span>Low</span><span>Medium</span><span>High</span></div>
        </div>

        <div className="modal-footer">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={() => onSave(form)}>
            <Check size={15} /> {isEdit ? 'Save Changes' : 'Add Profile'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Profiles() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)  // null | profile | 'new'
  const [filter, setFilter] = useState('')

  const { data: profiles = [] } = useQuery({ queryKey: ['profiles'], queryFn: fetchProfiles })

  const create = useMutation({
    mutationFn: createProfile,
    onSuccess: () => { toast.success('Profile added'); qc.invalidateQueries(['profiles']); setEditing(null) },
    onError: e => toast.error(e.response?.data?.detail ?? 'Error'),
  })

  const update = useMutation({
    mutationFn: ({ id, data }) => updateProfile(id, data),
    onSuccess: () => { toast.success('Profile updated'); qc.invalidateQueries(['profiles']); setEditing(null) },
    onError: e => toast.error(e.response?.data?.detail ?? 'Error'),
  })

  const remove = useMutation({
    mutationFn: deleteProfile,
    onSuccess: () => { toast.success('Profile deleted'); qc.invalidateQueries(['profiles']) },
  })

  const scrape = useMutation({
    mutationFn: p => scrapeProfile(p.id),
    onSuccess: (data) => toast.success(`Scraped: ${data.new_posts} new posts`),
    onError: () => toast.error('Scrape failed'),
  })

  const handleSave = (form) => {
    if (editing?.id) {
      update.mutate({ id: editing.id, data: form })
    } else {
      create.mutate(form)
    }
  }

  const handleDelete = (p) => {
    if (confirm(`Delete "${p.name}"? This will remove all embeddings.`)) remove.mutate(p.id)
  }

  const filtered = profiles.filter(p =>
    p.name.toLowerCase().includes(filter.toLowerCase()) ||
    p.url.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Profiles</h1>
          <p className="page-sub">Manage sources and trust ratings</p>
        </div>
        <button className="btn-primary" onClick={() => setEditing({})}>
          <Plus size={16} /> Add Profile
        </button>
      </div>

      <input
        className="search-input"
        placeholder="Filter profiles…"
        value={filter}
        onChange={e => setFilter(e.target.value)}
      />

      {filtered.length === 0 ? (
        <div className="empty-state">No profiles found.</div>
      ) : (
        <div className="profile-list">
          <div className="profile-list-header">
            <span>Profile</span>
            <span>Platform</span>
            <span>Trust</span>
            <span>Status</span>
            <span>Actions</span>
          </div>
          {filtered.map(p => (
            <ProfileRow
              key={p.id}
              profile={p}
              onEdit={setEditing}
              onDelete={handleDelete}
              onScrape={p => scrape.mutate(p)}
            />
          ))}
        </div>
      )}

      {editing !== null && (
        <ProfileModal
          profile={editing?.id ? editing : null}
          onClose={() => setEditing(null)}
          onSave={handleSave}
        />
      )}
    </div>
  )
}
