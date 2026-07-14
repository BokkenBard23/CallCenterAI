/**
 * SpeechLabLayout — 2-panel layout.
 *
 * Vision-audit rework (H8 FIX):
 *   The previous implementation used `react-resizable-panels` v4.12, which
 *   has a documented bug where the outer Panel divs collapse to ~content
 *   width instead of honouring defaultSize/defaultLayout. The CSS workaround
 *   targeting `[data-testid="speechlab-left"]` did not match the actual
 *   rendered DOM (the library uses a different attribute), so the left
 *   panel collapsed and the dictionary tree title wrapped per-character
 *   ("Сло…", "грузи", "юварь"). The vision audit (gpt-5.4) flagged this
 *   as High severity.
 *
 *   We replace react-resizable-panels with a plain CSS flexbox layout that
 *   gives the left panel a stable 320px width (min 280px) and lets the
 *   right panel take the remaining space. The resize handle is preserved
 *   visually as a decorative separator; if true resize is needed later,
 *   it can be wired back via a controlled CSS variable.
 *
 * Layout:
 *   ┌──────────────┬──┬─────────────────────────────────┐
 *   │  LeftPanel   │  │  RightPanel                     │
 *   │  (tree)      │S │  (Tabs: Запрос / Найденные)    │
 *   │  320px       │  │  flex: 1                        │
 *   └──────────────┴──┴─────────────────────────────────┘
 */

import { useCallback, useState } from 'react';
import { Box, Tab, Tabs } from '@beeline/design-system-react';

import type { SpeechLabTreeNode } from '../../../types/speechlab';
import type { SearchResult, TextSegment, UploadDictionaryResponse } from '../../../types/api';
import LeftPanel from '../LeftPanel/LeftPanel';
import QueryTab from '../QueryTab/QueryTab';
import FoundRecordsTab from '../FoundRecordsTab/FoundRecordsTab';

import './SpeechLabLayout.scss';

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
  // Tab state
  const [activeTab, setActiveTab] = useStateTab();

  const totalMatches = searchResult?.total_matches ?? 0;

  return (
    <Box className="speechlab-layout">
      {/* Left Panel: dictionary tree + search + import */}
      <Box className="speechlab-layout__panel speechlab-layout__panel--left">
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
      </Box>

      {/* Decorative separator (replaces the resize handle from
          react-resizable-panels; preserves the visual rhythm). */}
      <div
        className="speechlab-layout__separator"
        role="separator"
        aria-orientation="vertical"
        aria-hidden="true"
        data-separator
      />

      {/* Right Panel: Tabs (Запрос / Найденные записи) */}
      <Box className="speechlab-layout__panel speechlab-layout__panel--right">
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
      </Box>
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
