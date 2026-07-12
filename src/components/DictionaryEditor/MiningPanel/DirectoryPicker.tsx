/**
 * DirectoryPicker — controlled fallback for browser directory selection.
 *
 * MP-GAP-1: browser has no native directory picker API standardised in DS.
 * DS FileUploader supports only `multiple` + `accept` (no `webkitdirectory`),
 * so we wrap a hidden `<input type="file" webkitdirectory multiple>` inside a
 * DS Dialog and render the selected RTF file list via DS List + ListItem.
 *
 * Hybrid mode compliant (.opencode/rules/01-design-system-first.md п.8).
 * webkitdirectory is a stable HTML5 attribute supported by all modern
 * browsers (Chrome/Edge/Firefox/Safari).
 *
 * Selection contract: parent receives an array of { path, name, size } —
 * the BE resolves the absolute directory_path server-side (browser sandbox
 * only exposes relative paths inside the chosen folder, so we send the file
 * list and let BE inspect the directory). For Quick Win demo we also expose
 * `directoryPath` (top-level folder name) so the UI can label the chosen dir.
 */

import { memo, useCallback, useRef, useState, type ChangeEvent } from 'react';
import {
  Box,
  Button,
  Dialog,
  Icon,
  List,
  ListItem,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

export interface PickedFile {
  /** Relative path inside the picked directory (webkitdirectory exposes this). */
  path: string;
  name: string;
  size: number;
}

export interface DirectoryPickerProps {
  /** Currently picked directory label (top folder name) — null when empty. */
  directoryLabel: string | null;
  /** Number of files selected — shown next to the trigger button. */
  fileCount: number;
  /** Open dialog state (parent-controlled). */
  open: boolean;
  /** Open the picker dialog. */
  onOpen: () => void;
  /** Close the picker dialog (cancel). */
  onClose: () => void;
  /** Confirm selection — receives the picked files + directory label. */
  onConfirm: (files: PickedFile[], directoryLabel: string) => void;
}

interface PendingSelection {
  files: PickedFile[];
  directoryLabel: string;
}

function extractDirectoryLabel(fileList: FileList | null): string {
  if (!fileList || fileList.length === 0) return '';
  // webkitRelativePath is "folderName/sub/file.rtf" — top component is the dir.
  const first = fileList[0] as File & { webkitRelativePath?: string };
  const rel = first.webkitRelativePath || first.name;
  const top = rel.split('/')[0] || rel;
  return top;
}

function toPickedFiles(fileList: FileList | null): PickedFile[] {
  if (!fileList) return [];
  const out: PickedFile[] = [];
  for (let i = 0; i < fileList.length; i += 1) {
    const f = fileList[i] as File & { webkitRelativePath?: string };
    const rel = f.webkitRelativePath || f.name;
    out.push({ path: rel, name: f.name, size: f.size });
  }
  return out;
}

function DirectoryPickerBase({
  directoryLabel,
  fileCount,
  open,
  onOpen,
  onClose,
  onConfirm,
}: DirectoryPickerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [pending, setPending] = useState<PendingSelection | null>(null);

  const handleInputChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const fileList = event.target.files;
    const files = toPickedFiles(fileList);
    const directoryLabel = extractDirectoryLabel(fileList);
    setPending({ files, directoryLabel });
    // Reset input value so the same directory can be re-picked if needed.
    event.target.value = '';
  }, []);

  const handleConfirm = useCallback(() => {
    if (!pending || pending.files.length === 0) return;
    onConfirm(pending.files, pending.directoryLabel);
    setPending(null);
  }, [pending, onConfirm]);

  const handleCancel = useCallback(() => {
    setPending(null);
    onClose();
  }, [onClose]);

  const pendingFiles = pending?.files ?? [];
  const pendingLabel = pending?.directoryLabel ?? '';

  return (
    <>
      <Button variant="secondary" startIcon={<Icon iconName={Icons.Folder} />} onClick={onOpen}>
        Указать директорию с RTF
      </Button>
      {directoryLabel && (
        <Typography variant="caption" color="colorTextInactive">
          {directoryLabel} ({fileCount} файлов)
        </Typography>
      )}

      <Dialog open={open} onClose={handleCancel} applicationRootElement="root">
        <Box style={{ padding: 'var(--size-spacing-x4)', minWidth: 'min(520px, 92vw)' }}>
          <Stack direction="vertical" gap="x3">
            <Stack direction="horizontal" gap="x2" align="center" justify="space-between">
              <Typography variant="h6">Выбор директории с RTF</Typography>
            </Stack>

            {/* MP-GAP-1 controlled fallback: hidden native input with webkitdirectory.
                DS FileUploader does not support webkitdirectory (verified, 14 props). */}
            <input
              ref={inputRef}
              type="file"
              // webkitdirectory is a non-standard but universally-supported HTML attribute.
              // React types do not declare it; cast to any is forbidden by eslint rule,
              // so we set it via a wrapper attribute object spread below.
              multiple
              style={{ display: 'none' }}
              onChange={handleInputChange}
              {...({ webkitdirectory: '' } as unknown as Record<string, string>)}
            />
            <Button
              variant="secondary"
              startIcon={<Icon iconName={Icons.Folder} />}
              onClick={() => inputRef.current?.click()}
            >
              Выбрать папку
            </Button>

            <Typography variant="caption" color="colorTextInactive">
              Выбрано файлов: {pendingFiles.length}
              {pendingLabel ? ` в папке «${pendingLabel}»` : ''}
            </Typography>

            {pendingFiles.length > 0 && (
              <Box style={{ maxHeight: '240px', overflow: 'auto' }}>
                <List>
                  {pendingFiles.slice(0, 200).map((f) => (
                    <ListItem key={f.path}>{f.path}</ListItem>
                  ))}
                  {pendingFiles.length > 200 && (
                    <ListItem>…и ещё {pendingFiles.length - 200} файлов</ListItem>
                  )}
                </List>
              </Box>
            )}

            <Stack direction="horizontal" gap="x2" justify="end">
              <Button variant="ghost" onClick={handleCancel}>
                Отмена
              </Button>
              <Button
                variant="primary"
                disabled={pendingFiles.length === 0}
                onClick={handleConfirm}
              >
                Подтвердить
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>
    </>
  );
}

export const DirectoryPicker = memo(DirectoryPickerBase);
