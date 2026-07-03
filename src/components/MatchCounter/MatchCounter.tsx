/**
 * MatchCounter — animated counter for match statistics.
 * Wraps NumberTicker with label and semantic color variants.
 */

import { Stack, Typography } from '@beeline/design-system-react';
import { NumberTicker } from '../ui/number-ticker';

type MatchCounterVariant = 'default' | 'success' | 'warning' | 'danger';

interface MatchCounterProps {
  /** The number to animate to */
  count: number;
  /** Optional label text shown before the number */
  label?: string;
  /** Semantic color variant */
  variant?: MatchCounterVariant;
}

/** Map variant to CSS class that uses DS tokens */
const VARIANT_CLASS: Record<MatchCounterVariant, string> = {
  default: 'match-counter--default',
  success: 'match-counter--success',
  warning: 'match-counter--warning',
  danger: 'match-counter--danger',
};

export default function MatchCounter({
  count,
  label,
  variant = 'default',
}: MatchCounterProps) {
  return (
    <Stack direction="horizontal" spacing="x1" align="baseline">
      {label && (
        <Typography variant="caption" inactive>
          {label}
        </Typography>
      )}
      <span className={VARIANT_CLASS[variant]}>
        <NumberTicker
          value={count}
          className="match-counter__value"
        />
      </span>
    </Stack>
  );
}
