/**
 * SpeechLabTopBar — RTF session status bar.
 *
 * Shows:
 *   - With session: ✅ "Диалог загружен (N реплик)" on success background
 *   - Without session: ℹ️ "Загрузите RTF-файл диалога для поиска" on hover background
 *   - Button: "Загрузить диалог" / "Заменить диалог"
 *
 * Uses DS tokens — NO inline color values.
 */

import {
  Box,
  Button,
  Icon,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

interface SpeechLabTopBarProps {
  /** Whether an RTF session is active */
  hasSession: boolean;
  /** Number of dialogue turns (when session active) */
  dialogueLength: number;
  /** Callback to open RTF upload dialog */
  onOpenRtfDialog: () => void;
}

export default function SpeechLabTopBar({
  hasSession,
  dialogueLength,
  onOpenRtfDialog,
}: SpeechLabTopBarProps) {
  return (
    <Box
      style={{
        padding: 'var(--sizeSpacingX1) var(--sizeSpacingX4)',
        background: hasSession
          ? 'var(--color-status-success-background)'
          : 'var(--color-background-base-hover)',
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--sizeSpacingX2)',
        borderBottom: '1px solid var(--color-border)',
        flexShrink: 0,
      }}
    >
      {hasSession ? (
        <Stack direction="horizontal" spacing="x2" align="center" style={{ flex: 1 }}>
          <Icon
            iconName={Icons.Check}
            size="small"
            style={{ color: 'var(--color-status-success)' }}
          />
          <Typography variant="caption">
            Диалог загружен ({dialogueLength} реплик)
          </Typography>
        </Stack>
      ) : (
        <Stack direction="horizontal" spacing="x2" align="center" style={{ flex: 1 }}>
          <Icon iconName={Icons.InfoCircled} size="small" />
          <Typography variant="caption" inactive>
            Загрузите RTF-файл диалога для поиска совпадений
          </Typography>
        </Stack>
      )}
      <Box style={{ marginLeft: 'auto' }}>
        <Button variant="secondary" size="small" onClick={onOpenRtfDialog}>
          <Icon iconName={Icons.Upload} size="small" />
          {hasSession ? 'Заменить диалог' : 'Загрузить диалог'}
        </Button>
      </Box>
    </Box>
  );
}
