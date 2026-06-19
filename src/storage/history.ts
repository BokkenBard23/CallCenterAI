/**
 * History storage module — localStorage CRUD for analysis history entries.
 *
 * Capacity management:
 *   - Max entries: 50 (configurable)
 *   - FIFO cleanup when count exceeds MAX_ENTRIES
 *   - Result truncation when entry exceeds ~100KB
 *   - Warning when localStorage usage > 80%
 */

import type { HistoryEntry, SearchResult, LLMResult } from '../types/api';

const HISTORY_KEY = 'callcenter-analysis-history';
const MAX_ENTRIES = 50;
const MAX_ENTRY_SIZE_BYTES = 100 * 1024; // 100KB
const ESTIMATED_STORAGE_LIMIT = 5 * 1024 * 1024; // ~5MB
const STORAGE_QUOTA_WARNING = 0.8;

// ═══════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════

/** SSR guard: check if localStorage is available */
function isLocalStorageAvailable(): boolean {
  return typeof window !== 'undefined' && typeof localStorage !== 'undefined';
}

/** Truncate large searchResult to metadata-only if it exceeds size limit */
function truncateResult(
  searchResult: SearchResult | undefined,
): SearchResult | undefined {
  if (!searchResult) return undefined;
  const serialized = JSON.stringify(searchResult);
  if (serialized.length <= MAX_ENTRY_SIZE_BYTES) return searchResult;

  // Keep metadata only: total_matches, matches_by_level — drop segments/matches
  return {
    segments: [],
    total_matches: searchResult.total_matches,
    matches: [],
    matches_by_level: searchResult.matches_by_level,
  };
}

/** Truncate large llmResult similarly */
function truncateLLMResult(
  llmResult: LLMResult | undefined,
): LLMResult | undefined {
  if (!llmResult) return undefined;
  const serialized = JSON.stringify(llmResult);
  if (serialized.length <= MAX_ENTRY_SIZE_BYTES) return llmResult;

  // Keep only key fields — drop raw_response and restructured_dialogue
  return {
    summary: llmResult.summary,
    restructured_dialogue: '',
    topic: llmResult.topic,
    result: llmResult.result,
    key_points: llmResult.key_points,
    client_sentiment: llmResult.client_sentiment,
    resolution: llmResult.resolution,
    provider: llmResult.provider,
    model: llmResult.model,
  };
}

// ═══════════════════════════════════════════════════════════
// CRUD Operations
// ═══════════════════════════════════════════════════════════

/** Get all history entries from localStorage */
export function getAll(): HistoryEntry[] {
  if (!isLocalStorageAvailable()) return [];

  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as HistoryEntry[];
  } catch {
    return [];
  }
}

/** Add a new history entry with FIFO cleanup and truncation */
export function add(entry: HistoryEntry): void {
  if (!isLocalStorageAvailable()) return;

  const entries = getAll();

  // Truncate large results before saving
  const truncated: HistoryEntry = {
    ...entry,
    searchResult: truncateResult(entry.searchResult),
    llmResult: truncateLLMResult(entry.llmResult),
  };

  entries.unshift(truncated);

  // FIFO cleanup: remove oldest entries exceeding MAX_ENTRIES
  while (entries.length > MAX_ENTRIES) {
    entries.pop();
  }

  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
  } catch {
    // localStorage full — try removing oldest entries until it fits
    while (entries.length > 1) {
      entries.pop();
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
        return;
      } catch {
        // Continue removing
      }
    }
  }
}

/** Remove a single history entry by ID. Returns true if persisted, false if storage failed. */
export function remove(id: string): boolean {
  if (!isLocalStorageAvailable()) return false;

  const entries = getAll();
  const filtered = entries.filter((e) => e.id !== id);

  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(filtered));
    return true;
  } catch {
    return false;
  }
}

/** Clear all history entries */
export function clearAll(): void {
  if (!isLocalStorageAvailable()) return;

  try {
    localStorage.removeItem(HISTORY_KEY);
  } catch {
    // Silently fail
  }
}

// ═══════════════════════════════════════════════════════════
// Capacity Management
// ═══════════════════════════════════════════════════════════

/** Get localStorage usage statistics */
export function getStorageUsage(): {
  usedBytes: number;
  totalBytes: number;
  percentage: number;
} {
  if (!isLocalStorageAvailable()) {
    return { usedBytes: 0, totalBytes: ESTIMATED_STORAGE_LIMIT, percentage: 0 };
  }

  let usedBytes = 0;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) {
        const value = localStorage.getItem(key);
        if (value) {
          // Approximate byte count (2 bytes per char for UTF-16)
          usedBytes += (key.length + value.length) * 2;
        }
      }
    }
  } catch {
    // Ignore
  }

  return {
    usedBytes,
    totalBytes: ESTIMATED_STORAGE_LIMIT,
    percentage: usedBytes / ESTIMATED_STORAGE_LIMIT,
  };
}

/** Check if storage usage exceeds warning threshold */
export function isStorageNearCapacity(): boolean {
  return getStorageUsage().percentage > STORAGE_QUOTA_WARNING;
}

/** Remove oldest entries to free space. Returns count removed. */
export function cleanupOldEntries(maxEntries: number = MAX_ENTRIES): number {
  if (!isLocalStorageAvailable()) return 0;

  const entries = getAll();
  if (entries.length <= maxEntries) return 0;

  const toRemove = entries.length - maxEntries;
  const kept = entries.slice(0, maxEntries);

  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(kept));
  } catch {
    // Silently fail
  }

  return toRemove;
}
