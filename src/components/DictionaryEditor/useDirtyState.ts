/**
 * useDirtyState — tracks whether unsaved inline edits exist and warns
 * the user on `beforeunload`. Mirrors LexiCore's "unsaved changes" UX.
 */

import { useCallback, useEffect, useState } from 'react';

export interface UseDirtyStateResult {
  dirty: boolean;
  markDirty: () => void;
  markClean: () => void;
}

export function useDirtyState(initial = false): UseDirtyStateResult {
  const [dirty, setDirty] = useState(initial);

  const markDirty = useCallback(() => setDirty(true), []);
  const markClean = useCallback(() => setDirty(false), []);

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  return { dirty, markDirty, markClean };
}
