/**
 * HistoryPage — displays analysis history from localStorage.
 *
 * Route: /history
 *
 * Features:
 *   - List of past analysis entries with date, filename, match counts
 *   - Click to re-load results into context and navigate to /results
 *   - Delete individual entries or clear all
 *   - Storage usage indicator
 *   - Empty state when no history
 */

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Icon,
  IconButton,
  InlineAlert,
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

import { useAnalysisContext } from '../../context/AnalysisContext';
import * as api from '../../api/client';
import * as historyStorage from '../../storage/history';
import type { HistoryEntry } from '../../types/api';

/** Format ISO date string to locale-readable form */
function formatDate(iso: string): string {
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

/** Map entry status to Badge semantic */
function getStatusBadge(status: string) {
  switch (status) {
    case 'completed':
      return <Badge semantic="success">Завершён</Badge>;
    case 'partial':
      return <Badge semantic="warning">Частично</Badge>;
    case 'failed':
      return <Badge semantic="danger">Ошибка</Badge>;
    default:
      return <Badge semantic="info">{status}</Badge>;
  }
}

export default function HistoryPage() {
  const navigate = useNavigate();
  const { dispatch } = useAnalysisContext();

  // Single getAll() call: derive both entries and loading error from one initialization
  const [initialLoad] = useState<{ entries: HistoryEntry[]; error: string | null }>(() => {
    try {
      return { entries: historyStorage.getAll(), error: null };
    } catch {
      return { entries: [], error: 'Не удалось загрузить историю' };
    }
  });

  const [entries, setEntries] = useState<HistoryEntry[]>(initialLoad.entries);
  const loadingError = initialLoad.error;
  const [restoreError, setRestoreError] = useState<string | null>(null);

  // ─── Navigate to results for a history entry ────────────
  const handleEntryClick = useCallback(
    async (entry: HistoryEntry) => {
      setRestoreError(null);

      try {
        // Try to fetch full results from backend
        const result = await api.getResults(entry.analysisId);

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
        // Backend unavailable — try restoring from localStorage cache
        if (entry.searchResult || entry.llmResult) {
          dispatch({ type: 'SET_ANALYSIS_ID', payload: entry.analysisId });
          dispatch({ type: 'SET_SESSION_ID', payload: entry.sessionId });
          dispatch({
            type: 'SET_ANALYSIS_RESULTS',
            payload: {
              searchResult: entry.searchResult ?? null,
              llmResult: entry.llmResult ?? null,
            },
          });
          dispatch({ type: 'SET_ANALYSIS_STATUS', payload: entry.status === 'failed' ? 'error' : 'completed' });

          navigate('/results');
        } else {
          setRestoreError(
            `Результаты недоступны: сервер не отвечает, а кэш записи пуст. ID: ${entry.analysisId}`,
          );
        }
      }
    },
    [dispatch, navigate],
  );

  // ─── Delete single entry ────────────────────────────────
  const handleDelete = useCallback(
    (id: string) => {
      const removed = historyStorage.remove(id);
      if (removed) {
        setEntries((prev) => prev.filter((e) => e.id !== id));
      } else {
        // remove() failed (e.g. localStorage full) — re-read actual state to avoid stale UI
        setEntries(historyStorage.getAll());
      }
    },
    [],
  );

  // ─── Clear all history ─────────────────────────────────
  const handleClearAll = useCallback(() => {
    historyStorage.clearAll();
    setEntries([]);
  }, []);

  // ─── Back to upload ────────────────────────────────────
  const handleBack = useCallback(() => {
    navigate('/');
  }, [navigate]);

  // ─── Storage usage ─────────────────────────────────────
  const storageUsage = historyStorage.getStorageUsage();
  const isNearCapacity = historyStorage.isStorageNearCapacity();

  // ─── Render: Loading error ─────────────────────────────
  if (loadingError) {
    return (
      <Stack direction="vertical" spacing="x6">
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад"
            onClick={handleBack}
          />
          <Typography variant="h4">История анализов</Typography>
        </Stack>
        <InlineAlert type="error">{loadingError}</InlineAlert>
        <Button variant="outlined" onClick={handleBack}>
          На главную
        </Button>
      </Stack>
    );
  }

  // ─── Render: Empty state ────────────────────────────────
  if (entries.length === 0) {
    return (
      <Stack direction="vertical" spacing="x6" align="center">
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад"
            onClick={handleBack}
          />
          <Typography variant="h4">История анализов</Typography>
        </Stack>
        <Card>
          <Stack direction="vertical" spacing="x4" align="center">
            <Icon iconName={Icons.Clock} size="large" />
            <Typography variant="body1" inactive>
              История пуста. Выполните анализ диалога, чтобы увидеть результаты здесь.
            </Typography>
            <Button variant="primary" onClick={handleBack}>
              Загрузить диалог
            </Button>
          </Stack>
        </Card>
      </Stack>
    );
  }

  // ─── Render: Main content ───────────────────────────────
  return (
    <Stack direction="vertical" spacing="x6">
      {/* ── Header ── */}
      <Stack direction="horizontal" spacing="x3" align="center" justify="space-between">
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад к загрузке"
            onClick={handleBack}
          />
          <Typography variant="h4">История анализов</Typography>
        </Stack>
        <Button
          variant="outlined"
          size="small"
          onClick={handleClearAll}
        >
          Очистить всё
        </Button>
      </Stack>

      {/* ── Restore error ── */}
      {restoreError && (
        <InlineAlert type="error">{restoreError}</InlineAlert>
      )}

      {/* ── Storage warning ── */}
      {isNearCapacity && (
        <InlineAlert type="warning" iconName={Icons.WarningTriangle}>
          Хранилище заполнено на {Math.round(storageUsage.percentage * 100)}%.
          Рекомендуется очистить старые записи.
        </InlineAlert>
      )}

      {/* ── History Table ── */}
      <Card>
        <Table hover>
          <TableHead>
            <TableRow>
              <TableHeaderData>Дата</TableHeaderData>
              <TableHeaderData>Файл</TableHeaderData>
              <TableHeaderData horizontalAlign="right">Совпадений</TableHeaderData>
              <TableHeaderData>Словари</TableHeaderData>
              <TableHeaderData>Статус</TableHeaderData>
              <TableHeaderData />
            </TableRow>
          </TableHead>
          <TableBody>
            {entries.map((entry) => (
              <TableRow
                key={entry.id}
                role="button"
                tabIndex={0}
                style={{ cursor: 'pointer' }}
                onClick={() => handleEntryClick(entry)}
                onKeyDown={(e: React.KeyboardEvent) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleEntryClick(entry);
                  }
                }}
              >
                <TableData>{formatDate(entry.date)}</TableData>
                <TableData>{entry.fileName}</TableData>
                <TableData horizontalAlign="right">{entry.totalMatches}</TableData>
                <TableData>
                  {entry.dictionaryNames.length > 0
                    ? entry.dictionaryNames.slice(0, 2).join(', ') +
                      (entry.dictionaryNames.length > 2
                        ? ` +${entry.dictionaryNames.length - 2}`
                        : '')
                    : '—'}
                </TableData>
                <TableData>{getStatusBadge(entry.status)}</TableData>
                <TableData>
                  <IconButton
                    iconName={Icons.Delete}
                    variant="plain"
                    size="small"
                    aria-label={`Удалить запись от ${formatDate(entry.date)}`}
                    onClick={(e: React.MouseEvent) => {
                      e.stopPropagation();
                      handleDelete(entry.id);
                    }}
                  />
                </TableData>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* ── Summary ── */}
      <Typography variant="caption" inactive>
        Записей: {entries.length} · Хранилище: {Math.round(storageUsage.percentage * 100)}%
      </Typography>
    </Stack>
  );
}
