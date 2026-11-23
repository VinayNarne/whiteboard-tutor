// Bottom-left zoom controls (also resets pan).
interface Props {
  zoom: number;
  handleZoomIn: () => void;
  handleZoomOut: () => void;
  handleResetZoom: () => void;
  onPan: (dx: number, dy: number) => void;   // direction, -1/0/1 (a button alternative to dragging)
}

export function ZoomControls({ zoom, handleZoomIn, handleZoomOut, handleResetZoom, onPan }: Readonly<Props>) {
  return (
      <div style={{
        position: 'absolute', bottom: 16, left: 16,
        background: 'color-mix(in srgb, var(--panel) 94%, transparent)',
        border: '1px solid var(--border)',
        borderRadius: '24px',
        padding: '4px 8px',
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        backdropFilter: 'blur(8px)',
        zIndex: 10,
      }}>
        <button
          id="zoom-out-btn"
          onClick={handleZoomOut}
          disabled={zoom <= 0.21}
          title="Zoom out"
          style={{
            background: 'transparent', border: 'none',
            color: 'var(--ink-2)',
            fontSize: '14px', cursor: zoom <= 0.21 ? 'not-allowed' : 'pointer',
            padding: '4px 8px', borderRadius: '12px',
          }}
        >
          −
        </button>
        <button
          id="zoom-reset-btn"
          onClick={handleResetZoom}
          title="Reset the view: 100% zoom, whole board"
          aria-label={`Zoom ${Math.round(zoom * 100)}%. Reset the view to 100% and the whole board`}
          style={{
            background: 'transparent', border: 'none',
            color: 'var(--ink)', fontSize: '12px', fontWeight: 600,
            cursor: 'pointer', padding: '4px 6px',
          }}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          id="zoom-in-btn"
          onClick={handleZoomIn}
          disabled={zoom >= 7.9}
          title="Zoom in"
          style={{
            background: 'transparent', border: 'none',
            color: 'var(--ink-2)',
            fontSize: '14px', cursor: zoom >= 7.9 ? 'not-allowed' : 'pointer',
            padding: '4px 8px', borderRadius: '12px',
          }}
        >
          +
        </button>
        <span role="group" aria-label="Pan the board" style={{ display: "flex", alignItems: "center", gap: "2px", marginLeft: "4px", borderLeft: "1px solid var(--border)", paddingLeft: "6px" }}>
          {([["Pan up", "↑", 0, -1], ["Pan down", "↓", 0, 1], ["Pan left", "←", -1, 0], ["Pan right", "→", 1, 0]] as const).map(([label, arrow, dx, dy]) => (
            <button
              key={label}
              type="button"
              onClick={() => onPan(dx, dy)}
              aria-label={label}
              title={label}
              style={{
                background: "transparent", border: "none", color: "var(--ink-2)", fontSize: "14px", cursor: "pointer",
                width: "28px", height: "28px", padding: 0, borderRadius: "12px",
              }}
            >
              <span aria-hidden="true">{arrow}</span>
            </button>
          ))}
        </span>
        {zoom !== 1 && (
          <button
            onClick={handleResetZoom}
            title="Fit to Screen"
            style={{
              background: 'var(--panel-2)', border: 'none',
              color: 'var(--accent)', fontSize: '12px', fontWeight: 600,
              padding: '3px 8px', borderRadius: '12px', cursor: 'pointer',
              marginLeft: '4px',
            }}
          >
            Fit
          </button>
        )}
      </div>
  );
}
