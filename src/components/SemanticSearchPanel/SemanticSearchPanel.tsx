/**
 * SemanticSearchPanel — right sidebar for semantic/hybrid search
 * across analyzed dialogues powered by FRIDA embeddings.
 *
 * States: idle → searching → results / empty / error
 * Features:
 *   - TextField with 300ms debounce
 *   - Semantic / Hybrid toggle (two Buttons)
 *   - FRIDA status indicator (Badge dot + Tooltip)
 *   - Result cards with score Badge, speaker, entity Chips, <mark> highlights
 *   - SearchHistory in Collapse (localStorage, max 50)
 *   - Feedback IconButton (like/dislike) per result
 *   - Cross-highlighting: onResultClick callback
 *
 * Layout: 320px sidebar on desktop, overlay on mobile
 * (mirrors DictionaryPhraseList pattern)
 */

import { useCallback, useEffect, useRef, useState, memo } from 'react';
import {
  Badge,
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  IconButton,
  InlineAlert,
  Skeleton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import {
  searchHybrid,
  searchSemantic,
  getEmbeddingStatus,
  submitFeedback,
  ApiError,
} from '../../api/client';
import { useSnackbar } from '../../context/SnackbarContext';
import type {
  HybridSearchResult,
  VectorSearchResult,
  EmbeddingStatusResponse,
  SearchType,
  SearchHistoryEntry,
} from '../../types/api';

// ═══════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════

const DEBOUNCE_MS = 300;
const HISTORY_KEY = 'semantic_search_history';
const MAX_HISTORY = 50;
const MAX_VISIBLE_HISTORY = 7;
const DEFAULT_TOP_K = 10;

// ═══════════════════════════════════════════════════════════
// localStorage helpers
// ═══════════════════════════════════════════════════════════

function loadHistory(): SearchHistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as SearchHistoryEntry[];
  } catch {
    return [];
  }
}

function saveHistory(entries: SearchHistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)));
  } catch {
    // localStorage quota exceeded — silently ignore
  }
}

function addToHistory(query: string, resultCount: number, searchType: SearchType): void {
  const entries = loadHistory();
  // Remove duplicates of the same query
  const filtered = entries.filter((e) => e.query !== query);
  const newEntry: SearchHistoryEntry = {
    query,
    timestamp: new Date().toISOString(),
    resultCount,
    searchType,
  };
  saveHistory([newEntry, ...filtered]);
}

function removeFromHistory(query: string): SearchHistoryEntry[] {
  const entries = loadHistory().filter((e) => e.query !== query);
  saveHistory(entries);
  return entries;
}

function clearHistory(): SearchHistoryEntry[] {
  saveHistory([]);
  return [];
}

// ═══════════════════════════════════════════════════════════
// Highlight helper
// ═══════════════════════════════════════════════════════════

/**
 * Highlights matched text fragments with <mark> tags.
 * For hybrid results, matched_entities are highlighted.
 * For semantic results, the entire text is shown without highlighting
 * (since there's no explicit matched_entities field).
 */
function highlightText(
  text: string,
  matchedEntities: string[],
): React.ReactNode {
  if (matchedEntities.length === 0) {
    return text;
  }

  // Build a regex that matches any of the entities (case-insensitive, word-boundary)
  const escaped = matchedEntities.map((e) =>
    e.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  );
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');
  const parts = text.split(pattern);

  return parts.map((part, i) => {
    const isMatch = matchedEntities.some(
      (e) => e.toLowerCase() === part.toLowerCase(),
    );
    if (isMatch) {
      return (
        <mark key={i} className="semantic-highlight">
          {part}
        </mark>
      );
    }
    return part;
  });
}

// ═══════════════════════════════════════════════════════════
// Speaker label helper
// ═══════════════════════════════════════════════════════════

function getSpeakerLabel(speaker: string): string {
  const lower = speaker.toLowerCase();
  if (lower.includes('клиент') || lower.includes('client') || lower.includes('customer')) {
    return 'Кл.';
  }
  if (lower.includes('сотрудник') || lower.includes('operator') || lower.includes('agent')) {
    return 'Сотр.';
  }
  return speaker.slice(0, 4);
}

