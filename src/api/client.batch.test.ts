/**
 * Tests for Batch API endpoints.
 * Covers: submitBatch, getBatchStatus, getBatchResults.
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

describe('Batch API', () => {
  describe('submitBatch', () => {
    it('POSTs files and params to /api/analysis/batch', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          batch_id: 'batch-1',
          session_id: 'sess-123',
          total_files: 2,
          status: 'pending',
          items: [],
          completed_count: 0,
          failed_count: 0,
        }),
      });

      const files = [new File(['a'], 'a.rtf'), new File(['b'], 'b.rtf')];
      const result = await api.submitBatch(files, 'sess-123', 'ollama');

      expect(result.batch_id).toBe('batch-1');
      expect(result.status).toBe('pending');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/batch',
        expect.objectContaining({
          method: 'POST',
          body: expect.any(FormData),
        }),
      );
    });

    it('passes optional parameters in FormData', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          batch_id: 'b1', session_id: 's1', total_files: 1,
          status: 'pending', items: [], completed_count: 0, failed_count: 0,
        }),
      });

      await api.submitBatch(
        [new File(['x'], 'x.rtf')],
        'sess-1',
        'beeline',
        'qwen-medium-dense',
        true,
        true,
        ['dict-1'],
      );

      const callBody = mockFetch.mock.calls[0][1].body as FormData;
      expect(callBody.get('session_id')).toBe('sess-1');
      expect(callBody.get('llm_model')).toBe('qwen-medium-dense');
      expect(callBody.get('include_summary')).toBe('true');
      expect(callBody.get('include_restructured')).toBe('true');
      expect(callBody.get('dictionary_ids')).toBe('dict-1');
    });

    it('supports AbortSignal', async () => {
      const controller = new AbortController();
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ batch_id: 'b1', session_id: 's1', total_files: 0, status: 'pending', items: [], completed_count: 0, failed_count: 0 }),
      });

      await api.submitBatch([], 's1', 'ollama', undefined, undefined, undefined, undefined, controller.signal);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/batch',
        expect.objectContaining({ signal: controller.signal }),
      );
    });
  });

  describe('getBatchStatus', () => {
    it('GETs /api/analysis/batch/{id}/status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          batch_id: 'batch-1', session_id: 'sess-1',
          total_files: 2, status: 'processing',
          items: [{ filename: 'a.rtf', status: 'completed' }],
          completed_count: 1, failed_count: 0,
        }),
      });

      const result = await api.getBatchStatus('batch-1');
      expect(result.batch_id).toBe('batch-1');
      expect(result.status).toBe('processing');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/batch/batch-1/status',
        { signal: undefined },
      );
    });
  });

  describe('getBatchResults', () => {
    it('GETs /api/analysis/batch/{id}/results', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          batch_id: 'batch-1', session_id: 'sess-1',
          total_files: 1, status: 'completed',
          items: [{ filename: 'a.rtf', status: 'completed' }],
          completed_count: 1, failed_count: 0,
        }),
      });

      const result = await api.getBatchResults('batch-1');
      expect(result.status).toBe('completed');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/batch/batch-1/results',
        { signal: undefined },
      );
    });
  });
});
