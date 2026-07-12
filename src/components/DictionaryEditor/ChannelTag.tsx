/**
 * ChannelTag — Badge wrapper that maps an editable channel value
 * (ANY/CLIENT/OPERATOR) to a DS Badge semantic color per the lock-in
 * brief. SYSTEM is hidden (BE gap — `_VALID_CHANNELS` excludes it).
 */

import { memo } from 'react';
import { Badge } from '@beeline/design-system-react';
import { CHANNEL_BADGE, type EditableChannel } from './constants';

export interface ChannelTagProps {
  channel: string;
  /** Show full label (ANY/CLIENT/OPERATOR) instead of short (ANY/CL/OP). */
  full?: boolean;
}

function ChannelTagBase({ channel, full = false }: ChannelTagProps) {
  // Normalize: only ANY/CLIENT/OPERATOR are editable; anything else (incl. SYSTEM)
  // renders as neutral "—" to honour the SYSTEM-hidden contract.
  const editable = (['ANY', 'CLIENT', 'OPERATOR'] as const).find(
    (c) => c === channel,
  );
  if (!editable) {
    return (
      <Badge type="secondary" semantic="neutral">
        —
      </Badge>
    );
  }
  const cfg = CHANNEL_BADGE[editable as EditableChannel];
  return (
    <Badge type={cfg.type} semantic={cfg.semantic}>
      {full ? editable : cfg.label}
    </Badge>
  );
}

export const ChannelTag = memo(ChannelTagBase);
