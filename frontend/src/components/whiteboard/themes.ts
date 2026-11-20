// Whiteboard canvas constants and the three board themes (the board keeps its own paper colours in any app theme).
export const CANVAS_WIDTH = 1200;
export const CANVAS_HEIGHT = 800;

export type CanvasTheme = 'paper' | 'white' | 'blackboard';

export const THEME_STYLES: Record<CanvasTheme, { canvasBg: string; shadow: string; dotColor: string }> = {
  paper: {
    canvasBg: '#FFFDF7',
    shadow: '0 1px 2px rgba(31,42,55,0.08), 0 18px 48px rgba(31,42,55,0.18)',
    dotColor: 'rgba(161, 98, 7, 0.12)',
  },
  white: {
    canvasBg: '#ffffff',
    shadow: '0 1px 2px rgba(31,42,55,0.08), 0 18px 48px rgba(31,42,55,0.18)',
    dotColor: 'rgba(100, 116, 139, 0.15)',
  },
  blackboard: {
    canvasBg: '#0d1526',
    shadow: '0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent), 0 24px 64px rgba(0,0,0,0.7)',
    dotColor: 'rgba(148, 163, 184, 0.12)',
  },
};
