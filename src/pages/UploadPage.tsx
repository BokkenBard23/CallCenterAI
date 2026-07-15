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

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Banner,
  Box,
  Button,
  Card,
  Dialog,
  DialogContent,
  Divider,
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
import * as api from '../api/client';
import * as historyStorage from '../storage/history';
import type {
  AnalysisResponse,
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
  // Two-phase strategy with non-blocking Phase 2:
  //   Phase 1 (search, ~1s)  → awaited. Sets search result, navigates to /results.
  //   Phase 2 (LLM summary)  → fire-and-forget. Runs in background via .then()/.catch().
  //                             User can interact with dialogue/dictionary immediately.
  //                             When done → snackbar notification + SET_LLM_RESULT.
  //
  // dispatch (from useReducer) and showSnackbar (from useCallback in SnackbarProvider)
  // are stable references, so the fire-and-forget callbacks work even if UploadPage
  // unmounts after navigate('/results') — the global AnalysisContext persists.
  const handleAnalyze = useCallback(async () => {
    if (!state.sessionId || !state.selectedProvider) return;

    // Capture values for the fire-and-forget Phase 2 closure
    const sessionId = state.sessionId;
    const selectedProvider = state.selectedProvider;
    const selectedModel = state.selectedModel;

    setAnalyzing(true);
    dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'analyzing' });
    dispatch({ type: 'SET_ANALYSIS_ERROR', payload: null });
    dispatch({ type: 'SET_LLM_LOADING', payload: false });

    // ─── Phase 1: Dictionary search (awaited — fast, needed for results) ───
    let phase1Result: AnalysisResponse;
    try {
      phase1Result = await api.analyze({
        session_id: sessionId,
        llm_provider: selectedProvider,
        llm_model: selectedModel ?? undefined,
        include_summary: false,
        include_restructured: false,
      });
    } catch (err) {
      dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'error' });
      const msg = err instanceof Error ? err.message : 'Ошибка при выполнении анализа';
      dispatch({ type: 'SET_ANALYSIS_ERROR', payload: msg });
      showSnackbar(msg, { variant: 'fixed', delay: 6000 });
      setAnalyzing(false);
      return;
    }

    const searchResult = phase1Result.search_result;

    dispatch({ type: 'SET_ANALYSIS_ID', payload: phase1Result.analysis_id });
    dispatch({ type: 'SET_SEARCH_RESULT', payload: searchResult });
    dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'completed' });

    showSnackbar('Анализ запущен. Ожидайте результатов.', {
      variant: 'elastic',
      delay: 4000,
      action: { label: 'Посмотреть', onClick: () => navigate('/results') },
    });

    navigate('/results');

    // Save history entry immediately — Phase 1 is done, LLM result pending.
    // historyStorage has no update() method, so llmResult stays undefined here.
    // This is acceptable: the entry captures the search result; LLM summary is
    // available live in the Results view via AnalysisContext.
    const entry: HistoryEntry = {
      id: crypto.randomUUID(),
      analysisId: phase1Result.analysis_id,
      sessionId,
      date: new Date().toISOString(),
      fileName: rtfFileName ?? state.rtfFile?.name ?? 'dialog.rtf',
      dictionaryNames: state.dictionaries
        .map((d) => d.response.dictionary?.name)
        .filter(Boolean) as string[],
      totalMatches: searchResult?.total_matches ?? 0,
      matchesByLevel: searchResult?.matches_by_level ?? {},
      status: 'completed' as const,
      searchResult: searchResult ?? undefined,
      llmResult: undefined,
    };
    historyStorage.add(entry);

    // Phase 1 is done — button can be re-used
    setAnalyzing(false);

    // ─── Phase 2: LLM analysis — fire-and-forget (NO await) ───
    // Runs in background. dispatch and showSnackbar are stable context references,
    // so callbacks fire correctly even after UploadPage unmounts.
    if (searchResult) {
      dispatch({ type: 'SET_LLM_LOADING', payload: true });

      api.analyze({
        session_id: sessionId,
        llm_provider: selectedProvider,
        llm_model: selectedModel ?? undefined,
        include_summary: true,
        include_restructured: true,
      })
        .then((llmResult) => {
          dispatch({ type: 'SET_LLM_RESULT', payload: llmResult.llm_result });
          dispatch({ type: 'SET_LLM_LOADING', payload: false });
          showSnackbar('Анализ готов. Сводка доступна во вкладке «Сводка»', {
            variant: 'elastic',
            delay: 6000,
          });
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
    }
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

      {/* Page title — H1 for accessibility */}
      <Typography variant="h1" style={{ margin: 0 }}>Загрузка данных для анализа</Typography>

      {/* Stepper */}
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
