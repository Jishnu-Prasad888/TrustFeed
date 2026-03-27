import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchSettings, updateSettings } from '../api'
import { Save } from 'lucide-react'
import toast from 'react-hot-toast'

export default function Settings() {
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const [form, setForm] = useState({
    scrape_interval_minutes: 30,
    ollama_model:            'llama3',
    recency_decay_lambda:    0.05,
    max_rag_chunks:          8,
  })

  useEffect(() => {
    if (settings) {
      setForm({
        scrape_interval_minutes: parseInt(settings.scrape_interval_minutes),
        ollama_model:            settings.ollama_model,
        recency_decay_lambda:    parseFloat(settings.recency_decay_lambda),
        max_rag_chunks:          parseInt(settings.max_rag_chunks),
      })
    }
  }, [settings])

  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => { toast.success('Settings saved'); qc.invalidateQueries(['settings']) },
    onError:   () => toast.error('Failed to save settings'),
  })

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">Global scraper and RAG configuration</p>
        </div>
        <button className="btn-primary" onClick={() => save.mutate(form)} disabled={save.isPending}>
          <Save size={16} /> Save Settings
        </button>
      </div>

      <div className="settings-grid">

        <div className="settings-card">
          <h3 className="settings-section-title">Scraper</h3>

          <div className="form-group">
            <label>Scrape Interval (minutes)</label>
            <input
              type="number" min={1} max={1440}
              value={form.scrape_interval_minutes}
              onChange={e => set('scrape_interval_minutes', parseInt(e.target.value))}
            />
            <span className="form-hint">How often to auto-scrape all active profiles</span>
          </div>
        </div>

        <div className="settings-card">
          <h3 className="settings-section-title">LLM (Ollama)</h3>

          <div className="form-group">
            <label>Model Name</label>
            <input
              value={form.ollama_model}
              onChange={e => set('ollama_model', e.target.value)}
              placeholder="llama3"
            />
            <span className="form-hint">
              Any model pulled via <code>ollama pull &lt;model&gt;</code>.
              Recommended: llama3, mistral, phi3
            </span>
          </div>

          <div className="form-group">
            <label>Max RAG Chunks — <strong>{form.max_rag_chunks}</strong></label>
            <input
              type="range" min={1} max={20}
              value={form.max_rag_chunks}
              onChange={e => set('max_rag_chunks', parseInt(e.target.value))}
              className="trust-slider"
            />
            <span className="form-hint">Number of source chunks injected into the prompt</span>
          </div>
        </div>

        <div className="settings-card">
          <h3 className="settings-section-title">Recency Decay</h3>

          <div className="form-group">
            <label>Lambda (λ) — <strong>{form.recency_decay_lambda}</strong></label>
            <input
              type="range" min={0.001} max={0.5} step={0.001}
              value={form.recency_decay_lambda}
              onChange={e => set('recency_decay_lambda', parseFloat(e.target.value))}
              className="trust-slider"
            />
            <div className="slider-labels">
              <span>Slow decay (long memory)</span>
              <span>Fast decay (recent only)</span>
            </div>
            <span className="form-hint">
              score = trust × exp(−λ × age_days).
              Low λ = older posts still relevant. High λ = recency matters more.
            </span>
          </div>

          <div className="decay-preview">
            {[1, 7, 30, 90].map(days => {
              const score = Math.exp(-form.recency_decay_lambda * days)
              const pct = Math.round(score * 100)
              const color = pct >= 60 ? '#22c55e' : pct >= 30 ? '#f59e0b' : '#ef4444'
              return (
                <div key={days} className="decay-row">
                  <span>{days}d ago</span>
                  <div className="decay-bar">
                    <div style={{ width: `${pct}%`, background: color, height: '100%', borderRadius: 2, transition: 'width 0.3s' }} />
                  </div>
                  <span style={{ color }}>{pct}%</span>
                </div>
              )
            })}
          </div>
        </div>

      </div>
    </div>
  )
}
