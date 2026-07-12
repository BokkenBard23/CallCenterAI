/**
 * Tests for AnalysisContext — reducer logic, provider, and hook.
 */
import { describe, it, expect, vi } from 'vitest';
import { renderHook, act, render } from '@testing-library/react';
import {
  AnalysisProvider,
  useAnalysisContext,
  initialState,
} from './AnalysisContext';
import type { AnalysisAction } from './AnalysisContext';
import type {
  ProviderInfo,
  SearchResult,
  LLMResult,
  UploadedDictionary,
} from '../types/api';

// ─── Reducer unit tests (via Provider) ────────────────────

describe('AnalysisContext', () => {
  describe('initial state', () => {
    it('has correct default values', () => {
      expect(initialState.sessionId).toBeNull();
      expect(initialState.rtfUploadStatus).toBe('idle');
      expect(initialState.dictionaries).toEqual([]);
      expect(initialState.providers).toEqual([]);
      expect(initialState.selectedProvider).toBeNull();
      expect(initialState.analysisStatus).toBe('idle');
      expect(initialState.searchResult).toBeNull();
      expect(initialState.llmResult).toBeNull();
      expect(initialState.viewMode).toBe('summary');
      expect(initialState.hideNoMatch).toBe(true);
    });
  });

  describe('useAnalysisContext hook', () => {
    it('throws when used outside provider', () => {
      // Suppress console.error and jsdom error reporting for expected error
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const errorListener = (event: Event) => { event.preventDefault(); };
      window.addEventListener('error', errorListener, true);

      expect(() => {
        renderHook(() => useAnalysisContext());
      }).toThrow('useAnalysisContext must be used within an AnalysisProvider');

      window.removeEventListener('error', errorListener, true);
      consoleSpy.mockRestore();
    });

    it('returns state and dispatch within provider', () => {
      const { result } = renderHook(() => useAnalysisContext(), {
        wrapper: ({ children }) => (
          <AnalysisProvider>{children}</AnalysisProvider>
        ),
      });

      expect(result.current.state).toEqual(initialState);
      expect(typeof result.current.dispatch).toBe('function');
    });
  });

  describe('reducer actions', () => {
    function setup() {
      return renderHook(() => useAnalysisContext(), {
        wrapper: ({ children }) => (
          <AnalysisProvider>{children}</AnalysisProvider>
        ),
      });
    }

    it('SET_SESSION_ID', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({ type: 'SET_SESSION_ID', payload: 'sess-1' });
      });
      expect(result.current.state.sessionId).toBe('sess-1');
    });

    it('SET_RTF_UPLOAD_STATUS', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({
          type: 'SET_RTF_UPLOAD_STATUS',
          payload: 'uploading',
        });
      });
      expect(result.current.state.rtfUploadStatus).toBe('uploading');
    });

    it('SET_RTF_ERROR', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({
          type: 'SET_RTF_ERROR',
          payload: 'File too large',
        });
      });
      expect(result.current.state.rtfError).toBe('File too large');
    });

    it('ADD_DICTIONARY and REMOVE_DICTIONARY', () => {
      const { result } = setup();
      const dict: UploadedDictionary = {
        file: new File(['<xml/>'], 'test.xml', { type: 'text/xml' }),
        response: {
          session_id: 'sess-1',
          dictionary: null,
          validation: { valid: true, warnings: [], errors: [] },
          error: null,
        },
      };

      act(() => {
        result.current.dispatch({ type: 'ADD_DICTIONARY', payload: dict });
      });
      expect(result.current.state.dictionaries).toHaveLength(1);
      expect(result.current.state.dictionaries[0].file?.name).toBe('test.xml');

      act(() => {
        result.current.dispatch({ type: 'REMOVE_DICTIONARY', payload: 0 });
      });
      expect(result.current.state.dictionaries).toHaveLength(0);
    });

    it('SET_PROVIDERS', () => {
      const { result } = setup();
      const providers: ProviderInfo[] = [
        { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        { id: 'yandex', name: 'YandexGPT', models: ['yandexgpt-lite'], configured: true, available: false },
      ];

      act(() => {
        result.current.dispatch({ type: 'SET_PROVIDERS', payload: providers });
      });
      expect(result.current.state.providers).toHaveLength(2);
      expect(result.current.state.providers[0].id).toBe('ollama');
    });

    it('SET_SELECTED_PROVIDER clears selectedModel', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({
          type: 'SET_SELECTED_MODEL',
          payload: 'llama3',
        });
      });
      expect(result.current.state.selectedModel).toBe('llama3');

      act(() => {
        result.current.dispatch({
          type: 'SET_SELECTED_PROVIDER',
          payload: 'ollama',
        });
      });
      expect(result.current.state.selectedProvider).toBe('ollama');
      expect(result.current.state.selectedModel).toBeNull();
    });

    it('SET_ANALYSIS_RESULTS sets both search and LLM results', () => {
      const { result } = setup();
      const searchResult: SearchResult = {
        segments: [],
        total_matches: 0,
        matches: [],
        matches_by_level: {},
      };
      const llmResult: LLMResult = {
        summary: 'Test',
        restructured_dialogue: '',
        topic: 'Test topic',
        result: 'Resolved',
        key_points: [],
        client_sentiment: 'neutral',
        resolution: 'resolved',
        provider: 'ollama',
        model: 'llama3',
      };

      act(() => {
        result.current.dispatch({
          type: 'SET_ANALYSIS_RESULTS',
          payload: { searchResult, llmResult },
        });
      });

      expect(result.current.state.searchResult).toEqual(searchResult);
      expect(result.current.state.llmResult).toEqual(llmResult);
    });

    it('SET_ANALYSIS_RESULTS accepts null values', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({
          type: 'SET_ANALYSIS_RESULTS',
          payload: { searchResult: null, llmResult: null },
        });
      });
      expect(result.current.state.searchResult).toBeNull();
      expect(result.current.state.llmResult).toBeNull();
    });

    it('SET_VIEW_MODE', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({ type: 'SET_VIEW_MODE', payload: 'highlighted' });
      });
      expect(result.current.state.viewMode).toBe('highlighted');
    });

    it('SET_HIDE_NO_MATCH', () => {
      const { result } = setup();
      act(() => {
        result.current.dispatch({ type: 'SET_HIDE_NO_MATCH', payload: true });
      });
      expect(result.current.state.hideNoMatch).toBe(true);
    });

    it('RESET_UPLOAD resets all upload and analysis state', () => {
      const { result } = setup();

      // Set some state first
      act(() => {
        result.current.dispatch({ type: 'SET_SESSION_ID', payload: 'sess-1' });
        result.current.dispatch({
          type: 'SET_RTF_UPLOAD_STATUS',
          payload: 'success',
        });
        result.current.dispatch({
          type: 'SET_ANALYSIS_STATUS',
          payload: 'completed',
        });
        result.current.dispatch({
          type: 'SET_VIEW_MODE',
          payload: 'highlighted',
        });
      });

      // Verify state is set
      expect(result.current.state.sessionId).toBe('sess-1');
      expect(result.current.state.rtfUploadStatus).toBe('success');

      // Reset
      act(() => {
        result.current.dispatch({ type: 'RESET_UPLOAD' });
      });

      expect(result.current.state.sessionId).toBeNull();
      expect(result.current.state.rtfUploadStatus).toBe('idle');
      expect(result.current.state.dictionaries).toEqual([]);
      expect(result.current.state.analysisStatus).toBe('idle');
      expect(result.current.state.searchResult).toBeNull();
      expect(result.current.state.llmResult).toBeNull();
      // View mode should NOT be reset
      expect(result.current.state.viewMode).toBe('highlighted');
    });

    it('unknown action type returns same state', () => {
      const { result } = setup();
      const beforeState = result.current.state;
      act(() => {
        result.current.dispatch({ type: 'UNKNOWN_ACTION' } as unknown as AnalysisAction);
      });
      expect(result.current.state).toEqual(beforeState);
    });
  });

  describe('AnalysisProvider rendering', () => {
    it('renders children', () => {
      const { getByText } = render(
        <AnalysisProvider>
          <div>Child content</div>
        </AnalysisProvider>,
      );
      expect(getByText('Child content')).toBeInTheDocument();
    });
  });
});
