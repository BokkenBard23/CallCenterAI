/**
 * Tests for KeywordsDisplay — flex-wrap container for DisplayToken[].
 * Covers: empty state, tokens rendering, mixed token types.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import KeywordsDisplay from './KeywordsDisplay';
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

describe('KeywordsDisplay', () => {
  it('renders empty state when no tokens', () => {
    render(<KeywordsDisplay tokens={[]} />);
    expect(screen.getByText('Нет ключевых слов')).toBeInTheDocument();
  });

  it('renders WORD tokens as badges', () => {
    const tokens: DisplayToken[] = [
      makeToken({ text: 'переключить', type: 'WORD', channel: 'CLIENT' }),
      makeToken({ text: 'отказаться', type: 'WORD', channel: 'ANY' }),
    ];
    render(<KeywordsDisplay tokens={tokens} />);
    expect(screen.getByText('переключить')).toBeInTheDocument();
    expect(screen.getByText('отказаться')).toBeInTheDocument();
  });

  it('renders LEXEME tokens as grey text', () => {
    const tokens: DisplayToken[] = [
      makeToken({ text: 'переключить', type: 'WORD', channel: 'CLIENT' }),
      makeToken({ text: 'ИЛИ', type: 'LEXEME', channel: 'ANY' }),
      makeToken({ text: 'ждать', type: 'WORD', channel: 'OPERATOR' }),
    ];
    render(<KeywordsDisplay tokens={tokens} />);
    expect(screen.getByText('переключить')).toBeInTheDocument();
    expect(screen.getByText('или')).toBeInTheDocument();
    expect(screen.getByText('ждать')).toBeInTheDocument();
  });

  it('renders BRACKET tokens as gold text', () => {
    const tokens: DisplayToken[] = [
      makeToken({ text: '(', type: 'BRACKET', channel: 'ANY' }),
      makeToken({ text: 'ждать', type: 'WORD', channel: 'OPERATOR' }),
      makeToken({ text: ')', type: 'BRACKET', channel: 'ANY' }),
    ];
    render(<KeywordsDisplay tokens={tokens} />);
    expect(screen.getByText('(')).toBeInTheDocument();
    expect(screen.getByText('ждать')).toBeInTheDocument();
    expect(screen.getByText(')')).toBeInTheDocument();
  });

  it('renders PHRASE with exact match markers', () => {
    const tokens: DisplayToken[] = [
      makeToken({ text: 'переключусь на другого', type: 'PHRASE', channel: 'CLIENT', is_exact: true }),
    ];
    render(<KeywordsDisplay tokens={tokens} />);
    expect(screen.getByText(/переключусь на другого/)).toBeInTheDocument();
  });
});
