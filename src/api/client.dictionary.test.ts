/**
 * Tests for Dictionary CRUD API endpoints.
 * Covers: getDictionaryTree, add/update/delete node, condition CRUD,
 * dictionary AI analysis, suggestions, duplicates, stats, validation, XML export.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as api from './client';

const mockFetch = vi.fn();
const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = mockFetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  mockFetch.mockReset();
});

describe('Dictionary API', () => {
  describe('getDictionaryTree', () => {
    it('GETs /api/dictionary/{sessionId}', async () => {
      const tree = [{ name: 'root', children: [] }];
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => tree,
      });

      const result = await api.getDictionaryTree('sess-1');
      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('root');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/dictionary/sess-1',
        { signal: undefined },
      );
    });
  });

  describe('addDictionaryNode', () => {
    it('POSTs to /api/dictionary/{sessionId}/nodes', async () => {
      const created = { id: 'node-1', name: 'NewDict', children: [] };
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => created,
      });

      const result = await api.addDictionaryNode('sess-1', {
        name: 'NewDict', parent_name: null,
      });
      expect(result.name).toBe('NewDict');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/dictionary/sess-1/nodes',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('updateDictionaryNode', () => {
    it('PATCHes /api/dictionary/{sessionId}/nodes/{nodeId}', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ id: 'node-1', name: 'Updated' }),
      });

      const result = await api.updateDictionaryNode('sess-1', 'node-1', { name: 'Updated' });
      expect(result.name).toBe('Updated');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/dictionary/sess-1/nodes/node-1',
        expect.objectContaining({ method: 'PATCH' }),
      );
    });
  });

  describe('deleteDictionaryNode', () => {
    it('DELETEs /api/dictionary/{sessionId}/nodes/{nodeId}', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ deleted: true }),
      });

      const result = await api.deleteDictionaryNode('sess-1', 'node-1');
      expect(result.deleted).toBe(true);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/dictionary/sess-1/nodes/node-1',
        expect.objectContaining({ method: 'DELETE' }),
      );
    });

    it('includes dict_name query param when provided', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ deleted: true }),
      });

      await api.deleteDictionaryNode('sess-1', 'node-1', 'MyDict');
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain('dict_name=MyDict');
    });
  });

  describe('addDictionaryCondition', () => {
    it('POSTs to /api/dictionary/{sessionId}/nodes/{nodeId}/conditions', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ condition: { id: 'cond-1' }, index: 0 }),
      });

      const result = await api.addDictionaryCondition('sess-1', 'node-1', {
        text: 'тест', word_distance: 2,
      });
      expect(result.index).toBe(0);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/dictionary/sess-1/nodes/node-1/conditions',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('updateDictionaryCondition', () => {
    it('PATCHes condition endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ id: 'cond-1', text: 'обновлено' }),
      });

      const result = await api.updateDictionaryCondition('sess-1', 'node-1', 0, { text: 'обновлено' });
      expect(result.text).toBe('обновлено');
    });
  });

  describe('deleteDictionaryCondition', () => {
    it('DELETEs condition endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ deleted: true }),
      });

      const result = await api.deleteDictionaryCondition('sess-1', 'node-1', 0);
      expect(result.deleted).toBe(true);
    });
  });

  describe('reorderDictionaryConditions', () => {
    it('PUTs reorder endpoint with new_order', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ conditions: [] }),
      });

      const result = await api.reorderDictionaryConditions('sess-1', 'node-1', { new_order: [2, 0, 1] });
      expect(result.conditions).toEqual([]);
    });
  });

  describe('analyzeDictionaryAi', () => {
    it('POSTs AI analysis endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ summary: 'OK', examples: [], recommendations: [], raw_response: '' }),
      });

      const result = await api.analyzeDictionaryAi('sess-1', { dict_name: 'MyDict' });
      expect(result.summary).toBe('OK');
    });
  });

  describe('suggestDictionaryPhrases', () => {
    it('POSTs suggest endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ suggestions: [{ phrase: 'фраза1', reason: 'test' }, { phrase: 'фраза2', reason: 'test' }] }),
      });

      const result = await api.suggestDictionaryPhrases('sess-1', { dict_name: 'MyDict' });
      expect(result.suggestions).toHaveLength(2);
    });
  });

  describe('findDictionaryDuplicates', () => {
    it('POSTs duplicate finder endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ full: [], soft: [] }),
      });

      const result = await api.findDictionaryDuplicates('sess-1', { dict_name: 'MyDict' });
      expect(result.full).toEqual([]);
    });
  });

  describe('getDictionaryStatistics', () => {
    it('POSTs statistics endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ total_conditions: 5, total_words: 20, unique_words: 15, operators_count: {}, brackets_count: 0, channels_distribution: {} }),
      });

      const result = await api.getDictionaryStatistics('sess-1', { dict_name: 'MyDict' });
      expect(result.total_conditions).toBe(5);
    });
  });

  describe('validateDictionary', () => {
    it('POSTs validation endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, json: async () => ({ errors: [], warnings: [] }),
      });

      const result = await api.validateDictionary('sess-1', { dict_name: 'MyDict' });
      expect(result.errors).toEqual([]);
    });
  });

  describe('exportDictionaryXml', () => {
    it('POSTs export-xml and returns Blob', async () => {
      const xmlBlob = new Blob(['<xml/>'], { type: 'application/xml' });
      mockFetch.mockResolvedValueOnce({
        ok: true, blob: async () => xmlBlob,
      });

      const result = await api.exportDictionaryXml('sess-1', { dict_name: 'MyDict' });
      expect(result).toBeInstanceOf(Blob);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/dictionary/sess-1/export-xml',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    it('throws ApiError on failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false, status: 400,
        json: async () => ({ detail: 'Bad request' }),
      });

      await expect(
        api.exportDictionaryXml('sess-1', { dict_name: 'MyDict' }),
      ).rejects.toThrow('Bad request');
    });
  });
});
