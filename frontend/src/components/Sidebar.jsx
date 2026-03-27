import { LayoutDashboard, Users, FileText, Brain, Settings, Rss } from 'lucide-react'

const nav = [
  { id: 'dashboard', label: 'Dashboard',  icon: LayoutDashboard },
  { id: 'profiles',  label: 'Profiles',   icon: Users },
  { id: 'posts',     label: 'Posts',      icon: FileText },
  { id: 'rag',       label: 'Ask AI',     icon: Brain },
  { id: 'settings',  label: 'Settings',   icon: Settings },
]

export default function Sidebar({ current, navigate }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <Rss size={22} className="brand-icon" />
        <span>TrustFeed</span>
      </div>
      <nav className="sidebar-nav">
        {nav.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`nav-item ${current === id ? 'active' : ''}`}
            onClick={() => navigate(id)}
          >
            <Icon size={18} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="version-tag">v1.0.0</span>
      </div>
    </aside>
  )
}
