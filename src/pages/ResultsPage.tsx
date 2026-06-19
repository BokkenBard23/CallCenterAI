/**
 * ResultsPage — displays analysis results with:
 *   - Sidebar (DictionaryTree) on the left
 *   - Main content (Tabs: Сводка / Выделенный текст) in the center
 *   - SemanticSearchPanel sidebar on the right (toggleable)
 *   - Cross-highlighting via HoverContext
 *   - Collapsible sidebars
 *   - "Векторизовать" ProgressButton
 *   - FRIDA status Badge
 *   - Theme toggle
 *   - Phrase Popover integration
 *
 * Routes: /results
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Banner,
  Box,
  IconButton,
  ProgressButton,
  Stack,
  Switch,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { indexDialogue, getEmbeddingStatus, ApiError } from '../api/client';
import { useAnalysisContext } from '../context/AnalysisContext';
import { HoverProvider } from '../context/HoverContext';
import useTheme from '../hooks/useTheme';
import SummaryView from '../components/SummaryView';
import HighlightedTextView from '../components/HighlightedTextView';
import DictionaryTree from '../components/DictionaryTree';
import PhrasePopover from '../components/PhrasePopover';
import SemanticSearchPanel from '../components/SemanticSearchPanel';
import type { DictMatch, DictionaryCondition } from '../types/api';

import '../components/SemanticSearchPanel/SemanticSearchPanel.scss';

export default function ResultsPage() {
  return (
    <HoverProvider>
      <ResultsPageContent />
    </HoverProvider>
  );
}

function ResultsPageContent() {
  const { state, dispatch } = useAnalysisContext();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  // Sidebar collapse state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Semantic search panel state
  const [semanticPanelOpen, setSemanticPanelOpen] = useState(false);

  // Phrase Popover state (Chunk 4)
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [popoverMatch, setPopoverMatch] = useState<DictMatch | null>(null);
  const [popoverCondition, setPopoverCondition] = useState<DictionaryCondition | null>(null);
  const [popoverAnchor, setPopoverAnchor] = useState<HTMLElement | null>(null);

  // Vectorize (index dialogue) state
  const [indexState, setIndexState] = useState<'default' | 'loading' | 'success' | 'error'>('default');
  const [indexError, setIndexError] = useState<string | null>(null);
  const indexAbortRef = useRef<AbortController | null>(null);

  // FRIDA status
  const [fridaStatus, setFridaStatus] = useState<import('../types/api').EmbeddingStatusResponse | null>(null);

  const handleBack = useCallback(() => {
    navigate('/');
  }, [navigate]);

  const handleViewModeChange = useCallback(
    (tabIndex: number) => {
      dispatch({
        type: 'SET_VIEW_MODE',
        payload: tabIndex === 0 ? 'summary' : 'highlighted',
      });
    },
    [dispatch],
  );

  const handleHideNoMatchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      dispatch({
        type: 'SET_HIDE_NO_MATCH',
        payload: e.target.checked,
      });
    },
    [dispatch],
  );

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  const toggleSemanticPanel = useCallback(() => {
    setSemanticPanelOpen((prev) => !prev);
  }, []);

  // ── Phrase Popover click handler (Chunk 4) ──
  const handleSegmentClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'MARK' && target instanceof HTMLElement) {
        // Find the match data from the clicked mark
        const phrase = target.getAttribute('data-phrase');
        const cascadeOrder = target.getAttribute('data-cascade-order');

        if (phrase && state.searchResult) {
          const match = state.searchResult.matches.find(
            (m) => m.phrase_text === phrase && m.cascade_order === Number(cascadeOrder),
          );
          if (match) {
            // Find corresponding condition
            const dictNodes = state.dictionaries.map((d) => d.response.dictionary).filter(Boolean);
            let condition: DictionaryCondition | null = null;
            for (const dict of dictNodes) {
              const found = findCondition(dict, phrase);
              if (found) {
                condition = found;
                break;
              }
            }

            // Toggle popover — if clicking the same mark, close it
            if (popoverOpen && popoverAnchor === target) {
              setPopoverOpen(false);
            } else {
              setPopoverMatch(match);
              setPopoverCondition(condition);
              setPopoverAnchor(target);
              setPopoverOpen(true);
            }
          }
        }
      }
    },
    [state.searchResult, state.dictionaries, popoverOpen, popoverAnchor],
  );

  const handlePopoverClose = useCallback(() => {
    setPopoverOpen(false);
  }, []);

  // ── Fetch FRIDA status on mount ──
  useEffect(() => {
    const controller = new AbortController();

    async function fetchStatus() {
      try {
        const status = await getEmbeddingStatus(controller.signal);
        setFridaStatus(status);
      } catch {
        // Status unavailable — FRIDA offline
      }
    }

    fetchStatus();
    return () => controller.abort();
  }, []);

  // ── Vectorize (index dialogue) handler ──
  const handleVectorize = useCallback(async () => {
    if (!state.sessionId) return;

    // Abort previous request
    if (indexAbortRef.current) {
      indexAbortRef.current.abort();
    }
    const controller = new AbortController();
    indexAbortRef.current = controller;

    setIndexState('loading');
    setIndexError(null);

    try {
      await indexDialogue(
        { session_id: state.sessionId },
        controller.signal,
      );
      setIndexState('success');
      // Refresh FRIDA status after indexing
      try {
        const status = await getEmbeddingStatus();
        setFridaStatus(status);
      } catch {
        // Ignore status refresh error
      }
    } catch (err) {
      if (controller.signal.aborted) return;

      if (err instanceof ApiError) {
        if (err.status === 503) {
          setIndexError('FRIDA недоступна');
        } else if (err.status === 429) {
          setIndexError('Слишком много запросов');
        } else {
          setIndexError(err.message);
        }
      } else {
        setIndexError('Ошибка при векторизации');
      }
      setIndexState('error');
    }
  }, [state.sessionId]);

  // ── Cross-highlighting: result click → scroll to turn ──
  const handleResultClick = useCallback((_dialogueId: string, turnIndex: number) => {
    // Scroll to the utterance in the dialog view
    const utteranceElement = document.querySelector(
      `[data-turn-index="${turnIndex}"]`,
    );
    if (utteranceElement) {
      utteranceElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Add temporary highlight class
      utteranceElement.classList.add('semantic-result-highlight');
      setTimeout(() => {
        utteranceElement.classList.remove('semantic-result-highlight');
      }, 2000);
    }
  }, []);

  // ─── Empty state: no results yet ──────────────────────
  if (!state.searchResult && !state.llmResult) {
    return (
      <Stack direction="vertical" spacing="x6" align="center">
        <Typography variant="h4">Результаты не найдены</Typography>
        <Typography variant="body1" inactive>
          Сначала загрузите диалог и выполните анализ.
        </Typography>
        <IconButton
          iconName={Icons.ArrowLeft}
          variant="outlined"
          aria-label="Назад к загрузке"
          onClick={handleBack}
        />
      </Stack>
    );
  }

  const activeTabIndex = state.viewMode === 'summary' ? 0 : 1;
  const fridaAvailable = fridaStatus?.frida_available ?? false;

  // Extract dictionary nodes from uploaded dictionaries
  const dictionaryNodes = state.dictionaries.map((d) => d.response.dictionary).filter(Boolean);

  return (
    <Stack direction="horizontal" spacing="none" style={{ minHeight: 0, flex: '1 1 0' }}>
      {/* ═══ Left Sidebar (Dictionary) ═══ */}
      {!sidebarCollapsed && (
        <Box
          className="results-sidebar"
          style={{
            width: '300px',
            flexShrink: 0,
            borderRight: '1px solid var(--color-border-default, #e0e0e0)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            backgroundColor: 'var(--color-background-secondary, #fafafa)',
          }}
        >
          <DictionaryTree
            dictionaries={dictionaryNodes as import('../types/api').DictionaryNode[]}
            searchResult={state.searchResult}
          />

          {/* Collapse button */}
          <Box
            padding="x2"
            style={{ borderTop: '1px solid var(--color-border-default, #e0e0e0)' }}
          >
            <IconButton
              iconName={Icons.Collapse}
              variant="plain"
              size="small"
              aria-label="Свернуть панель словаря"
              onClick={toggleSidebar}
            />
          </Box>
        </Box>
      )}

      {/* ═══ Main Content ═══ */}
      <Box style={{ flex: '1 1 0', minWidth: 0, overflow: 'auto' }}>
        <Stack direction="vertical" spacing="x4" style={{ padding: '0 0 0 16px' }}>
          {/* ── Header row ── */}
          <Stack direction="horizontal" spacing="x3" align="center" justify="space-between">
            <Stack direction="horizontal" spacing="x3" align="center">
              {/* Expand button (when sidebar collapsed) */}
              {sidebarCollapsed && (
                <IconButton
                  iconName={Icons.Expand}
                  variant="plain"
                  aria-label="Развернуть панель словаря"
                  onClick={toggleSidebar}
                />
              )}
              <IconButton
                iconName={Icons.ArrowLeft}
                variant="plain"
                aria-label="Назад к загрузке"
                onClick={handleBack}
              />
              <Typography variant="h4">Результаты анализа</Typography>
            </Stack>

            {/* ── Action buttons ── */}
            <Stack direction="horizontal" spacing="x2" align="center">
              {/* Vectorize button */}
              {state.sessionId && (
                <ProgressButton
                  variant="secondary"
                  size="small"
                  state={indexState}
                  determinateMode={false}
                  onClick={handleVectorize}
                  statusDelayTime={3000}
                >
                  Векторизовать
                </ProgressButton>
              )}

              {/* Semantic search toggle */}
              <Tooltip title="Семантический поиск">
                <IconButton
                  iconName={Icons.Search}
                  variant={semanticPanelOpen ? 'outlined' : 'plain'}
                  aria-label="Семантический поиск"
                  onClick={toggleSemanticPanel}
                  aria-pressed={semanticPanelOpen}
                />
              </Tooltip>

              {/* FRIDA status indicator */}
              <Tooltip
                title={
                  fridaAvailable
                    ? `FRIDA доступна · ${fridaStatus?.vectors_stored ?? 0} векторов`
                    : 'FRIDA недоступна'
                }
              >
                <Badge
                  type="tertiary"
                  semantic={fridaAvailable ? 'success' : 'danger'}
                  dot
                >
                  FRIDA
                </Badge>
              </Tooltip>
            </Stack>
          </Stack>

          {/* ── Indexing error message ── */}
          {indexError && (
            <Typography variant="caption" style={{ color: 'var(--color-text-danger, #e53935)' }}>
              {indexError}
            </Typography>
          )}

          {/* ── LLM warning banner ── */}
          {!state.llmResult && state.searchResult && (
            <Banner
              title="Сводка недоступна — LLM-анализ не выполнен или завершился с ошибкой"
              color="warning"
              iconName={Icons.Alarm}
            />
          )}

          {/* ── Tabs + controls ── */}
          <Stack direction="horizontal" spacing="x4" align="center" justify="space-between">
            <Tabs
              selectedTabIndex={activeTabIndex}
              onChange={handleViewModeChange}
            >
              <Tab label="Сводка" iconName={Icons.Chat}>
                <SummaryView
                  llmResult={state.llmResult}
                  searchResult={state.searchResult}
                />
              </Tab>
              <Tab label="Выделенный текст" iconName={Icons.Search}>
                <div onClick={handleSegmentClick}>
                  <HighlightedTextView
                    searchResult={state.searchResult}
                    hideNoMatch={state.hideNoMatch}
                  />
                </div>
              </Tab>
            </Tabs>

            <Stack direction="horizontal" spacing="x2" align="center">
              {state.viewMode === 'highlighted' && (
                <Switch
                  label="Скрыть без совпадений"
                  checked={state.hideNoMatch}
                  onChange={handleHideNoMatchChange}
                />
              )}
              <Tooltip
                title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}
              >
                <IconButton
                  iconName={
                    theme === 'light' ? Icons.HalfMoon : Icons.Sun
                  }
                  variant="plain"
                  aria-label={
                    theme === 'light'
                      ? 'Включить тёмную тему'
                      : 'Включить светлую тему'
                  }
                  onClick={toggleTheme}
                />
              </Tooltip>
            </Stack>
          </Stack>

          {/* ── Stats ── */}
          {state.searchResult && (
            <Box>
              <Typography variant="caption" inactive>
                Всего совпадений: {state.searchResult.total_matches} · Сегментов:{' '}
                {state.searchResult.segments.length}
              </Typography>
            </Box>
          )}
        </Stack>
      </Box>

      {/* ═══ Phrase Popover (Chunk 4) ═══ */}
      <PhrasePopover
        match={popoverMatch}
        condition={popoverCondition}
        open={popoverOpen}
        onClose={handlePopoverClose}
        anchorElement={popoverAnchor}
        sessionId={state.sessionId}
      />

      {/* ═══ Right Sidebar (SemanticSearchPanel) ═══ */}
      {semanticPanelOpen && (
        <>
          {/* Mobile backdrop */}
          <Box
            className="semantic-sidebar-backdrop"
            onClick={toggleSemanticPanel}
          />
          <Box className="semantic-sidebar">
            <SemanticSearchPanel
              sessionId={state.sessionId ?? undefined}
              onResultClick={handleResultClick}
              onClose={toggleSemanticPanel}
            />
          </Box>
        </>
      )}
    </Stack>
  );
}

// ═══════════════════════════════════════════════════════════
// Helper: find condition by phrase text in dictionary tree
// ═══════════════════════════════════════════════════════════

function findCondition(
  node: import('../types/api').DictionaryNode | null,
  phraseText: string,
): DictionaryCondition | null {
  if (!node) return null;
  const found = node.conditions.find((c) => c.text === phraseText);
  if (found) return found;
  for (const child of node.children) {
    const result = findCondition(child, phraseText);
    if (result) return result;
  }
  return null;
}
