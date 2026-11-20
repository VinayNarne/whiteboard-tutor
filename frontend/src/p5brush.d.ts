// p5.brush ships no types; the few calls PaintLayer makes (components/whiteboard/PaintLayer.tsx).
declare module 'p5.brush/standalone' {
  export const DEGREES: string;
  export function createCanvas(w: number, h: number, options?: { parent?: Element | string | null; pixelDensity?: number }): HTMLCanvasElement;
  export function load(target: HTMLCanvasElement): void;
  export function angleMode(mode: string): void;
  export function clear(color?: string): void;
  export function push(): void;
  export function pop(): void;
  export function translate(x: number, y: number): void;
  export function scale(x: number, y?: number): void;
  export function seed(n: number): void;
  export function noiseSeed(n: number): void;
  export function noStroke(): void;
  export function fill(color: string, opacity?: number): void;
  export function noFill(): void;
  export function fillBleed(strength: number, direction?: 'out' | 'in'): void;
  export function fillTexture(texture: number, border: number, scatter?: boolean, split?: number): void;
  export function hatch(dist: number, angle: number, options?: { rand?: number; continuous?: boolean; gradient?: number }): void;
  export function hatchStyle(name: string, color: string, weight: number): void;
  export function noHatch(): void;
  export function polygon(points: [number, number][]): unknown;
  export function render(): void;
}
