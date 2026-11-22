import { useEffect, useState } from 'react';

/** True while the viewport matches the CSS media query, e.g. useMediaQuery('(max-width: 820px)'). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => globalThis.matchMedia(query).matches);
  useEffect(() => {
    const mq = globalThis.matchMedia(query);
    const update = () => setMatches(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, [query]);
  return matches;
}
