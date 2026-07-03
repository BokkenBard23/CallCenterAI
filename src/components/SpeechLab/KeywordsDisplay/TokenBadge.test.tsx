/**
 * Tests for TokenBadge — single token rendering.
 * Covers: WORD, PHRASE, LEXEME, BRACKET types with channel colors.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import TokenBadge from './TokenBadge';
import type { DisplayToken } from '../../../types/speechlab';

function makeToken(overrides: Partial<DisplayToken> & { text: string; type: DisplayToken['type'] }): DisplayToken {
  return {
    channel: 'ANY',
    word_distance: 2,
    is_error: false,
    is_exact: false,
    ...overrides,
  };
}

describe('TokenBadge', () => {
  it('renders WORD token as Badge with channel color', () => {
    const token = makeToken({ text: 'переключить', type: 'WORD', channel: 'CLIENT' });
    render(<TokenBadge token={token} />);
    expect(screen.getByText('переключить')).toBeInTheDocument();
  });

  it('renders PHRASE token with guillemet quotes', () => {
    const token = makeToken({ text: 'переключусь на другого оператора', type: 'PHRASE', channel: 'CLIENT', is_exact: true });
    render(<TokenBadge token={token} />);
    expect(screen.getByText(/переключусь на другого оператора/)).toBeInTheDocument();
  });

  it('renders LEXEME token as grey text (NOT Badge)', () => {
    const token = makeToken({ text: 'ИЛИ', type: 'LEXEME', channel: 'ANY' });
    render(<TokenBadge token={token} />);
    expect(screen.getByText('или')).toBeInTheDocument();
  });

  it('renders BRACKET token as gold text', () => {
    const token = makeToken({ text: '(', type: 'BRACKET', channel: 'ANY' });
    render(<TokenBadge token={token} />);
    expect(screen.getByText('(')).toBeInTheDocument();
  });

  it('renders WORD with OPERATOR channel color', () => {
    const token = makeToken({ text: 'ждать', type: 'WORD', channel: 'OPERATOR' });
    render(<TokenBadge token={token} />);
    expect(screen.getByText('ждать')).toBeInTheDocument();
  });

  it('renders error token with red border', () => {
    const token = makeToken({ text: 'ошибка', type: 'WORD', channel: 'ANY', is_error: true });
    render(<TokenBadge token={token} />);
    expect(screen.getByText('ошибка')).toBeInTheDocument();
  });

  it('renders PHRASE with is_exact as bold', () => {
    const token = makeToken({ text: 'точная фраза', type: 'PHRASE', channel: 'CLIENT', is_exact: true });
    render(<TokenBadge token={token} />);
    expect(screen.getByText(/точная фраза/)).toBeInTheDocument();
  });
});
