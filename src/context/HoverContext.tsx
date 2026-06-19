/**
 * HoverContext — shared state for bidirectional cross-highlighting
 * between DictionaryTree (sidebar) and HighlightRenderer (text),
 * plus multi-dictionary level filtering (selectedDictLevel).
 *
 * - hoveredPhrase: the phrase_text currently being hovered
 * - setHoveredPhrase: updates hoveredPhrase with 150ms debounce
 * - selectedDictLevel: 1/2/3 for dict-level filter, null = show all
 * - setSelectedDictLevel: updates selectedDictLevel
 * - hideUnmatched: whether to hide phrases with 0 matches in sidebar
 * - setHideUnmatched: updates hideUnmatched
 *
 * Provider wraps ResultsPage only (not App) to narrow re-render scope.
 * Uses useState (not useReducer) — simple state, no complex transitions.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

// ═══════════════════════════════════════════════════════════
// Context interface
// ═══════════════════════════════════════════════════════════

interface HoverContextValue {
  /** Currently hovered phrase text, or null if nothing is hovered */
  hoveredPhrase: string | null;
  /** Update hovered phrase (debounced internally at 150ms) */
  setHoveredPhrase: (phrase: string | null) => void;
  /** Selected dictionary level for filtering: 1, 2, 3, or null (all) */
  selectedDictLevel: number | null;
  /** Update selected dictionary level */
  setSelectedDictLevel: (level: number | null) => void;
  /** Whether to hide phrases with 0 matches in sidebar (default: true) */
  hideUnmatched: boolean;
  /** Update hideUnmatched */
  setHideUnmatched: (hide: boolean) => void;
}

// ═══════════════════════════════════════════════════════════
// Context
// ═══════════════════════════════════════════════════════════

const HoverContext = createContext<HoverContextValue | null>(null);

// ═══════════════════════════════════════════════════════════
// Provider
// ═══════════════════════════════════════════════════════════

const DEBOUNCE_MS = 150;

export function HoverProvider({ children }: { children: ReactNode }) {
  const [hoveredPhrase, setHoveredPhraseState] = useState<string | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Chunk 2: Multi-dict filtering state
  const [selectedDictLevel, setSelectedDictLevel] = useState<number | null>(null);

  // Chunk 3: Hide unmatched by default
  const [hideUnmatched, setHideUnmatched] = useState<boolean>(true);

  const setHoveredPhrase = useCallback((phrase: string | null) => {
    // Clear any pending debounce
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }

    // Null (mouseleave) — apply immediately, no debounce
    if (phrase === null) {
      setHoveredPhraseState(null);
      return;
    }

    // Non-null — debounce 150ms
    debounceTimerRef.current = setTimeout(() => {
      setHoveredPhraseState(phrase);
      debounceTimerRef.current = null;
    }, DEBOUNCE_MS);
  }, []);

  // Clean up debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current !== null) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  return (
    <HoverContext.Provider
      value={{
        hoveredPhrase,
        setHoveredPhrase,
        selectedDictLevel,
        setSelectedDictLevel,
        hideUnmatched,
        setHideUnmatched,
      }}
    >
      {children}
    </HoverContext.Provider>
  );
}

// ═══════════════════════════════════════════════════════════
// Hook
// ═══════════════════════════════════════════════════════════

// eslint-disable-next-line react-refresh/only-export-components
export function useHoverContext(): HoverContextValue {
  const context = useContext(HoverContext);
  if (!context) {
    throw new Error(
      'useHoverContext must be used within a HoverProvider',
    );
  }
  return context;
}
