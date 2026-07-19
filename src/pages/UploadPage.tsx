/**
 * UploadPage — reworked upload form with Stepper wizard, drag-and-drop,
 * ProgressButton, Dialog confirmation, and BorderBeam animation.
 *
 * Routes: /
 *
 * Stepper flow:
 *   Step 1 (rtf): Upload RTF dialogue file
 *   Step 2 (dict): Upload XML dictionary files
 *   Step 3 (analyze): Configure LLM provider and run analysis
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Banner,
  Box,
  Button,
  Card,
  Dialog,
  DialogContent,
  Divider,
  Grid,
  GridItem,
  Icon,
  IconButton,
  InlineAlert,
  Select,
  Skeleton,
  Stack,
  Stepper,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { useAnalysisContext } from '../context/AnalysisContext';
import { useSnackbar } from '../context/SnackbarContext';
import { DropZone } from '../components/DropZone';
import RouterLink from '../components/RouterLink';
import * as api from '../api/client';
import * as historyStorage from '../storage/history';
import type {
  HistoryEntry,
  ProviderInfo,
  UploadDictionaryResponse,
} from '../types/api';

// ═══════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════

const UPLOAD_STEPS = [
  { id: 'rtf', label: 'Загрузка RTF', step: 1 },
  { id: 'dict', label: 'Словарь', step: 2 },
  { id: 'analyze', label: 'Анализ', step: 3 },
];

type StepId = 'rtf' | 'dict' | 'analyze';

/** Select option shape for DS Select component */
interface SelectOption {
  value: string;
  label: string;
}

/** Format bytes to human-readable string */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

/** Format ISO date string to locale-readable form for recent section. */
function formatRecentDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

/** Dashboard feature card descriptor — 4 cards above the Stepper. */
interface DashboardCardDescriptor {
  id: 'upload' | 'speechlab' | 'dictionary' | 'history';
  title: string;
  description: string;
  iconName: Icons;
  ctaLabel: string;
  /** 'scroll' = scroll to Stepper below; 'navigate' = SPA navigate to route. */
  ctaAction:
    | { kind: 'scroll'; targetId: string }
    | { kind: 'navigate'; to: string };
}

const DASHBOARD_CARDS: readonly DashboardCardDescriptor[] = [
  {
    id: 'upload',
    title: 'Загрузка и анализ',
    description: 'Загрузите RTF-диалог и XML-словари, запустите анализ совпадений.',
    iconName: Icons.Upload,
    ctaLabel: 'Начать',
    ctaAction: { kind: 'scroll', targetId: 'quick-upload' },
  },
  {
    id: 'speechlab',
    title: 'SpeechLab',
    description: '3-панельная лаборатория: дерево словаря, токены, поиск по диалогам.',
    iconName: Icons.Mic,
    ctaLabel: 'Открыть',
    ctaAction: { kind: 'navigate', to: '/speechlab' },
  },
  {
    id: 'dictionary',
    title: 'Редактор словарей',
    description: 'Иерархическое дерево, AI-подсказки, поиск дубликатов и валидация.',
    iconName: Icons.Book,
    ctaLabel: 'Открыть',
    ctaAction: { kind: 'navigate', to: '/dictionary' },
  },
  {
    id: 'history',
    title: 'История анализов',
    description: 'Последние запуски анализа, поиск по имени файла или словарю.',
    iconName: Icons.Clock,
    ctaLabel: 'Открыть',
    ctaAction: { kind: 'navigate', to: '/history' },
  },
] as const;

/** Max number of recent analyses shown in the dashboard Recent section. */
const MAX_RECENT_ENTRIES = 5;

// ═══════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════

