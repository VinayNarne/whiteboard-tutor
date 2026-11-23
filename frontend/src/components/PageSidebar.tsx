// frontend/src/components/PageSidebar.tsx
// Left rail: quiet page list. Content first — the whiteboard is the hero, so this panel stays
// plain: text navigation, one row per page, per-row actions behind a "more" menu, a one-line
// fullness readout, and two text actions at the bottom. Collapses to a thin numbered rail.

import { useEffect, useState } from 'react';
import type { PageSummary } from '../types';
import { Menu } from './Menu';

interface Props {
  pages: PageSummary[];
  activePageId: string | null;
  isReplaying: boolean;
  onSelectPage: (pageId: string) => void;
  onNewPage: () => void;
  onSavePage: () => void;
  onReplayPage: () => void;
  onBack: () => void;
  onForward: () => void;
  onRenamePage?: (pageId: string, newTitle: string) => void;
  onDeletePage?: (pageId: string) => void;
  /** Off on a lesson board (scene mode), which never fills up. */
  showFullness?: boolean;
  /** wide: full list; compact: starts as a thin rail; phone: full width inside a tab */
  layout?: 'wide' | 'compact' | 'phone';
}

const SOFT_CAP = 15;
const HARD_CAP = 25;

const textButton: React.CSSProperties = {
  background: 'transparent', border: 'none', color: 'var(--ink-2)', cursor: 'pointer',
  fontSize: '13px', fontWeight: 500, padding: '4px 8px', borderRadius: '6px',
};

const LockIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2.5" y="5.5" width="7" height="5" rx="1" /><path d="M4 5.5V4a2 2 0 0 1 4 0v1.5" />
  </svg>
);

const Chevron = ({ dir }: { dir: 'left' | 'right' }) => (
  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d={dir === 'left' ? 'M7.5 2.5 4 6l3.5 3.5' : 'M4.5 2.5 8 6l-3.5 3.5'} />
  </svg>
);

