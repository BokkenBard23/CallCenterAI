/**
 * BatchResultsPage — displays batch analysis progress and summary table.
 *
 * Route: /batch-results/:batchId
 *
 * Features:
 *   - AnimatedCircularProgressBar hero element for overall progress
 *   - NumberTicker for animated percentage display
 *   - Auto-polling batch status every 2 seconds until complete
 *   - DS Table with Badge statuses and clickable completed rows
 *   - AnimatedList for sequential file appearance
 *   - ProgressButton for retry action
 *   - Snackbar notification on batch completion
 *   - BlurFade for section entrance animation
 *   - Empty state for zero items
 *   - TablePagination for >20 files
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Banner,
  Button,
  Card,
  Icon,
  IconButton,
  InlineAlert,
  Progress,
  ProgressButton,
  Stack,
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeaderData,
  TablePagination,
  TableRow,
  Tooltip,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { useAnalysisContext } from '../context/AnalysisContext';
import { useSnackbar } from '../context/SnackbarContext';
import * as api from '../api/client';
import * as historyStorage from '../storage/history';
import type { BatchAnalysisResponse, BatchItemStatus, HistoryEntry } from '../types/api';

import { AnimatedCircularProgressBar } from '../components/ui/animated-circular-progress-bar';
import { NumberTicker } from '../components/ui/number-ticker';
import { BlurFade } from '../components/ui/blur-fade';
import { AnimatedList, AnimatedListItem } from '../components/ui/animated-list';
import { StatusBadge } from '../components/StatusBadge/StatusBadge';

/** Polling interval in ms */
const POLL_INTERVAL = 2000;

/** Items per page in table */
const ITEMS_PER_PAGE = 20;

// ═══════════════════════════════════════════════════════════
// StatusBadge helper for failed items with tooltip
// ═══════════════════════════════════════════════════════════

function FailedStatusBadge({ error }: { error: string | null }) {
  const badge = (
    <StatusBadge status="failed" />
  );

  if (error) {
    return (
      <Tooltip title={error}>
        {badge}
      </Tooltip>
    );
  }

  return badge;
}

// ═══════════════════════════════════════════════════════════
// Get status badge with tooltip for failed
// ═══════════════════════════════════════════════════════════

function getItemStatusBadge(status: string, error: string | null) {
  switch (status) {
    case 'completed':
      return <StatusBadge status="completed" />;
    case 'processing':
      return <StatusBadge status="processing" />;
    case 'failed':
      return <FailedStatusBadge error={error} />;
    case 'pending':
    default:
      return <StatusBadge status="pending" />;
  }
}

// ═══════════════════════════════════════════════════════════
// Main component
// ═══════════════════════════════════════════════════════════

