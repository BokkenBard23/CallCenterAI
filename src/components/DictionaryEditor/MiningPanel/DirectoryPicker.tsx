/**
 * DirectoryPicker — controlled fallback for browser directory selection.
 *
 * MP-GAP-1: browser has no native directory picker API standardised in DS.
 * DS FileUploader supports only `multiple` + `accept` (no `webkitdirectory`),
 * so we wrap a hidden `<input type="file" webkitdirectory multiple>` and
 * trigger it directly from a DS Button. The picked files are auto-confirmed
 * (no separate confirm step) and reported back to the parent via `onPick`.
 *
 * Layout fix (MINING-LAYOUT-FIX): previously this component rendered a DS
 * `Dialog` (nested modal) inside the parent `Sidesheet`, which caused a
 * z-index conflict — the Dialog appeared over the table content behind the
 * Sidesheet rather than over the Sidesheet content, and lacked a proper
 * backdrop. Replacing the Dialog with an inline hidden-input pattern
 * eliminates the nested-modal overlay problem entirely.
 *
 * Hybrid mode compliant (.opencode/rules/01-design-system-first.md п.8).
 * webkitdirectory is a stable HTML5 attribute supported by all modern
 * browsers (Chrome/Edge/Firefox/Safari).
 *
 * Selection contract: parent receives an array of { path, name, size } —
 * the BE resolves the absolute directory_path server-side (browser sandbox
 * only exposes relative paths inside the chosen folder, so we send the file
 * list and let BE inspect the directory). For Quick Win demo we also expose
 * `directoryLabel` (top-level folder name) so the UI can label the chosen dir.
 */

import { memo, useCallback, useRef, type ChangeEvent } from 'react';
import { Button, Icon, Typography } from '@beeline/design-system-react';
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
  /** Called immediately when the user picks a directory (auto-confirm). */
  onPick: (files: PickedFile[], directoryLabel: string) => void;
  /** Optional: disable the trigger button (e.g. while indexing). */
  disabled?: boolean;
  /** Optional: show loading state on the trigger button. */
  loading?: boolean;
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
  onPick,
  disabled,
  loading,
}: DirectoryPickerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const fileList = event.target.files;
      const files = toPickedFiles(fileList);
      const label = extractDirectoryLabel(fileList);
      if (files.length > 0) {
        onPick(files, label);
      }
      // Reset input value so the same directory can be re-picked if needed.
      event.target.value = '';
    },
    [onPick],
  );

  return (
    <span className="directory-picker">
      <Button
        variant="secondary"
        startIcon={<Icon iconName={Icons.Folder} />}
        disabled={disabled}
        loading={loading}
        onClick={() => inputRef.current?.click()}
      >
        Указать директорию с RTF
      </Button>

      {directoryLabel && (
        <Typography variant="caption" color="colorTextInactive" className="directory-picker__label">
          {directoryLabel} ({fileCount} файлов)
        </Typography>
      )}

      {/* MP-GAP-1 controlled fallback: hidden native input with webkitdirectory.
          DS FileUploader does not support webkitdirectory (verified, 14 props).
          Kept hidden — no nested modal is rendered, avoiding the Sidesheet
          z-index / backdrop conflict described in MINING-LAYOUT-FIX. */}
      <input
        ref={inputRef}
        type="file"
        // webkitdirectory is a non-standard but universally-supported HTML attribute.
        // React types do not declare it; cast to a record and spread below.
        multiple
        className="directory-picker__input"
        onChange={handleInputChange}
        {...({ webkitdirectory: '' } as unknown as Record<string, string>)}
      />
    </span>
  );
}

export const DirectoryPicker = memo(DirectoryPickerBase);
