/**
 * HoverContext — shared state for bidirectional cross-highlighting
 * between DictionaryTree (sidebar) and HighlightRenderer (text),
 * plus hierarchical tree node filtering.
 *
 * - hoveredPhrase: the phrase_text currently being hovered
 * - setHoveredPhrase: updates hoveredPhrase with 150ms debounce
 * - selectedTreeNodeId: ID of the selected tree node (replaces selectedDictLevel)
 * - setSelectedTreeNodeId: updates selectedTreeNodeId
 * - activePhrases: Set of phrase_texts from selected node + descendants
 * - setActivePhrases: updates activePhrases
 * - hoveredTreeNodeId: ID of the tree node being hovered (cross-highlight)
 * - setHoveredTreeNodeId: updates hoveredTreeNodeId
 * - selectedDictLevel: DEPRECATED — kept for backward compatibility (MatchLegend)
 * - setSelectedDictLevel: DEPRECATED — use setSelectedTreeNodeId + setActivePhrases
 * - hideUnmatched: whether to hide phrases with 0 matches in sidebar
 * - setHideUnmatched: updates hideUnmatched
 * - levelNames: Map of cascade_order → human-readable name
 * - setLevelNames: updates levelNames
 *
 * Provider wraps ResultsPage only (not App) to narrow re-render scope.
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

  /** ID of the selected tree node, or null (show all) */
  selectedTreeNodeId: string | null;
  /** Update selected tree node */
  setSelectedTreeNodeId: (id: string | null) => void;

  /** Set of phrase texts from the selected tree node and its descendants.
   *  Used by HighlightRenderer for dim/bright filtering. */
  activePhrases: Set<string>;
  /** Update active phrases set */
  setActivePhrases: (phrases: Set<string>) => void;

  /** ID of the tree node currently being hovered (cross-highlight) */
  hoveredTreeNodeId: string | null;
  /** Update hovered tree node */
  setHoveredTreeNodeId: (id: string | null) => void;

  /** @deprecated Use selectedTreeNodeId + activePhrases instead.
   *  Kept for backward compatibility with MatchLegend. */
  selectedDictLevel: number | null;
  /** @deprecated Use setSelectedTreeNodeId + setActivePhrases instead. */
  setSelectedDictLevel: (level: number | null) => void;

  /** Whether to hide phrases with 0 matches in sidebar (default: true) */
  hideUnmatched: boolean;
  /** Update hideUnmatched */
  setHideUnmatched: (hide: boolean) => void;

  /** Level names extracted from dictionary data: cascade_order → human-readable name */
  levelNames: Map<number, string>;
  /** Update level names (called by DictionaryTree when data is available) */
  setLevelNames: (names: Map<number, string>) => void;
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

  // Tree node selection (replaces Q1/Q2/Q3 level filtering)
  const [selectedTreeNodeId, setSelectedTreeNodeId] = useState<string | null>(null);
  const [activePhrases, setActivePhrases] = useState<Set<string>>(new Set());
  const [hoveredTreeNodeId, setHoveredTreeNodeId] = useState<string | null>(null);

  // DEPRECATED: kept for backward compat (MatchLegend, etc.)
  const [selectedDictLevel, setSelectedDictLevel] = useState<number | null>(null);

  // Hide unmatched by default
  const [hideUnmatched, setHideUnmatched] = useState<boolean>(true);

  // Level names from dictionary data
  const [levelNames, setLevelNames] = useState<Map<number, string>>(new Map());

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
        selectedTreeNodeId,
        setSelectedTreeNodeId,
        activePhrases,
        setActivePhrases,
        hoveredTreeNodeId,
        setHoveredTreeNodeId,
        selectedDictLevel,
        setSelectedDictLevel,
        hideUnmatched,
        setHideUnmatched,
        levelNames,
        setLevelNames,
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