// ═══════════════════════════════════════════════════════════
// Entity type → Chip label mapping
// ═══════════════════════════════════════════════════════════

const ENTITY_TYPE_LABELS: Record<string, string> = {
  PER: 'PER',
  LOC: 'LOC',
  ORG: 'ORG',
};

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

interface SemanticSearchPanelProps {
  /** Session ID for scoping search to current dialogue */
  sessionId?: string;
  /** Callback when user clicks a result — for cross-highlighting */
  onResultClick?: (dialogueId: string, turnIndex: number) => void;
  /** Close panel handler */
  onClose?: () => void;
}

// ═══════════════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════════════

/** Single result card */
function ResultCard({
  result,
  onNavigate,
  vote,
  onVote,
}: {
  result: HybridSearchResult | VectorSearchResult;
  onNavigate: (dialogueId: string, turnIndex: number) => void;
  /** Current optimistic vote for this result ('like' | 'dislike' | null). */
  vote: 'like' | 'dislike' | null;
  /** Feedback handler (W2 known-issues #1, #2). */
  onVote: (result: HybridSearchResult | VectorSearchResult, kind: 'like' | 'dislike') => void;
}) {
  const isHybrid = 'combined_score' in result;
  const score = isHybrid
    ? (result as HybridSearchResult).combined_score
    : (result as VectorSearchResult).score;
  const matchedEntities = isHybrid
    ? (result as HybridSearchResult).matched_entities
    : (result as VectorSearchResult).entities.map((e) => e.text);
  const speakerLabel = getSpeakerLabel(result.speaker);

  // Extract unique entity types for Chip display
  const entityTypes: string[] = isHybrid
    ? [] // HybridSearchResult only has matched_entities (strings)
    : (result as VectorSearchResult).entities
        .map((e) => ENTITY_TYPE_LABELS[e.type] ?? e.type)
        .filter((v, i, a) => a.indexOf(v) === i);

  return (
    <Box
      className="semantic-result-card"
      padding="x3"
      style={{ cursor: 'pointer' }}
      role="button"
      tabIndex={0}
      onClick={() => onNavigate(result.dialogue_id, result.turn_index)}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onNavigate(result.dialogue_id, result.turn_index);
        }
      }}
      aria-label={`Результат: ${result.speaker}, совпадение ${score.toFixed(2)}`}
    >
      <Stack direction="vertical" spacing="x1">
        {/* Speaker + Score row */}
        <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
          <Stack direction="horizontal" spacing="x1" align="center">
            <Typography variant="caption" inactive>
              {speakerLabel}
            </Typography>
            {entityTypes.map((type) => (
              <Chip key={type} label={type} disabled />
            ))}
          </Stack>
          <Badge type="secondary" semantic="info">
            {score.toFixed(2)}
          </Badge>
        </Stack>

        {/* Highlighted text */}
        <Typography variant="body2" className="semantic-result-text">
          {highlightText(result.text, matchedEntities)}
        </Typography>

        {/* Feedback buttons — W2 wiring (known-issues #1, #2):
            POST /api/feedback with optimistic UI. The vote is applied
            immediately and reverted with an error snackbar on failure. */}
        <Stack direction="horizontal" spacing="x1" justify="end">
          <IconButton
            iconName={Icons.Like}
            variant={vote === 'like' ? 'outlined' : 'plain'}
            size="small"
            aria-label="Полезный результат"
            aria-pressed={vote === 'like'}
            disabled={vote !== null}
            onClick={(e: React.MouseEvent) => {
              e.stopPropagation();
              onVote(result, 'like');
            }}
          />
          <IconButton
            iconName={Icons.Dislike}
            variant={vote === 'dislike' ? 'outlined' : 'plain'}
            size="small"
            aria-label="Неполезный результат"
            aria-pressed={vote === 'dislike'}
            disabled={vote !== null}
            onClick={(e: React.MouseEvent) => {
              e.stopPropagation();
              onVote(result, 'dislike');
            }}
          />
        </Stack>
      </Stack>
    </Box>
  );
}

