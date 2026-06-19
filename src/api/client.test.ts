/**
 * Tests for API client — fetch-based HTTP wrapper.
 * Covers: successful requests, error handling, ApiError class.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as api from './client';

// ─── Mock fetch globally ─────────────────────────────────

const mockFetch = vi.fn();
const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = mockFetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  mockFetch.mockReset();
});

// ─── Tests ────────────────────────────────────────────────

describe('API client', () => {
  describe('checkHealth', () => {
    it('calls /health endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'ok', version: '1.0.0' }),
      });

      const result = await api.checkHealth();
      expect(result.status).toBe('ok');
      expect(result.version).toBe('1.0.0');
      expect(mockFetch).toHaveBeenCalledWith('/health', { signal: undefined });
    });
  });

  describe('uploadRtf', () => {
    it('POSTs file to /api/upload/rtf', async () => {
      const file = new File(['rtf content'], 'test.rtf', { type: 'text/rtf' });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'sess-123',
          dialogue: null,
          turn_count: 0,
          raw_text_length: 100,
          error: null,
        }),
      });

      const result = await api.uploadRtf(file);
      expect(result.session_id).toBe('sess-123');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/upload/rtf',
        expect.objectContaining({
          method: 'POST',
          body: expect.any(FormData),
        }),
      );
    });
  });

  describe('uploadDictionary', () => {
    it('POSTs file to /api/upload/dictionary', async () => {
      const file = new File(['<xml/>'], 'dict.xml', { type: 'text/xml' });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'sess-123',
          dictionary: null,
          validation: { valid: true, warnings: [], errors: [] },
          error: null,
        }),
      });

      const result = await api.uploadDictionary(file);
      expect(result.session_id).toBe('sess-123');
      expect(result.validation.valid).toBe(true);
    });
  });

  describe('analyze', () => {
    it('POSTs analysis request to /api/analysis/analyze', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          analysis_id: 'anal-1',
          session_id: 'sess-123',
          status: 'completed',
          search_result: { segments: [], total_matches: 0, matches: [], matches_by_level: {} },
          llm_result: null,
          error: null,
          warning: null,
        }),
      });

      const result = await api.analyze({
        session_id: 'sess-123',
        llm_provider: 'ollama',
        include_summary: true,
      });

      expect(result.analysis_id).toBe('anal-1');
      expect(result.status).toBe('completed');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/analyze',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });
  });

  describe('getResults', () => {
    it('GETs /api/analysis/results/{id}', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          analysis_id: 'anal-1',
          session_id: 'sess-123',
          status: 'completed',
          search_result: null,
          llm_result: null,
          error: null,
          warning: null,
        }),
      });

      const result = await api.getResults('anal-1');
      expect(result.analysis_id).toBe('anal-1');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/results/anal-1',
        { signal: undefined },
      );
    });
  });

  describe('getProviders', () => {
    it('GETs /api/providers/', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          providers: [
            { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
          ],
        }),
      });

      const result = await api.getProviders();
      expect(result.providers).toHaveLength(1);
      expect(result.providers[0].id).toBe('ollama');
    });
  });

  describe('getProviderStatus', () => {
    it('GETs /api/providers/{id}/status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 'ollama',
          available: true,
          models: ['llama3'],
        }),
      });

      const result = await api.getProviderStatus('ollama');
      expect(result.id).toBe('ollama');
      expect(result.available).toBe(true);
    });
  });

  describe('error handling', () => {
    it('throws ApiError on non-2xx response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'Not found' }),
      });

      try {
        await api.checkHealth();
        expect.fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(api.ApiError);
        expect((err as api.ApiError).status).toBe(404);
        expect((err as api.ApiError).message).toBe('Not found');
      }
    });

    it('throws ApiError with HTTP status when body parse fails', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      try {
        await api.checkHealth();
        expect.fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(api.ApiError);
        expect((err as api.ApiError).status).toBe(500);
        expect((err as api.ApiError).message).toBe('HTTP 500');
      }
    });

    it('supports AbortSignal', async () => {
      const controller = new AbortController();
      controller.abort();

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'ok', version: '1.0.0' }),
      });

      await api.checkHealth(controller.signal);
      expect(mockFetch).toHaveBeenCalledWith('/health', {
        signal: controller.signal,
      });
    });
  });

  // ═══════════════════════════════════════════════════════════
  // FRIDA Embeddings
  // ═══════════════════════════════════════════════════════════

  describe('indexDialogue', () => {
    it('POSTs to /api/embeddings/index', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'sess-123',
          chunks_indexed: 10,
          vectors_stored: 150,
        }),
      });

      const result = await api.indexDialogue({ session_id: 'sess-123' });
      expect(result.session_id).toBe('sess-123');
      expect(result.chunks_indexed).toBe(10);
      expect(result.vectors_stored).toBe(150);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/embeddings/index',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });
  });

  describe('searchSemantic', () => {
    it('POSTs to /api/embeddings/search/semantic', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          results: [
            {
              chunk_id: 'c1',
              text: 'подключить',
              dialogue_id: 'd1',
              turn_index: 3,
              speaker: 'Клиент',
              score: 0.9,
              chunk_type: 'turn',
              entities: [],
            },
          ],
          query: 'услуга',
          total: 1,
        }),
      });

      const result = await api.searchSemantic({ query: 'услуга', top_k: 10 });
      expect(result.results).toHaveLength(1);
      expect(result.results[0].score).toBe(0.9);
      expect(result.total).toBe(1);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/embeddings/search/semantic',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('searchHybrid', () => {
    it('POSTs to /api/embeddings/search/hybrid', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          results: [
            {
              text: 'подключить услугу',
              dialogue_id: 'd1',
              turn_index: 3,
              speaker: 'Клиент',
              morph_score: 0.5,
              semantic_score: 0.8,
              ner_boost: 0.1,
              matched_entities: ['услугу'],
              combined_score: 0.87,
              source: 'hybrid',
            },
          ],
          query: 'услуга',
          total: 1,
        }),
      });

      const result = await api.searchHybrid({ query: 'услуга' });
      expect(result.results).toHaveLength(1);
      expect(result.results[0].combined_score).toBe(0.87);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/embeddings/search/hybrid',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('getEmbeddingStatus', () => {
    it('GETs /api/embeddings/status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          frida_available: true,
          vectors_stored: 150,
          unique_dialogues: 12,
          index_size_bytes: 1024000,
          nlp_provider: 'natasha',
          natasha_available: true,
          deeppavlov_available: false,
        }),
      });

      const result = await api.getEmbeddingStatus();
      expect(result.frida_available).toBe(true);
      expect(result.vectors_stored).toBe(150);
      expect(result.nlp_provider).toBe('natasha');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/embeddings/status',
        { signal: undefined },
      );
    });
  });
});
