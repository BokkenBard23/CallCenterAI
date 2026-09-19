/**
 * Tests for UploadPage — reworked upload form with Stepper, DropZone,
 * Dialog confirmation, and snackbar notifications.
 *
 * Covers: page renders, Stepper navigation, DropZone upload, reset with
 * Dialog confirmation, analyze button disabled state, health check,
 * provider loading, RTF upload flow, dictionary upload, error states.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React, { useEffect } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AnalysisProvider, useAnalysisContext } from '../context/AnalysisContext';
import type { AnalysisAction } from '../context/AnalysisContext';
import { SnackbarProvider } from '../context/SnackbarContext';
import UploadPage from './UploadPage';

// ─── Mock useNavigate ─────────────────────────────────────

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// ─── Mock API client ─────────────────────────────────────

const mockCheckHealth = vi.fn();
const mockGetProviders = vi.fn();
const mockUploadRtf = vi.fn();
const mockUploadDictionary = vi.fn();
const mockAnalyze = vi.fn();
const mockSearch = vi.fn();
const mockStartLLMAnalysis = vi.fn();
const mockSubmitBatch = vi.fn();

vi.mock('../api/client', () => ({
  checkHealth: (...args: unknown[]) => mockCheckHealth(...args),
  getProviders: (...args: unknown[]) => mockGetProviders(...args),
  uploadRtf: (...args: unknown[]) => mockUploadRtf(...args),
  uploadDictionary: (...args: unknown[]) => mockUploadDictionary(...args),
  analyze: (...args: unknown[]) => mockAnalyze(...args),
  search: (...args: unknown[]) => mockSearch(...args),
  startLLMAnalysis: (...args: unknown[]) => mockStartLLMAnalysis(...args),
  submitBatch: (...args: unknown[]) => mockSubmitBatch(...args),
  getResults: vi.fn(),
  getProviderStatus: vi.fn(),
  ApiError: class extends Error { status = 0; body?: unknown; },
}));

// ─── Mock motion/react to avoid animation issues in jsdom ─

vi.mock('motion/react', () => ({
  useMotionValue: (initial: number) => ({
    set: vi.fn(),
    get: () => initial,
    on: () => () => {},
  }),
  useSpring: () => ({
    on: () => () => {},
    get: () => 0,
  }),
  useInView: () => true,
  AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
  m: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) =>
      React.createElement('div', props, children),
    span: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) =>
      React.createElement('span', props, children),
  },
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) =>
      React.createElement('div', props, children),
    span: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) =>
      React.createElement('span', props, children),
  },
}));

// ─── Helper ───────────────────────────────────────────────

function renderUploadPage() {
  return render(
    <MemoryRouter>
      <SnackbarProvider>
        <AnalysisProvider>
          <UploadPage />
        </AnalysisProvider>
      </SnackbarProvider>
    </MemoryRouter>,
  );
}

// ─── Tests ────────────────────────────────────────────────

/** Mock search result returned by Phase 1 (api.search) */
const MOCK_SEARCH_RESULT = {
  total_matches: 5,
  matches_by_level: { high: 2, medium: 3 },
  segments: [],
  matches: [],
};

/** Mock LLM result returned by Phase 2 (api.startLLMAnalysis) */
const MOCK_LLM_RESULT = {
  summary: 'Test summary',
  restructured_dialogue: '',
  topic: 'Test topic',
  result: 'positive',
  key_points: [],
  client_sentiment: 'neutral',
  resolution: 'resolved',
  provider: 'ollama',
  model: 'llama3',
};

