/**
 * HistoryPage — displays analysis history from localStorage.
 *
 * Route: /history
 *
 * Features:
 *   - Pagination (DS Pagination, 10 items per page)
 *   - Search/filter TextField (client-side, by filename or dictionary names)
 *   - History entries as Cards with BlurFade animation
 *   - "Очистить всё" → Dialog confirmation → Snackbar
 *   - Delete individual entries with IconButton
 *   - Empty state when no history or no search results
 *   - Storage usage indicator
 */

import { useCallback, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Box,
  Button,
  Card,
  Dialog,
  Icon,
  IconButton,
  InlineAlert,
  Pagination,
  Stack,
  TextField,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { useAnalysisContext } from '../../context/AnalysisContext';
import { useSnackbar } from '../../context/SnackbarContext';
import * as api from '../../api/client';
import * as historyStorage from '../../storage/history';
import { BlurFade } from '../../components/ui/blur-fade';
import type { HistoryEntry } from '../../types/api';

const ITEMS_PER_PAGE = 10;

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
  const { showSnackbar } = useSnackbar();

  // ─── State ────────────────────────────────────────────────
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

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  // Clear all dialog
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // ─── Filtering ──────────────────────────────────────────
  const filteredEntries = useMemo(() => {
    if (!searchQuery.trim()) return entries;
    const query = searchQuery.toLowerCase();
    return entries.filter(
      (entry) =>
        entry.fileName.toLowerCase().includes(query) ||
        entry.dictionaryNames.some((name) => name.toLowerCase().includes(query)),
    );
  }, [entries, searchQuery]);

  // ─── Pagination ─────────────────────────────────────────
  const totalPages = Math.ceil(filteredEntries.length / ITEMS_PER_PAGE);
  const paginatedEntries = useMemo(
    () =>
      filteredEntries.slice(
        (currentPage - 1) * ITEMS_PER_PAGE,
        currentPage * ITEMS_PER_PAGE,
      ),
    [filteredEntries, currentPage],
  );

  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value);
    setCurrentPage(1);
  }, []);

  // ─── Navigate to results ─────────────────────────────────
  const handleEntryClick = useCallback(
    async (entry: HistoryEntry) => {
      setRestoreError(null);

      try {
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
          dispatch({
            type: 'SET_ANALYSIS_STATUS',
            payload: entry.status === 'failed' ? 'error' : 'completed',
          });

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

  // ─── Delete entry ────────────────────────────────────────
  const handleDelete = useCallback((id: string) => {
    const removed = historyStorage.remove(id);
    if (removed) {
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } else {
      setEntries(historyStorage.getAll());
    }
  }, []);

  // ─── Clear all (with Dialog confirmation) ────────────────
  const handleClearAllConfirm = useCallback(() => {
    historyStorage.clearAll();
    setEntries([]);
    setShowClearConfirm(false);
    showSnackbar('История очищена');
  }, [showSnackbar]);

  // ─── Back ────────────────────────────────────────────────
  const handleBack = useCallback(() => {
    navigate('/');
  }, [navigate]);

  // ─── Storage usage ──────────────────────────────────────
  const storageUsage = historyStorage.getStorageUsage();
  const isNearCapacity = historyStorage.isStorageNearCapacity();

  // ─── Render: Loading error ───────────────────────────────
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
          <Typography variant="h1" style={{ margin: 0 }}>История анализов</Typography>
        </Stack>
        <InlineAlert type="error">{loadingError}</InlineAlert>
        <Button variant="outlined" onClick={handleBack}>
          На главную
        </Button>
      </Stack>
    );
  }

  // ─── Render: Empty state (no entries at all) ──────────────
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
          <Typography variant="h1" style={{ margin: 0 }}>История анализов</Typography>
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

  // ─── Render: Main content ────────────────────────────────
  return (
    <Stack direction="vertical" spacing="x6" aria-label="История анализов">
      {/* ── Header ── */}
      <Stack direction="horizontal" spacing="x3" align="center" justify="space-between">
        <Stack direction="horizontal" spacing="x3" align="center">
          <IconButton
            iconName={Icons.ArrowLeft}
            variant="plain"
            aria-label="Назад к загрузке"
            onClick={handleBack}
          />
          <Typography variant="h1" style={{ margin: 0 }}>История анализов</Typography>
        </Stack>
        <Button
          variant="outlined"
          size="small"
          onClick={() => setShowClearConfirm(true)}
        >
          Очистить всё
        </Button>
      </Stack>

      {/* ── Search ── */}
      <TextField
        label="Поиск"
        placeholder="Поиск по файлу или словарю..."
        value={searchQuery}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          handleSearchChange(e.target.value)
        }
      />

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

      {/* ── No search results ── */}
      {filteredEntries.length === 0 && searchQuery.trim() ? (
        <Stack direction="vertical" spacing="x3" align="center" padding="x6">
          <Icon iconName={Icons.Search} size="large" />
          <Typography variant="body1" inactive>
            Ничего не найдено
          </Typography>
          <Typography variant="body2" inactive>
            Попробуйте изменить поисковый запрос
          </Typography>
        </Stack>
      ) : (
        <>
          {/* ── History Cards with BlurFade ── */}
          <Stack direction="vertical" spacing="x2">
            {paginatedEntries.map((entry, index) => (
              <BlurFade key={entry.id} delay={0.05 * index} duration={0.3} direction="up">
                <Card
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleEntryClick(entry)}
                >
                  <Box padding="x4">
                    <Stack direction="vertical" spacing="x2">
                      {/* Row 1: Filename + date + status */}
                      <Stack direction="horizontal" spacing="x3" align="center" justify="space-between">
                        <Stack direction="horizontal" spacing="x2" align="center" style={{ flex: 1, overflow: 'hidden' }}>
                          <Icon iconName={Icons.Attachment} size="small" />
                          <Typography variant="body1" style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {entry.fileName}
                          </Typography>
                        </Stack>
                        <Stack direction="horizontal" spacing="x2" align="center">
                          <Typography variant="caption" inactive>
                            {formatDate(entry.date)}
                          </Typography>
                          {getStatusBadge(entry.status)}
                        </Stack>
                      </Stack>

                      {/* Row 2: Dictionaries + match count + delete */}
                      <Stack direction="horizontal" spacing="x3" align="center" justify="space-between">
                        <Stack direction="horizontal" spacing="x2" align="center" style={{ flex: 1 }}>
                          <Icon iconName={Icons.Book} size="small" />
                          <Typography variant="body2" inactive style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {entry.dictionaryNames.length > 0
                              ? entry.dictionaryNames.slice(0, 3).join(', ') +
                                (entry.dictionaryNames.length > 3
                                  ? ` +${entry.dictionaryNames.length - 3}`
                                  : '')
                              : '—'}
                          </Typography>
                        </Stack>
                        <Stack direction="horizontal" spacing="x3" align="center">
                          <Typography variant="body2">
                            {entry.totalMatches} совпадений
                          </Typography>
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
                        </Stack>
                      </Stack>
                    </Stack>
                  </Box>
                </Card>
              </BlurFade>
            ))}
          </Stack>

          {/* ── Pagination ── */}
          {totalPages > 1 && (
            <Stack direction="horizontal" justify="center">
              <Pagination
                count={totalPages}
                page={currentPage}
                onChange={setCurrentPage}
                collapsed={true}
                siblingCount={2}
              />
            </Stack>
          )}
        </>
      )}

      {/* ── Summary ── */}
      <Typography variant="caption" inactive>
        Записей: {filteredEntries.length} · Хранилище: {Math.round(storageUsage.percentage * 100)}%
      </Typography>

      {/* ── Clear All Dialog ── */}
      <Dialog
        open={showClearConfirm}
        onClose={() => setShowClearConfirm(false)}
      >
        <Box style={{ padding: 'var(--sizeSpacingX6)' }}>
          <Stack direction="vertical" spacing="x4">
            <Typography variant="h5">Очистить всю историю?</Typography>
            <Typography variant="body2">
              Все записи будут удалены. Это действие нельзя отменить.
            </Typography>
            <Stack direction="horizontal" spacing="x2" justify="end">
              <Button variant="plain" onClick={() => setShowClearConfirm(false)}>
                Отмена
              </Button>
              <Button variant="primary" onClick={handleClearAllConfirm}>
                Очистить
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>
    </Stack>
  );
}
