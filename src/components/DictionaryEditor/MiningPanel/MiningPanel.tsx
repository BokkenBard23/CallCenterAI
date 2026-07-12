/**
 * MiningPanel — main component for Track B Quick Win.
 *
 * Composes:
 *   <Stack vertical>
 *     <DirectoryPicker ... />                // MP-GAP-1 controlled fallback
 *     <Button primary loading onClick={handleIndex}>Обработать</Button>
 *     <MiningProgress job={indexJob} onCancel={handleCancelIndex} />
 *     <Divider />
 *     <Tabs selectedTabIndex={tab} onChange={setTab}>
 *       <Tab label="Похожие на фразы">    <SimilarDialoguesTab ... /></Tab>
 *       <Tab label="False Negatives">    <FalseNegativesTab ... /></Tab>
 *       <Tab label="LLM-аудит"> <DictAuditTab ... /></Tab>
 *     </Tabs>
 *   </Stack>
 *
 * State is owned by `useMiningState` (custom polling hook, NOT TanStack Query).
 * Directory picker state + tab state is local.
 */

import { memo, useCallback, useState } from 'react';
import {
  Divider,
  InlineAlert,
  Stack,
  Tabs,
  Typography,
} from '@beeline/design-system-react';
import { useMiningState } from '../../../hooks/useMiningState';
import type { DictionarySuggestion, DictionaryNode } from '../../../types/api';
import { DirectoryPicker, type PickedFile } from './DirectoryPicker';
import { MiningProgress } from './MiningProgress';
import { SimilarDialoguesTab } from './SimilarDialoguesTab';
import { FalseNegativesTab } from './FalseNegativesTab';
import { DictAuditTab } from './DictAuditTab';
import './MiningPanel.css';

export interface MiningPanelProps {
  /** Route session id. */
  sessionId: string;
  /** Root dictionary name (from DictionaryEditorPage — selected root). */
  dictionaryId: string | null;
  /** Editor tree for PhraseGroupSelect options. */
  tree: DictionaryNode[];
  /** Click-to-add handler — delegates to DictionaryEditorPage.handleAddSuggestion. */
  onAddSuggestion: (suggestion: DictionarySuggestion) => Promise<void> | void;
}

type TabKey = 'similar' | 'fn' | 'audit';
const TAB_KEYS: TabKey[] = ['similar', 'fn', 'audit'];

