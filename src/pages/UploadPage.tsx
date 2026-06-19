/**
 * UploadPage — main upload form for RTF dialogues, dictionaries, and LLM settings.
 *
 * Routes: /
 *
 * Supports two modes:
 *   - Single-file analysis (default): upload one RTF → analyze → /results
 *   - Batch analysis: upload multiple RTFs → batch analyze → /batch-results/:batchId
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Banner,
  Box,
  Button,
  Card,
  Divider,
  Icon,
  IconButton,
  InlineAlert,
  Select,
  Skeleton,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { useAnalysisContext } from '../context/AnalysisContext';
import * as api from '../api/client';
import * as historyStorage from '../storage/history';
import type {
  HistoryEntry,
  ProviderInfo,
  UploadDictionaryResponse,
} from '../types/api';

/** Select option shape for DS Select component */
interface SelectOption {
  value: string;
  label: string;
}

export default function UploadPage() {
  const { state, dispatch } = useAnalysisContext();
  const navigate = useNavigate();

  // --- Local UI state ---
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [rtfFileName, setRtfFileName] = useState<string | null>(null);
  const [dictFileNames, setDictFileNames] = useState<string[]>([]);
  const [providerOptions, setProviderOptions] = useState<SelectOption[]>([]);
  const [analyzing, setAnalyzing] = useState(false);

  // --- Batch mode state ---
  const [batchMode, setBatchMode] = useState(false);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);

  // --- Refs for hidden file inputs ---
  const rtfInputRef = useRef<HTMLInputElement>(null);
  const dictInputRef = useRef<HTMLInputElement>(null);
  const batchInputRef = useRef<HTMLInputElement>(null);

  // ─── Health check on mount ─────────────────────────────
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

  // ─── RTF file selection ───────────────────────────────
  const handleRtfSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setRtfFileName(file.name);
      dispatch({ type: 'SET_RTF_FILE', payload: file });
      dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'uploading' });
      dispatch({ type: 'SET_RTF_ERROR', payload: null });

      try {
        const result = await api.uploadRtf(file, state.sessionId);
        dispatch({ type: 'SET_SESSION_ID', payload: result.session_id });
        dispatch({ type: 'SET_DIALOGUE', payload: result.dialogue });
        dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'success' });

        if (result.error) {
          dispatch({ type: 'SET_RTF_ERROR', payload: result.error });
        }
      } catch (err) {
        dispatch({ type: 'SET_RTF_UPLOAD_STATUS', payload: 'error' });
        dispatch({
          type: 'SET_RTF_ERROR',
          payload: err instanceof Error ? err.message : 'Ошибка загрузки RTF',
        });
      }
    },
    [dispatch, state.sessionId],
  );

  // ─── Dictionary file selection ────────────────────────
  const handleDictSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'uploading' });
      dispatch({ type: 'SET_DICTIONARY_ERROR', payload: null });

      const newNames: string[] = [];

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        newNames.push(file.name);

        try {
          const result: UploadDictionaryResponse =
            await api.uploadDictionary(file, state.sessionId);
          // Always sync session_id from backend response
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
          dispatch({
            type: 'SET_DICTIONARY_ERROR',
            payload:
              err instanceof Error ? err.message : 'Ошибка загрузки словаря',
          });
          return;
        }
      }

      setDictFileNames((prev) => [...prev, ...newNames]);
      dispatch({ type: 'SET_DICTIONARY_UPLOAD_STATUS', payload: 'success' });
    },
    [dispatch, state.sessionId],
  );

  // ─── Remove dictionary ────────────────────────────────
  const handleRemoveDict = useCallback(
    (index: number) => {
      dispatch({ type: 'REMOVE_DICTIONARY', payload: index });
      setDictFileNames((prev) => prev.filter((_, i) => i !== index));
    },
    [dispatch],
  );

  // ─── Start analysis ───────────────────────────────────
  const handleAnalyze = useCallback(async () => {
    if (!state.sessionId || !state.selectedProvider) return;

    setAnalyzing(true);
    dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'analyzing' });
    dispatch({ type: 'SET_ANALYSIS_ERROR', payload: null });

    try {
      const result = await api.analyze({
        session_id: state.sessionId,
        llm_provider: state.selectedProvider,
        llm_model: state.selectedModel ?? undefined,
        include_summary: true,
        include_restructured: true,
      });

      dispatch({ type: 'SET_ANALYSIS_ID', payload: result.analysis_id });
      dispatch({
        type: 'SET_ANALYSIS_RESULTS',
        payload: {
          searchResult: result.search_result,
          llmResult: result.llm_result,
        },
      });

      if (result.status === 'completed' || result.status === 'partial') {
        dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'completed' });

        // Save to analysis history
        const entry: HistoryEntry = {
          id: crypto.randomUUID(),
          analysisId: result.analysis_id,
          sessionId: state.sessionId!,
          date: new Date().toISOString(),
          fileName: rtfFileName ?? state.rtfFile?.name ?? 'dialog.rtf',
          dictionaryNames: state.dictionaries
            .map((d) => d.response.dictionary?.name)
            .filter(Boolean) as string[],
          totalMatches: result.search_result?.total_matches ?? 0,
          matchesByLevel: result.search_result?.matches_by_level ?? {},
          status: result.status as 'completed' | 'partial' | 'failed',
          searchResult: result.search_result ?? undefined,
          llmResult: result.llm_result ?? undefined,
        };
        historyStorage.add(entry);

        navigate('/results');
      } else if (result.status === 'failed') {
        dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'error' });
        dispatch({
          type: 'SET_ANALYSIS_ERROR',
          payload: result.error ?? 'Анализ не удался',
        });
      }
    } catch (err) {
      dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'error' });
      dispatch({
        type: 'SET_ANALYSIS_ERROR',
        payload:
          err instanceof Error ? err.message : 'Ошибка при выполнении анализа',
      });
    } finally {
      setAnalyzing(false);
    }
  }, [state.sessionId, state.selectedProvider, state.selectedModel, rtfFileName, state.rtfFile, state.dictionaries, dispatch, navigate]);

  // ─── Reset ────────────────────────────────────────────
  const handleReset = useCallback(() => {
    dispatch({ type: 'RESET_UPLOAD' });
    setRtfFileName(null);
    setDictFileNames([]);
    setBatchFiles([]);
    setBatchError(null);
    setBatchMode(false);
  }, [dispatch]);

  // ─── Batch: select multiple RTF files ──────────────────
  const handleBatchFilesSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      const fileArray = Array.from(files);
      setBatchFiles((prev) => [...prev, ...fileArray]);
      setBatchError(null);
    },
    [],
  );

  // ─── Batch: remove single file from list ───────────────
  const handleRemoveBatchFile = useCallback((index: number) => {
    setBatchFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // ─── Batch: submit all files ───────────────────────────
  const handleBatchAnalyze = useCallback(async () => {
    if (batchFiles.length === 0 || !state.selectedProvider) return;

    setBatchSubmitting(true);
    setBatchError(null);

    try {
      const result = await api.submitBatch(
        batchFiles,
        state.sessionId ?? '',
        state.selectedProvider,
        state.selectedModel,
        true,
        true,
        state.dictionaries.map((d) => d.response.dictionary?.id).filter(Boolean) as string[],
      );

      dispatch({ type: 'SET_BATCH_ID', payload: result.batch_id });
      dispatch({ type: 'SET_SESSION_ID', payload: result.session_id });
      navigate(`/batch-results/${result.batch_id}`);
    } catch (err) {
      setBatchError(
        err instanceof Error ? err.message : 'Ошибка запуска batch-анализа',
      );
    } finally {
      setBatchSubmitting(false);
    }
  }, [batchFiles, state.selectedProvider, state.selectedModel, state.sessionId, state.dictionaries, dispatch, navigate]);

  // ─── Derived state ───────────────────────────────────
  const canAnalyze =
    state.sessionId !== null &&
    state.selectedProvider !== null &&
    state.rtfUploadStatus === 'success' &&
    state.dictionaryUploadStatus === 'success' &&
    state.dictionaries.length > 0 &&
    !analyzing;

  const canBatchAnalyze =
    batchFiles.length > 0 &&
    state.selectedProvider !== null &&
    state.dictionaries.length > 0 &&
    !batchSubmitting;

  // ─── Render ───────────────────────────────────────────
  return (
    <Stack direction="vertical" spacing="x6">
      {/* Health check banner */}
      {healthOk === false && (
        <Banner
          title="Сервер недоступен. Проверьте подключение и перезапустите приложение."
          color="error"
          iconName={Icons.Alarm}
        />
      )}

      {/* Page title */}
      <Typography variant="h3">Загрузка данных для анализа</Typography>

      {/* ── RTF Upload Card ── */}
      <Card>
        <Stack direction="vertical" spacing="x4">
          <Typography variant="h5">Диалог</Typography>

          <div
            className={`upload-area ${
              state.rtfUploadStatus === 'error'
                ? 'upload-area--error'
                : state.rtfUploadStatus === 'success'
                  ? 'upload-area--success'
                  : ''
            }`}
            onClick={() => rtfInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                rtfInputRef.current?.click();
              }
            }}
            role="button"
            tabIndex={0}
            aria-label="Загрузить RTF-файл диалога"
            aria-disabled={state.rtfUploadStatus === 'uploading'}
          >
            <input
              ref={rtfInputRef}
              type="file"
              accept=".rtf"
              style={{ display: 'none' }}
              onChange={handleRtfSelect}
              aria-hidden="true"
              data-testid="rtf-input"
            />
            <Stack direction="vertical" spacing="x2" align="center">
              <Icon iconName={Icons.CloudUpload} size="large" />
              <Typography variant="body1">
                {rtfFileName
                  ? `Загружен: ${rtfFileName}`
                  : 'Нажмите или перетащите RTF-файл'}
              </Typography>
              <Typography variant="caption" inactive>
                Формат .rtf, один файл
              </Typography>
            </Stack>
          </div>

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
      </Card>

      {/* ── Dictionary Upload Card ── */}
      <Card>
        <Stack direction="vertical" spacing="x4">
          <Typography variant="h5">Словари</Typography>

          <div
            className={`upload-area ${
              state.dictionaryUploadStatus === 'error'
                ? 'upload-area--error'
                : ''
            }`}
            onClick={() => dictInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                dictInputRef.current?.click();
              }
            }}
            role="button"
            tabIndex={0}
            aria-label="Загрузить XML-файлы словарей"
            aria-disabled={state.dictionaryUploadStatus === 'uploading'}
          >
            <input
              ref={dictInputRef}
              type="file"
              accept=".xml"
              multiple
              style={{ display: 'none' }}
              onChange={handleDictSelect}
              aria-hidden="true"
              data-testid="dict-input"
            />
            <Stack direction="vertical" spacing="x2" align="center">
              <Icon iconName={Icons.CloudUpload} size="large" />
              <Typography variant="body1">
                {dictFileNames.length > 0
                  ? `Загружено словарей: ${dictFileNames.length}`
                  : 'Нажмите или перетащите XML-файлы словарей'}
              </Typography>
              <Typography variant="caption" inactive>
                Формат .xml, можно несколько
              </Typography>
            </Stack>
          </div>

          {/* Dictionary file chips */}
          {dictFileNames.length > 0 && (
            <Box>
              {dictFileNames.map((name, idx) => (
                <span key={`${name}-${idx}`} className="file-chip">
                  <Typography variant="caption">{name}</Typography>
                  <button
                    className="file-chip__remove"
                    onClick={() => handleRemoveDict(idx)}
                    aria-label={`Удалить ${name}`}
                    type="button"
                  >
                    ×
                  </button>
                </span>
              ))}
            </Box>
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
      </Card>

      {/* ── Provider / Model Selection Card ── */}
      <Card>
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

          {state.providerStatus === 'loaded' && providerOptions.length === 0 && (
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
                      ? [providerOptions.find((o) => o.value === state.selectedProvider)!]
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
                        ? [modelOptions.find((o) => o.value === state.selectedModel)!]
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
        </Stack>
      </Card>

      {/* ── Action buttons ── */}
      <Divider />

      <Stack direction="vertical" spacing="x4">
        {/* Batch mode toggle */}
        <Stack direction="horizontal" spacing="x3" align="center">
          <Button
            variant={batchMode ? 'primary' : 'outlined'}
            size="small"
            onClick={() => {
              setBatchMode((prev) => !prev);
              setBatchFiles([]);
              setBatchError(null);
            }}
            startIcon={<Icon iconName={Icons.PagesMultiple} />}
          >
            {batchMode ? 'Один файл' : 'Batch-анализ'}
          </Button>
          <Typography variant="caption" inactive>
            {batchMode
              ? 'Загрузите несколько RTF-файлы для batch-обработки'
              : 'Нажмите для анализа нескольких файлов'}
          </Typography>
        </Stack>

        {/* Batch file upload area */}
        {batchMode && (
          <Card>
            <Stack direction="vertical" spacing="x4">
              <Typography variant="h5">Файлы для batch-анализа</Typography>

              <div
                className="upload-area"
                onClick={() => batchInputRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    batchInputRef.current?.click();
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label="Загрузить RTF-файлы для batch-анализа"
              >
                <input
                  ref={batchInputRef}
                  type="file"
                  accept=".rtf"
                  multiple
                  style={{ display: 'none' }}
                  onChange={handleBatchFilesSelect}
                  aria-hidden="true"
                  data-testid="batch-rtf-input"
                />
                <Stack direction="vertical" spacing="x2" align="center">
                  <Icon iconName={Icons.CloudUpload} size="large" />
                  <Typography variant="body1">
                    {batchFiles.length > 0
                      ? `Выбрано файлов: ${batchFiles.length}`
                      : 'Нажмите или перетащите RTF-файлы'}
                  </Typography>
                  <Typography variant="caption" inactive>
                    Максимум 10 файлов формата .rtf
                  </Typography>
                </Stack>
              </div>

              {/* Batch file list */}
              {batchFiles.length > 0 && (
                <Stack direction="vertical" spacing="x2">
                  {batchFiles.map((file, idx) => (
                    <Stack key={`${file.name}-${idx}`} direction="horizontal" spacing="x2" align="center" justify="space-between">
                      <Typography variant="body2">
                        {idx + 1}. {file.name}
                      </Typography>
                      <IconButton
                        iconName={Icons.Close}
                        variant="plain"
                        size="small"
                        aria-label={`Удалить ${file.name}`}
                        onClick={() => handleRemoveBatchFile(idx)}
                      />
                    </Stack>
                  ))}
                </Stack>
              )}

              {batchError && (
                <InlineAlert type="error">{batchError}</InlineAlert>
              )}
            </Stack>
          </Card>
        )}

        {/* Action row */}
        <Stack direction="horizontal" spacing="x4" align="center" justify="end">
          <Button variant="secondary" onClick={handleReset}>
            Сбросить
          </Button>

          {batchMode ? (
            <Button
              variant="primary"
              disabled={!canBatchAnalyze}
              onClick={handleBatchAnalyze}
              startIcon={
                batchSubmitting ? undefined : <Icon iconName={Icons.PagesMultiple} />
              }
            >
              {batchSubmitting ? 'Запуск…' : `Анализировать (${batchFiles.length})`}
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled={!canAnalyze}
              onClick={handleAnalyze}
              startIcon={
                analyzing ? undefined : <Icon iconName={Icons.Search} />
              }
            >
              {analyzing ? 'Анализируем…' : 'Анализировать'}
            </Button>
          )}
        </Stack>
      </Stack>

      {/* ── Analysis error banner ── */}
      {state.analysisError && (
        <Banner
          title={state.analysisError}
          color="error"
          iconName={Icons.Alarm}
        />
      )}
    </Stack>
  );
}