/** Loading skeleton for results */
function ResultsSkeleton() {
  return (
    <Stack direction="vertical" spacing="x2" padding="x3">
      {Array.from({ length: 3 }, (_, i) => (
        <Stack key={i} direction="vertical" spacing="x1">
          <Skeleton variant="line" height={16} width="40%" />
          <Skeleton variant="line" height={14} width="100%" />
          <Skeleton variant="line" height={14} width="80%" />
        </Stack>
      ))}
    </Stack>
  );
}

/** Empty state when no results */
function EmptyResultsState({ query }: { query: string }) {
  return (
    <Box padding="x4">
      <Stack direction="vertical" spacing="x3" align="center">
        <IconButton iconName={Icons.Search} variant="plain" aria-label="" />
        <Typography variant="body2" inactive>
          Ничего не найдено по запросу &laquo;{query}&raquo;
        </Typography>
      </Stack>
    </Box>
  );
}

/** Idle empty state — before first search */
function IdleState() {
  return (
    <Box padding="x4">
      <Stack direction="vertical" spacing="x3" align="center">
        <IconButton iconName={Icons.Search} variant="plain" aria-label="" />
        <Typography variant="body2" inactive>
          Введите запрос для семантического поиска
        </Typography>
      </Stack>
    </Box>
  );
}

// ═══════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════

