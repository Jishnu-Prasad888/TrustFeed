import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchPosts, fetchProfiles } from '../api'
import { formatDistanceToNow, format } from 'date-fns'

export default function Posts() {
  const [selectedProfile, setSelectedProfile] = useState('')

  const { data: profiles = [] } = useQuery({ queryKey: ['profiles'], queryFn: fetchProfiles })
  const { data: posts = [], isLoading } = useQuery({
    queryKey: ['posts', selectedProfile],
    queryFn: () => fetchPosts(selectedProfile || undefined),
    refetchInterval: 30_000,
  })

  const profileMap = Object.fromEntries(profiles.map(p => [p.id, p]))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Posts</h1>
          <p className="page-sub">All scraped posts (latest first)</p>
        </div>
        <select
          className="filter-select"
          value={selectedProfile}
          onChange={e => setSelectedProfile(e.target.value)}
        >
          <option value="">All profiles</option>
          {profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      {isLoading ? (
        <div className="loading-state">Loading posts…</div>
      ) : posts.length === 0 ? (
        <div className="empty-state">No posts yet. Trigger a scrape from Dashboard.</div>
      ) : (
        <div className="post-list">
          {posts.map(post => {
            const profile = profileMap[post.profile_id]
            const trust = post.trust_at_embed ?? profile?.trust ?? 0
            const color = trust >= 0.7 ? '#22c55e' : trust >= 0.4 ? '#f59e0b' : '#ef4444'
            return (
              <div key={post.id} className="post-card">
                <div className="post-card-header">
                  <div className="post-meta">
                    <span className="post-source">{profile?.name ?? `Profile ${post.profile_id}`}</span>
                    <span className="trust-chip" style={{ color, borderColor: color }}>
                      trust {(trust * 100).toFixed(0)}%
                    </span>
                    {post.embedded && <span className="badge badge-embedded">embedded</span>}
                  </div>
                  <div className="post-time">
                    {post.published_at
                      ? format(new Date(post.published_at), 'MMM d, yyyy')
                      : formatDistanceToNow(new Date(post.scraped_at), { addSuffix: true })}
                  </div>
                </div>
                <div className="post-content">{post.raw_content.slice(0, 320)}{post.raw_content.length > 320 ? '…' : ''}</div>
                {post.url && (
                  <a href={post.url} target="_blank" rel="noreferrer" className="post-link">
                    View source →
                  </a>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
