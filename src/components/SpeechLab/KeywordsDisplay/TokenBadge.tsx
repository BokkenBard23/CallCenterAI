/**
 * TokenBadge — renders a single DisplayToken as a DS Badge (WORD/PHRASE)
 * or a styled span (LEXEME/BRACKET).
 *
 * Rendering rules (from design-spec-chunk-3):
 *   WORD:    Badge type="secondary" + channel-color border/bg/text via inline style
 *   PHRASE:  Same as WORD + guillemet quotes «...» + is_exact → fontWeight: 600
 *   LEXEME:  Typography variant="caption" inactive (grey), NOT a Badge
 *   BRACKET: Typography variant="body2" + color gold (#ffc107), NOT a Badge
 */

import React from 'react';
import { Badge, Typography } from '@beeline/design-system-react';

import type { DisplayToken, ChannelType } from '../../../types/speechlab';
import { CHANNEL_COLORS } from '../../../types/speechlab';

interface TokenBadgeProps {
  token: DisplayToken;
}

/** Channel color CSS custom property names (with fallback) */
function getChannelStyle(channel: ChannelType): React.CSSProperties {
  const colors = CHANNEL_COLORS[channel];
  return {
    borderColor: colors.border,
    backgroundColor: colors.bg,
    color: colors.text,
  };
}

const TokenBadge = React.memo(function TokenBadge({ token }: TokenBadgeProps) {
  // LEXEME: grey separator text — NOT a Badge
  if (token.type === 'LEXEME') {
    return (
      <Typography
        variant="caption"
        inactive
        style={{ fontStyle: 'italic', margin: '0 2px' }}
      >
        {token.text.toLowerCase()}
      </Typography>
    );
  }

  // BRACKET: gold/yellow text — NOT a Badge
  if (token.type === 'BRACKET') {
    return (
      <Typography
        variant="body2"
        style={{ color: 'var(--color-status-warning, #ffc107)', fontWeight: 600 }}
      >
        {token.text}
      </Typography>
    );
  }

  // WORD or PHRASE: DS Badge with channel-color styling
  const channelStyle = getChannelStyle(token.channel);
  const isPhrase = token.type === 'PHRASE';
  const displayText = isPhrase && token.is_exact
    ? `\u00AB${token.text}\u00BB`
    : isPhrase
      ? `\u00AB${token.text}\u00BB`
      : token.text;

  const badgeStyle: React.CSSProperties = {
    ...channelStyle,
    borderWidth: '1px',
    borderStyle: 'solid',
    fontWeight: token.is_exact ? 600 : 400,
  };

  // Error state: red border
  if (token.is_error) {
    badgeStyle.borderColor = 'var(--color-status-error, #d32f2f)';
  }

  return (
    <Badge type="secondary" style={badgeStyle}>
      {displayText}
    </Badge>
  );
});

export default TokenBadge;
