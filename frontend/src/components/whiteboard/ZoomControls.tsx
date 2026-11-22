// Bottom-left zoom controls (also resets pan).
interface Props {
  zoom: number;
  handleZoomIn: () => void;
  handleZoomOut: () => void;
  handleResetZoom: () => void;
}

export function ZoomControls({ zoom, handleZoomIn, handleZoomOut, handleResetZoom }: Readonly<Props>) {
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
