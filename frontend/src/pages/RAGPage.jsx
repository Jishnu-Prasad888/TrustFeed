import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ragQuery } from '../api'
import { Brain, Send, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

function ScoreBar({ score }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.6 ? '#22c55e' : score >= 0.35 ? '#f59e0b' : '#ef4444'
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span style={{ color, fontSize: '11px', whiteSpace: 'nowrap' }}>{pct}</span>
    </div>
  )
}

function ChunkItem({ chunk }) {
  const [open, setOpen] = useState(false)
  const pubDate = chunk.published_ts
    ? formatDistanceToNow(new Date(chunk.published_ts * 1000), { addSuffix: true })
    : 'unknown date'

  return (
    <div className="chunk-item">
      <div className="chunk-header" onClick={() => setOpen(!open)}>
        <div className="chunk-meta">
          <span className="chunk-source">{chunk.profile_name}</span>
          <span className="chunk-date">{pubDate}</span>
        </div>
        <div className="chunk-score-row">
          <span className="chunk-score-label">score</span>
          <ScoreBar score={chunk.score} />
          <span className="chunk-trust-label">trust {(chunk.trust * 100).toFixed(0)}%</span>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>
      {open && (
        <div className="chunk-body">
          <p>{chunk.snippet}…</p>
          {chunk.post_url && (
            <a href={chunk.post_url} target="_blank" rel="noreferrer" className="chunk-link">
              <ExternalLink size={12} /> Source
            </a>
          )}
        </div>
      )}
    </div>
  )
}

const SUGGESTIONS = [
  'What are the latest AI model releases?',
  'Summarize recent news about LLMs.',
  'What do trusted sources say about open source AI?',
  'Any conflicting information about AI safety?',
]

export default function RAGPage() {
  const [question, setQuestion] = useState('')
  const [onlyActive, setOnlyActive] = useState(true)
  const [result, setResult] = useState(null)

  const ask = useMutation({
    mutationFn: () => ragQuery(question, onlyActive),
    onSuccess: data => setResult(data),
  })

  const handleSend = () => {
    if (!question.trim()) return
    ask.mutate()
  }

  return (
    <div className="page rag-page">
      <div className="page-header">
        <div>
          <h1 className="page-title"><Brain size={22} style={{ display: 'inline', marginRight: 8 }} />Ask AI</h1>
          <p className="page-sub">Query your knowledge base — answers weighted by trust × recency</p>
        </div>
        <label className="toggle-label">
          <input type="checkbox" checked={onlyActive} onChange={e => setOnlyActive(e.target.checked)} />
          Active profiles only
        </label>
      </div>

      {!result && (
        <div className="suggestions">
          {SUGGESTIONS.map(s => (
            <button key={s} className="suggestion-chip" onClick={() => setQuestion(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="rag-input-row">
        <textarea
          className="rag-textarea"
          rows={3}
          placeholder="Ask anything about your scraped posts…"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) handleSend() }}
        />
        <button className="btn-primary rag-send" onClick={handleSend} disabled={ask.isPending || !question.trim()}>
          {ask.isPending ? <div className="spinner" /> : <Send size={18} />}
        </button>
      </div>
      <div className="rag-hint">⌘ + Enter to send</div>

      {ask.isPending && (
        <div className="rag-loading">
          <div className="pulse-dot" /><div className="pulse-dot" /><div className="pulse-dot" />
          <span>Thinking…</span>
        </div>
      )}

      {result && !ask.isPending && (
        <div className="rag-result">
          <div className="rag-answer-label">Answer <span className="model-tag">{result.model}</span></div>
          <div className="rag-answer">{result.answer}</div>

          <div className="rag-sources-label">
            Sources used ({result.chunks_used.length})
            <span className="sources-hint">sorted by trust × recency score</span>
          </div>
          <div className="chunk-list">
            {result.chunks_used.map((chunk, i) => (
              <ChunkItem key={i} chunk={chunk} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
