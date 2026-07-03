/**
 * Tests for useSpeechLabState hook.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSpeechLabState } from './useSpeechLabState';

// ─── Mock AnalysisContext ────────────────────────────────

const mockDispatch = vi.fn();
const mockState = {
  sessionId: null,
  dialogue: null,
  dictionaries: [],
  analysisStatus: 'idle' as const,
  analysisError: null,
  selectedProvider: null,
  selectedModel: null,
  searchResult: null,
};

vi.mock('../context/AnalysisContext', () => ({
  useAnalysisContext: () => ({
    state: mockState,
    dispatch: mockDispatch,
  }),
}));

// ─── Mock API ────────────────────────────────────────────

const mockUploadRtf = vi.fn();
const mockAnalyze = vi.fn();

vi.mock('../api/client', () => ({
  uploadRtf: (...args: unknown[]) => mockUploadRtf(...args),
  analyze: (...args: unknown[]) => mockAnalyze(...args),
}));

// ─── Tests ──────────────────────────────────────────────

describe('useSpeechLabState', () => {
  beforeEach(() => {
    mockDispatch.mockReset();
    mockUploadRtf.mockReset();
    mockAnalyze.mockReset();

    // Reset mock state
    mockState.sessionId = null;
    mockState.dialogue = null;
    mockState.dictionaries = [];
    mockState.analysisStatus = 'idle';
    mockState.analysisError = null;
  });

  it('initializes with correct default state', () => {
    const { result } = renderHook(() => useSpeechLabState());

    expect(result.current.state.treeNodes).toEqual([]);
    expect(result.current.state.selectedNodeId).toBeNull();
    expect(result.current.state.rtfDialogOpen).toBe(false);
    expect(result.current.derived.hasSession).toBe(false);
    expect(result.current.derived.isSearching).toBe(false);
  });

  it('handleSelectNode updates selectedNodeId', () => {
    const { result } = renderHook(() => useSpeechLabState());

    act(() => {
      result.current.actions.handleSelectNode({
        id: 'node-1',
        name: 'Test Node',
        has_children: false,
        children_count: 0,
        is_remainder: false,
        display_tokens: [],
        children: [],
        attributes: [],
      });
    });

    expect(result.current.state.selectedNodeId).toBe('node-1');
  });

  it('handleToggleExpand updates expandedNodes', () => {
    const { result } = renderHook(() => useSpeechLabState());

    act(() => {
      result.current.actions.handleToggleExpand('node-1', true);
    });

    expect(result.current.state.expandedNodes['node-1']).toBe(true);

    act(() => {
      result.current.actions.handleToggleExpand('node-1', false);
    });

    expect(result.current.state.expandedNodes['node-1']).toBe(false);
  });

  it('openRtfDialog sets dialog state', () => {
    const { result } = renderHook(() => useSpeechLabState());

    act(() => {
      result.current.actions.openRtfDialog();
    });

    expect(result.current.state.rtfDialogOpen).toBe(true);
  });

  it('closeRtfDialog clears dialog state', () => {
    const { result } = renderHook(() => useSpeechLabState());

    act(() => {
      result.current.actions.openRtfDialog();
    });

    act(() => {
      result.current.actions.closeRtfDialog();
    });

    expect(result.current.state.rtfDialogOpen).toBe(false);
    expect(result.current.state.rtfFileName).toBeNull();
  });

  it('handleRtfSelect stores file name', () => {
    const { result } = renderHook(() => useSpeechLabState());

    const mockFile = new File(['test'], 'test.rtf', { type: 'application/rtf' });

    act(() => {
      result.current.actions.handleRtfSelect(mockFile);
    });

    expect(result.current.state.rtfFileName).toBe('test.rtf');
  });

  it('derived.isSearching reflects context analysisStatus', () => {
    mockState.analysisStatus = 'analyzing';

    const { result } = renderHook(() => useSpeechLabState());

    expect(result.current.derived.isSearching).toBe(true);
  });

  it('derived.hasSession reflects context sessionId', () => {
    mockState.sessionId = 'test-session';

    const { result } = renderHook(() => useSpeechLabState());

    expect(result.current.derived.hasSession).toBe(true);
  });
});
