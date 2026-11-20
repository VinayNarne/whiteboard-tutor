// Developer-only logging. Silent by default; turn on in the browser console with:
//   localStorage.setItem('debug', '1')   (and reload)   — turn off with localStorage.removeItem('debug')
export function debug(...args: unknown[]): void {
  try {
    if (localStorage.getItem('debug') === '1') console.debug(...args);
  } catch {
    /* storage unavailable: stay silent */
  }
}
