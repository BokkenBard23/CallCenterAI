/**
 * DropZone — drag-and-drop file upload area with BorderBeam animation.
 *
 * Supports HTML5 Drag and Drop API with keyboard fallback (click to open file picker).
 * Visual states: idle → drag-over (BorderBeam) → accepted/rejected.
 */

import { useCallback, useRef, useState, type ReactNode } from 'react';
import { Icon, Stack, Typography } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { BorderBeam } from '@/components/ui/border-beam';
import { cn } from '@/lib/utils';

export interface DropZoneProps {
  /** Accepted file extension(s), e.g. '.rtf' or '.xml' */
  accept: string;
  /** Allow multiple file selection */
  multiple?: boolean;
  /** Callback when files are selected (via drop or click) */
  onFilesSelected: (files: File[]) => void;
  /** Label shown in idle state */
  idleLabel: string;
  /** Sub-label shown in idle state */
  idleSubLabel?: string;
  /** Label shown during drag-over */
  dragLabel?: string;
  /** Icon shown in idle state */
  idleIcon?: ReactNode;
  /** aria-label for the drop zone */
  ariaLabel: string;
  /** Whether the zone is disabled */
  disabled?: boolean;
  /** Test ID for the hidden file input */
  inputTestId?: string;
  /** Additional CSS class */
  className?: string;
}

export function DropZone({
  accept,
  multiple = false,
  onFilesSelected,
  idleLabel,
  idleSubLabel,
  dragLabel = 'Отпустите файл для загрузки',
  idleIcon,
  ariaLabel,
  disabled = false,
  inputTestId,
  className,
}: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setIsDragging(true);
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only set false if leaving the drop zone itself
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      if (disabled || !e.dataTransfer.files.length) return;

      // Filter files by accepted extension
      const acceptedExts = accept.split(',').map((ext) => ext.trim().toLowerCase());
      const files = Array.from(e.dataTransfer.files);
      const matched = files.filter((f) => {
        const ext = '.' + f.name.split('.').pop()?.toLowerCase();
        return acceptedExts.includes(ext);
      });

      if (matched.length > 0) {
        onFilesSelected(matched);
      }
      // If no matched files, caller should show snackbar via onFilesSelected not being called
      // The parent component handles the "unsupported format" snackbar
    },
    [accept, disabled, onFilesSelected],
  );

  const handleClick = useCallback(() => {
    if (!disabled) inputRef.current?.click();
  }, [disabled]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.key === 'Enter' || e.key === ' ') && !disabled) {
        e.preventDefault();
        inputRef.current?.click();
      }
    },
    [disabled],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        onFilesSelected(Array.from(e.target.files));
      }
      // Reset input value so the same file can be re-selected
      e.target.value = '';
    },
    [onFilesSelected],
  );

  return (
    <div
      className={cn('drop-zone-wrapper', className)}
      style={{ position: 'relative', overflow: 'hidden' }}
    >
      <div
        className={cn('drop-zone', isDragging && 'drop-zone--dragging')}
        style={{
          border: isDragging
            ? '2px solid var(--color-background-brand)'
            : '2px dashed var(--color-border)',
          borderRadius: 'var(--sizeBorderRadiusX4, 8px)',
          padding: 'var(--sizeSpacingX6, 24px)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          textAlign: 'center',
          transition: 'border-color 200ms ease, background-color 200ms ease',
          backgroundColor: isDragging
            ? 'rgba(253, 216, 53, 0.06)'
            : 'transparent',
          opacity: disabled ? 0.5 : 1,
        }}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={ariaLabel}
        aria-disabled={disabled}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          style={{ display: 'none' }}
          onChange={handleInputChange}
          aria-hidden="true"
          data-testid={inputTestId}
        />
        <Stack direction="vertical" spacing="x2" align="center">
          {idleIcon ?? (
            <Icon
              iconName={isDragging ? Icons.DragIndicator : Icons.CloudUpload}
              size="large"
              style={{
                color: isDragging
                  ? 'var(--color-background-brand)'
                  : 'var(--color-text-inactive)',
                transition: 'color 200ms ease',
              }}
            />
          )}
          <Typography variant="body1">
            {isDragging ? dragLabel : idleLabel}
          </Typography>
          {!isDragging && idleSubLabel && (
            <Typography variant="caption" inactive>
              {idleSubLabel}
            </Typography>
          )}
        </Stack>
      </div>
      {isDragging && (
        <BorderBeam
          duration={3}
          colorFrom="#fdd835"
          colorTo="#ffaa40"
        />
      )}
    </div>
  );
}
