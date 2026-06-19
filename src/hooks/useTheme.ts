/**
 * useTheme — theme management hook with localStorage persistence
 * and prefers-color-scheme detection on first visit.
 *
 * Priority: localStorage('callcenter-theme') > prefers-color-scheme > default('light')
 * SSR guard: typeof window !== 'undefined'
 * localStorage key: 'callcenter-theme'
 */
import { useCallback, useEffect, useRef } from 'react';
import useLocalStorage from './useLocalStorage';

export type Theme = 'light' | 'dark';

export interface UseThemeReturn {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
  /** true if the current theme was determined from prefers-color-scheme
   *  (i.e. user never made a manual choice) */
  isSystemPreference: boolean;
}

const STORAGE_KEY = 'callcenter-theme';

function getSystemTheme(): Theme {
  if (typeof window === 'undefined') return 'light';
  const prefersDark = window.matchMedia(
    '(prefers-color-scheme: dark)',
  ).matches;
  return prefersDark ? 'dark' : 'light';
}

function useTheme(): UseThemeReturn {
  // Track whether user has ever made a manual choice
  // We use a separate localStorage key for this flag
  const [manualChoice, setManualChoice] = useLocalStorage<
    boolean | null
  >('callcenter-theme-manual', null);

  // On first visit (no stored theme), detect from prefers-color-scheme
  const [theme, setThemeValue] = useLocalStorage<Theme>(
    STORAGE_KEY,
    () => getSystemTheme(),
  );

  // Ref to track current theme for matchMedia listener
  const manualChoiceRef = useRef(manualChoice);
  useEffect(() => {
    manualChoiceRef.current = manualChoice;
  });

  // Listen for system theme changes (only if user hasn't made manual choice)
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia(
      '(prefers-color-scheme: dark)',
    );

    const handler = (e: MediaQueryListEvent) => {
      // Only auto-switch if user hasn't made a manual choice
      if (!manualChoiceRef.current) {
        const newTheme: Theme = e.matches ? 'dark' : 'light';
        setThemeValue(newTheme);
      }
    };

    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, [setThemeValue]);

  const toggleTheme = useCallback(() => {
    setThemeValue((prev) => (prev === 'light' ? 'dark' : 'light'));
    setManualChoice(true);
  }, [setThemeValue, setManualChoice]);

  const setTheme = useCallback(
    (newTheme: Theme) => {
      setThemeValue(newTheme);
      setManualChoice(true);
    },
    [setThemeValue, setManualChoice],
  );

  const isSystemPreference = manualChoice === null;

  return { theme, toggleTheme, setTheme, isSystemPreference };
}

export default useTheme;
