// Whiteboard export helpers: serialise the live SVG, download it as SVG or PNG, copy the markup.

/** The board as a standalone SVG string at its full canvas size (the on-screen copy may be zoomed or panned). */
/** The board as a standalone SVG of `view` (board coordinates), whatever the camera is showing right now. */
export function serializeSvg(svg: SVGSVGElement | null, view: { x: number; y: number; w: number; h: number }): string {
  if (!svg) return '';
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
  clone.setAttribute('width', `${Math.round(view.w)}`);
  clone.setAttribute('height', `${Math.round(view.h)}`);
  return new XMLSerializer().serializeToString(clone);
}

function triggerDownload(href: string, filename: string): void {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  link.click();
}

export function downloadSvg(svgString: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' }));
  triggerDownload(url, filename);
  URL.revokeObjectURL(url);
}

/** Render the SVG onto a 2x canvas (sharp on retina screens) over `background`, then download it. */
export function downloadPng(svgString: string, filename: string, background: string, width: number, height: number): void {
  const canvas = document.createElement('canvas');
  canvas.width = width * 2;
  canvas.height = height * 2;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const img = new Image();
  const url = URL.createObjectURL(new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' }));
  img.onload = () => {
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    triggerDownload(canvas.toDataURL('image/png'), filename);
  };
  img.src = url;
}

/** Copy text to the clipboard; false when the browser refuses. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    console.warn('Failed to copy to clipboard', e);
    return false;
  }
}