export default function BatchResultsPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();
  const { state, dispatch } = useAnalysisContext();
  const { showSnackbar } = useSnackbar();

  const [batchData, setBatchData] = useState<BatchAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(0);
  const [retryState, setRetryState] = useState<'default' | 'loading' | 'success' | 'error'>('default');
  const [retryError, setRetryError] = useState<string | null>(null);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const prevStatusRef = useRef<string | null>(null);

  // ─── Save completed items to history ─────────────────────
  const saveCompletedToHistory = useCallback(
    (data: BatchAnalysisResponse) => {
      data.items.forEach((item: BatchItemStatus) => {
        if (item.status === 'completed' && item.analysis_id) {
          const entry: HistoryEntry = {
            id: crypto.randomUUID(),
            analysisId: item.analysis_id,
            sessionId: data.session_id,
            date: new Date().toISOString(),
            fileName: item.filename,
            dictionaryNames: state.dictionaries.map((d) => d.response.dictionary?.name).filter(Boolean) as string[],
            totalMatches: item.total_matches,
            matchesByLevel: item.matches_by_level,
            status: 'completed',
          };
          historyStorage.add(entry);
        }
      });
    },
    [state.dictionaries],
  );

  // ─── Navigate to first completed item ────────────────────
  const navigateToFirstCompleted = useCallback(
    async (data: BatchAnalysisResponse) => {
      const firstCompleted = data.items.find(
        (item: BatchItemStatus) => item.status === 'completed' && item.analysis_id,
      );
      if (!firstCompleted?.analysis_id || !batchId) return;

      try {
        const result = await api.getResults(firstCompleted.analysis_id);
        dispatch({ type: 'SET_ANALYSIS_ID', payload: result.analysis_id });
        dispatch({ type: 'SET_SESSION_ID', payload: result.session_id });
        dispatch({
          type: 'SET_ANALYSIS_RESULTS',
          payload: {
            searchResult: result.search_result,
            llmResult: result.llm_result,
          },
        });
        dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'completed' });
        navigate('/results');
      } catch {
        // Silently fail — user can still click the row manually
      }
    },
    [batchId, dispatch, navigate],
  );

  // ─── Show snackbar on batch completion ──────────────────
  const showCompletionSnackbar = useCallback(
    (data: BatchAnalysisResponse) => {
      if (data.status === 'completed') {
        showSnackbar(
          `Анализ завершён: ${data.completed_count} из ${data.total_files} файлов обработано`,
          {
            action: {
              label: 'Посмотреть',
              onClick: () => navigateToFirstCompleted(data),
            },
          },
        );
      } else if (data.status === 'partial') {
        showSnackbar('Часть файлов обработана с ошибкой', {
          action: {
            label: 'Посмотреть',
            onClick: () => navigateToFirstCompleted(data),
          },
        });
      } else if (data.status === 'failed') {
        showSnackbar('Batch-анализ не удался', { variant: 'fixed', delay: 6000 });
      }
    },
    [showSnackbar, navigateToFirstCompleted],
  );

  // ─── Fetch batch status ─────────────────────────────────
  const fetchStatus = useCallback(async () => {
    if (!batchId) return;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const data = await api.getBatchStatus(batchId, controller.signal);
      setBatchData(data);
      dispatch({ type: 'SET_BATCH_STATUS', payload: data });
      setIsLoading(false);

      // Stop polling when batch is done
      if (['completed', 'partial', 'failed'].includes(data.status)) {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }

        // Save completed items to history
        if (data.status === 'completed' || data.status === 'partial') {
          saveCompletedToHistory(data);
        }

        // Show snackbar on status CHANGE only (prevent repeated snackbar)
        if (prevStatusRef.current !== data.status) {
          prevStatusRef.current = data.status;
          showCompletionSnackbar(data);
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError(err instanceof Error ? err.message : 'Ошибка получения статуса batch');
      setIsLoading(false);
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    }
  }, [batchId, dispatch, saveCompletedToHistory, showCompletionSnackbar]);

  // ─── Start polling on mount ─────────────────────────────
  useEffect(() => {
    let active = true;

    const load = async () => {
      if (!batchId || !active) return;
      await fetchStatus();
    };
    load();

    pollingRef.current = setInterval(fetchStatus, POLL_INTERVAL);

    return () => {
      active = false;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [batchId, fetchStatus]);

  // ─── Navigate to ResultsPage for a specific file ────────
  const handleRowClick = useCallback(
    async (item: BatchItemStatus) => {
      if (item.status !== 'completed' || !item.analysis_id || !batchId) return;

      try {
        const result = await api.getResults(item.analysis_id);

        dispatch({ type: 'SET_ANALYSIS_ID', payload: result.analysis_id });
        dispatch({ type: 'SET_SESSION_ID', payload: result.session_id });
        dispatch({
          type: 'SET_ANALYSIS_RESULTS',
          payload: {
            searchResult: result.search_result,
            llmResult: result.llm_result,
          },
        });
        dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'completed' });

        navigate('/results');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Ошибка загрузки результатов');
      }
    },
    [batchId, dispatch, navigate],
  );

  // ─── Back to upload ─────────────────────────────────────
  const handleBack = useCallback(() => {
    navigate('/');
  }, [navigate]);

  // ─── Retry ──────────────────────────────────────────────
  const handleRetry = useCallback(async () => {
    setRetryState('loading');
    setRetryError(null);
    try {
      // Navigate back to upload page for re-submission
      navigate('/');
      setRetryState('success');
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : 'Ошибка');
      setRetryState('error');
    }
  }, [navigate]);

  // ─── Derived state ──────────────────────────────────────
  const progressPercent = useMemo(() => {
    if (!batchData || batchData.total_files === 0) return 0;
    return Math.round(
      ((batchData.completed_count + batchData.failed_count) / batchData.total_files) * 100,
    );
  }, [batchData]);

  const isDone = batchData ? ['completed', 'partial', 'failed'].includes(batchData.status) : false;

  const completedCount = batchData?.completed_count ?? 0;
  const totalFiles = batchData?.total_files ?? 0;

  // Pagination
  const paginatedItems = useMemo(() => {
    if (!batchData) return [];
    const start = currentPage * ITEMS_PER_PAGE;
    return batchData.items.slice(start, start + ITEMS_PER_PAGE);
  }, [batchData, currentPage]);

  const totalPages = batchData ? Math.ceil(batchData.items.length / ITEMS_PER_PAGE) : 0;

  // ─── Render: Loading ────────────────────────────────────
  if (isLoading && !batchData) {
    return (
      <Stack direction="vertical" spacing="x6">
        <Typography variant="h1" style={{ margin: 0 }}>Batch-анализ</Typography>
        <Progress shape="linear" />
        <Typography variant="body2" inactive>
          Загрузка статуса…
        </Typography>
      </Stack>
    );
  }

  // ─── Render: Error ──────────────────────────────────────
  if (error && !batchData) {
    return (
      <Stack direction="vertical" spacing="x6">
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад"
            onClick={handleBack}
          />
          <Typography variant="h1" style={{ margin: 0 }}>Batch-анализ</Typography>
        </Stack>
        <Banner title={error} color="error" iconName={Icons.Alarm} />
        <Button variant="outlined" onClick={handleRetry}>
          Повторить
        </Button>
      </Stack>
    );
  }

  if (!batchData) return null;

  // ─── Render: Empty state ────────────────────────────────
  if (batchData.items.length === 0) {
    return (
      <Stack direction="vertical" spacing="x6">
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад к загрузке"
            onClick={handleBack}
          />
          <Typography variant="h1" style={{ margin: 0 }}>Batch-анализ</Typography>
        </Stack>
        <BlurFade delay={0} duration={0.4} direction="up" inView>
          <Card>
            <Stack direction="vertical" spacing="x4" align="center">
              <Icon iconName={Icons.Archive} size="large" inactive />
              <Typography variant="body1" inactive>
                Нет файлов для анализа
              </Typography>
              <Typography variant="body2" inactive>
                Добавьте RTF-файлы на странице загрузки
              </Typography>
              <Button variant="primary" onClick={handleBack}>
                На страницу загрузки
              </Button>
            </Stack>
          </Card>
        </BlurFade>
      </Stack>
    );
  }

  // ─── Render: Main ──────────────────────────────────────
  return (
    <Stack direction="vertical" spacing="x6" aria-label="Batch-анализ">
      {/* ── Header ── */}
      <BlurFade delay={0} duration={0.4} direction="up" inView>
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад к загрузке"
            onClick={handleBack}
          />
          <Typography variant="h1" style={{ margin: 0 }}>Batch-анализ</Typography>
          {isDone && batchData.status !== 'failed' && (
            <ProgressButton
              state={retryState}
              onClick={handleRetry}
              variant="outlined"
              size="small"
              statusDelayTime={3000}
            >
              {retryState === 'loading' ? 'Повторяем…' : 'Повторить анализ'}
            </ProgressButton>
          )}
        </Stack>
      </BlurFade>

      {/* ── Hero Progress ── */}
      <BlurFade delay={0.1} duration={0.4} direction="up" inView>
        <Stack direction="vertical" spacing="x4" align="center">
          <AnimatedCircularProgressBar
            key={batchId} // force remount on batch change for animation
            value={progressPercent}
            gaugePrimaryColor="var(--color-background-brand)"
            gaugeSecondaryColor="var(--color-background-secondary)"
          />
          <Stack direction="horizontal" spacing="x2" align="baseline">
            <Typography variant="h4">
              <NumberTicker value={progressPercent} />%
            </Typography>
          </Stack>
          <Typography variant="body2" inactive>
            {isDone
              ? `Обработано ${completedCount} из ${totalFiles} файлов`
              : `Обработано ${completedCount + (batchData.failed_count ?? 0)} из ${totalFiles} файлов`}
          </Typography>
          {/* Linear progress bar */}
          <Progress shape="linear" value={progressPercent} />
        </Stack>
      </BlurFade>

      {/* ── Summary Statistics Card ── */}
      <BlurFade delay={0.15} duration={0.4} direction="up" inView>
        <Card>
          <Stack direction="horizontal" spacing="x6" align="center" justify="space-around" style={{ flexWrap: 'wrap' }}>
            <Stack direction="vertical" spacing="x1" align="center">
              <Typography variant="h4" style={{ margin: 0 }}>{totalFiles}</Typography>
              <Typography variant="caption" inactive>Всего файлов</Typography>
            </Stack>
            <Stack direction="vertical" spacing="x1" align="center">
              <Typography variant="h4" style={{ margin: 0, color: 'var(--color-text-success, #4caf50)' }}>
                {completedCount}
              </Typography>
              <Typography variant="caption" inactive>Успешно</Typography>
            </Stack>
            <Stack direction="vertical" spacing="x1" align="center">
              <Typography variant="h4" style={{ margin: 0, color: 'var(--color-text-danger, #f44336)' }}>
                {batchData.failed_count ?? 0}
              </Typography>
              <Typography variant="caption" inactive>С ошибкой</Typography>
            </Stack>
          </Stack>
        </Card>
      </BlurFade>

      {/* ── Error banner for failed batch ── */}
      {batchData.status === 'failed' && batchData.error && (
        <Banner title={batchData.error} color="error" iconName={Icons.Alarm} />
      )}

      {/* ── Retry error InlineAlert ── */}
      {retryError && (
        <InlineAlert type="error">{retryError}</InlineAlert>
      )}

      {/* ── Summary Table ── */}
      <BlurFade delay={0.2} duration={0.4} direction="up" inView>
        <Table hover>
          <TableHead>
            <TableRow>
              <TableHeaderData>№</TableHeaderData>
              <TableHeaderData>Файл</TableHeaderData>
              <TableHeaderData horizontalAlign="right">Всего</TableHeaderData>
              <TableHeaderData horizontalAlign="right">Q1</TableHeaderData>
              <TableHeaderData horizontalAlign="right">Q2</TableHeaderData>
              <TableHeaderData horizontalAlign="right">Q3</TableHeaderData>
              <TableHeaderData>Статус</TableHeaderData>
            </TableRow>
          </TableHead>
          <TableBody>
            <AnimatedList delay={300}>
              {paginatedItems.map((item, idx) => {
                const globalIdx = currentPage * ITEMS_PER_PAGE + idx;
                return (
                  <AnimatedListItem key={`${item.filename}-${globalIdx}`} index={idx} delay={300}>
                    <TableRow
                      role={item.status === 'completed' ? 'button' : undefined}
                      tabIndex={item.status === 'completed' ? 0 : undefined}
                      style={{
                        cursor: item.status === 'completed' ? 'pointer' : 'default',
                      }}
                      onClick={() => handleRowClick(item)}
                      onKeyDown={(e: React.KeyboardEvent) => {
                        if (item.status === 'completed' && (e.key === 'Enter' || e.key === ' ')) {
                          e.preventDefault();
                          handleRowClick(item);
                        }
                      }}
                    >
                      <TableData>{globalIdx + 1}</TableData>
                      <TableData>{item.filename}</TableData>
                      <TableData horizontalAlign="right">
                        {item.status === 'completed' ? item.total_matches : '—'}
                      </TableData>
                      <TableData horizontalAlign="right">
                        {item.status === 'completed'
                          ? (item.matches_by_level['1'] ?? '—')
                          : '—'}
                      </TableData>
                      <TableData horizontalAlign="right">
                        {item.status === 'completed'
                          ? (item.matches_by_level['2'] ?? '—')
                          : '—'}
                      </TableData>
                      <TableData horizontalAlign="right">
                        {item.status === 'completed'
                          ? (item.matches_by_level['3'] ?? '—')
                          : '—'}
                      </TableData>
                      <TableData>{getItemStatusBadge(item.status, item.error)}</TableData>
                    </TableRow>
                  </AnimatedListItem>
                );
              })}
            </AnimatedList>
          </TableBody>
        </Table>

        {/* ── Pagination ── */}
        {totalPages > 1 && (
          <TablePagination
            rowsCount={batchData.items.length}
            rowsPerPage={ITEMS_PER_PAGE}
            page={currentPage}
            onUserActions={(e) => setCurrentPage(e.page)}
          />
        )}
      </BlurFade>

      {/* ── Partial batch info ── */}
      {batchData.status === 'partial' && (
        <InlineAlert type="warning">
          Часть файлов обработана с ошибкой. Успешные результаты доступны по клику на строку.
        </InlineAlert>
      )}
    </Stack>
  );
}
