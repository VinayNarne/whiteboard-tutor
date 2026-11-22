// Light / dark / match-system theme. The choice is stored in localStorage; the page gets data-theme="light|dark".
// (index.html applies the saved choice before the app loads, so there is no flash of the wrong theme.)
import { useEffect, useState } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';
const KEY = 'theme';
const query = () => globalThis.matchMedia('(prefers-color-scheme: dark)');

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'dark' || v === 'system' ? v : 'light';
  } catch {
    return 'light';
  }
}

export function resolveTheme(pref: ThemePref): 'light' | 'dark' {
  return pref === 'dark' || (pref === 'system' && query().matches) ? 'dark' : 'light';
}

export function applyTheme(pref: ThemePref): void {
  document.documentElement.dataset.theme = resolveTheme(pref);
}

export function setThemePref(pref: ThemePref): void {
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* storage unavailable: the choice lasts until reload */
  }
  applyTheme(pref);
  globalThis.dispatchEvent(new Event('themechange'));
}

/** Current preference plus a setter; keeps every switcher in sync and follows the OS when set to "system". */
export function useThemePref(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(getThemePref);
  useEffect(() => {
    const sync = () => setPref(getThemePref());
    const os = () => { if (getThemePref() === 'system') applyTheme('system'); };
    globalThis.addEventListener('themechange', sync);
    query().addEventListener('change', os);
    return () => {
      globalThis.removeEventListener('themechange', sync);
      query().removeEventListener('change', os);
    };
  }, []);
  return [pref, setThemePref];
}

export const THEME_CHOICES: { id: ThemePref; label: string }[] = [
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
  { id: 'system', label: 'Match system' },
];
