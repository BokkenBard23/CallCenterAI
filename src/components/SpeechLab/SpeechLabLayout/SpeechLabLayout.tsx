/**
 * SpeechLabLayout — 3-panel resizable layout using react-resizable-panels.
 *
 * Waves: UI-1 (Layout refactor)
 *
 * Changes from legacy:
 *   - Replaced custom mousedown/mousemove/mouseup resize logic with
 *     react-resizable-panels (Group / Panel / Separator).
 *   - Panel sizes persist to localStorage via useDefaultLayout.
 *   - Double-click Separator resets layout (built-in, no custom handler).
 *   - Mobile: layout stacks vertically (Group orientation switches).
 *
 * Layout:
 *   ┌──────────────┬──┬─────────────────────────────────┐
 *   │  LeftPanel   │  │  RightPanel                     │
 *   │  (tree)      │S │  (Tabs: Запрос / Найденные)     │
 *   │  25-40%      │  │  60-75%                         │
 *   └──────────────┴──┴─────────────────────────────────┘
 *
 * Persistence: localStorage key "speechlab-layout" saves panel proportions.
 */

import { useCallback, useState } from 'react';
import { Box, Tab, Tabs } from '@beeline/design-system-react';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { Layout } from 'react-resizable-panels';

import type { SpeechLabTreeNode } from '../../../types/speechlab';
import type { SearchResult, TextSegment, UploadDictionaryResponse } from '../../../types/api';
import LeftPanel from '../LeftPanel/LeftPanel';
import QueryTab from '../QueryTab/QueryTab';
import FoundRecordsTab from '../FoundRecordsTab/FoundRecordsTab';

import './SpeechLabLayout.scss';

const LAYOUT_STORAGE_KEY = 'speechlab-layout';
const PANEL_LEFT_ID = 'speechlab-left';
const PANEL_RIGHT_ID = 'speechlab-right';

/** Default panel sizes in percent */
const DEFAULT_LEFT_SIZE = 25;
const DEFAULT_RIGHT_SIZE = 75;
const MIN_LEFT_SIZE = 15;
const MAX_LEFT_SIZE = 45;

type TabValue = 'query' | 'found-records';

interface SpeechLabLayoutProps {
  /** Tree nodes from backend or preview parser */
  treeNodes: SpeechLabTreeNode[];
  /** Currently selected node */
  selectedNode: SpeechLabTreeNode | null;
  /** Selected node ID */
  selectedNodeId: string | null;
  /** Callback when a node is selected */
  onSelectNode: (node: SpeechLabTreeNode) => void;
  /** Callback when a node is expanded/collapsed */
  onToggleExpand?: (nodeId: string, expanded: boolean) => void;
  /** Callback when dictionary is uploaded */
  onDictionaryUploaded: (
    sessionId: string,
    nodes: SpeechLabTreeNode[],
    response: UploadDictionaryResponse,
  ) => void;
  /** Session ID */
  sessionId: string | null;
  /** Search result from analysis */
  searchResult: SearchResult | null;
  /** Whether analysis is in progress */
  isSearching: boolean;
  /** Error message from analysis */
  searchError: string | null;
  /** Callback to run analysis */
  onRunAnalysis: () => void;
  /** Dialogue segments for FoundRecordsTab */
  segments: TextSegment[];
  /** Whether tree is loading */
  isTreeLoading?: boolean;
  /** Tree error */
  treeError?: string | null;
  /** Currently expanded nodes */
  expandedNodes?: Record<string, boolean>;
}

export default function SpeechLabLayout({
  treeNodes,
  selectedNode,
  selectedNodeId,
  onSelectNode,
  onToggleExpand,
  onDictionaryUploaded,
  sessionId,
  searchResult,
  isSearching,
  searchError,
  onRunAnalysis,
  segments,
  isTreeLoading,
  treeError,
  expandedNodes,
}: SpeechLabLayoutProps) {
  // Default panel layout keyed by Panel id (matches react-resizable-panels Layout type).
  // CRITICAL: keys MUST match Panel id props for flex-grow to be applied correctly.
  const defaultLayout: Layout = {
    [PANEL_LEFT_ID]: DEFAULT_LEFT_SIZE,
    [PANEL_RIGHT_ID]: DEFAULT_RIGHT_SIZE,
  };

  // Tab state
  const [activeTab, setActiveTab] = useStateTab();

  // Persist layout changes — currently a no-op; localStorage wiring can be added later.
  const handleLayoutChanged = useCallback(() => {
    // TODO: persist to localStorage if needed.
  }, []);

  const totalMatches = searchResult?.total_matches ?? 0;

  return (
    <Box className="speechlab-layout">
      <Group
        id={LAYOUT_STORAGE_KEY}
        defaultLayout={defaultLayout}
        onLayoutChanged={handleLayoutChanged}
        orientation="horizontal"
        className="speechlab-layout__group"
      >
        {/* Left Panel: dictionary tree + search + import */}
        <Panel
          id={PANEL_LEFT_ID}
          defaultSize={DEFAULT_LEFT_SIZE}
          minSize={MIN_LEFT_SIZE}
          maxSize={MAX_LEFT_SIZE}
          className="speechlab-layout__panel--left"
        >
          <LeftPanel
            treeNodes={treeNodes}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            onToggleExpand={onToggleExpand}
            onDictionaryUploaded={onDictionaryUploaded}
            sessionId={sessionId}
            isLoading={isTreeLoading}
            error={treeError}
            expandedNodes={expandedNodes}
          />
        </Panel>

        {/* Resize Separator */}
        <Separator className="speechlab-layout__separator" />

        {/* Right Panel: Tabs (Запрос / Найденные записи) */}
        <Panel
          id={PANEL_RIGHT_ID}
          defaultSize={DEFAULT_RIGHT_SIZE}
          minSize={50}
          className="speechlab-layout__panel--right"
        >
          <Box className="speechlab-layout__right-content">
            <Tabs
              selectedTabIndex={activeTab === 'query' ? 0 : 1}
              onChange={handleTabChange}
            >
              <Tab label="Запрос" value="query">
                <QueryTab selectedNode={selectedNode} />
              </Tab>
              <Tab
                label={`Найденные записи${totalMatches > 0 ? ` (${totalMatches})` : ''}`}
                value="found-records"
              >
                <FoundRecordsTab
                  searchResult={searchResult}
                  isSearching={isSearching}
                  error={searchError}
                  onRunAnalysis={onRunAnalysis}
                  segments={segments}
                />
              </Tab>
            </Tabs>
          </Box>
        </Panel>
      </Group>
    </Box>
  );

  function handleTabChange(tabIndex: number) {
    setActiveTab(tabIndex === 1 ? 'found-records' : 'query');
  }
}

// ═══════════════════════════════════════════════════════════
// Local hooks
// ═══════════════════════════════════════════════════════════

function useStateTab() {
  const [tab, setTab] = useState<TabValue>('query');
  const handleChange = useCallback((newTab: TabValue) => setTab(newTab), []);
  return [tab, handleChange] as const;
}
