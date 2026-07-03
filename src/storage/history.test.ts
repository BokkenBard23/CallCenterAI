/**
 * Tests for history storage module — localStorage CRUD for analysis history.
 *
 * Covers:
 *   - CRUD: getAll, add, remove, clearAll
 *   - FIFO cleanup at MAX_ENTRIES (50)
 *   - Result truncation for large entries
 *   - localStorage unavailability
 *   - Capacity management: getStorageUsage, isStorageNearCapacity, cleanupOldEntries
 *   - Edge cases: corrupt JSON, empty storage, storage full
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as history from './history';
import type { HistoryEntry, SearchResult, LLMResult } from '../types/api';

// ─── Mock localStorage ──────────────────────────────────

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn((index: number) => {
      const keys = Object.keys(store);
      return keys[index] ?? null;
    }),
  };
})();

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

// ─── Sample data ──────────────────────────────────────────

function makeEntry(overrides: Partial<HistoryEntry> & { id: string }): HistoryEntry {
  return {
    analysisId: `analysis-${overrides.id}`,
    sessionId: `session-${overrides.id}`,
    date: new Date().toISOString(),
    fileName: `file-${overrides.id}.rtf`,
    dictionaryNames: ['Тестовый словарь'],
    totalMatches: 0,
    matchesByLevel: {},
    status: 'completed',
    ...overrides,
  };
}

const SAMPLE_SEARCH_RESULT: SearchResult = {
  segments: [],
  total_matches: 5,
  matches: [],
  matches_by_level: { '1': 3, '2': 2 },
};

const SAMPLE_LLM_RESULT: LLMResult = {
  summary: 'Test summary',
  restructured_dialogue: 'Test dialogue',
  topic: 'Test topic',
  result: 'resolved',
  key_points: ['point1'],
  client_sentiment: 'neutral',
  resolution: 'resolved',
  provider: 'test',
  model: 'test-model',
};

// ─── Tests ────────────────────────────────────────────────

describe('history storage', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  // ─── getAll ─────────────────────────────────────────────

  describe('getAll', () => {
    it('returns empty array when no entries exist', () => {
      expect(history.getAll()).toEqual([]);
    });

    it('returns entries from localStorage', () => {
      const entries = [makeEntry({ id: '1' }), makeEntry({ id: '2' })];
      localStorageMock.setItem('callcenter-analysis-history', JSON.stringify(entries));

      const result = history.getAll();
      expect(result).toHaveLength(2);
      expect(result[0].id).toBe('1');
      expect(result[1].id).toBe('2');
    });

    it('returns empty array when stored data is not valid JSON', () => {
      localStorageMock.setItem('callcenter-analysis-history', 'not-json');
      expect(history.getAll()).toEqual([]);
    });

    it('returns empty array when stored data is not an array', () => {
      localStorageMock.setItem('callcenter-analysis-history', JSON.stringify({ not: 'array' }));
      expect(history.getAll()).toEqual([]);
    });
  });

  // ─── add ────────────────────────────────────────────────

  describe('add', () => {
    it('adds an entry to the beginning of the list', () => {
      history.add(makeEntry({ id: '1' }));
      history.add(makeEntry({ id: '2' }));

      const entries = history.getAll();
      expect(entries).toHaveLength(2);
      expect(entries[0].id).toBe('2'); // newest first
      expect(entries[1].id).toBe('1');
    });

    it('performs FIFO cleanup when entries exceed 50', () => {
      // Add 51 entries
      for (let i = 1; i <= 51; i++) {
        history.add(makeEntry({ id: String(i) }));
      }

      const entries = history.getAll();
      expect(entries).toHaveLength(50);
      // Oldest entry (id=1) should be removed
      expect(entries.find((e) => e.id === '1')).toBeUndefined();
      // Newest entry (id=51) should be present
      expect(entries.find((e) => e.id === '51')).toBeTruthy();
    });

    it('truncates large searchResult before saving', () => {
      // Create a large search result (>100KB)
      const largeResult: SearchResult = {
        segments: [],
        total_matches: 100,
        matches: Array.from({ length: 5000 }, (_, i) => ({
          phrase_text: `phrase ${'x'.repeat(50)} ${i}`,
          matched_text: `match ${i}`,
          matched_start: -1,
          matched_end: -1,
          turn_index: 0,
          speaker: 'Клиент',
          match_type: 'morph_bow',
          word_distance_used: 1,
          quarter: 'Словарь',
          cascade_order: 1,
          is_exact_match: true,
        })),
        matches_by_level: { '1': 100 },
      };

      const entry = makeEntry({ id: '1', searchResult: largeResult } as HistoryEntry & { searchResult: SearchResult });
      history.add(entry);

      const saved = history.getAll();
      expect(saved).toHaveLength(1);
      // The saved entry should have truncated result (segments and matches removed)
      expect(saved[0].searchResult?.segments).toEqual([]);
      expect(saved[0].searchResult?.matches).toEqual([]);
      // But metadata should be preserved
      expect(saved[0].searchResult?.total_matches).toBe(100);
    });

    it('preserves small searchResult without truncation', () => {
      const entry = makeEntry({ id: '1', searchResult: SAMPLE_SEARCH_RESULT } as HistoryEntry & { searchResult: SearchResult });
      history.add(entry);

      const saved = history.getAll();
      expect(saved[0].searchResult).toEqual(SAMPLE_SEARCH_RESULT);
    });
  });

  // ─── remove ────────────────────────────────────────────

  describe('remove', () => {
    it('removes entry by id', () => {
      history.add(makeEntry({ id: '1' }));
      history.add(makeEntry({ id: '2' }));

      history.remove('1');

      const entries = history.getAll();
      expect(entries).toHaveLength(1);
      expect(entries[0].id).toBe('2');
    });

    it('does nothing when entry not found', () => {
      history.add(makeEntry({ id: '1' }));
      history.remove('nonexistent');

      expect(history.getAll()).toHaveLength(1);
    });

    it('returns true when remove succeeds', () => {
      history.add(makeEntry({ id: '1' }));
      const result = history.remove('1');
      expect(result).toBe(true);
    });

    it('returns true even when entry not found (setItem still succeeds)', () => {
      const result = history.remove('nonexistent');
      expect(result).toBe(true);
    });
  });

  // ─── clearAll ──────────────────────────────────────────

  describe('clearAll', () => {
    it('removes all entries', () => {
      history.add(makeEntry({ id: '1' }));
      history.add(makeEntry({ id: '2' }));

      history.clearAll();

      expect(history.getAll()).toEqual([]);
    });

    it('removes the localStorage key entirely', () => {
      history.add(makeEntry({ id: '1' }));
      history.clearAll();

      expect(localStorageMock.getItem('callcenter-analysis-history')).toBeNull();
    });
  });

  // ─── getStorageUsage ───────────────────────────────────

  describe('getStorageUsage', () => {
    it('returns usage statistics', () => {
      history.add(makeEntry({ id: '1' }));

      const usage = history.getStorageUsage();
      expect(usage.usedBytes).toBeGreaterThan(0);
      expect(usage.totalBytes).toBe(5 * 1024 * 1024); // ~5MB
      expect(usage.percentage).toBeGreaterThan(0);
      expect(usage.percentage).toBeLessThan(1);
    });

    it('returns zero usage when localStorage is empty', () => {
      const usage = history.getStorageUsage();
      expect(usage.usedBytes).toBe(0);
      expect(usage.percentage).toBe(0);
    });
  });

  // ─── isStorageNearCapacity ─────────────────────────────

  describe('isStorageNearCapacity', () => {
    it('returns false when storage is well under limit', () => {
      history.add(makeEntry({ id: '1' }));
      expect(history.isStorageNearCapacity()).toBe(false);
    });
  });

  // ─── cleanupOldEntries ─────────────────────────────────

  describe('cleanupOldEntries', () => {
    it('removes oldest entries to fit within maxEntries', () => {
      for (let i = 1; i <= 10; i++) {
        history.add(makeEntry({ id: String(i) }));
      }

      const removed = history.cleanupOldEntries(5);
      expect(removed).toBe(5);

      const entries = history.getAll();
      expect(entries).toHaveLength(5);
      // Newest entries should remain
      expect(entries.find((e) => e.id === '10')).toBeTruthy();
    });

    it('returns 0 when entries are within limit', () => {
      history.add(makeEntry({ id: '1' }));
      history.add(makeEntry({ id: '2' }));

      expect(history.cleanupOldEntries(10)).toBe(0);
      expect(history.getAll()).toHaveLength(2);
    });
  });

  // ─── FIFO edge cases ──────────────────────────────────

  describe('FIFO cleanup edge cases', () => {
    it('maintains exactly 50 entries after adding beyond limit', () => {
      for (let i = 1; i <= 60; i++) {
        history.add(makeEntry({ id: String(i) }));
      }

      const entries = history.getAll();
      expect(entries).toHaveLength(50);
    });

    it('keeps most recent 50 entries after FIFO cleanup', () => {
      for (let i = 1; i <= 55; i++) {
        history.add(makeEntry({ id: String(i) }));
      }

      const entries = history.getAll();
      // First 5 entries (1-5) should be removed, entries 6-55 should remain
      expect(entries.find((e) => e.id === '1')).toBeUndefined();
      expect(entries.find((e) => e.id === '5')).toBeUndefined();
      expect(entries.find((e) => e.id === '6')).toBeTruthy();
      expect(entries.find((e) => e.id === '55')).toBeTruthy();
    });

    it('preserves entries with searchResult and llmResult after FIFO', () => {
      const entry = makeEntry({
        id: '50',
        searchResult: SAMPLE_SEARCH_RESULT,
        llmResult: SAMPLE_LLM_RESULT,
      } as HistoryEntry & { searchResult: SearchResult; llmResult: LLMResult });

      // Add 49 simple entries first
      for (let i = 1; i <= 49; i++) {
        history.add(makeEntry({ id: `simple-${i}` }));
      }
      // Add the rich entry last
      history.add(entry);

      // Should have 50 entries
      const entries = history.getAll();
      expect(entries).toHaveLength(50);

      // The rich entry should still be there
      const richEntry = entries.find((e) => e.id === '50');
      expect(richEntry).toBeTruthy();
      expect(richEntry!.searchResult).toBeTruthy();
    });
  });

  // ─── localStorage key ────────────────────────────────

  describe('localStorage key', () => {
    it('uses "callcenter-analysis-history" as the localStorage key', () => {
      history.add(makeEntry({ id: '1' }));
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'callcenter-analysis-history',
        expect.any(String),
      );
    });
  });
});
