/**
 * ResultsPage — displays analysis results with:
 *   - Responsive layout: 3-col desktop → 2-col tablet → 1-col mobile
 *   - NavigationDrawer for mobile sidebar (DictionaryTree)
 *   - Tabs with proper TabPanel a11y pattern
 *   - NumberTicker for animated match counts
 *   - BlurFade for smooth card appearance
 *   - DS tokens for all colors/spacing (no inline hard-coded values)
 *   - SemanticSearchPanel responsive (side-sheet desktop, overlay mobile)
 *   - Cross-highlighting via HoverContext
 *   - "Векторизовать" ProgressButton
 *   - FRIDA status Badge
 *   - LLM loading progress bar
 *   - Phrase Popover integration (Chunk 4)
 *
 * Routes: /results
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Banner,
  Box,
  Button,
  Icon,
  IconButton,
  InlineAlert,
  NavigationDrawer,
  Progress,
  ProgressButton,
  Stack,
  Switch,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { indexDialogue, getEmbeddingStatus, exportExcel, exportPdf, ApiError } from '../api/client';
import { useAnalysisContext } from '../context/AnalysisContext';
import { HoverProvider } from '../context/HoverContext';
import SummaryView from '../components/SummaryView';
import HighlightedTextView from '../components/HighlightedTextView';
import DictionaryTree from '../components/DictionaryTree';
import PhrasePopover from '../components/PhrasePopover';
import SemanticSearchPanel from '../components/SemanticSearchPanel';
import MatchCounter from '../components/MatchCounter/MatchCounter';
import { QualityScorePanel } from '../components/QualityScorePanel';
import { BlurFade } from '../components/ui/blur-fade';
import type { Group as NavGroup } from '@beeline/design-system-react';
import type { DictMatch, DictionaryCondition, DictionaryNode, EmbeddingStatusResponse, ViewMode } from '../types/api';

import './ResultsPage.scss';
import '../components/SemanticSearchPanel/SemanticSearchPanel.scss';

// ═══════════════════════════════════════════════════════════
// Responsive breakpoint hook
// ═══════════════════════════════════════════════════════════

interface BreakpointState {
  isMobile: boolean;   // < 768px
  isTablet: boolean;   // 768 – 1023px
  isDesktop: boolean;  // >= 1024px
}

function useBreakpoints(): BreakpointState {
  const [state, setState] = useState<BreakpointState>(() => ({
    isMobile: window.innerWidth < 768,
    isTablet: window.innerWidth >= 768 && window.innerWidth < 1024,
    isDesktop: window.innerWidth >= 1024,
  }));

  useEffect(() => {
    const handleResize = () => {
      const w = window.innerWidth;
      setState({
        isMobile: w < 768,
        isTablet: w >= 768 && w < 1024,
        isDesktop: w >= 1024,
      });
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return state;
}

// ═══════════════════════════════════════════════════════════
// NavigationDrawer items for DictionaryTree
// ═══════════════════════════════════════════════════════════

function buildNavItems(
  dictionaries: DictionaryNode[],
): NavGroup[] {
  return [
    {
      name: 'Словарь',
      children: dictionaries.map((d) => ({
        name: d.name,
        path: d.id,
        icon: Icons.Folder,
      })),
    },
  ];
}

// ═══════════════════════════════════════════════════════════
// Loading skeleton
// ═══════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════

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
  const breakpoints = useBreakpoints();
  const { isMobile, isTablet, isDesktop } = breakpoints;

  // Sidebar collapse state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Mobile drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);

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
  const [fridaStatus, setFridaStatus] = useState<EmbeddingStatusResponse | null>(null);

  // Export state
  const [exportExcelLoading, setExportExcelLoading] = useState(false);
  const [exportPdfLoading, setExportPdfLoading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportAbortRef = useRef<AbortController | null>(null);

  const handleBack = useCallback(() => {
    navigate('/');
  }, [navigate]);

  const handleViewModeChange = useCallback(
    (tabIndex: number) => {
      const mode: ViewMode =
        tabIndex === 0 ? 'summary' : tabIndex === 1 ? 'highlighted' : 'structure';
      dispatch({
        type: 'SET_VIEW_MODE',
        payload: mode,
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
        const phrase = target.getAttribute('data-phrase');
        const cascadeOrder = target.getAttribute('data-cascade-order');

        if (phrase && state.searchResult) {
          const match = state.searchResult.matches.find(
            (m) => m.phrase_text === phrase && m.cascade_order === Number(cascadeOrder),
          );
          if (match) {
            const dictNodes = state.dictionaries.map((d) => d.response.dictionary).filter(Boolean);
            let condition: DictionaryCondition | null = null;
            for (const dict of dictNodes) {
              const found = findCondition(dict, phrase);
              if (found) {
                condition = found;
                break;
              }
            }

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

  // ── Handle highlight-click custom event (Chunk 4) ──
  useEffect(() => {
    const handleHighlightClick = (e: Event) => {
      const customEvent = e as CustomEvent;
      const { phrase, cascadeOrder, element } = customEvent.detail;

      if (phrase && state.searchResult) {
        const match = state.searchResult.matches.find(
          (m) => m.phrase_text === phrase && m.cascade_order === Number(cascadeOrder),
        );
        if (match) {
          const dictNodes = state.dictionaries.map((d) => d.response.dictionary).filter(Boolean);
          let condition: DictionaryCondition | null = null;
          for (const dict of dictNodes) {
            const found = findCondition(dict, phrase);
            if (found) {
              condition = found;
              break;
            }
          }

          setPopoverMatch(match);
          setPopoverCondition(condition);
          setPopoverAnchor(element as HTMLElement);
          setPopoverOpen(true);
        }
      }
    };

    document.addEventListener('highlight-click', handleHighlightClick as EventListener);
    return () => document.removeEventListener('highlight-click', handleHighlightClick as EventListener);
  }, [state.searchResult, state.dictionaries]);

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

  // ── Export Excel handler ──
  const handleExportExcel = useCallback(async () => {
    if (!state.sessionId) return;

    exportAbortRef.current?.abort();
    const controller = new AbortController();
    exportAbortRef.current = controller;

    setExportExcelLoading(true);
    setExportError(null);

    try {
      const blob = await exportExcel(state.sessionId, controller.signal);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analysis_${state.sessionId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (controller.signal.aborted) return;
      setExportError(err instanceof ApiError ? err.message : 'Ошибка при экспорте Excel');
    } finally {
      if (!controller.signal.aborted) {
        setExportExcelLoading(false);
      }
    }
  }, [state.sessionId]);

  // ── Export PDF handler ──
  const handleExportPdf = useCallback(async () => {
    if (!state.sessionId) return;

    exportAbortRef.current?.abort();
    const controller = new AbortController();
    exportAbortRef.current = controller;

    setExportPdfLoading(true);
    setExportError(null);

    try {
      const blob = await exportPdf(state.sessionId, controller.signal);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analysis_${state.sessionId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (controller.signal.aborted) return;
      setExportError(err instanceof ApiError ? err.message : 'Ошибка при экспорте PDF');
    } finally {
      if (!controller.signal.aborted) {
        setExportPdfLoading(false);
      }
    }
  }, [state.sessionId]);

  // ── Cross-highlighting: result click → scroll to turn ──
  const handleResultClick = useCallback((_dialogueId: string, turnIndex: number) => {
    const utteranceElement = document.querySelector(
      `[data-turn-index="${turnIndex}"]`,
    );
    if (utteranceElement) {
      utteranceElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      utteranceElement.classList.add('semantic-result-highlight');
      setTimeout(() => {
        utteranceElement.classList.remove('semantic-result-highlight');
      }, 2000);
    }
  }, []);

  // ── NavigationDrawer item click ──
  const handleDrawerItemClick = useCallback(
    () => {
      // Close drawer on mobile after item click
      if (!isDesktop) {
        setDrawerOpen(false);
      }
    },
    [isDesktop],
  );

  // ─── Derived values ──────────────────────────────────
  const activeTabIndex = state.viewMode === 'summary' ? 0 : state.viewMode === 'highlighted' ? 1 : 2;
  const fridaAvailable = fridaStatus?.frida_available ?? false;
  const dictionaryNodes = state.dictionaries.map((d) => d.response.dictionary).filter(Boolean);

  const navItems = useMemo(
    () => buildNavItems(dictionaryNodes as DictionaryNode[]),
    [dictionaryNodes],
  );

  // ─── Empty state: no results yet ──────────────────────
  if (!state.searchResult && !state.llmResult) {
    return (
      <Stack direction="vertical" spacing="x6" align="center">
        <Typography variant="h1" style={{ margin: 0 }}>Результаты не найдены</Typography>
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

  // ─── Main layout ─────────────────────────────────────
  return (
    <Box style={{ display: 'flex', minHeight: 0, flex: '1 1 0' }} aria-label="Результаты анализа">
      {/* ═══ Left Sidebar (Dictionary) — Desktop only ═══ */}
      {isDesktop && !sidebarCollapsed && (
        <Box className="results-sidebar">
          <DictionaryTree
            dictionaries={dictionaryNodes as DictionaryNode[]}
            searchResult={state.searchResult}
          />

          {/* Collapse button */}
          <Box className="results-sidebar__collapse">
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

      {/* ═══ NavigationDrawer for mobile/tablet ═══ */}
      {!isDesktop && (
        <NavigationDrawer
          groups={navItems}
          isOpen={drawerOpen}
          onOpen={() => setDrawerOpen(true)}
          onClose={() => setDrawerOpen(false)}
          onClickItem={handleDrawerItemClick}
          disableMobileView={false}
        />
      )}

      {/* ═══ Main Content Area ═══ */}
      <Box className="results-main">
        <Stack direction="vertical" spacing="x4" style={{ padding: '0 0 0 var(--sizeSpacingX4, 16px)' }}>
          {/* ── Header row ── */}
          <Stack direction="horizontal" spacing="x3" align="center" justify="space-between">
            <Stack direction="horizontal" spacing="x3" align="center">
              {/* Burger button — mobile/tablet only */}
              {!isDesktop && (
                <IconButton
                  iconName={Icons.Menu}
                  variant="plain"
                  aria-label="Открыть панель словаря"
                  onClick={() => setDrawerOpen(true)}
                />
              )}

              {/* Expand button (when desktop sidebar collapsed) */}
              {isDesktop && sidebarCollapsed && (
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
              <Typography variant="h1" style={{ margin: 0 }}>Результаты анализа</Typography>
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

              {/* Export Excel button */}
              {state.sessionId && !isMobile && (
                <Button
                  variant="outlined"
                  size="small"
                  disabled={exportExcelLoading}
                  onClick={handleExportExcel}
                  startIcon={<Icon iconName={Icons.Download} />}
                >
                  {exportExcelLoading ? 'Выгрузка…' : 'Excel'}
                </Button>
              )}

              {/* Export PDF button */}
              {state.sessionId && !isMobile && (
                <Button
                  variant="outlined"
                  size="small"
                  disabled={exportPdfLoading}
                  onClick={handleExportPdf}
                  startIcon={<Icon iconName={Icons.Download} />}
                >
                  {exportPdfLoading ? 'Выгрузка…' : 'PDF'}
                </Button>
              )}

              {/* FRIDA status indicator */}
              <Tooltip
                title={
                  fridaAvailable
                    ? `FRIDA доступна · ${fridaStatus?.vectors_stored ?? 0} векторов`
                    : 'FRIDA недоступна'
                }
              >
                <span>
                  <Badge
                    type="tertiary"
                    semantic={fridaAvailable ? 'success' : 'danger'}
                    dot
                  >
                    FRIDA
                  </Badge>
                </span>
              </Tooltip>
            </Stack>
          </Stack>

          {/* ── Indexing error message ── */}
          {indexError && (
            <Typography variant="caption" className="text-error">
              {indexError}
            </Typography>
          )}

          {/* ── Export error message ── */}
          {exportError && (
            <InlineAlert type="error" iconName={Icons.WarningCircled}>
              {exportError}
            </InlineAlert>
          )}

          {/* ── LLM loading state ── */}
          {state.llmLoading && (
            <Stack direction="vertical" spacing="x2">
              <Typography variant="body2" className="text-info">
                LLM-анализ выполняется...
              </Typography>
              <Progress shape="animated" cycled />
            </Stack>
          )}

          {/* ── LLM result unavailable (after loading complete) ── */}
          {!state.llmLoading && !state.llmResult && state.searchResult && (
            <Banner
              title="LLM-сводка недоступна — анализ не выполнен или завершился с ошибкой"
              color="warning"
              iconName={Icons.Alarm}
            />
          )}

          {/* ── Stats with NumberTicker ── */}
          {state.searchResult && (
            <BlurFade delay={0} duration={0.4} direction="up" inView={true}>
              <Box className="results-stats">
                <MatchCounter
                  count={state.searchResult.total_matches}
                  label="Совпадений:"
                  variant={state.searchResult.total_matches > 0 ? 'success' : 'default'}
                />
                <Stack direction="horizontal" spacing="x1" align="baseline">
                  <Typography variant="caption" inactive>
                    Сегментов:
                  </Typography>
                  <Typography variant="body2">
                    {state.searchResult.segments.length}
                  </Typography>
                </Stack>
              </Box>
            </BlurFade>
          )}

          {/* ── Tabs + controls ── */}
          <Stack direction="horizontal" spacing="x4" align="center" justify="space-between">
            <Tabs
              selectedTabIndex={activeTabIndex}
              onChange={handleViewModeChange}
            >
              <Tab label="Сводка" iconName={Icons.Chat}>
                <div
                  role="tabpanel"
                  aria-labelledby="tab-summary"
                  className="results-tabpanel"
                >
                  <BlurFade delay={0.1} duration={0.4} direction="up" inView={true}>
                    <SummaryView
                      llmResult={state.llmResult}
                      searchResult={state.searchResult}
                      llmLoading={state.llmLoading}
                    />
                  </BlurFade>
                </div>
              </Tab>
              <Tab label="Выделенный текст" iconName={Icons.Search}>
                <div
                  role="tabpanel"
                  aria-labelledby="tab-highlighted"
                  className="results-tabpanel"
                >
                  <div onClick={handleSegmentClick} onPointerDown={(e) => e.stopPropagation()}>
                    <HighlightedTextView
                      searchResult={state.searchResult}
                      hideNoMatch={state.hideNoMatch}
                    />
                  </div>
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
            </Stack>
          </Stack>

          {/* ── Quality Score Panel (load on demand) ── */}
          {state.sessionId && (
            <BlurFade delay={0.3} duration={0.4} direction="up" inView={true}>
              <QualityScorePanel sessionId={state.sessionId} />
            </BlurFade>
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
      {semanticPanelOpen && isDesktop && (
        <Box className="results-semantic-panel">
          <SemanticSearchPanel
            sessionId={state.sessionId ?? undefined}
            onResultClick={handleResultClick}
            onClose={toggleSemanticPanel}
          />
        </Box>
      )}

      {/* Mobile semantic panel: fullscreen overlay */}
      {semanticPanelOpen && isMobile && (
        <Box className="results-semantic-panel--mobile">
          <Box padding="x4">
            <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
              <Typography variant="h5">Семантический поиск</Typography>
              <IconButton
                iconName={Icons.Close}
                variant="plain"
                aria-label="Закрыть"
                onClick={toggleSemanticPanel}
              />
            </Stack>
          </Box>
          <SemanticSearchPanel
            sessionId={state.sessionId ?? undefined}
            onResultClick={handleResultClick}
            onClose={toggleSemanticPanel}
          />
        </Box>
      )}

      {/* Tablet semantic panel: side sheet (same as desktop but narrower context) */}
      {semanticPanelOpen && isTablet && (
        <Box className="results-semantic-panel">
          <SemanticSearchPanel
            sessionId={state.sessionId ?? undefined}
            onResultClick={handleResultClick}
            onClose={toggleSemanticPanel}
          />
        </Box>
      )}
    </Box>
  );
}

// ═══════════════════════════════════════════════════════════
// Helper: find condition by phrase text in dictionary tree
// ═══════════════════════════════════════════════════════════

function findCondition(
  node: DictionaryNode | null,
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