export default function UploadPage() {
  const { state, dispatch } = useAnalysisContext();
  const navigate = useNavigate();
  const { showSnackbar } = useSnackbar();

  // ─── Local UI state ───────────────────────────────────
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [rtfFileName, setRtfFileName] = useState<string | null>(null);
  const [rtfFileSize, setRtfFileSize] = useState<number>(0);
  const [dictFileNames, setDictFileNames] = useState<string[]>([]);
  const [providerOptions, setProviderOptions] = useState<SelectOption[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  /** Recent analyses — initialised from localStorage lazily on first
   *  render (mount). Refreshed via setRecentEntries() after each
   *  successful analysis. Shows last N entries in the dashboard hub. */
  const [recentEntries, setRecentEntries] = useState<HistoryEntry[]>(() => {
    try {
      return historyStorage.getAll().slice(0, MAX_RECENT_ENTRIES);
    } catch {
      return [];
    }
  });

  /** Ref to the Stepper Card wrapper — used by the Upload dashboard card
   *  "Начать" CTA to scroll-into-view the quick upload section. */
  const quickUploadRef = useRef<HTMLDivElement | null>(null);

  // ─── Stepper state ─────────────────────────────────────
  const [activeStep, setActiveStep] = useState<StepId>('rtf');

  // ─── Health check on mount ────────────────────────────
  useEffect(() => {
    const controller = new AbortController();
    api.checkHealth(controller.signal)
      .then(() => setHealthOk(true))
      .catch(() => setHealthOk(false));
    return () => controller.abort();
  }, []);

  // ─── Load providers on mount ──────────────────────────
  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loading' });

    api.getProviders(controller.signal)
      .then((data) => {
        dispatch({ type: 'SET_PROVIDERS', payload: data.providers });
        dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'loaded' });
        setProviderOptions(
          data.providers
            .filter((p: ProviderInfo) => p.configured && p.available)
            .map((p: ProviderInfo) => ({ value: p.id, label: p.name })),
        );
      })
      .catch(() => {
        dispatch({ type: 'SET_PROVIDER_STATUS', payload: 'error' });
      });

    return () => controller.abort();
  }, [dispatch]);

  // ─── Auto-advance stepper ──────────────────────────────
  // setActiveStep synchronizes the stepper with upload status changes.
  // This is a "react to external system" pattern — the external system
  // is the upload state machine, and we update the stepper to match.
  useEffect(() => {
    if (state.rtfUploadStatus === 'success' && activeStep === 'rtf') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Intentional: auto-advance stepper when RTF upload succeeds
      setActiveStep('dict');
    }
  }, [state.rtfUploadStatus, activeStep]);

  useEffect(() => {
    if (
      state.dictionaryUploadStatus === 'success' &&
      state.dictionaries.length > 0 &&
      activeStep === 'dict'
    ) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Intentional: auto-advance stepper when dictionary upload succeeds
      setActiveStep('analyze');
    }
  }, [state.dictionaryUploadStatus, state.dictionaries.length, activeStep]);

  // ─── Derive model options from selected provider ───────
  const modelOptions = useMemo(() => {
    const provider = state.providers.find(
      (p: ProviderInfo) => p.id === state.selectedProvider,
    );
    if (provider) {
      return provider.models.map((m: string) => ({ value: m, label: m }));
    }
    return [];
  }, [state.selectedProvider, state.providers]);

  // ─── RTF file selection (via DropZone) ─────────────────
  const handleRtfFilesSelected = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;

      setRtfFileName(file.name);
      setRtfFileSize(file.size);
      dispatch({ type: 'SET_RTF_FILE', payload: file });
      dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'uploading' });
      dispatch({ type: 'SET_RTF_ERROR', payload: null });

      try {
        const result = await api.uploadRtf(file, state.sessionId);
        dispatch({ type: 'SET_SESSION_ID', payload: result.session_id });
        dispatch({ type: 'SET_DIALOGUE', payload: result.dialogue });
        dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'success' });
        showSnackbar('Файл RTF загружен', { variant: 'elastic', delay: 4000 });

        if (result.error) {
          dispatch({ type: 'SET_RTF_ERROR', payload: result.error });
        }
      } catch (err) {
        dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'error' });
        const msg = err instanceof Error ? err.message : 'Ошибка загрузки RTF';
        dispatch({ type: 'SET_RTF_ERROR', payload: msg });
        showSnackbar(msg, { variant: 'fixed', delay: 6000 });
      }
    },
    [dispatch, state.sessionId, showSnackbar],
  );

  // ─── Dictionary file selection ────────────────────────
  const handleDictFilesSelected = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'uploading' });
      dispatch({ type: 'SET_DICTIONARY_ERROR', payload: null });

      const newNames: string[] = [];

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        newNames.push(file.name);

        try {
          const result: UploadDictionaryResponse =
            await api.uploadDictionary(file, state.sessionId);
          if (result.session_id) {
            dispatch({ type: 'SET_SESSION_ID', payload: result.session_id });
          }
          dispatch({
            type: 'ADD_DICTIONARY',
            payload: { file, response: result },
          });

          if (result.validation.errors.length > 0) {
            dispatch({
              type: 'SET_DICTIONARY_ERROR',
              payload: result.validation.errors.join('; '),
            });
          }
        } catch (err) {
          dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'error' });
          const msg = err instanceof Error ? err.message : 'Ошибка загрузки словаря';
          dispatch({ type: 'SET_DICTIONARY_ERROR', payload: msg });
          showSnackbar(msg, { variant: 'fixed', delay: 6000 });
          return;
        }
      }

      setDictFileNames((prev) => [...prev, ...newNames]);
      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'success' });
      showSnackbar('Словарь загружен', { variant: 'elastic', delay: 4000 });
    },
    [dispatch, state.sessionId, showSnackbar],
  );

  // ─── Remove dictionary ────────────────────────────────
  const handleRemoveDict = useCallback(
    (index: number) => {
      dispatch({ type: 'REMOVE_DICTIONARY', payload: index });
      setDictFileNames((prev) => prev.filter((_, i) => i !== index));
    },
    [dispatch],
  );

  // ─── Remove RTF file ──────────────────────────────────
  const handleRemoveRtf = useCallback(() => {
    setRtfFileName(null);
    setRtfFileSize(0);
    dispatch({ type: 'SET_RTF_FILE', payload: null });
    dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'idle' });
    dispatch({ type: 'SET_RTF_ERROR', payload: null });
    dispatch({ type: 'SET_DIALOGUE', payload: null });
    setActiveStep('rtf');
  }, [dispatch]);

  // ─── Start analysis ───────────────────────────────────
  //
  // P2 — Two-phase strategy with the SAME analysis_id for both phases:
  //   Phase 1 (search, ~1s)   → POST /api/analysis/search. Returns analysis_id
  //                             + search_result. Cached server-side: repeated
  //                             clicks do NOT re-run run_hierarchical_search().
  //   Phase 2 (LLM summary)   → POST /api/analysis/llm with the same analysis_id.
  //                             The LLM result is ATTACHED to the existing
  //                             analysis record (the analysis_id does NOT change).
  //                             This means GET /api/analysis/results/{id} returns
  //                             BOTH search_result and llm_result — fixing the
  //                             bug where re-opening from History lost the LLM
  //                             summary.
  //
  // Phase 2 is still fire-and-forget (no polling): the user navigates to /results
  // immediately after Phase 1, and the LLM summary appears via a snackbar +
  // SET_LLM_RESULT dispatch when it completes (10-30 sec later). The history
  // entry now stores the SAME analysis_id that the LLM was attached to, so
  // opening from History shows the LLM summary instantly.
  const handleAnalyze = useCallback(async () => {
    if (!state.sessionId || !state.selectedProvider) return;

    const sessionId = state.sessionId;
    const selectedProvider = state.selectedProvider;
    const selectedModel = state.selectedModel;

    setAnalyzing(true);
    dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'analyzing' });
    dispatch({ type: 'SET_ANALYSIS_ERROR', payload: null });
    dispatch({ type: 'SET_LLM_LOADING', payload: false });

    // ─── Phase 1: Dictionary search (awaited — fast, needed for results) ───
    let phase1: import('../types/api').SearchResult | null;
    let analysisId: string;
    let cacheHit = false;
    try {
      const searchResp = await api.search({
        session_id: sessionId,
        dictionary_ids: state.dictionaries
          .map((d) => d.response.dictionary?.name)
          .filter(Boolean) as string[],
      });
      analysisId = searchResp.analysis_id;
      phase1 = searchResp.search_result;
      cacheHit = searchResp.cache_hit;
    } catch (err) {
      dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'error' });
      const msg = err instanceof Error ? err.message : 'Ошибка при выполнении поиска';
      dispatch({ type: 'SET_ANALYSIS_ERROR', payload: msg });
      showSnackbar(msg, { variant: 'fixed', delay: 6000 });
      setAnalyzing(false);
      return;
    }

    dispatch({ type: 'SET_ANALYSIS_ID', payload: analysisId });
    dispatch({ type: 'SET_SEARCH_RESULT', payload: phase1 });
    dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'completed' });

    showSnackbar(
      cacheHit ? 'Поиск взят из кэша. Анализ запущен.' : 'Анализ запущен. Ожидайте результатов.',
      {
        variant: 'elastic',
        delay: 4000,
        action: { label: 'Посмотреть', onClick: () => navigate('/results') },
      },
    );

    navigate('/results');

    // Save history entry with the analysis_id that BOTH phases share.
    // The LLM result will be attached to this same id by Phase 2 below,
    // so opening from History loads an analysis that already has llm_result.
    const entry: HistoryEntry = {
      id: crypto.randomUUID(),
      analysisId,
      sessionId,
      date: new Date().toISOString(),
      fileName: rtfFileName ?? state.rtfFile?.name ?? 'dialog.rtf',
      dictionaryNames: state.dictionaries
        .map((d) => d.response.dictionary?.name)
        .filter(Boolean) as string[],
      totalMatches: phase1?.total_matches ?? 0,
      matchesByLevel: phase1?.matches_by_level ?? {},
      status: 'completed' as const,
      searchResult: phase1 ?? undefined,
      llmResult: undefined,
    };
    historyStorage.add(entry);
    try {
      setRecentEntries(historyStorage.getAll().slice(0, MAX_RECENT_ENTRIES));
    } catch {
      // ignore — recent section is non-critical
    }

    setAnalyzing(false);

    // ─── Phase 2: LLM analysis — fire-and-forget (NO await) ───
    // Attaches llm_result to the SAME analysis_id. dispatch and showSnackbar
    // are stable context references, so callbacks fire correctly even after
    // UploadPage unmounts.
    dispatch({ type: 'SET_LLM_LOADING', payload: true });

    api.startLLMAnalysis({
      analysis_id: analysisId,
      llm_provider: selectedProvider,
      llm_model: selectedModel ?? undefined,
      include_summary: true,
      include_restructured: true,
    })
      .then((llmResp) => {
        dispatch({ type: 'SET_LLM_RESULT', payload: llmResp.llm_result });
        dispatch({ type: 'SET_LLM_LOADING', payload: false });
        if (llmResp.warning) {
          showSnackbar('LLM-анализ неполный: ' + llmResp.warning, {
            variant: 'fixed',
            delay: 6000,
          });
        } else {
          showSnackbar('Анализ готов. Сводка доступна во вкладке «Сводка»', {
            variant: 'elastic',
            delay: 6000,
          });
        }
      })
      .catch((llmErr: unknown) => {
        console.warn('LLM analysis failed:', llmErr);
        dispatch({ type: 'SET_LLM_RESULT', payload: null });
        dispatch({ type: 'SET_LLM_LOADING', payload: false });
        const errMsg = llmErr instanceof Error ? llmErr.message : 'Неизвестная ошибка';
        showSnackbar('LLM-анализ не выполнен: ' + errMsg, {
          variant: 'fixed',
          delay: 6000,
        });
      });
  }, [
    state.sessionId, state.selectedProvider, state.selectedModel, rtfFileName,
    state.rtfFile, state.dictionaries, dispatch, navigate, showSnackbar,
  ]);

  // ─── Reset with confirmation ──────────────────────────
  const handleResetClick = useCallback(() => {
    setShowResetConfirm(true);
  }, []);

  const handleResetConfirm = useCallback(() => {
    dispatch({ type: 'RESET_UPLOAD' });
    setRtfFileName(null);
    setRtfFileSize(0);
    setDictFileNames([]);
    setActiveStep('rtf');
    setShowResetConfirm(false);
    showSnackbar('Данные сброшены', { variant: 'elastic', delay: 4000 });
  }, [dispatch, showSnackbar]);

  const handleResetCancel = useCallback(() => {
    setShowResetConfirm(false);
  }, []);

  // ─── Step change ──────────────────────────────────────
  const handleStepChange = useCallback(
    (id: string) => {
      const stepId = id as StepId;
      // Allow going back to previous steps freely
      // Forward navigation is controlled by upload completion
      if (stepId === 'rtf') {
        setActiveStep(stepId);
      } else if (stepId === 'dict') {
        // Can go to dict only if rtf is uploaded
        if (state.rtfUploadStatus === 'success') {
          setActiveStep(stepId);
        }
      } else if (stepId === 'analyze') {
        // Can go to analyze only if rtf + dict are done
        if (
          state.rtfUploadStatus === 'success' &&
          state.dictionaries.length > 0
        ) {
          setActiveStep(stepId);
        }
      }
    },
    [state.rtfUploadStatus, state.dictionaries.length],
  );

  /** Scroll the Stepper Card into view — used by the "Upload" dashboard
   *  card CTA. Pure DOM API; no layout reflow concerns since the target
   *  is already rendered in the same page. */
  const handleScrollToQuickUpload = useCallback(() => {
    quickUploadRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
    // Move keyboard focus to the Stepper for accessibility.
    quickUploadRef.current?.focus({ preventScroll: true });
  }, []);

  /** Click handler for dashboard cards — dispatches by CTA action kind. */
  const handleCardCta = useCallback(
    (card: DashboardCardDescriptor) => {
      if (card.ctaAction.kind === 'scroll') {
        handleScrollToQuickUpload();
      } else {
        navigate(card.ctaAction.to);
      }
    },
    [handleScrollToQuickUpload, navigate],
  );

  // ─── Derived state ───────────────────────────────────
  const canAnalyze =
    state.sessionId !== null &&
    state.selectedProvider !== null &&
    state.rtfUploadStatus === 'success' &&
    state.dictionaryUploadStatus === 'success' &&
    state.dictionaries.length > 0 &&
    !analyzing;

  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;

  // ─── Render ───────────────────────────────────────────
  return (
    <Stack direction="vertical" spacing="x6" aria-label="Загрузка данных для анализа">
      {/* Health check banner */}
      {healthOk === false && (
        <Banner
          title="Сервер недоступен. Проверьте подключение и перезапустите приложение."
          color="error"
          iconName={Icons.Alarm}
        />
      )}

      {/* ─── Dashboard: Welcome ─── */}
      <Stack direction="vertical" spacing="x2">
        <Typography variant="h1" style={{ margin: 0 }}>
          Анализ диалогов
        </Typography>
        <Typography variant="body1" inactive>
          Загружайте RTF-диалоги, сопоставляйте их со словарями фраз, исследуйте
          результаты и переиспользуйте словари между сессиями. Все разделы
          доступны из панели навигации сверху или из карточек ниже.
        </Typography>
      </Stack>

      {/* ─── Dashboard: Feature cards grid (4 cards) ─── */}
      <Grid columns={4} gap="x4" align="stretch">
        {DASHBOARD_CARDS.map((card) => (
          <GridItem key={card.id} colSpan={1}>
            <Card>
              <Stack direction="vertical" spacing="x3" align="start">
                <Stack direction="horizontal" spacing="x2" align="center">
                  <Icon iconName={card.iconName} size="medium" />
                  <Typography variant="h6">{card.title}</Typography>
                </Stack>
                <Typography variant="body2" inactive>
                  {card.description}
                </Typography>
                {card.ctaAction.kind === 'navigate' ? (
                  <RouterLink to={card.ctaAction.to}>
                    {card.ctaLabel}
                  </RouterLink>
                ) : (
                  <Button
                    variant="secondary"
                    size="small"
                    onClick={() => handleCardCta(card)}
                  >
                    {card.ctaLabel}
                  </Button>
                )}
              </Stack>
            </Card>
          </GridItem>
        ))}
      </Grid>

      {/* ─── Dashboard: Quick Upload (existing Stepper, wrapped in Card) ─── */}
      <Card>
        <Stack direction="vertical" spacing="x4">
          {/* Anchor for the "Начать" CTA scroll target. tabIndex={-1} so
              focus moves programmatically without entering the tab order. */}
          <Stack
            direction="horizontal"
            spacing="x2"
            align="center"
            justify="space-between"
          >
            <Stack direction="horizontal" spacing="x2" align="center">
              <Icon iconName={Icons.Upload} />
              <Typography variant="h5">Быстрая загрузка</Typography>
            </Stack>
          </Stack>

          {/* Stepper wizard — pre-existing logic preserved as-is */}
          <div
            id="quick-upload"
            ref={quickUploadRef}
            tabIndex={-1}
            role="group"
            aria-label="Мастер быстрой загрузки"
            style={{ outline: 'none' }}
          >
            <Stack direction="vertical" spacing="x4">
              <Stepper
                steps={UPLOAD_STEPS}
                activeStepId={activeStep}
                onStepChange={handleStepChange}
                direction="horizontal"
                mobile={isMobile}
              />

      {/* ── Step Content ── */}
      <Card>
        <Stack direction="vertical" spacing="x6">
          {/* Step 1: RTF Upload */}
          {activeStep === 'rtf' && (
            <Stack direction="vertical" spacing="x4">
              <Typography variant="h5">Диалог</Typography>

              {rtfFileName ? (
                // File preview card
                <Card>
                  <Stack
                    direction="horizontal"
                    spacing="x2"
                    align="center"
                    justify="space-between"
                  >
                    <Stack direction="horizontal" spacing="x2" align="center">
                      <Icon iconName={Icons.Attachment} size="small" />
                      <Typography variant="body2">{rtfFileName}</Typography>
                      <Typography variant="caption" inactive>
                        {formatFileSize(rtfFileSize)}
                      </Typography>
                    </Stack>
                    <IconButton
                      iconName={Icons.Close}
                      variant="plain"
                      size="small"
                      aria-label={`Удалить ${rtfFileName}`}
                      onClick={handleRemoveRtf}
                    />
                  </Stack>
                </Card>
              ) : (
                <DropZone
                  accept=".rtf"
                  onFilesSelected={handleRtfFilesSelected}
                  idleLabel="Нажмите или перетащите RTF-файл"
                  idleSubLabel="Формат .rtf, один файл"
                  dragLabel="Отпустите файл для загрузки"
                  ariaLabel="Загрузить RTF-файл диалога"
                  disabled={state.rtfUploadStatus === 'uploading'}
                  inputTestId="rtf-input"
                />
              )}

              {state.rtfUploadStatus === 'uploading' && (
                <Skeleton variant="text" width="60%" height={20} />
              )}

              {state.rtfError && (
                <InlineAlert type="error">{state.rtfError}</InlineAlert>
              )}

              {state.dialogue && (
                <Typography variant="caption" inactive>
                  Загружено реплик: {state.dialogue.length}
                </Typography>
              )}
            </Stack>
          )}

          {/* Step 2: Dictionary Upload */}
          {activeStep === 'dict' && (
            <Stack direction="vertical" spacing="x4">
              <Typography variant="h5">Словари</Typography>

              <DropZone
                accept=".xml"
                multiple
                onFilesSelected={handleDictFilesSelected}
                idleLabel="Нажмите или перетащите XML-файлы словарей"
                idleSubLabel="Формат .xml, можно несколько"
                dragLabel="Отпустите файл для загрузки"
                ariaLabel="Загрузить XML-файлы словарей"
                disabled={state.dictionaryUploadStatus === 'uploading'}
                inputTestId="dict-input"
              />

              {/* Dictionary file preview cards */}
              {dictFileNames.length > 0 && (
                <Stack direction="vertical" spacing="x2">
                  {dictFileNames.map((name, idx) => (
                    <Card key={`${name}-${idx}`}>
                      <Stack
                        direction="horizontal"
                        spacing="x2"
                        align="center"
                        justify="space-between"
                      >
                        <Stack direction="horizontal" spacing="x2" align="center">
                          <Icon iconName={Icons.Attachment} size="small" />
                          <Typography variant="body2">{name}</Typography>
                        </Stack>
                        <IconButton
                          iconName={Icons.Close}
                          variant="plain"
                          size="small"
                          aria-label={`Удалить ${name}`}
                          onClick={() => handleRemoveDict(idx)}
                        />
                      </Stack>
                    </Card>
                  ))}
                </Stack>
              )}

              {state.dictionaryError && (
                <InlineAlert type="error">{state.dictionaryError}</InlineAlert>
              )}

              {/* Validation warnings */}
              {state.dictionaries.some(
                (d) => d.response.validation.warnings.length > 0,
              ) && (
                <InlineAlert type="warning">
                  {state.dictionaries
                    .flatMap((d) => d.response.validation.warnings)
                    .join('; ')}
                </InlineAlert>
              )}
            </Stack>
          )}

          {/* Step 3: Configure & Analyze */}
          {activeStep === 'analyze' && (
            <Stack direction="vertical" spacing="x4">
              <Typography variant="h5">LLM-провайдер</Typography>

              {state.providerStatus === 'loading' && (
                <Skeleton variant="text" width="100%" height={44} />
              )}

              {state.providerStatus === 'error' && (
                <InlineAlert type="error">
                  Не удалось загрузить список провайдеров
                </InlineAlert>
              )}

              {state.providerStatus === 'loaded' &&
                providerOptions.length === 0 && (
                  <InlineAlert type="warning">
                    Нет доступных провайдеров. Проверьте конфигурацию.
                  </InlineAlert>
                )}

              {providerOptions.length > 0 && (
                <Stack direction="vertical" spacing="x3">
                  <Box>
                    <Typography variant="caption" inactive>
                      Провайдер
                    </Typography>
                    <Select
                      options={providerOptions}
                      values={
                        state.selectedProvider
                          ? [
                              providerOptions.find(
                                (o) => o.value === state.selectedProvider,
                              )!,
                            ]
                          : []
                      }
                      onChange={(vals: SelectOption[]) => {
                        dispatch({
                          type: 'SET_SELECTED_PROVIDER',
                          payload: vals[0]?.value ?? null,
                        });
                      }}
                      filter
                      filterPlaceholder="Поиск провайдера..."
                      dataTestId="provider-select"
                    />
                  </Box>

                  {modelOptions.length > 0 && (
                    <Box>
                      <Typography variant="caption" inactive>
                        Модель
                      </Typography>
                      <Select
                        options={modelOptions}
                        values={
                          state.selectedModel
                            ? [
                                modelOptions.find(
                                  (o) => o.value === state.selectedModel,
                                )!,
                              ]
                            : []
                        }
                        onChange={(vals: SelectOption[]) => {
                          dispatch({
                            type: 'SET_SELECTED_MODEL',
                            payload: vals[0]?.value ?? null,
                          });
                        }}
                        filter
                        filterPlaceholder="Поиск модели..."
                        dataTestId="model-select"
                      />
                    </Box>
                  )}
                </Stack>
              )}

              {/* Analysis progress */}
              {analyzing && (
                <Stack direction="vertical" spacing="x3" align="center">
                  <Icon
                    iconName={Icons.AiAssistant}
                    size="large"
                    style={{ color: 'var(--color-background-brand)' }}
                  />
                  <Typography variant="body2" inactive>
                    Анализируем...
                  </Typography>
                </Stack>
              )}
            </Stack>
          )}
        </Stack>
      </Card>

            {/* close the new inner Stack around Stepper + Card */}
            </Stack>
          {/* close #quick-upload div */}
          </div>
        {/* close outer Card body Stack */}
        </Stack>
      {/* close outer "Быстрая загрузка" Card */}
      </Card>

      {/* ─── Dashboard: Recent analyses ─── */}
      <Stack direction="vertical" spacing="x3">
        <Typography variant="h5">Последние анализы</Typography>
        {recentEntries.length === 0 ? (
          <Card>
            <Stack direction="vertical" spacing="x3" align="center">
              <Icon iconName={Icons.Clock} size="large" />
              <Typography variant="body2" inactive>
                Нет сохранённых анализов. Запустите первый анализ, чтобы он
                появился в истории.
              </Typography>
              <Button
                variant="secondary"
                size="small"
                onClick={handleScrollToQuickUpload}
              >
                Начать анализ
              </Button>
            </Stack>
          </Card>
        ) : (
          <Stack direction="vertical" spacing="x2">
            {recentEntries.map((entry) => (
              <Card key={entry.id}>
                <Stack
                  direction="horizontal"
                  spacing="x3"
                  align="center"
                  justify="space-between"
                >
                  <Stack direction="vertical" spacing="x1" align="start">
                    <Stack direction="horizontal" spacing="x2" align="center">
                      <Icon iconName={Icons.Attachment} size="small" />
                      <Typography variant="body2">
                        {entry.fileName}
                      </Typography>
                    </Stack>
                    <Stack direction="horizontal" spacing="x2" align="center">
                      <Typography variant="caption" inactive>
                        {formatRecentDate(entry.date)}
                      </Typography>
                      <Typography variant="caption" inactive>
                        · {entry.totalMatches} совпадений
                      </Typography>
                      {entry.dictionaryNames.length > 0 && (
                        <Typography variant="caption" inactive>
                          · {entry.dictionaryNames.join(', ')}
                        </Typography>
                      )}
                    </Stack>
                  </Stack>
                  <RouterLink to="/history">Открыть</RouterLink>
                </Stack>
              </Card>
            ))}
            {/* Link to full history page */}
            <RouterLink to="/history">Вся история →</RouterLink>
          </Stack>
        )}
      </Stack>

      {/* ── Action buttons ── */}
      <Divider />

      <Stack direction="horizontal" spacing="x4" align="center" justify="end">
        {/* M9 FIX (vision-audit): disable "Сбросить" when there is nothing to
            reset — previously it stayed active in the empty initial state,
            contradicting the empty-state logic. */}
        <Button
          variant="secondary"
          onClick={handleResetClick}
          disabled={
            !rtfFileName &&
            dictFileNames.length === 0 &&
            state.rtfUploadStatus !== 'success' &&
            state.dictionaryUploadStatus !== 'success'
          }
        >
          Сбросить
        </Button>
        {/* H10 FIX (vision-audit): when there is nothing to analyze yet
            (no RTF + no dictionary + no provider), render the primary CTA
            as a secondary variant so the disabled state reads unambiguously
            as inactive. The vision audit flagged that DS Button
            variant="primary" disabled still looked "active" on a dark theme.
            Once canAnalyze becomes true, the button switches to primary. */}
        <Button
          variant={canAnalyze ? 'primary' : 'secondary'}
          disabled={!canAnalyze}
          onClick={handleAnalyze}
          startIcon={
            analyzing ? undefined : <Icon iconName={Icons.Search} />
          }
          title={
            canAnalyze
              ? undefined
              : 'Загрузите RTF-файл, XML-словарь и выберите провайдера, чтобы запустить анализ'
          }
        >
          {analyzing ? 'Анализируем…' : 'Анализировать'}
        </Button>
      </Stack>

      {/* ── Analysis error banner ── */}
      {state.analysisError && (
        <Banner
          title={state.analysisError}
          color="error"
          iconName={Icons.Alarm}
        />
      )}

      {/* ── Reset Confirmation Dialog ── */}
      <Dialog
        open={showResetConfirm}
        onClose={handleResetCancel}
      >
        <DialogContent>
          <Typography variant="h6" style={{ marginBottom: 'var(--sizeSpacingX2, 8px)' }}>
            Сбросить анализ?
          </Typography>
          <Typography variant="body2">
            Все загруженные данные и результаты будут потеряны. Продолжить?
          </Typography>
          <Stack
            direction="horizontal"
            spacing="x2"
            justify="end"
            style={{ marginTop: 'var(--sizeSpacingX4, 16px)' }}
          >
            <Button variant="plain" onClick={handleResetCancel}>
              Отмена
            </Button>
            <Button variant="primary" onClick={handleResetConfirm}>
              Сбросить
            </Button>
          </Stack>
        </DialogContent>
      </Dialog>
    </Stack>
  );
}
