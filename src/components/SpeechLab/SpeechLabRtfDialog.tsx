/**
 * SpeechLabRtfDialog — Dialog for uploading RTF dialogue files.
 *
 * Extracted from SpeechLabPage monolith.
 * Uses DS Dialog + Box + Stack + Typography — no inline color values.
 * Self-contained: manages its own file input ref, exposes getFile() for parent.
 */

import { useCallback, useRef } from 'react';
import {
  Box,
  Button,
  Dialog,
  Divider,
  Icon,
  InlineAlert,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

interface SpeechLabRtfDialogProps {
  /** Whether dialog is open */
  open: boolean;
  /** Selected RTF file name (controlled by parent via onFileSelect) */
  fileName: string | null;
  /** Whether upload is in progress */
  uploading: boolean;
  /** Upload error message */
  error: string | null;
  /** File selection handler — receives the selected File object */
  onFileSelect: (file: File) => void;
  /** Upload confirmation handler */
  onUpload: () => Promise<void>;
  /** Close dialog handler */
  onClose: () => void;
}

export default function SpeechLabRtfDialog({
  open,
  fileName,
  uploading,
  error,
  onFileSelect,
  onUpload,
  onClose,
}: SpeechLabRtfDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        onFileSelect(file);
      }
    },
    [onFileSelect],
  );

  return (
    <Dialog open={open} onClose={onClose}>
      <Box style={{ padding: 'var(--sizeSpacingX6)', minWidth: '400px' }}>
        <Stack direction="vertical" spacing="x4">
          <Typography variant="h5">Загрузка диалога</Typography>
          <Typography variant="body2" inactive>
            Выберите RTF-файл с записью диалога для поиска совпадений по словарю
          </Typography>

          <Divider />

          {/* Drop area / file picker */}
          <Box
            onClick={() => inputRef.current?.click()}
            style={{
              border: `2px dashed var(--color-border)`,
              borderRadius: 'var(--sizeBorderRadiusX4)',
              padding: 'var(--sizeSpacingX6)',
              textAlign: 'center',
              cursor: 'pointer',
              background: fileName
                ? 'var(--color-status-success-background)'
                : 'var(--color-background-base-hover)',
              transition: 'background 0.2s',
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".rtf"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
            {fileName ? (
              <Stack direction="vertical" spacing="x2" align="center">
                <Icon
                  iconName={Icons.Check}
                  size="large"
                  style={{ color: 'var(--color-status-success)' }}
                />
                <Typography variant="body2">{fileName}</Typography>
              </Stack>
            ) : (
              <Stack direction="vertical" spacing="x2" align="center">
                <Icon iconName={Icons.Upload} size="large" />
                <Typography variant="body2" inactive>
                  Нажмите или перетащите RTF-файл
                </Typography>
              </Stack>
            )}
          </Box>

          {/* Error */}
          {error && (
            <InlineAlert type="error">
              Ошибка загрузки: {error}
            </InlineAlert>
          )}

          {/* Actions */}
          <Stack direction="horizontal" spacing="x2" justify="end">
            <Button variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button
              variant="primary"
              onClick={onUpload}
              disabled={!fileName || uploading}
            >
              {uploading ? 'Загрузка...' : 'Загрузить'}
            </Button>
          </Stack>
        </Stack>
      </Box>
    </Dialog>
  );
}
