/**
 * KeywordsDisplay — flex-wrap container that renders DisplayToken[] as
 * TokenBadge (WORD/PHRASE), LEXEME spans, and BRACKET spans.
 *
 * From design-spec-chunk-3:
 *   - Container: Box with display:flex, flexWrap:wrap, gap:8px, alignItems:center
 *   - Empty state: Typography "Нет ключевых слов"
 */

import React from 'react';
import { Box, Typography, Icon } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { DisplayToken } from '../../../types/speechlab';
import TokenBadge from './TokenBadge';

import './KeywordsDisplay.scss';

interface KeywordsDisplayProps {
  tokens: DisplayToken[];
}

const KeywordsDisplay = React.memo(function KeywordsDisplay({ tokens }: KeywordsDisplayProps) {
  if (tokens.length === 0) {
    return (
      <Box className="keywords-display keywords-display--empty" padding="x2">
        <Icon iconName={Icons.Search} size="small" />
        <Typography variant="body2" inactive>
          Нет ключевых слов
        </Typography>
      </Box>
    );
  }

  return (
    <Box className="keywords-display">
      {tokens.map((token, idx) => (
        <TokenBadge key={`${token.type}-${token.text}-${idx}`} token={token} />
      ))}
    </Box>
  );
});

export default KeywordsDisplay;
