/**
 * WordFrequencyBar — custom bar chart for top-N word frequency.
 *
 * ds_gap (custom component): DS has no dedicated frequency-bar component.
 * Uses DS tokens only (no custom hex / rgb / hsl):
 *   - bar background: `var(--color-background-active)` (theme-aware)
 *   - track background: `var(--color-background-secondary)`
 *   - text: default Typography (inherits `--color-text-primary`)
 *
 * Width = `(count / maxCount) * 100%` per LexiCore pattern (design-spec-chunk-2).
 */

import { memo, useMemo } from 'react';
import { Stack, Typography } from '@beeline/design-system-react';
import type { WordFreq } from '../../types/api';

export interface WordFrequencyBarProps {
  data: WordFreq[];
  /** Maximum number of items to render (default 15, per spec). */
  maxItems?: number;
}

function WordFrequencyBarBase({ data, maxItems = 15 }: WordFrequencyBarProps) {
  const items = useMemo(() => data.slice(0, maxItems), [data, maxItems]);
  const maxCount = useMemo(
    () => items.reduce((m, w) => (w.count > m ? w.count : m), 0),
    [items],
  );

  if (items.length === 0) {
    return (
      <Typography variant="body2" color="colorTextInactive">
        Нет данных о частоте слов.
      </Typography>
    );
  }

  return (
    <Stack direction="vertical" gap="x1">
      {items.map((w, i) => {
        const pct = maxCount > 0 ? (w.count / maxCount) * 100 : 0;
        return (
          <div
            key={`${w.word}-${i}`}
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(80px, 140px) 1fr 32px',
              gap: 'var(--size-spacing-x2)',
              alignItems: 'center',
            }}
          >
            <Typography variant="body2" title={w.word}>
              {w.word}
            </Typography>
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={maxCount}
              aria-valuenow={w.count}
              aria-label={`Частота слова ${w.word}: ${w.count}`}
              style={{
                height: 'var(--size-spacing-x3)',
                minWidth: '4px',
                width: `${pct}%`,
                background: 'var(--color-background-active)',
                borderRadius: 'var(--size-border-radius-x2)',
                transition: 'width 200ms ease-out',
              }}
            />
            <Typography variant="caption" color="colorTextInactive">
              {w.count}
            </Typography>
          </div>
        );
      })}
    </Stack>
  );
}

export const WordFrequencyBar = memo(WordFrequencyBarBase);
