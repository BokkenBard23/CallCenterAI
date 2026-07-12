/**
 * XmlExportDialog — Dialog for exporting the dictionary to canonical XML.
 *
 * DS Dialog renders only `open` / `onClose` / `children`; this wrapper
 * composes a Box + Stack inside with:
 *   - title (Typography)
 *   - dict_name Select (root dictionaries list)
 *   - pretty Switch (default on)
 *   - Export / Cancel actions
 *   - exporting state (Progress indeterminate + "Генерируем XML…")
 *   - error (InlineAlert + retry)
 *
 * On success: receives `Blob` from `exportDictionaryXml`, triggers a
 * browser download via `URL.createObjectURL` + transient `<a download>`,
 * shows a Snackbar success, and auto-closes.
 *
 * Anti-clone: uses `Blob` + `URL.createObjectURL` (canonical browser
 * download) — NOT LexiCore's `saveAs` shim. DS components only.
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  InlineAlert,
  Progress,
  Snackbar,
  Stack,
  Switch,
  Typography,
} from '@beeline/design-system-react';
import { exportDictionaryXml } from '../../api/client';
import { SimpleSelect, type SimpleOption } from './SimpleSelect';

export interface XmlExportDialogProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  /** Root dictionary names (top-level entries in the tree). */
  rootDictNames: string[];
  /** Default dict_name when dialog opens (selected node's root). */
  defaultDictName?: string | null;
}

type ExportStatus = 'idle' | 'exporting' | 'error';

function XmlExportDialogBase({
  open,
  onClose,
  sessionId,
  rootDictNames,
  defaultDictName,
}: XmlExportDialogProps) {
  const [dictName, setDictName] = useState<string>(defaultDictName ?? '');
  const [pretty, setPretty] = useState(true);
  const [status, setStatus] = useState<ExportStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [snackMessage, setSnackMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Reset form when dialog opens with the latest default.
  useEffect(() => {
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form state when dialog opens; intentional one-time sync.
      setDictName(defaultDictName ?? rootDictNames[0] ?? '');
      setPretty(true);
      setStatus('idle');
      setError(null);
    }
  }, [open, defaultDictName, rootDictNames]);

  // Abort on close.
  useEffect(() => {
    if (!open) {
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open]);

  const dictOptions: SimpleOption[] = rootDictNames.map((n) => ({
    value: n,
    label: n,
  }));

  const handleExport = useCallback(async () => {
    if (!dictName) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('exporting');
    setError(null);
    try {
      const blob = await exportDictionaryXml(
        sessionId,
        { dict_name: dictName, pretty },
        controller.signal,
      );
      // Trigger browser download via transient anchor.
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${dictName}.xml`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Revoke on next tick to allow the download to start.
      setTimeout(() => URL.revokeObjectURL(url), 0);

      setStatus('idle');
      setSnackMessage(`XML экспортирован: ${dictName}.xml`);
      // Auto-close dialog on success.
      onClose();
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus('error');
      setError(
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: string }).message)
          : 'Ошибка экспорта XML',
      );
    }
  }, [dictName, pretty, sessionId, onClose]);

  return (
    <>
      <Dialog open={open} onClose={onClose}>
        <Box style={{ padding: 'var(--size-spacing-x5)', minWidth: 360 }}>
          <Stack direction="vertical" gap="x4">
            <Typography variant="h6">Экспорт XML</Typography>

            {status === 'exporting' ? (
              <Stack direction="vertical" gap="x3" align="center">
                <Progress shape="circle" cycled />
                <Typography variant="body2" color="colorTextInactive">
                  Генерируем XML…
                </Typography>
              </Stack>
            ) : status === 'error' ? (
              <Stack direction="vertical" gap="x3">
                <InlineAlert type="error">Ошибка экспорта</InlineAlert>
                {error && (
                  <Typography variant="caption" color="colorTextInactive">
                    {error}
                  </Typography>
                )}
                <Button variant="contained" onClick={handleExport}>
                  Повторить
                </Button>
              </Stack>
            ) : (
              <Stack direction="vertical" gap="x3">
                <Stack direction="vertical" gap="x1">
                  <Typography variant="body2" color="colorTextInactive">
                    Словарь
                  </Typography>
                  <div style={{ minWidth: 220 }}>
                    <SimpleSelect
                      options={dictOptions}
                      value={dictName}
                      onChange={setDictName}
                      placeholder="Выберите словарь"
                    />
                  </div>
                </Stack>
                <Switch
                  label="Форматированный XML"
                  checked={pretty}
                  onChange={() => setPretty((v) => !v)}
                />
                <Stack direction="horizontal" gap="x2" justify="end">
                  <Button variant="outlined" onClick={onClose}>
                    Отмена
                  </Button>
                  <Button
                    variant="contained"
                    disabled={!dictName}
                    onClick={handleExport}
                  >
                    Экспортировать
                  </Button>
                </Stack>
              </Stack>
            )}
          </Stack>
        </Box>
      </Dialog>

      <Snackbar
        open={snackMessage !== null}
        message={snackMessage ?? ''}
        delay={3000}
        onClose={() => setSnackMessage(null)}
      />
    </>
  );
}

export const XmlExportDialog = memo(XmlExportDialogBase);
