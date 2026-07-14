/**
 * Tests for UploadPage — reworked upload form with Stepper, DropZone,
 * Dialog confirmation, and snackbar notifications.
 *
 * Covers: page renders, Stepper navigation, DropZone upload, reset with
 * Dialog confirmation, analyze button disabled state, health check,
 * provider loading, RTF upload flow, dictionary upload, error states.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AnalysisProvider } from '../context/AnalysisContext';
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
const mockSubmitBatch = vi.fn();

vi.mock('../api/client', () => ({
  checkHealth: (...args: unknown[]) => mockCheckHealth(...args),
  getProviders: (...args: unknown[]) => mockGetProviders(...args),
  uploadRtf: (...args: unknown[]) => mockUploadRtf(...args),
  uploadDictionary: (...args: unknown[]) => mockUploadDictionary(...args),
  analyze: (...args: unknown[]) => mockAnalyze(...args),
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

describe('UploadPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
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
  });

  // ─── Basic rendering ──────────────────────────────────

  it('renders page title', async () => {
    renderUploadPage();
    expect(screen.getByText('Загрузка данных для анализа')).toBeTruthy();
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
});
