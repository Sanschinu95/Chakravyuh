import { useState, type ReactNode } from 'react'

interface Props {
  title: string
  badge?: string
  defaultOpen?: boolean
  children: ReactNode
}

/** Sidebar section that can be folded away, so the rail shows one thing at a time. */
export default function Collapsible({
  title,
  badge,
  defaultOpen = true,
  children,
}: Props) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`sect ${open ? 'open' : ''}`}>
      <button className="sect-head" onClick={() => setOpen(!open)}>
        <span className={`sect-caret ${open ? 'open' : ''}`}>▸</span>
        <span className="sect-title">{title}</span>
        {badge && <span className="sect-badge">{badge}</span>}
      </button>
      {open && <div className="sect-body">{children}</div>}
    </section>
  )
}
