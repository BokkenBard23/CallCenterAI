/**
 * StatusBadge — DS Badge wrapper for batch analysis item status.
 * Maps analysis status strings to DS Badge with appropriate semantic color and icon.
 */

import React from 'react';
import { Badge } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import type { BadgeSemantic, BadgeType } from '@beeline/design-system-react';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

/** Analysis item status values */
export type AnalysisItemStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface StatusBadgeProps {
  /** Analysis item status */
  status: AnalysisItemStatus;
  /** Error message to display in tooltip for failed status */
  error?: string | null;
  /** Additional CSS class */
  className?: string;
  /** Test ID */
  dataTestId?: string;
}

// ═══════════════════════════════════════════════════════════
// Status config mapping
// ═══════════════════════════════════════════════════════════

interface StatusConfig {
  label: string;
  semantic: BadgeSemantic;
  type: BadgeType;
  icon: Icons;
}

const STATUS_CONFIG: Record<AnalysisItemStatus, StatusConfig> = {
  pending: {
    label: 'Ожидание',
    semantic: 'warning',
    type: 'secondary',
    icon: Icons.Clock,
  },
  processing: {
    label: 'Обработка',
    semantic: 'info',
    type: 'secondary',
    icon: Icons.LoadingPlaceholder,
  },
  completed: {
    label: 'Завершён',
    semantic: 'success',
    type: 'secondary',
    icon: Icons.Check,
  },
  failed: {
    label: 'Ошибка',
    semantic: 'danger',
    type: 'secondary',
    icon: Icons.WarningCircled,
  },
};

// ═══════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════

export const StatusBadge = React.forwardRef<HTMLSpanElement, StatusBadgeProps>(
  function StatusBadge({ status, className, dataTestId }, ref) {
    const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;

    // DS Badge does not support forwardRef, so we wrap it in a <span>
    // that receives the forwarded ref. This ensures Tooltip/Popover
    // can attach refs to StatusBadge without breaking the chain.
    return (
      <span ref={ref} className={className}>
        <Badge
          type={config.type}
          semantic={config.semantic}
          icon={config.icon}
          dataTestId={dataTestId}
        >
          {config.label}
        </Badge>
      </span>
    );
  },
);
