/**
 * MiningProgress — composed progress + checkpoint + cancel band.
 *
 * DS does NOT ship a dedicated "batch progress with checkpoint" component;
 * this composition uses Progress + Typography + Counter + Button (DS bundle
 * confirms all 4 ready). Two visual modes:
 *   - determinate (indexing): Progress shape="linear" value=N
 *   - indeterminate (LLM phase without ETA): Progress shape="animated" cycled
 *
 * Cancel button is `variant="ghost"` per design mapping; disabled when job is
 * not running (spec: "Cancel Button ghost; disabled when status!==running").
 */

import { memo } from 'react';
import {
  Box,
  Button,
  Counter,
  Progress,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import type { MiningJobStatus } from '../../../types/api';

export interface MiningProgressProps {
  /** Active job status payload (polling snapshot from useMiningState). */
  job: MiningJobStatus | null;
  /** Cancel handler — calls POST /mining/cancel/{job_id}. */
  onCancel: () => void;
  /** True when a cancel request is in-flight (disables the button). */
  cancelling?: boolean;
}

/**
 * Decide whether the progress band is determinate (value known) or
 * indeterminate (LLM phase / pending count). When total=0 or progress=0 but
 * status=running, treat as indeterminate.
 */
function isIndeterminate(job: MiningJobStatus): boolean {
  if (job.status === 'pending') return true;
  if (job.total_dialogues === 0) return true;
  if (job.progress === 0 && job.status === 'running') return true;
  return false;
}

function formatCheckpointTip(checkpointAt: string | null, job: MiningJobStatus): string {
  if (!checkpointAt) {
    return `Last checkpoint: нет, обработано ${job.processed_dialogues}/${job.total_dialogues}`;
  }
  return `Last checkpoint: ${checkpointAt}, обработано ${job.processed_dialogues}/${job.total_dialogues}`;
}

function MiningProgressBase({ job, onCancel, cancelling = false }: MiningProgressProps) {
  if (!job) return null;

  const indeterminate = isIndeterminate(job);
  const running = job.status === 'running' || job.status === 'pending';
  const tooltip = formatCheckpointTip(job.checkpoint_at, job);
  const statusText =
    job.total_dialogues > 0
      ? `Обработано ${job.processed_dialogues} из ${job.total_dialogues}`
      : job.status === 'running'
        ? 'Индексация корпуса…'
        : job.status === 'pending'
          ? 'Ожидание запуска…'
          : job.status === 'completed'
            ? `Индексация завершена: ${job.processed_dialogues} диалогов`
            : job.status === 'failed'
              ? 'Ошибка индексации'
              : job.status === 'cancelled'
                ? 'Операция отменена'
                : 'Частичные результаты';

  return (
    <Stack direction="vertical" gap="x2">
      <Stack direction="horizontal" gap="x3" align="center" wrap="wrap">
        <Box flexGrow={1} minWidth="200px">
          {indeterminate ? (
            <Progress shape="animated" cycled />
          ) : (
            <Progress
              shape="linear"
              value={Math.min(100, Math.max(0, Math.round(job.progress * 100)))}
            />
          )}
        </Box>
        <Counter count={job.processed_dialogues} tooltipTitle={tooltip} size="medium" />
        <Button
          variant="ghost"
          size="small"
          disabled={!running || cancelling}
          loading={cancelling}
          onClick={onCancel}
        >
          Отменить
        </Button>
      </Stack>
      <Typography variant="body2" color="colorTextInactive">
        {statusText}
      </Typography>
    </Stack>
  );
}

export const MiningProgress = memo(MiningProgressBase);