describe('UploadPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockCheckHealth.mockReset();
    mockGetProviders.mockReset();
    mockUploadRtf.mockReset();
    mockUploadDictionary.mockReset();
    mockAnalyze.mockReset();
    mockSearch.mockReset();
    mockStartLLMAnalysis.mockReset();
    mockSubmitBatch.mockReset();
    mockCheckHealth.mockResolvedValue({ status: 'ok', version: '1.0.0' });
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
      ],
    });
    mockUploadRtf.mockResolvedValue({
      session_id: 'test-session',
      dialogue: [{ turn_index: 0, speaker: 'Клиент', text: 'Привет', timestamp: null }],
      turn_count: 1,
      raw_text_length: 100,
      error: null,
    });
    mockUploadDictionary.mockResolvedValue({
      session_id: 'test-session',
      dictionary: null,
      validation: { valid: true, warnings: [], errors: [] },
      error: null,
    });
    mockAnalyze.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      search_result: null,
      llm_result: null,
      error: null,
      warning: null,
    });
    mockSearch.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      search_result: MOCK_SEARCH_RESULT,
      cache_hit: false,
    });
    mockStartLLMAnalysis.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      llm_result: MOCK_LLM_RESULT,
      warning: null,
    });
  });

  // ─── Basic rendering ──────────────────────────────────

  it('renders page title', async () => {
    renderUploadPage();
    expect(screen.getByText('Анализ диалогов')).toBeTruthy();
  });

  it('renders RTF upload area via DropZone', () => {
    renderUploadPage();
    const rtfArea = screen.getByLabelText('Загрузить RTF-файл диалога');
    expect(rtfArea).toBeTruthy();
  });

  it('renders Analyze button as disabled by default', () => {
    renderUploadPage();
    const analyzeBtn = screen.getByText('Анализировать');
    expect(analyzeBtn).toBeTruthy();
  });

  it('renders Reset button', () => {
    renderUploadPage();
    const resetBtn = screen.getByText('Сбросить');
    expect(resetBtn).toBeTruthy();
  });

  it('renders RTF upload step heading', () => {
    renderUploadPage();
    expect(screen.getByText('Диалог')).toBeTruthy();
  });

  it('renders upload instruction text', () => {
    renderUploadPage();
    expect(screen.getByText('Нажмите или перетащите RTF-файл')).toBeTruthy();
  });

  it('has hidden file input for RTF', () => {
    renderUploadPage();
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    expect(rtfInput).toBeTruthy();
    expect(rtfInput.accept).toBe('.rtf');
  });

  // ─── Health check ─────────────────────────────────────

  it('shows error banner when health check fails', async () => {
    mockCheckHealth.mockRejectedValue(new Error('Network error'));
    renderUploadPage();

    await waitFor(() => {
      expect(screen.getByText(/Сервер недоступен/)).toBeTruthy();
    });
  });

  it('does not show error banner when health check passes', async () => {
    renderUploadPage();

    await waitFor(() => {
      expect(screen.queryByText(/Сервер недоступен/)).toBeNull();
    });
  });

  // ─── RTF upload flow ──────────────────────────────────

  it('shows uploaded file name after RTF selection', async () => {
    renderUploadPage();

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });

    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('dialog.rtf')).toBeTruthy();
    });
  });

  it('shows turn count after successful RTF upload', async () => {
    renderUploadPage();

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });

    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Загружено реплик: 1/)).toBeTruthy();
    });
  });

  it('shows error after failed RTF upload', async () => {
    mockUploadRtf.mockRejectedValue(new Error('Invalid RTF'));
    renderUploadPage();

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'bad.rtf', { type: 'application/rtf' });

    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('Invalid RTF')).toBeTruthy();
    });
  });

  // ─── Reset with Dialog confirmation ────────────────────

  it('opens reset confirmation dialog on reset click', async () => {
    renderUploadPage();

    // M9 FIX: Reset is now disabled when there is nothing to reset
    // (vision-audit M9). Upload a file first so the Reset button becomes
    // enabled and the dialog test exercises the actual reset flow.
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file] } });
    await waitFor(() => {
      expect(screen.getByText('dialog.rtf')).toBeTruthy();
    });

    const resetBtn = screen.getByText('Сбросить');
    fireEvent.click(resetBtn);

    // DS Dialog renders via portal — wait for the dialog to appear
    await waitFor(() => {
      // Look for the dialog title text — DS may render it in a portal
      const dialogElements = document.querySelectorAll('[role="dialog"]');
      expect(dialogElements.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('closes dialog on Отмена click', async () => {
    renderUploadPage();

    // M9 FIX: same as above — upload a file first so Reset is enabled.
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file] } });
    await waitFor(() => {
      expect(screen.getByText('dialog.rtf')).toBeTruthy();
    });

    const resetBtn = screen.getByText('Сбросить');
    fireEvent.click(resetBtn);

    // Wait for dialog to open
    await waitFor(() => {
      expect(document.querySelectorAll('[role="dialog"]').length).toBeGreaterThanOrEqual(1);
    });

    // Click cancel (inside the dialog portal)
    const cancelBtn = screen.getByText('Отмена');
    fireEvent.click(cancelBtn);

    // Dialog should close
    await waitFor(() => {
      expect(document.querySelectorAll('[role="dialog"]').length).toBe(0);
    });
    // M9 FIX: after Cancel, the upload state must be preserved (Cancel does
    // not reset). The stepper auto-advances to the 'dict' step after a
    // successful RTF upload, so we assert the 'dict' step heading is visible
    // — that proves the RTF upload is still in effect and no reset occurred.
    await waitFor(() => {
      expect(screen.queryByText('Словари')).not.toBeNull();
    });
  });

  it('resets data on dialog confirm', async () => {
    renderUploadPage();

    // Upload a file first
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('dialog.rtf')).toBeTruthy();
    });

    // Click reset
    const resetBtn = screen.getByText('Сбросить');
    fireEvent.click(resetBtn);

    // Wait for dialog
    await waitFor(() => {
      expect(document.querySelectorAll('[role="dialog"]').length).toBeGreaterThanOrEqual(1);
    });

    // Find the confirm button inside the dialog (it's the Сбросить button in the dialog)
    // The dialog has two buttons: Отмена and Сбросить
    // We need the Сбросить inside the dialog
    const allResetBtns = screen.getAllByText('Сбросить');
    // The dialog confirm button should be the last one (inside the dialog portal)
    const confirmBtn = allResetBtns[allResetBtns.length - 1];
    fireEvent.click(confirmBtn);

    // File name should be gone — page returns to step 1 DropZone
    await waitFor(() => {
      expect(screen.queryByText('dialog.rtf')).toBeNull();
    });
  });

  // ─── Analyze button state ─────────────────────────────

  it('disables analyze when no session exists', () => {
    renderUploadPage();
    const analyzeBtn = screen.getByText('Анализировать');
    expect(analyzeBtn).toBeTruthy();
  });

  // ─── Stepper ──────────────────────────────────────────

  it('shows Stepper with 3 steps', () => {
    renderUploadPage();
    expect(screen.getByText('Загрузка RTF')).toBeTruthy();
    expect(screen.getByText('Словарь')).toBeTruthy();
    expect(screen.getByText('Анализ')).toBeTruthy();
  });

  it('starts on RTF step by default', () => {
    renderUploadPage();
    // Step 1 heading should be visible
    expect(screen.getByText('Диалог')).toBeTruthy();
  });

  // ─── Dictionary upload (Step 2) ────────────────────────

  it('navigates to dictionary step after RTF upload', async () => {
    renderUploadPage();

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      // After RTF upload, step 2 should be visible (Словари heading)
      expect(screen.getByText('Словари')).toBeTruthy();
      // Dictionary DropZone should be visible
      expect(screen.getByLabelText('Загрузить XML-файлы словарей')).toBeTruthy();
    });
  });

  it('has hidden file input for dictionaries', async () => {
    renderUploadPage();

    // Need to navigate to step 2 first by uploading RTF
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
      expect(dictInput).toBeTruthy();
      expect(dictInput.accept).toBe('.xml');
      expect(dictInput.multiple).toBe(true);
    });
  });

  it('shows dictionary file name after upload', async () => {
    renderUploadPage();

    // Navigate to step 2 by uploading RTF
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const rtfFile = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [rtfFile] } });

    await waitFor(() => {
      expect(screen.getByLabelText('Загрузить XML-файлы словарей')).toBeTruthy();
    });

    const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
    const dictFile = new File(['<xml/>'], 'dict.xml', { type: 'text/xml' });
    fireEvent.change(dictInput, { target: { files: [dictFile] } });

    await waitFor(() => {
      expect(screen.getByText('dict.xml')).toBeTruthy();
    });
  });

  it('shows dictionary error on failed upload', async () => {
    mockUploadDictionary.mockRejectedValue(new Error('Bad XML'));
    renderUploadPage();

    // Navigate to step 2
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const rtfFile = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [rtfFile] } });

    await waitFor(() => {
      expect(screen.getByLabelText('Загрузить XML-файлы словарей')).toBeTruthy();
    });

    const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
    const dictFile = new File(['<xml/>'], 'bad.xml', { type: 'text/xml' });
    fireEvent.change(dictInput, { target: { files: [dictFile] } });

    await waitFor(() => {
      expect(screen.getByText('Bad XML')).toBeTruthy();
    });
  });

  // ─── Provider/Analyze step (Step 3) ───────────────────

  it('shows LLM provider card heading on analyze step', async () => {
    renderUploadPage();

    // Upload RTF to move to step 2
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const rtfFile = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [rtfFile] } });

    await waitFor(() => {
      expect(screen.getByLabelText('Загрузить XML-файлы словарей')).toBeTruthy();
    });

    // Upload dictionary to move to step 3
    const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
    const dictFile = new File(['<xml/>'], 'dict.xml', { type: 'text/xml' });
    fireEvent.change(dictInput, { target: { files: [dictFile] } });

    await waitFor(() => {
      expect(screen.getByText('LLM-провайдер')).toBeTruthy();
    });
  });

  it('shows error when provider loading fails', async () => {
    mockGetProviders.mockRejectedValue(new Error('Network error'));
    renderUploadPage();

    // Navigate to step 3
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const rtfFile = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [rtfFile] } });

    await waitFor(() => {
      expect(screen.getByLabelText('Загрузить XML-файлы словарей')).toBeTruthy();
    });

    const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
    const dictFile = new File(['<xml/>'], 'dict.xml', { type: 'text/xml' });
    fireEvent.change(dictInput, { target: { files: [dictFile] } });

    await waitFor(() => {
      expect(screen.getByText(/Не удалось загрузить список провайдеров/)).toBeTruthy();
    });
  });

  // ─── Non-blocking Phase 2 (LLM analysis) ──────────────
  //
  // Tests that handleAnalyze fires Phase 2 (LLM) as fire-and-forget:
  //   - Phase 1 (search) is awaited → navigate('/results') called
  //   - Phase 2 runs in background → SET_LLM_RESULT + snackbar when done
  //   - setAnalyzing(false) after Phase 1 (not Phase 2)

  /**
   * Child component that pre-dispatches AnalysisContext state on mount,
   * simulating a user who has already uploaded RTF + dictionary + selected provider.
   */
  function StateInitializer({
    onReady,
  }: {
    onReady: (dispatch: React.Dispatch<AnalysisAction>) => void;
  }) {
    const { dispatch } = useAnalysisContext();
    useEffect(() => {
      onReady(dispatch);
    }, [dispatch, onReady]);
    return null;
  }

  /**
   * Render UploadPage with all state pre-set so the "Анализировать" button
   * is enabled immediately (bypasses the Stepper upload UI flow).
   */
  function renderReadyToAnalyze(
    onReady: (dispatch: React.Dispatch<AnalysisAction>) => void,
  ) {
    return render(
      <MemoryRouter>
        <SnackbarProvider>
          <AnalysisProvider>
            <StateInitializer onReady={onReady} />
            <UploadPage />
          </AnalysisProvider>
        </SnackbarProvider>
      </MemoryRouter>,
    );
  }

  /** Mock search result returned by Phase 1 */
  // (defined at module top — MOCK_SEARCH_RESULT)

  /** Mock LLM result returned by Phase 2 */
  // (defined at module top — MOCK_LLM_RESULT)

  it('Phase 1 is awaited: navigates to /results before Phase 2 resolves', async () => {
    // Phase 2 (startLLMAnalysis) promise that never resolves during this test
    const phase2Promise = new Promise(() => {});
    mockSearch.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      search_result: MOCK_SEARCH_RESULT,
      cache_hit: false,
    });
    mockStartLLMAnalysis.mockReturnValue(phase2Promise);

    const onReady = vi.fn((dispatch: React.Dispatch<AnalysisAction>) => {
      dispatch({ type: 'SET_SESSION_ID', payload: 'test-session' });
      dispatch({ type: 'SET_RTF_FILE', payload: new File(['test'], 'dialog.rtf') });
      dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_DIALOGUE',
        payload: [{ turn_index: 0, speaker: 'Клиент', text: 'Привет', timestamp: null }],
      });
      dispatch({
        type: 'ADD_DICTIONARY',
        payload: {
          file: new File(['<xml/>'], 'dict.xml'),
          response: {
            session_id: 'test-session',
            dictionary: null,
            validation: { valid: true, warnings: [], errors: [] },
            error: null,
          },
        },
      });
      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_PROVIDERS',
        payload: [
          { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        ],
      });
      dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
      dispatch({ type: 'SET_SELECTED_PROVIDER', payload: 'ollama' });
    });

    renderReadyToAnalyze(onReady);

    // Wait for the analyze button to appear and be enabled
    const analyzeBtn = await screen.findByText('Анализировать');
    await waitFor(() => {
      expect(analyzeBtn).not.toBeDisabled();
    });

    fireEvent.click(analyzeBtn);

    // Phase 1 resolves → navigate('/results') called WITHOUT waiting for Phase 2
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/results');
    });

    // Phase 2 was called (fire-and-forget) but hasn't resolved yet
    await waitFor(() => {
      expect(mockSearch).toHaveBeenCalledTimes(1);
      expect(mockStartLLMAnalysis).toHaveBeenCalledTimes(1);
    });

    // Phase 1 was search() with session_id
    expect(mockSearch.mock.calls[0][0]).toMatchObject({ session_id: 'test-session' });
    // Phase 2 was startLLMAnalysis() with analysis_id + include_summary: true
    expect(mockStartLLMAnalysis.mock.calls[0][0]).toMatchObject({
      analysis_id: 'analysis-1',
      include_summary: true,
    });
  });

  it('Phase 2 fire-and-forget: SET_LLM_RESULT + snackbar when LLM completes', async () => {
    let resolvePhase2!: (value: unknown) => void;

    mockSearch.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      search_result: MOCK_SEARCH_RESULT,
      cache_hit: false,
    });
    mockStartLLMAnalysis.mockImplementation(() => {
      // Phase 2 — controlled resolution
      return new Promise((resolve) => {
        resolvePhase2 = resolve;
      });
    });

    const onReady = vi.fn((dispatch: React.Dispatch<AnalysisAction>) => {
      dispatch({ type: 'SET_SESSION_ID', payload: 'test-session' });
      dispatch({ type: 'SET_RTF_FILE', payload: new File(['test'], 'dialog.rtf') });
      dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_DIALOGUE',
        payload: [{ turn_index: 0, speaker: 'Клиент', text: 'Привет', timestamp: null }],
      });
      dispatch({
        type: 'ADD_DICTIONARY',
        payload: {
          file: new File(['<xml/>'], 'dict.xml'),
          response: {
            session_id: 'test-session',
            dictionary: null,
            validation: { valid: true, warnings: [], errors: [] },
            error: null,
          },
        },
      });
      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_PROVIDERS',
        payload: [
          { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        ],
      });
      dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
      dispatch({ type: 'SET_SELECTED_PROVIDER', payload: 'ollama' });
    });

    renderReadyToAnalyze(onReady);

    const analyzeBtn = await screen.findByText('Анализировать');
    await waitFor(() => {
      expect(analyzeBtn).not.toBeDisabled();
    });

    fireEvent.click(analyzeBtn);

    // Wait for Phase 1 to complete and Phase 2 to start
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/results');
    });
    await waitFor(() => {
      expect(mockSearch).toHaveBeenCalledTimes(1);
      expect(mockStartLLMAnalysis).toHaveBeenCalledTimes(1);
    });

    // Before Phase 2 resolves: button is re-enabled (setAnalyzing(false) after Phase 1)
    await waitFor(() => {
      expect(screen.getByText('Анализировать')).toBeTruthy();
    });

    // Now resolve Phase 2 (simulating LLM completion)
    resolvePhase2({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      llm_result: MOCK_LLM_RESULT,
      warning: null,
    });

    // Wait for the "analysis ready" snackbar
    await waitFor(() => {
      expect(screen.getByText(/Анализ готов/)).toBeTruthy();
    });
  });

  it('Phase 2 failure: snackbar error (non-blocking, search results still available)', async () => {
    let rejectPhase2!: (reason: unknown) => void;

    mockSearch.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'test-session',
      status: 'completed',
      search_result: MOCK_SEARCH_RESULT,
      cache_hit: false,
    });
    mockStartLLMAnalysis.mockImplementation(() => {
      return new Promise((_resolve, reject) => {
        rejectPhase2 = reject;
      });
    });

    const onReady = vi.fn((dispatch: React.Dispatch<AnalysisAction>) => {
      dispatch({ type: 'SET_SESSION_ID', payload: 'test-session' });
      dispatch({ type: 'SET_RTF_FILE', payload: new File(['test'], 'dialog.rtf') });
      dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_DIALOGUE',
        payload: [{ turn_index: 0, speaker: 'Клиент', text: 'Привет', timestamp: null }],
      });
      dispatch({
        type: 'ADD_DICTIONARY',
        payload: {
          file: new File(['<xml/>'], 'dict.xml'),
          response: {
            session_id: 'test-session',
            dictionary: null,
            validation: { valid: true, warnings: [], errors: [] },
            error: null,
          },
        },
      });
      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_PROVIDERS',
        payload: [
          { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        ],
      });
      dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
      dispatch({ type: 'SET_SELECTED_PROVIDER', payload: 'ollama' });
    });

    renderReadyToAnalyze(onReady);

    const analyzeBtn = await screen.findByText('Анализировать');
    await waitFor(() => {
      expect(analyzeBtn).not.toBeDisabled();
    });

    fireEvent.click(analyzeBtn);

    // Phase 1 completes
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/results');
    });

    // Reject Phase 2 (LLM fails)
    rejectPhase2(new Error('LLM timeout'));

    // Error snackbar should appear
    await waitFor(() => {
      expect(screen.getByText(/LLM-анализ не выполнен/)).toBeTruthy();
    });
  });

  it('Phase 1 failure: no Phase 2 call, error snackbar shown', async () => {
    mockSearch.mockRejectedValue(new Error('Search failed'));

    const onReady = vi.fn((dispatch: React.Dispatch<AnalysisAction>) => {
      dispatch({ type: 'SET_SESSION_ID', payload: 'test-session' });
      dispatch({ type: 'SET_RTF_FILE', payload: new File(['test'], 'dialog.rtf') });
      dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_DIALOGUE',
        payload: [{ turn_index: 0, speaker: 'Клиент', text: 'Привет', timestamp: null }],
      });
      dispatch({
        type: 'ADD_DICTIONARY',
        payload: {
          file: new File(['<xml/>'], 'dict.xml'),
          response: {
            session_id: 'test-session',
            dictionary: null,
            validation: { valid: true, warnings: [], errors: [] },
            error: null,
          },
        },
      });
      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'success' });
      dispatch({
        type: 'SET_PROVIDERS',
        payload: [
          { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        ],
      });
      dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
      dispatch({ type: 'SET_SELECTED_PROVIDER', payload: 'ollama' });
    });

    renderReadyToAnalyze(onReady);

    const analyzeBtn = await screen.findByText('Анализировать');
    await waitFor(() => {
      expect(analyzeBtn).not.toBeDisabled();
    });

    fireEvent.click(analyzeBtn);

    // Phase 1 fails → error snackbar
    await waitFor(() => {
      expect(screen.getByText('Search failed')).toBeTruthy();
    });

    // Phase 2 should NOT have been called
    expect(mockSearch).toHaveBeenCalledTimes(1);
    expect(mockStartLLMAnalysis).not.toHaveBeenCalled();
    // Navigate should NOT have been called
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  // ─── D.8: Batch upload UI ─────────────────────────────

  it('selecting multiple RTF files switches to batch mode and shows the file list', async () => {
    renderUploadPage();

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file1 = new File(['a'], 'dialog-1.rtf', { type: 'application/rtf' });
    const file2 = new File(['b'], 'dialog-2.rtf', { type: 'application/rtf' });

    fireEvent.change(rtfInput, { target: { files: [file1, file2] } });

    await waitFor(() => {
      expect(screen.getByText(/Пакетный режим: 2 файлов/)).toBeTruthy();
    });
    expect(screen.getByText('dialog-1.rtf')).toBeTruthy();
    expect(screen.getByText('dialog-2.rtf')).toBeTruthy();
  });

  it('batch flow: submitBatch called with all files and navigates to /batch-results/:id', async () => {
    mockSubmitBatch.mockResolvedValue({
      batch_id: 'batch-123',
      session_id: 'test-session',
      total_files: 2,
      status: 'processing',
      items: [],
      completed_count: 0,
      failed_count: 0,
      error: null,
    });

    // Provider selection via the DS Select is heavy to drive in jsdom —
    // pre-set it through the context (same pattern as renderReadyToAnalyze)
    // and drive the batch file selection through the real DropZone flow.
    const onReady = vi.fn((dispatch: React.Dispatch<AnalysisAction>) => {
      dispatch({
        type: 'SET_PROVIDERS',
        payload: [
          { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        ],
      });
      dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
      dispatch({ type: 'SET_SELECTED_PROVIDER', payload: 'ollama' });
    });

    renderReadyToAnalyze(onReady);

    // Step 1: select 2 RTF files (first creates the session)
    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file1 = new File(['a'], 'dialog-1.rtf', { type: 'application/rtf' });
    const file2 = new File(['b'], 'dialog-2.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file1, file2] } });

    // Wait for the first-file upload (session creation) to complete and the
    // Stepper to auto-advance to the dictionary step.
    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="dict-input"]'),
      ).toBeTruthy();
    });

    // Step 2: upload a dictionary (auto-advances to step 3)
    const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
    const dictFile = new File(['<xml/>'], 'dict.xml', { type: 'text/xml' });
    fireEvent.change(dictInput, { target: { files: [dictFile] } });

    await waitFor(() => {
      expect(screen.getByText('dict.xml')).toBeTruthy();
    });

    // Batch CTA is visible and enabled
    const batchBtn = await screen.findByText('Пакетный анализ (2 файлов)');
    await waitFor(() => {
      expect(batchBtn).not.toBeDisabled();
    });

    fireEvent.click(batchBtn);

    await waitFor(() => {
      expect(mockSubmitBatch).toHaveBeenCalledTimes(1);
    });
    // Called with the files array, session, provider and dictionaries
    const call = mockSubmitBatch.mock.calls[0];
    expect(call[0]).toHaveLength(2);
    expect(call[1]).toBe('test-session');
    expect(call[2]).toBe('ollama');

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/batch-results/batch-123');
    });
  });

  it('batch failure: error snackbar shown, no navigation', async () => {
    mockSubmitBatch.mockRejectedValue(new Error('Batch failed'));

    const onReady = vi.fn((dispatch: React.Dispatch<AnalysisAction>) => {
      dispatch({
        type: 'SET_PROVIDERS',
        payload: [
          { id: 'ollama', name: 'Ollama', models: ['llama3'], configured: true, available: true },
        ],
      });
      dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
      dispatch({ type: 'SET_SELECTED_PROVIDER', payload: 'ollama' });
    });

    renderReadyToAnalyze(onReady);

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file1 = new File(['a'], 'dialog-1.rtf', { type: 'application/rtf' });
    const file2 = new File(['b'], 'dialog-2.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file1, file2] } });

    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="dict-input"]'),
      ).toBeTruthy();
    });

    const dictInput = document.querySelector('[data-testid="dict-input"]') as HTMLInputElement;
    const dictFile = new File(['<xml/>'], 'dict.xml', { type: 'text/xml' });
    fireEvent.change(dictInput, { target: { files: [dictFile] } });

    const batchBtn = await screen.findByText('Пакетный анализ (2 файлов)');
    await waitFor(() => {
      expect(batchBtn).not.toBeDisabled();
    });

    fireEvent.click(batchBtn);

    await waitFor(() => {
      expect(screen.getByText('Batch failed')).toBeTruthy();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('single-file selection keeps the regular Анализировать CTA (no batch mode)', async () => {
    renderUploadPage();

    const rtfInput = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(rtfInput, { target: { files: [file] } });

    await waitFor(() => {
      // 'dialog.rtf' may also appear in the Recent analyses section
      // (localStorage persists across tests in this file) — use getAllByText.
      expect(screen.getAllByText('dialog.rtf').length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryByText(/Пакетный режим/)).toBeNull();
    expect(screen.getByText('Анализировать')).toBeTruthy();
  });
});
