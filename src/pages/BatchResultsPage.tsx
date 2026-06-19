/**
 * BatchResultsPage — displays batch analysis progress and summary table.
 *
 * Route: /batch-results/:batchId
 *
 * Features:
 *   - Auto-polling batch status every 2 seconds until complete
 *   - Progress bar showing completed/total files
 *   - Summary table with per-file status badges
 *   - Clickable completed rows → navigate to ResultsPage
 *   - Error banner for failed batches
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Banner,
  Button,
  IconButton,
  InlineAlert,
  Progress,
  Stack,
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeaderData,
  TableRow,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { useAnalysisContext } from '../context/AnalysisContext';
import * as api from '../api/client';
import * as historyStorage from '../storage/history';
import type { BatchAnalysisResponse, BatchItemStatus, HistoryEntry } from '../types/api';

/** Polling interval in ms */
const POLL_INTERVAL = 2000;

/** Map batch item status to Badge semantic color */
function getStatusBadge(status: string, error: string | null) {
  switch (status) {
    case 'completed':
      return <Badge semantic="success">Завершён</Badge>;
    case 'processing':
      return <Badge semantic="info">Обработка</Badge>;
    case 'failed':
      return (
        <Badge semantic="danger">
          Ошибка{error ? `: ${error.slice(0, 50)}` : ''}
        </Badge>
      );
    case 'pending':
    default:
      return <Badge semantic="warning">Ожидание</Badge>;
  }
}

export default function BatchResultsPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();
  const { state, dispatch } = useAnalysisContext();

  const [batchData, setBatchData] = useState<BatchAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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

  // ─── Fetch batch status ─────────────────────────────────
  const fetchStatus = useCallback(async () => {
    if (!batchId) return;

    // Create a new AbortController for this request
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
      }
    } catch (err) {
      // Ignore AbortError — component was unmounted
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError(err instanceof Error ? err.message : 'Ошибка получения статуса batch');
      setIsLoading(false);
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    }
  }, [batchId, dispatch, saveCompletedToHistory]);

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
      // Abort any in-flight fetch on unmount
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
        // Fetch the analysis result for this item
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
  const handleRetry = useCallback(() => {
    navigate('/');
  }, [navigate]);

  // ─── Render: Loading ────────────────────────────────────
  if (isLoading && !batchData) {
    return (
      <Stack direction="vertical" spacing="x6">
        <Typography variant="h4">Batch-анализ</Typography>
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
          <Typography variant="h4">Batch-анализ</Typography>
        </Stack>
        <Banner title={error} color="error" iconName={Icons.Alarm} />
        <Button variant="outlined" onClick={handleRetry}>
          Повторить
        </Button>
      </Stack>
    );
  }

  if (!batchData) return null;

  // ─── Derived state ──────────────────────────────────────
  const progressPercent =
    batchData.total_files > 0
      ? Math.round(
          ((batchData.completed_count + batchData.failed_count) /
            batchData.total_files) *
            100,
        )
      : 0;

  const isDone = ['completed', 'partial', 'failed'].includes(batchData.status);

  return (
    <Stack direction="vertical" spacing="x6">
      {/* ── Header ── */}
      <Stack direction="horizontal" spacing="x3" align="center">
        <IconButton
          iconName={Icons.ArrowLeft}
          variant="plain"
          aria-label="Назад к загрузке"
          onClick={handleBack}
        />
        <Typography variant="h4">Batch-анализ</Typography>
      </Stack>

      {/* ── Progress ── */}
      <Stack direction="vertical" spacing="x2">
        <Progress shape="linear" value={progressPercent} />
        <Typography variant="body2" inactive>
          {isDone
            ? `Обработано ${batchData.completed_count} из ${batchData.total_files} файлов`
            : `Обработано ${batchData.completed_count + batchData.failed_count} из ${batchData.total_files} файлов`}
        </Typography>
      </Stack>

      {/* ── Error banner for failed batch ── */}
      {batchData.status === 'failed' && batchData.error && (
        <Banner title={batchData.error} color="error" iconName={Icons.Alarm} />
      )}

      {/* ── Summary Table ── */}
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
          {batchData.items.map((item, idx) => (
            <TableRow
              key={`${item.filename}-${idx}`}
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
              <TableData>{idx + 1}</TableData>
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
              <TableData>{getStatusBadge(item.status, item.error)}</TableData>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* ── Partial batch info ── */}
      {batchData.status === 'partial' && (
        <InlineAlert type="warning">
          Часть файлов обработана с ошибкой. Успешные результаты доступны по клику на строку.
        </InlineAlert>
      )}
    </Stack>
  );
}