export function PageSidebar({
  pages, activePageId, isReplaying, onSelectPage, onNewPage, onSavePage, onReplayPage,
  onBack, onForward, onRenamePage, onDeletePage, layout = 'wide', showFullness = true,
}: Readonly<Props>) {
  const phone = layout === 'phone';
  const [isCollapsed, setIsCollapsed] = useState(layout === 'compact');
  // follow the screen size: a laptop-width window starts collapsed, a wide one expanded
  useEffect(() => { setIsCollapsed(layout === 'compact'); }, [layout]);
  const [editingPageId, setEditingPageId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  const activeIndex = pages.findIndex(p => p.id === activePageId);
  const canBack = activeIndex > 0;
  const canForward = activeIndex < pages.length - 1;
  const activePage = pages.find(p => p.id === activePageId);

  const elementCount = activePage?.element_count || 0;
  const fullness = Math.min(elementCount / HARD_CAP, 1);
  const fullnessColor = elementCount >= HARD_CAP ? 'var(--danger)' : elementCount >= SOFT_CAP ? 'var(--warn)' : 'var(--accent)';

  const startEditing = (page: PageSummary) => {
    setEditingPageId(page.id);
    setEditTitle(page.title || `Page ${page.page_number}`);
  };
  const commitTitle = (pageId: string) => {
    if (editTitle.trim()) onRenamePage?.(pageId, editTitle.trim());
    setEditingPageId(null);
  };
  const askDelete = (page: PageSummary, i: number) => {
    if (confirm(`Delete ${page.title || `Page ${i + 1}`}?`)) onDeletePage?.(page.id);
  };

  if (isCollapsed && !phone) {
    return (
      <nav aria-label="Notebook pages" style={{
        width: '52px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px',
        background: 'var(--bg)', borderRight: '1px solid var(--border)', padding: '12px 0',
      }}>
        <button onClick={() => setIsCollapsed(false)} aria-label="Expand page list" title="Expand page list" style={{ ...textButton, padding: '6px' }}>
          <Chevron dir="right" />
        </button>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px', overflowY: 'auto' }}>
          {pages.map((p, i) => (
            <button
              key={p.id}
              onClick={() => onSelectPage(p.id)}
              aria-label={`Page ${i + 1}: ${p.title || 'Untitled'}`}
              aria-current={p.id === activePageId ? 'page' : undefined}
              title={`${p.title || `Page ${i + 1}`}`}
              style={{
                ...textButton, width: '32px', height: '32px', padding: 0,
                background: p.id === activePageId ? 'var(--panel)' : 'transparent',
                color: p.id === activePageId ? 'var(--ink)' : 'var(--ink-2)',
                fontWeight: p.id === activePageId ? 600 : 500,
                border: p.id === activePageId ? '1px solid var(--border)' : '1px solid transparent',
              }}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <button onClick={onNewPage} aria-label="New page" title="New page" style={{ ...textButton, fontSize: '18px', padding: '2px 8px', color: 'var(--accent)' }}>+</button>
      </nav>
    );
  }

  return (
    <nav aria-label="Notebook pages" style={{
      width: phone ? '100%' : '240px', minWidth: phone ? 0 : '210px', display: 'flex', flexDirection: 'column', flex: phone ? 1 : undefined,
      background: 'var(--bg)', borderRight: phone ? 'none' : '1px solid var(--border)',
    }}>
      {/* Heading + collapse */}
      <div style={{ padding: '14px 12px 4px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }}>Pages</span>
        {!phone && (
          <button onClick={() => setIsCollapsed(true)} aria-label="Collapse page list" title="Collapse page list" style={{ ...textButton, padding: '6px' }}>
            <Chevron dir="left" />
          </button>
        )}
      </div>

      {/* Navigation: previous / next / replay — frequent, so they stay visible but quiet */}
      <div style={{ padding: '0 8px 8px', display: 'flex', alignItems: 'center', gap: '2px', borderBottom: '1px solid var(--border)' }}>
        <button id="btn-back" onClick={onBack} disabled={!canBack} title="Previous page" aria-label="Previous page"
          style={{ ...textButton, opacity: canBack ? 1 : 0.4, cursor: canBack ? 'pointer' : 'default' }}>
          <Chevron dir="left" />
        </button>
        <button id="btn-forward" onClick={onForward} disabled={!canForward} title="Next page" aria-label="Next page"
          style={{ ...textButton, opacity: canForward ? 1 : 0.4, cursor: canForward ? 'pointer' : 'default' }}>
          <Chevron dir="right" />
        </button>
        <button
          id="btn-replay"
          onClick={onReplayPage}
          disabled={!activePageId || isReplaying}
          title="Replay this page"
          style={{ ...textButton, marginLeft: 'auto', color: 'var(--ink)', opacity: !activePageId || isReplaying ? 0.5 : 1 }}
        >
          {isReplaying ? 'Playing…' : 'Replay'}
        </button>
      </div>

      {/* Page list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {pages.length === 0 && (
          <div style={{ padding: '16px', color: 'var(--ink-2)', fontSize: '13px' }}>No pages yet</div>
        )}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {pages.map((page, i) => {
          const isActive = page.id === activePageId;
          return (
            <li
              key={page.id}
              className="page-row"
              data-current={isActive ? 'true' : undefined}
              style={{
                display: 'flex', alignItems: 'center', gap: '8px',
                padding: '4px 6px 4px 14px', minHeight: '36px',
                background: isActive ? 'var(--panel)' : undefined,
                borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              }}
            >
              {editingPageId === page.id ? (
                <>
                  <span style={{ color: 'var(--ink-2)', fontSize: '12px', minWidth: '14px' }}>{i + 1}</span>
                  <input
                    value={editTitle}
                    onChange={e => setEditTitle(e.target.value)}
                    onBlur={() => commitTitle(page.id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') commitTitle(page.id);
                      if (e.key === 'Escape') setEditingPageId(null);
                    }}
                    aria-label="Page title"
                    maxLength={200}
                    autoFocus
                    style={{
                      flex: 1, minWidth: 0, background: 'var(--panel)', border: '1px solid var(--accent)',
                      borderRadius: '6px', color: 'var(--ink)', fontSize: '13px', padding: '3px 8px',
                    }}
                  />
                </>
              ) : (
                <>
                  <button
                    type="button"
                    id={`page-btn-${i + 1}`}
                    aria-label={`Page ${i + 1}: ${page.title || 'Untitled'} (${page.status})`}
                    aria-current={isActive ? 'page' : undefined}
                    title={page.summary || undefined}
                    onClick={() => onSelectPage(page.id)}
                    onDoubleClick={() => startEditing(page)}
                    style={{
                      flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: '8px', textAlign: 'left',
                      background: 'transparent', border: 'none', padding: 0, margin: 0, font: 'inherit', cursor: 'pointer',
                      minHeight: '28px',
                    }}
                  >
                    <span style={{ color: 'var(--ink-2)', fontSize: '12px', minWidth: '14px' }}>{i + 1}</span>
                    <span
                      style={{
                        flex: 1, minWidth: 0, fontSize: '13px', color: isActive ? 'var(--ink)' : 'var(--ink-2)',
                        fontWeight: isActive ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}
                    >
                      {page.title || `Page ${i + 1}`}
                    </span>
                    {page.status === 'saved' && (
                      <span title="Saved and locked" aria-hidden="true" style={{ color: 'var(--ink-2)', display: 'inline-flex' }}><LockIcon /></span>
                    )}
                  </button>
                  <span className="row-actions">
                    <Menu label={`Actions for page ${i + 1}`} icon="dots" items={[
                      { label: 'Rename', onSelect: () => startEditing(page) },
                      ...(pages.length > 1 ? [{ label: 'Delete page', onSelect: () => askDelete(page, i) }] : []),
                    ]} />
                  </span>
                </>
              )}
            </li>
          );
        })}
        </ul>
      </div>

      {/* Page fullness: one quiet line */}
      {activePage && showFullness && (
        <div style={{ padding: '10px 16px 6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--ink-2)' }}>
            <span>Page fullness</span>
            <span style={{ color: elementCount >= SOFT_CAP ? fullnessColor : 'var(--ink-2)', fontWeight: elementCount >= SOFT_CAP ? 600 : 400 }}>
              {elementCount} / {SOFT_CAP} elements
            </span>
          </div>
          <div aria-hidden="true" style={{ height: '2px', background: 'var(--border)', borderRadius: '1px', marginTop: '6px' }}>
            <div style={{ width: `${fullness * 100}%`, height: '100%', background: fullnessColor, borderRadius: '1px', transition: 'width 0.3s ease' }} />
          </div>
          {elementCount >= SOFT_CAP && (
            <output style={{ display: 'block', fontSize: '12px', color: 'var(--warn)', marginTop: '6px' }}>
              This page is getting full. A new page would give the next idea room.
            </output>
          )}
        </div>
      )}

      {/* Bottom actions */}
      <div style={{ padding: '8px 12px 14px', display: 'flex', gap: '8px' }}>
        {activePage?.status === 'active' && (
          <button
            id="btn-save-page"
            onClick={onSavePage}
            style={{
              flex: 1, padding: '7px 8px', borderRadius: '8px', background: 'transparent', whiteSpace: 'nowrap',
              border: '1px solid var(--border-strong)', color: 'var(--ink)', fontSize: '13px', fontWeight: 500, cursor: 'pointer',
            }}
          >
            Save and lock
          </button>
        )}
        <button
          id="btn-new-page"
          onClick={onNewPage}
          style={{
            flex: 1, padding: '7px 8px', borderRadius: '8px', background: 'transparent', whiteSpace: 'nowrap',
            border: '1px solid var(--border-strong)', color: 'var(--accent)', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
          }}
        >
          New page
        </button>
      </div>
    </nav>
  );
}