function MiningPanelBase({
  sessionId,
  dictionaryId,
  tree,
  onAddSuggestion,
}: MiningPanelProps) {
  const mining = useMiningState(sessionId);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [directoryLabel, setDirectoryLabel] = useState<string | null>(null);
  const [fileCount, setFileCount] = useState(0);
  const [tab, setTab] = useState<number>(0);

  const activeTab = TAB_KEYS[tab] ?? 'similar';

  // Build a directory_path that the backend can resolve. webkitRelativePath
  // exposes folderName/sub/file.rtf; for Quick Win we send a joined label.
  // The BE is expected to walk the picked directory server-side (frontend
  // sandbox cannot expose absolute paths). For Quick Win demo we send the
  // top-level folder label and the BE matches against the configured corpus
  // directory via env var MINING_CORPUS_ROOT.
  const directoryPath = directoryLabel ?? '';

  const handleConfirm = useCallback(
    (_files: PickedFile[], label: string) => {
      setDirectoryLabel(label);
      setFileCount(_files.length);
      setPickerOpen(false);
    },
    [],
  );

  const handleIndex = useCallback(() => {
    if (!dictionaryId) return;
    void mining.indexCorpus(directoryPath, dictionaryId);
  }, [dictionaryId, directoryPath, mining]);

  const handleCancelIndex = useCallback(() => {
    if (mining.indexJob) {
      void mining.cancelJob(mining.indexJob.job_id);
    }
  }, [mining]);

  const handleCancelFN = useCallback(() => {
    if (mining.fnJob) {
      void mining.cancelJob(mining.fnJob.job_id);
    }
  }, [mining]);

  const handleCancelAudit = useCallback(() => {
    if (mining.auditJob) {
      void mining.cancelJob(mining.auditJob.job_id);
    }
  }, [mining]);

  const indexing = mining.indexJob?.status === 'pending' || mining.indexJob?.status === 'running';
  const indexError = mining.indexJob?.status === 'failed' ? mining.indexJob.error : mining.errors.index;
  const indexPartial = mining.indexJob?.status === 'partial';
  const indexCancelled = mining.indexJob?.status === 'cancelled';

  const indexJobId =
    mining.indexJob && (mining.indexJob.status === 'completed' || mining.indexJob.status === 'partial')
      ? mining.indexJob.job_id
      : null;

  return (
    <Stack
      direction="vertical"
      gap="x4"
      style={{ padding: 'var(--size-spacing-x4)' }}
      className="mining-panel"
    >
      {/* Picker row (medium density) */}
      <Stack
        direction="horizontal"
        gap="x3"
        align="center"
        wrap="wrap"
        className="mining-panel__picker-row"
      >
        <DirectoryPicker
          directoryLabel={directoryLabel}
          fileCount={fileCount}
          open={pickerOpen}
          onOpen={() => setPickerOpen(true)}
          onClose={() => setPickerOpen(false)}
          onConfirm={handleConfirm}
        />
        <Divider type="vertical" isDecorative />
        <ButtonPrimaryInline
          loading={indexing}
          disabled={!directoryLabel || !dictionaryId || indexing}
          onClick={handleIndex}
        >
          Обработать
        </ButtonPrimaryInline>
        {!dictionaryId && (
          <Typography variant="caption" color="colorTextInactive">
            Выберите словарь в дереве, чтобы включить обработку.
          </Typography>
        )}
      </Stack>

      {/* Progress band (only when job exists) */}
      {mining.indexJob && (
        <MiningProgress
          job={mining.indexJob}
          onCancel={handleCancelIndex}
          cancelling={mining.cancelling}
        />
      )}

      {indexError && <InlineAlert type="error">{indexError}</InlineAlert>}
      {indexPartial && mining.indexJob?.warning && (
        <InlineAlert type="warning">{mining.indexJob.warning}</InlineAlert>
      )}
      {indexCancelled && (
        <InlineAlert type="info">
          Операция отменена. Обработано {mining.indexJob?.processed_dialogues ?? 0}
          из {mining.indexJob?.total_dialogues ?? 0} до отмены.
        </InlineAlert>
      )}

      <Divider type="horizontal" isDecorative />

      <Tabs selectedTabIndex={tab} onChange={(idx) => setTab(idx)}>
        {/* Each Tab renders its content unconditionally; children wrap
            internal state guards (empty/loading/error states). */}
        <Tab label="Похожие на фразы">
          <SimilarDialoguesTab
            sessionId={sessionId}
            jobId={indexJobId}
            tree={tree}
            loading={mining.loadingSimilar}
            error={mining.errors.findSimilar}
            results={mining.similarResults?.dialogues ?? []}
            onFindSimilar={mining.findSimilar}
          />
        </Tab>
        <Tab label="False Negatives">
          <FalseNegativesTab
            jobId={indexJobId}
            loading={mining.loadingFN}
            error={mining.errors.findFN}
            candidates={mining.fnCandidates ?? []}
            partial={mining.fnPartial}
            expectedTotal={mining.fnJob?.total_dialogues}
            onAddSuggestion={onAddSuggestion}
            onFindFN={() => {
              if (!dictionaryId || !indexJobId) return;
              void mining.findFalseNegatives(dictionaryId, 0.7);
            }}
            cancelling={mining.cancelling}
            onCancel={handleCancelFN}
          />
        </Tab>
        <Tab label="LLM-аудит">
          <DictAuditTab
            jobId={indexJobId}
            loading={mining.loadingAudit}
            error={mining.errors.audit}
            results={mining.auditResults ?? []}
            partial={mining.auditPartial}
            onAddSuggestion={onAddSuggestion}
            onAudit={() => {
              if (!dictionaryId || !indexJobId) return;
              void mining.auditDictionary(dictionaryId);
            }}
            cancelling={mining.cancelling}
            onCancel={handleCancelAudit}
          />
        </Tab>
      </Tabs>

      {/* Hidden hint to ease testing — exposes active tab key for assertions. */}
      <span hidden aria-hidden data-testid="mining-panel-active-tab" data-tab={activeTab} />
    </Stack>
  );
}

/**
 * Thin inline wrapper so we can keep the Button primary import in a single
 * place and avoid importing Button at the top of the panel for just one usage.
 * Keeps file size predictable and avoids lint noise on the inline JSX.
 */
import { Button as ButtonPrimaryInlineAlias } from '@beeline/design-system-react';
import { Tab as TabComponent } from '@beeline/design-system-react';

function ButtonPrimaryInline(
  props: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    loading?: boolean;
    disabled?: boolean;
    onClick?: () => void;
    children: React.ReactNode;
  },
) {
  const { loading, disabled, onClick, children, ...rest } = props;
  return (
    <ButtonPrimaryInlineAlias
      variant="primary"
      loading={loading}
      disabled={disabled}
      onClick={onClick}
      {...rest}
    >
      {children}
    </ButtonPrimaryInlineAlias>
  );
}

// Aliases used in JSX above (Tabs render <Tab> children).
const Tab = TabComponent;

export const MiningPanel = memo(MiningPanelBase);
