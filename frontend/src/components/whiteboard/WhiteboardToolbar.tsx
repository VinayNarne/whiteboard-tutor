// The whiteboard's top strip: quiet status text, the learner's drawing tools, and the View / Export menus.
import type { Dispatch, SetStateAction } from 'react';
import { Menu } from '../Menu';
import type { LearnerTool } from '../../types';
import type { CanvasTheme } from './themes';

interface Props {
  isPlaying: boolean;
  activeElementId: string | null;
  hoveredElementId: string | null;
  learnerTool: LearnerTool;
  setLearnerTool: Dispatch<SetStateAction<LearnerTool>>;
  learnerColor: string;
  setLearnerColor: Dispatch<SetStateAction<string>>;
  hasMarks: boolean;
  onClearMarks: () => void;
  theme: CanvasTheme;
  setTheme: Dispatch<SetStateAction<CanvasTheme>>;
  showGrid: boolean;
  setShowGrid: Dispatch<SetStateAction<boolean>>;
  isHandDrawn: boolean;
  setIsHandDrawn: Dispatch<SetStateAction<boolean>>;
  handleExportSvg: () => void;
  handleExportPng: () => void;
  handleCopySvg: () => void;
  canUndo: boolean;
  handleUndo: () => void;
}

export function WhiteboardToolbar({
  isPlaying, activeElementId, hoveredElementId,
  learnerTool, setLearnerTool, learnerColor, setLearnerColor, hasMarks, onClearMarks,
  theme, setTheme, showGrid, setShowGrid, isHandDrawn, setIsHandDrawn,
  handleExportSvg, handleExportPng, handleCopySvg, canUndo, handleUndo,
}: Props) {
  return (
    <>
      {/* Top left: quiet status text (what the tutor is explaining / what the pointer is over) */}
      <div className="wb-status" style={{ position: 'absolute', top: 18, left: 20, display: 'flex', gap: '14px', zIndex: 10, alignItems: 'center' }}>
        {isPlaying && (
          <span style={{ fontSize: '12px', color: 'var(--ink-2)', display: 'inline-flex', alignItems: 'center', gap: '7px' }}>
            <span aria-hidden="true" style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent)', animation: 'pulse 1s infinite' }} />
            {activeElementId && !/^b\d+_s\d+$/.test(activeElementId) ? `Explaining ${activeElementId.replace(/_/g, ' ')}` : 'Speaking…'}
          </span>
        )}
        {hoveredElementId && (
          <span style={{ fontSize: '12px', color: 'var(--ink-2)' }}>{hoveredElementId.replace(/_/g, ' ')}</span>
        )}
      </div>

      {/* Top centre: learner tools — plain text, the active one is simply set apart */}
      <div
        id="learner-toolbar"
        role="toolbar"
        aria-label="Drawing tools"
        style={{
          position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
          background: 'color-mix(in srgb, var(--panel) 92%, transparent)',
          border: '1px solid var(--border)', borderRadius: '8px', padding: '2px',
          display: 'flex', alignItems: 'center', gap: '2px', zIndex: 25,
        }}
      >
        {[
          { id: 'select', label: 'Pan', title: 'Pan and select' },
          { id: 'pen', label: 'Pen', title: 'Draw with a pen' },
          { id: 'highlighter', label: 'Highlight', title: 'Highlighter' },
          { id: 'eraser', label: 'Eraser', title: 'Click one of your strokes to erase it' },
        ].map(t => (
          <button
            key={t.id}
            id={`learner-tool-${t.id}`}
            onClick={() => setLearnerTool(t.id as LearnerTool)}
            title={t.title}
            aria-pressed={learnerTool === t.id}
            style={{
              padding: '4px 12px', borderRadius: '6px', border: 'none',
              background: learnerTool === t.id ? 'var(--panel-2)' : 'transparent',
              color: learnerTool === t.id ? 'var(--ink)' : 'var(--ink-2)',
              fontSize: '13px', fontWeight: learnerTool === t.id ? 600 : 500, cursor: 'pointer',
            }}
          >
            {t.label}
          </button>
        ))}

        {(learnerTool === 'pen' || learnerTool === 'highlighter') && (
          <div role="group" aria-label="Ink colour" style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            borderLeft: '1px solid var(--border)', padding: '0 8px', marginLeft: '4px',
          }}>
            {[
              { color: 'var(--warn)', title: 'Amber' },
              { color: '#06b6d4', title: 'Cyan' },
              { color: 'var(--danger)', title: 'Red' },
              { color: 'var(--ok)', title: 'Green' },
            ].map(c => (
              <button
                key={c.color}
                onClick={() => setLearnerColor(c.color)}
                title={c.title}
                aria-label={`${c.title} ink`}
                aria-pressed={learnerColor === c.color}
                style={{
                  width: '16px', height: '16px', minWidth: '16px', minHeight: '16px', borderRadius: '50%',
                  background: c.color, cursor: 'pointer', padding: 0,
                  border: learnerColor === c.color ? '2px solid var(--ink)' : '1px solid var(--border-strong)',
                }}
              />
            ))}
          </div>
        )}

        {hasMarks && (
          <button
            id="clear-learner-notes-btn"
            onClick={onClearMarks}
            title="Clear your pen and highlighter marks on this page"
            style={{
              borderLeft: '1px solid var(--border)', borderTop: 'none', borderRight: 'none', borderBottom: 'none',
              marginLeft: '4px', padding: '4px 10px', background: 'transparent',
              color: 'var(--ink-2)', fontSize: '13px', fontWeight: 500, cursor: 'pointer',
            }}
          >
            Clear marks
          </button>
        )}
      </div>

      {/* Top right: everything secondary lives in two menus */}
      <div className="wb-menus" style={{ position: 'absolute', top: 14, right: 16, display: 'flex', alignItems: 'center', gap: '2px', zIndex: 20 }}>
        {canUndo && (
          <Menu label="Edit" items={[
            { label: 'Undo last drawing (Ctrl+Z)', onSelect: handleUndo },
          ]} />
        )}
        <Menu label="View" items={[
          { heading: 'Canvas' },
          { label: 'Paper', kind: 'radio', checked: theme === 'paper', onSelect: () => setTheme('paper') },
          { label: 'White', kind: 'radio', checked: theme === 'white', onSelect: () => setTheme('white') },
          { label: 'Slate', kind: 'radio', checked: theme === 'blackboard', onSelect: () => setTheme('blackboard') },
          { heading: 'Display' },
          { label: 'Dot grid', kind: 'toggle', checked: showGrid, onSelect: () => setShowGrid(v => !v) },
          { label: 'Hand-drawn style', kind: 'toggle', checked: isHandDrawn, onSelect: () => setIsHandDrawn(v => !v) },
        ]} />
        <Menu label="Export" items={[
          { label: 'Export SVG', onSelect: handleExportSvg },
          { label: 'Export PNG', onSelect: handleExportPng },
          { label: 'Copy SVG markup', onSelect: handleCopySvg },
        ]} />
      </div>
    </>
  );
}
