// Bottom-centre bar shown while a page replays: progress and speed.
interface Props {
  isReplaying: boolean;
  replayStep: number;
  replayTotal: number;
  playbackSpeed: number;
  setPlaybackSpeed: (speed: number) => void;
}

export function ReplayBar({ isReplaying, replayStep, replayTotal, playbackSpeed, setPlaybackSpeed }: Readonly<Props>) {
  return (
    <>
      {isReplaying && (
        <div style={{
          position: 'absolute', bottom: 16,
          background: 'color-mix(in srgb, var(--panel) 94%, transparent)',
          border: '1px solid var(--accent)',
          borderRadius: '24px',
          padding: '6px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          boxShadow: '0 8px 32px rgba(31, 42, 55, 0.18)',
          zIndex: 20,
          backdropFilter: 'blur(10px)',
        }}>
          <span role="status" style={{ color: 'var(--accent)', fontSize: '12px', fontWeight: 600 }}>
            ▶ Replaying: Step {replayStep} / {replayTotal}
          </span>
          <div style={{
            display: 'flex', alignItems: 'center', gap: '4px',
            borderLeft: '1px solid var(--border-strong)', paddingLeft: '8px',
          }}>
            <span style={{ color: 'var(--ink-2)', fontSize: '12px' }}>Speed:</span>
            {[1, 1.25, 1.5].map(spd => (
              <button
                key={spd}
                onClick={() => setPlaybackSpeed(spd)}
                style={{
                  background: playbackSpeed === spd ? 'var(--accent)' : 'transparent',
                  border: 'none',
                  borderRadius: '10px',
                  color: playbackSpeed === spd ? 'var(--on-accent)' : 'var(--ink-2)',
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '2px 6px',
                  cursor: 'pointer',
                }}
              >
                {spd}x
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
