/**
 * Tests for Mining (Track B) API endpoints.
 * Covers: indexCorpus, getMiningStatus, cancelMining,
 * findSimilar, findFalseNegatives, auditDictionary.
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

describe('Mining API (Track B)', () => {
  describe('indexCorpus', () => {
    it('POSTs to /api/mining/index', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-1',
          status: 'pending',
          total_dialogues: 0,
          message: 'Indexing started',
        }),
      });

      const result = await api.indexCorpus({
        session_id: 'sess-1',
        directory_path: '/data/rtf',
        dictionary_id: 'dict-1',
      });
      expect(result.job_id).toBe('job-1');
      expect(result.status).toBe('pending');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/mining/index',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('getMiningStatus', () => {
    it('GETs /api/mining/status/{jobId}', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-1',
          status: 'running',
          job_type: 'index',
          progress: 0.5,
          processed_dialogues: 25,
          total_dialogues: 50,
          started_at: '2026-07-19T00:00:00',
        }),
      });

      const result = await api.getMiningStatus('job-1');
      expect(result.job_id).toBe('job-1');
      expect(result.status).toBe('running');
      expect(result.progress).toBe(0.5);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/mining/status/job-1',
        { signal: undefined },
      );
    });

    it('encodes job_id in URL', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'j/1', status: 'pending', started_at: '' }),
      });

      await api.getMiningStatus('j/1');
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain(encodeURIComponent('j/1'));
    });
  });

  describe('cancelMining', () => {
    it('POSTs to /api/mining/cancel/{jobId}', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'cancelled', message: 'Job cancelled' }),
      });

      const result = await api.cancelMining('job-1');
      expect(result.status).toBe('cancelled');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/mining/cancel/job-1',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('findSimilar', () => {
    it('POSTs to /api/mining/find_similar', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          phrase_group_id: 'pg-1',
          total: 1,
          dialogues: [{ dialogue_id: 'd1', file_path: '/d1.rtf', snippet: '...', score: 0.9, channel: 'CLIENT', turn_count: 10 }],
        }),
      });

      const result = await api.findSimilar({
        session_id: 'sess-1',
        job_id: 'job-1',
        phrase_group_id: 'pg-1',
        top_k: 10,
      });
      expect(result.total).toBe(1);
      expect(result.dialogues[0].score).toBe(0.9);
    });
  });

  describe('findFalseNegatives', () => {
    it('POSTs to /api/mining/find_fn', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'fn-job-1',
          dictionary_id: 'dict-1',
          total: 0,
          candidates: [],
          partial: false,
        }),
      });

      const result = await api.findFalseNegatives({
        session_id: 'sess-1',
        job_id: 'job-1',
        dictionary_id: 'dict-1',
        threshold: 0.7,
      });
      expect(result.job_id).toBe('fn-job-1');
      expect(result.candidates).toEqual([]);
    });
  });

  describe('auditDictionary', () => {
    it('POSTs to /api/mining/audit', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'audit-job-1',
          dictionary_id: 'dict-1',
          phrase_groups: [],
          partial: false,
        }),
      });

      const result = await api.auditDictionary({
        session_id: 'sess-1',
        job_id: 'job-1',
        dictionary_id: 'dict-1',
      });
      expect(result.job_id).toBe('audit-job-1');
      expect(result.phrase_groups).toEqual([]);
    });
  });
});
