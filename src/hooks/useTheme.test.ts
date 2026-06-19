/**
 * Tests for useTheme hook.
 * Covers: default theme, localStorage persistence, prefers-color-scheme detection,
 * toggleTheme, setTheme, isSystemPreference flag.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useTheme from './useTheme';

// Helper to mock matchMedia
function mockMatchMedia(prefersDark: boolean) {
  const listeners: Array<(e: MediaQueryListEvent) => void> = [];
  return {
    matches: prefersDark,
    addEventListener: vi.fn((event: string, handler: (e: MediaQueryListEvent) => void) => {
      if (event === 'change') listeners.push(handler);
    }),
    removeEventListener: vi.fn(),
    /** Simulate system theme change */
    fireChange(newMatches: boolean) {
      const event = { matches: newMatches } as MediaQueryListEvent;
      for (const handler of listeners) {
        handler(event);
      }
    },
  };
}

describe('useTheme', () => {
  let matchMediaMock: ReturnType<typeof mockMatchMedia>;

  beforeEach(() => {
    localStorage.clear();
    matchMediaMock = mockMatchMedia(false); // default: prefers light
    vi.stubGlobal('matchMedia', vi.fn(() => matchMediaMock));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('defaults to light when no localStorage and no prefers-color-scheme: dark', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('light');
  });

  it('detects dark from prefers-color-scheme when no localStorage value', () => {
    matchMediaMock = mockMatchMedia(true); // prefers dark
    vi.stubGlobal('matchMedia', vi.fn(() => matchMediaMock));

    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('dark');
    // Should also save detected theme to localStorage (after useEffect runs)
    expect(localStorage.getItem('callcenter-theme')).toBe('"dark"');
  });

  it('reads theme from localStorage when present', () => {
    localStorage.setItem('callcenter-theme', JSON.stringify('dark'));
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('dark');
  });

  it('toggleTheme switches from light to dark', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('light');

    act(() => {
      result.current.toggleTheme();
    });

    expect(result.current.theme).toBe('dark');
    expect(localStorage.getItem('callcenter-theme')).toBe('"dark"');
  });

  it('toggleTheme switches from dark to light', () => {
    localStorage.setItem('callcenter-theme', JSON.stringify('dark'));
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.toggleTheme();
    });

    expect(result.current.theme).toBe('light');
    expect(localStorage.getItem('callcenter-theme')).toBe('"light"');
  });

  it('setTheme sets specific theme', () => {
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.setTheme('dark');
    });

    expect(result.current.theme).toBe('dark');
    expect(localStorage.getItem('callcenter-theme')).toBe('"dark"');
  });

  it('isSystemPreference is true on first visit', () => {
    // No manual choice stored
    expect(localStorage.getItem('callcenter-theme-manual')).toBeNull();
    const { result } = renderHook(() => useTheme());
    expect(result.current.isSystemPreference).toBe(true);
  });

  it('isSystemPreference becomes false after manual toggle', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.isSystemPreference).toBe(true);

    act(() => {
      result.current.toggleTheme();
    });

    expect(result.current.isSystemPreference).toBe(false);
  });

  it('isSystemPreference becomes false after setTheme', () => {
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.setTheme('dark');
    });

    expect(result.current.isSystemPreference).toBe(false);
  });

  it('isSystemPreference is false when returning user had manual choice', () => {
    localStorage.setItem('callcenter-theme', JSON.stringify('dark'));
    localStorage.setItem('callcenter-theme-manual', JSON.stringify(true));
    const { result } = renderHook(() => useTheme());
    expect(result.current.isSystemPreference).toBe(false);
  });

  it('persists theme across hook remounts (localStorage)', () => {
    const { result: result1 } = renderHook(() => useTheme());

    act(() => {
      result1.current.setTheme('dark');
    });

    // Unmount and re-mount
    const { result: result2 } = renderHook(() => useTheme());
    expect(result2.current.theme).toBe('dark');
  });

  it('auto-switches on system theme change when no manual choice', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('light');
    expect(result.current.isSystemPreference).toBe(true);

    act(() => {
      matchMediaMock.fireChange(true); // system switches to dark
    });

    expect(result.current.theme).toBe('dark');
  });

  it('does NOT auto-switch on system theme change after manual toggle', () => {
    const { result } = renderHook(() => useTheme());

    act(() => {
      result.current.toggleTheme(); // manual: light → dark
    });

    expect(result.current.theme).toBe('dark');
    expect(result.current.isSystemPreference).toBe(false);

    act(() => {
      matchMediaMock.fireChange(false); // system switches to light
    });

    // Should stay dark — user made a manual choice
    expect(result.current.theme).toBe('dark');
  });
});
