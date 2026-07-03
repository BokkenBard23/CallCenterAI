/**
 * SpeechLabPage — main page for SpeechLab UI.
 *
 * AUTONOMOUS: works without leaving the page.
 *   1. Load XML dictionary → see tree + tokens immediately (preview parser)
 *   2. Upload XML to backend → full data with attributes, saved_state
 *   3. Load RTF dialog → session created → "Найти в диалогах" works
 *
 * All operations happen within /speechlab — no redirect to / needed.
 *
 * Refactored from 357-line monolith into extracted components:
 *   - useSpeechLabState hook (state + callbacks)
 *   - SpeechLabTopBar (RTF status bar)
 *   - SpeechLabRtfDialog (RTF upload dialog)
 *   - SpeechLabLayout (3-panel layout — unchanged API)
 */

import { Box } from '@beeline/design-system-react';

import { useAnalysisContext } from '../context/AnalysisContext';
import { HoverProvider } from '../context/HoverContext';
import { useSpeechLabState } from '../hooks/useSpeechLabState';
import SpeechLabLayout from '../components/SpeechLab/SpeechLabLayout/SpeechLabLayout';
import SpeechLabTopBar from '../components/SpeechLab/SpeechLabTopBar';
import SpeechLabRtfDialog from '../components/SpeechLab/SpeechLabRtfDialog';

export default function SpeechLabPage() {
  return (
    <HoverProvider>
      <SpeechLabPageContent />
    </HoverProvider>
  );
}

function SpeechLabPageContent() {
  const { state: ctxState } = useAnalysisContext();
  const { state, actions, derived } = useSpeechLabState();

  return (
    <Box style={{ height: 'calc(100vh - 56px)', display: 'flex', flexDirection: 'column' }} aria-label="SpeechLab — анализ диалогов">
      {/* P1-1: H1 for accessibility (visually hidden) */}
      <h1 className="sr-only">SpeechLab</h1>

      {/* Top bar: RTF session status or prompt */}
      <SpeechLabTopBar
        hasSession={derived.hasSession}
        dialogueLength={ctxState.dialogue?.length ?? 0}
        onOpenRtfDialog={actions.openRtfDialog}
      />

      {/* 3-panel SpeechLab layout */}
      <Box style={{ flex: 1, minHeight: 0 }}>
        <SpeechLabLayout
          treeNodes={derived.effectiveTreeNodes}
          selectedNode={derived.selectedNode}
          selectedNodeId={state.selectedNodeId}
          onSelectNode={actions.handleSelectNode}
          onToggleExpand={actions.handleToggleExpand}
          onDictionaryUploaded={actions.handleDictionaryUploaded}
          sessionId={ctxState.sessionId ?? null}
          searchResult={ctxState.searchResult}
          isSearching={derived.isSearching}
          searchError={derived.searchError}
          onRunAnalysis={actions.handleRunAnalysis}
          segments={ctxState.dialogue ?? []}
          isTreeLoading={false}
          treeError={null}
          expandedNodes={state.expandedNodes}
        />
      </Box>

      {/* RTF Upload Dialog */}
      <SpeechLabRtfDialog
        open={state.rtfDialogOpen}
        fileName={state.rtfFileName}
        uploading={state.rtfUploading}
        error={state.rtfError}
        onFileSelect={actions.handleRtfSelect}
        onUpload={actions.handleRtfUpload}
        onClose={actions.closeRtfDialog}
      />
    </Box>
  );
}