export default memo(function SemanticSearchPanel({
  sessionId,
  onResultClick,
  onClose,
}: SemanticSearchPanelProps) {
  const { showSnackbar } = useSnackbar();

  // ── Search state ──
  const [query, setQuery] = useState('');
  const [searchType, setSearchType] = useState<SearchType>('hybrid');
  const [results, setResults] = useState<(HybridSearchResult | VectorSearchResult)[]>([]);
  const [totalResults, setTotalResults] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorType, setErrorType] = useState<'frida' | 'rate_limit' | 'generic' | null>(null);

  // ── FRIDA status ──
  const [fridaStatus, setFridaStatus] = useState<EmbeddingStatusResponse | null>(null);
  const [fridaStatusLoading, setFridaStatusLoading] = useState(true);

  // ── Feedback votes (W2: optimistic UI per result) ──
  const [votes, setVotes] = useState<Record<string, 'like' | 'dislike'>>({});

  // ── Search history ──
  const [history, setHistory] = useState<SearchHistoryEntry[]>(() => loadHistory());
  const [historyExpanded, setHistoryExpanded] = useState(false);

  // ── Abort controller for search requests ──
  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Ref to track current searchType for debounced callback ──
  const searchTypeRef = useRef<SearchType>(searchType);
  useEffect(() => {
    searchTypeRef.current = searchType;
  }, [searchType]);

  // ── Fetch FRIDA status on mount ──
  useEffect(() => {
    const controller = new AbortController();

    async function fetchStatus() {
      try {
        setFridaStatusLoading(true);
        const status = await getEmbeddingStatus(controller.signal);
        setFridaStatus(status);
      } catch {
        // Status fetch failed — FRIDA unavailable
        setFridaStatus(null);
      } finally {
        setFridaStatusLoading(false);
      }
    }

    fetchStatus();
    return () => controller.abort();
  }, []);

  // ── Cleanup debounce on unmount ──
  useEffect(() => {
    return () => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  // ── Search handler ──
  const performSearch = useCallback(
    async (searchQuery: string, type: SearchType) => {
      if (!searchQuery.trim()) return;

      // Abort previous request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setIsLoading(true);
      setError(null);
      setErrorType(null);

      try {
        const request = {
          query: searchQuery.trim(),
          session_id: sessionId,
          top_k: DEFAULT_TOP_K,
          use_semantic: type === 'hybrid' ? true : undefined,
          use_ner: type === 'hybrid' ? true : undefined,
        };

        let response: { results: (HybridSearchResult | VectorSearchResult)[]; total: number };

        if (type === 'semantic') {
          const res = await searchSemantic(request, controller.signal);
          response = { results: res.results, total: res.total };
        } else {
          const res = await searchHybrid(request, controller.signal);
          response = { results: res.results, total: res.total };
        }

        if (!controller.signal.aborted) {
          setResults(response.results);
          setTotalResults(response.total);
          setHasSearched(true);
          addToHistory(searchQuery.trim(), response.total, type);
          setHistory(loadHistory());
        }
      } catch (err) {
        if (controller.signal.aborted) return;

        if (err instanceof ApiError) {
          if (err.status === 429) {
            setError('Слишком много запросов. Попробуйте через 30 сек.');
            setErrorType('rate_limit');
          } else if (err.status === 503) {
            setError('FRIDA недоступна. Используется морфологический поиск.');
            setErrorType('frida');
          } else {
            setError(err.message);
            setErrorType('generic');
          }
        } else {
          setError('Произошла ошибка при поиске');
          setErrorType('generic');
        }
        setHasSearched(true);
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    },
    [sessionId],
  );

  // ── Submit handler (button click or Enter) ──
  const handleSubmit = useCallback(() => {
    if (!query.trim()) return;
    performSearch(query, searchType);
  }, [query, searchType, performSearch]);

  // ── Debounced input change ──
  const handleQueryChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setQuery(value);

      // Clear previous debounce
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }

      // Debounce search — auto-search after 300ms if query is non-empty
      if (value.trim()) {
        debounceRef.current = setTimeout(() => {
          // Use ref to get current searchType (avoids stale closure)
          performSearch(value, searchTypeRef.current);
        }, DEBOUNCE_MS);
      } else {
        // Reset results when input is cleared
        setResults([]);
        setTotalResults(0);
        setHasSearched(false);
        setError(null);
        setErrorType(null);
      }
    },
    [performSearch],
  );

  // ── Result click → cross-highlighting ──
  const handleResultClick = useCallback(
    (dialogueId: string, turnIndex: number) => {
      onResultClick?.(dialogueId, turnIndex);
    },
    [onResultClick],
  );

  // ── Search type toggle ──
  const handleSearchTypeChange = useCallback(
    (type: SearchType) => {
      setSearchType(type);
      // Re-search with new type if there's a query
      if (query.trim()) {
        performSearch(query, type);
      }
    },
    [query, performSearch],
  );

  // ── History handlers ──
  const handleHistoryClick = useCallback(
    (entry: SearchHistoryEntry) => {
      setQuery(entry.query);
      setSearchType(entry.searchType);
      performSearch(entry.query, entry.searchType);
    },
    [performSearch],
  );

  const handleDeleteHistory = useCallback((entryQuery: string) => {
    const updated = removeFromHistory(entryQuery);
    setHistory(updated);
  }, []);

  const handleClearHistory = useCallback(() => {
    const updated = clearHistory();
    setHistory(updated);
  }, []);

  // ── Derived: FRIDA available / embedding mode ──
  const fridaAvailable = fridaStatus?.frida_available ?? false;
  // W2 (Wave 1 health fields): /api/embeddings/status now returns
  // embedding_provider {provider, mode}. When provider === 'local' the
  // semantic search runs on local TF-IDF embeddings and is AVAILABLE —
  // it must NOT be shown as broken.
  const embeddingProvider = fridaStatus?.embedding_provider?.provider ?? null;
  const isLocalMode = embeddingProvider === 'local';
  const searchAvailable = fridaAvailable || isLocalMode;

  // ── Feedback vote handler (W2 known-issues #1, #2) ──
  const resultKey = (r: HybridSearchResult | VectorSearchResult): string =>
    `${r.dialogue_id}-${r.turn_index}`;

  const handleVote = useCallback(
    (result: HybridSearchResult | VectorSearchResult, kind: 'like' | 'dislike') => {
      const key = resultKey(result);

      if (!sessionId) {
        showSnackbar('Нет активной сессии — feedback не отправлен', {
          variant: 'fixed',
          delay: 5000,
        });
        return;
      }

      // Optimistic update
      setVotes((prev) => ({ ...prev, [key]: kind }));

      submitFeedback({
        session_id: sessionId,
        phrase_text: result.text.slice(0, 200),
        matched_text: result.text.slice(0, 200),
        turn_index: result.turn_index,
        feedback_text:
          kind === 'like'
            ? 'Положительная оценка результата семантического поиска'
            : 'Отрицательная оценка результата семантического поиска',
      })
        .then(() => {
          showSnackbar('Спасибо за отзыв!', { variant: 'elastic', delay: 3000 });
        })
        .catch((err: unknown) => {
          // Revert the optimistic vote
          setVotes((prev) => {
            const next = { ...prev };
            delete next[key];
            return next;
          });
          const msg =
            err instanceof ApiError || err instanceof Error
              ? err.message
              : 'Неизвестная ошибка';
          showSnackbar(`Ошибка отправки отзыва: ${msg}`, {
            variant: 'fixed',
            delay: 6000,
          });
        });
    },
    [sessionId, showSnackbar],
  );

  // ── Render ──

  return (
    <Box
      className="semantic-search-panel"
      role="complementary"
      aria-label="Семантический поиск"
    >
      {/* ── Header ── */}
      <Box padding="x3">
        <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
          <Stack direction="horizontal" spacing="x2" align="center">
            <Typography variant="h6">Семантический поиск</Typography>
            {/* Embedding mode indicator — W2 (Wave 1 health fields):
                FRIDA vs local TF-IDF. In local mode the search is fully
                available (offline), so the badge is green, not danger. */}
            <Tooltip
              title={
                fridaStatusLoading
                  ? 'Проверка статуса…'
                  : isLocalMode
                    ? 'Семантический поиск работает в локальном режиме (TF-IDF)'
                    : fridaAvailable
                      ? `FRIDA доступна · ${fridaStatus?.vectors_stored ?? 0} векторов · ${fridaStatus?.nlp_provider ?? 'none'}`
                      : 'Семантический поиск недоступен'
              }
            >
              <span>
                <Badge
                  type="tertiary"
                  /* W2: neutral '…' while the status probe is in flight —
                     a transient red OFF badge (before the /status response
                     lands) read as "semantic search broken" and contradicted
                     the green FRIDA badge in the page action bar. */
                  semantic={
                    fridaStatusLoading
                      ? 'neutral'
                      : searchAvailable
                        ? 'success'
                        : 'danger'
                  }
                  dot={!fridaStatusLoading}
                >
                  {fridaStatusLoading
                    ? '…'
                    : isLocalMode
                      ? 'Локальный режим (TF-IDF)'
                      : fridaAvailable
                        ? 'FRIDA'
                        : 'OFF'}
                </Badge>
              </span>
            </Tooltip>
          </Stack>
          {onClose && (
            <IconButton
              iconName={Icons.Close}
              variant="plain"
              size="small"
              aria-label="Закрыть панель поиска"
              onClick={onClose}
            />
          )}
        </Stack>
      </Box>

      <Divider />

      {/* ── Input area ── */}
      <Box padding="x3">
        <Stack direction="vertical" spacing="x2">
          <TextField
            label="Поиск по смыслу"
            placeholder="Поиск по смыслу…"
            value={query}
            onChange={handleQueryChange}
            disabled={!searchAvailable && !fridaStatusLoading}
            fullWidth
            aria-label="Поисковый запрос"
          />

          {/* Search type toggle */}
          <Stack direction="horizontal" spacing="none">
            <Button
              variant={searchType === 'semantic' ? 'primary' : 'secondary'}
              size="small"
              fullWidth
              onClick={() => handleSearchTypeChange('semantic')}
              aria-pressed={searchType === 'semantic'}
            >
              Семантический
            </Button>
            <Button
              variant={searchType === 'hybrid' ? 'primary' : 'secondary'}
              size="small"
              fullWidth
              onClick={() => handleSearchTypeChange('hybrid')}
              aria-pressed={searchType === 'hybrid'}
            >
              Гибридный
            </Button>
          </Stack>

          {/* Search button */}
          <Button
            variant="primary"
            fullWidth
            onClick={handleSubmit}
            disabled={!query.trim() || isLoading || (!searchAvailable && !fridaStatusLoading)}
          >
            {isLoading ? 'Поиск…' : 'Искать'}
          </Button>
        </Stack>
      </Box>

      {/* ── Error alert ── */}
      {error && (
        <Box padding="x3">
          <InlineAlert
            type={
              errorType === 'frida'
                ? 'error'
                : errorType === 'rate_limit'
                  ? 'warning'
                  : 'error'
            }
            iconName={
              errorType === 'rate_limit' ? Icons.Alarm : undefined
            }
          >
            {error}
          </InlineAlert>
        </Box>
      )}

      <Divider />

      {/* ── Search History ── */}
      <Box padding="x3">
        <Collapse
          expanded={historyExpanded}
          onToggle={() => setHistoryExpanded((prev) => !prev)}
          labelCollapsed={`История запросов (${history.length})`}
          labelExpanded={`История запросов (${history.length})`}
          size="small"
        >
          {history.length === 0 ? (
            <Typography variant="caption" inactive>
              Нет сохранённых запросов
            </Typography>
          ) : (
            <Stack direction="vertical" spacing="x1">
              {history.slice(0, MAX_VISIBLE_HISTORY).map((entry) => (
                <Stack
                  key={entry.query}
                  direction="horizontal"
                  spacing="x2"
                  align="center"
                  justify="space-between"
                  className="semantic-history-item"
                  role="button"
                  tabIndex={0}
                  aria-label={`Повторить запрос: ${entry.query}`}
                  onClick={() => handleHistoryClick(entry)}
                  onKeyDown={(e: React.KeyboardEvent) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleHistoryClick(entry);
                    }
                  }}
                >
                  <Stack direction="vertical" spacing="none">
                    <Typography variant="body2">{entry.query}</Typography>
                    <Typography variant="caption" inactive>
                      {entry.resultCount} рез. · {entry.searchType === 'semantic' ? 'сем.' : 'гибр.'}
                    </Typography>
                  </Stack>
                  <IconButton
                    iconName={Icons.Close}
                    variant="plain"
                    size="small"
                    aria-label={`Удалить запрос: ${entry.query}`}
                    onClick={(e: React.MouseEvent) => {
                      e.stopPropagation();
                      handleDeleteHistory(entry.query);
                    }}
                  />
                </Stack>
              ))}
              {history.length > 0 && (
                <Button variant="ghost" size="small" onClick={handleClearHistory}>
                  Очистить историю
                </Button>
              )}
            </Stack>
          )}
        </Collapse>
      </Box>

      <Divider />

      {/* ── Results area ── */}
      <Box
        className="semantic-results-container"
        style={{
          overflowY: 'auto',
          flex: '1 1 0',
          minHeight: 0,
        }}
      >
        {isLoading ? (
          <ResultsSkeleton />
        ) : !hasSearched ? (
          <IdleState />
        ) : results.length === 0 && !error ? (
          <EmptyResultsState query={query} />
        ) : (
          <Stack direction="vertical" spacing="none" role="list">
            {results.map((result, index) => (
              <ResultCard
                key={`${result.dialogue_id}-${result.turn_index}-${index}`}
                result={result}
                onNavigate={handleResultClick}
                vote={votes[`${result.dialogue_id}-${result.turn_index}`] ?? null}
                onVote={handleVote}
              />
            ))}
          </Stack>
        )}
      </Box>

      {/* ── Results count footer ── */}
      {hasSearched && results.length > 0 && (
        <Box padding="x2">
          <Typography variant="caption" inactive>
            Найдено: {totalResults} результатов
          </Typography>
        </Box>
      )}
    </Box>
  );
});
