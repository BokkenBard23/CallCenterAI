/**
 * Tests for Export, Feedback, and Quality Scoring API endpoints.
 * Covers: exportExcel, exportPdf, submitFeedback, getQualityScore.
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

describe('Export API', () => {
  describe('exportExcel', () => {
    it('GETs /api/export/{sessionId}/excel and returns Blob', async () => {
      const blob = new Blob(['excel data'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      mockFetch.mockResolvedValueOnce({
        ok: true, blob: async () => blob,
      });

      const result = await api.exportExcel('sess-1');
      expect(result).toBeInstanceOf(Blob);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/export/sess-1/excel',
        { signal: undefined },
      );
    });

    it('throws ApiError on non-2xx', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false, status: 404,
        json: async () => ({ detail: 'Session not found' }),
      });

      await expect(api.exportExcel('ghost')).rejects.toThrow('Session not found');
    });

    it('falls back to HTTP status when body parse fails', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false, status: 500,
        json: async () => { throw new Error('bad json'); },
      });

      await expect(api.exportExcel('sess-1')).rejects.toThrow('HTTP 500');
    });

    it('supports AbortSignal', async () => {
      const controller = new AbortController();
      mockFetch.mockResolvedValueOnce({
        ok: true, blob: async () => new Blob(),
      });

      await api.exportExcel('sess-1', controller.signal);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/export/sess-1/excel',
        expect.objectContaining({ signal: controller.signal }),
      );
    });
  });

  describe('exportPdf', () => {
    it('GETs /api/export/{sessionId}/pdf and returns Blob', async () => {
      const blob = new Blob(['pdf data'], { type: 'application/pdf' });
      mockFetch.mockResolvedValueOnce({
        ok: true, blob: async () => blob,
      });

      const result = await api.exportPdf('sess-1');
      expect(result).toBeInstanceOf(Blob);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/export/sess-1/pdf',
        { signal: undefined },
      );
    });

    it('throws on PDF export failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false, status: 404,
        json: async () => ({ detail: 'Not found' }),
      });

      await expect(api.exportPdf('ghost')).rejects.toThrow('Not found');
    });
  });
});

describe('Feedback API', () => {
  describe('submitFeedback', () => {
    it('POSTs to /api/feedback', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          status: 'ok',
          feedback_id: 'fb-1',
          message: 'Feedback submitted',
        }),
      });

      const result = await api.submitFeedback({
        phrase_text: 'тест',
        session_id: 'sess-1',
        matched_text: 'тест',
        turn_index: 0,
        feedback_text: 'Отличный матч!',
      });
      expect(result.status).toBe('ok');
      expect(result.feedback_id).toBe('fb-1');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/feedback',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });

    it('includes optional fields', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'ok', feedback_id: 'fb-2', message: '' }),
      });

      await api.submitFeedback({
        phrase_text: 'фраза',
        session_id: 'sess-1',
        matched_text: 'найденная фраза',
        turn_index: 3,
        feedback_text: 'Тест',
        channel_constraint: 'CLIENT',
        word_distance: 2,
      });

      const body = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(body.matched_text).toBe('найденная фраза');
      expect(body.channel_constraint).toBe('CLIENT');
      expect(body.word_distance).toBe(2);
    });
  });
});

describe('Quality Scoring API', () => {
  describe('getQualityScore', () => {
    it('POSTs to /api/analysis/quality-score', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'sess-1',
          categories: [],
          overall_score: 0.75,
          overall_level: 'medium',
          strengths: [],
          weaknesses: [],
          recommendations: [],
          provider: 'beeline',
          model: 'qwen-medium-dense',
        }),
      });

      const result = await api.getQualityScore({
        session_id: 'sess-1',
        provider_id: 'beeline',
      });
      expect(result.overall_score).toBe(0.75);
      expect(result.overall_level).toBe('medium');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/analysis/quality-score',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
