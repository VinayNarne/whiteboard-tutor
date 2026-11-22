// Small accessible dropdown menu used for secondary actions (header, whiteboard toolbar).
// Keyboard: Enter/Space/ArrowDown open on the first item, Arrow keys move, Home/End jump,
// Escape closes and returns focus to the trigger, Tab closes. Items can be plain, toggles or radios.
import { useEffect, useId, useRef, useState } from 'react';

export type MenuItem =
  | { heading: string }
  | { label: string; onSelect: () => void; checked?: boolean; kind?: 'item' | 'radio' | 'toggle' };

const triggerStyle: React.CSSProperties = {
  background: 'transparent', border: 'none', color: 'var(--ink-2)',
  fontSize: '13px', fontWeight: 500, padding: '4px 8px', borderRadius: '6px',
  cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '4px',
};

export function Menu({ label, items, align = 'right', icon }: Readonly<{
  label: string;
  items: MenuItem[];
  align?: 'left' | 'right';
  icon?: 'dots'; // icon-only trigger: `label` becomes its accessible name
}>) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const itemButtons = () => [...(rootRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
  const focusItem = (i: number) => {
    const els = itemButtons();
    if (els.length) els[(i + els.length) % els.length].focus();
  };
  const close = (returnFocus = true) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };

  // focus the first item once the menu is rendered
  useEffect(() => { if (open) focusItem(0); }, [open]);

  // click outside closes without stealing focus
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!rootRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const onMenuKey = (e: React.KeyboardEvent) => {
    const els = itemButtons();
    const i = els.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(i + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(i - 1); }
    else if (e.key === 'Home') { e.preventDefault(); focusItem(0); }
    else if (e.key === 'End') { e.preventDefault(); focusItem(els.length - 1); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'Tab') { setOpen(false); }
  };

  return (
    <div ref={rootRef} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={icon ? label : undefined}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(v => !v)}
        onKeyDown={e => { if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); } }}
        style={{ ...triggerStyle, color: open ? 'var(--ink)' : 'var(--ink-2)', background: open ? 'var(--panel-2)' : 'transparent' }}
      >
        {icon === 'dots' ? (
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
            <circle cx="3" cy="8" r="1.4" /><circle cx="8" cy="8" r="1.4" /><circle cx="13" cy="8" r="1.4" />
          </svg>
        ) : (
          <>
            {label}
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </>
        )}
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKey}
          style={{
            position: 'absolute', top: 'calc(100% + 6px)', [align]: 0, zIndex: 60, minWidth: '190px',
            background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: '10px',
            boxShadow: 'var(--shadow)', padding: '6px',
          }}
        >
          {items.map((it, i) => 'heading' in it ? (
            <div key={i} role="presentation" style={{
              padding: '8px 10px 4px', fontSize: '12px', fontWeight: 600, color: 'var(--ink-2)',
              borderTop: i > 0 ? '1px solid var(--border)' : 'none', marginTop: i > 0 ? '6px' : 0,
            }}>{it.heading}</div>
          ) : (
            <button
              key={i}
              type="button"
              role={it.kind === 'radio' ? 'menuitemradio' : it.kind === 'toggle' ? 'menuitemcheckbox' : 'menuitem'}
              aria-checked={it.kind ? !!it.checked : undefined}
              onClick={() => { close(); it.onSelect(); }}
              style={{
                width: '100%', textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer',
                padding: '7px 10px', borderRadius: '6px', fontSize: '13px', color: 'var(--ink)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel-2)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              onFocus={e => (e.currentTarget.style.background = 'var(--panel-2)')}
              onBlur={e => (e.currentTarget.style.background = 'transparent')}
            >
              <span>{it.label}</span>
              {it.checked && (
                <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                  <path d="M2.5 6.5 5 9l4.5-5.5" fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
