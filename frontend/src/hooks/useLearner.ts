// Holds the learner card shared by the feedback chips and the "What I know about you" panel.
import { useCallback, useEffect, useState } from 'react';
import type { LearnerCard } from '../types';
import * as api from '../services/api';

export function useLearner() {
  const [card, setCard] = useState<LearnerCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (call: () => Promise<Response>) => {
    try {
      const res = await call();
      if (!res.ok) throw new Error(String(res.status));
      setCard(await res.json());
      setError(null);
      return true;
    } catch {
      setError('That did not work. Please try again.');
      return false;   // the panel announces and moves focus only after a change that worked
    }
  }, []);

  useEffect(() => { void run(api.getLearner); }, [run]);

  return { card, error, run };
}

export type Learner = ReturnType<typeof useLearner>;
