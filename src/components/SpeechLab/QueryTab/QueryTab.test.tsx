/**
 * Tests for QueryTab — right panel tab with node details.
 * Covers: empty state, node details, attributes, keywords, additional section.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import QueryTab from './QueryTab';
import type { SpeechLabTreeNode } from '../../../types/speechlab';

function makeNode(overrides: Partial<SpeechLabTreeNode> & { id: string; name: string }): SpeechLabTreeNode {
  return {
    has_children: false,
    children_count: 0,
    is_remainder: false,
    display_tokens: [],
    children: [],
    ...overrides,
  };
}

const sampleNode = makeNode({
  id: '1',
  name: 'Риск расторжения',
  display_tokens: [
    { text: 'переключить', type: 'WORD', channel: 'CLIENT', word_distance: 2, is_error: false, is_exact: false },
    { text: 'ИЛИ', type: 'LEXEME', channel: 'ANY', word_distance: 2, is_error: false, is_exact: false },
    { text: 'отказаться', type: 'WORD', channel: 'ANY', word_distance: 2, is_error: false, is_exact: false },
  ],
  attributes: [
    { key: 'Направление', raw_value: 'Входящий', human_readable: 'Направление: Входящий' },
    { key: 'Длительность', raw_value: '>=30', human_readable: 'Длительность: >=30' },
  ],
});

describe('QueryTab', () => {
  it('renders empty state when no node selected', () => {
    render(<QueryTab selectedNode={null} />);
    expect(screen.getByText('Выберите словарь в дереве')).toBeInTheDocument();
  });

  it('renders node name as header', () => {
    render(<QueryTab selectedNode={sampleNode} />);
    expect(screen.getByText('Риск расторжения')).toBeInTheDocument();
  });

  it('renders attributes section', () => {
    render(<QueryTab selectedNode={sampleNode} />);
    expect(screen.getByText('Атрибуты записи')).toBeInTheDocument();
    expect(screen.getByText('Направление: Входящий')).toBeInTheDocument();
  });

  it('renders keywords section', () => {
    render(<QueryTab selectedNode={sampleNode} />);
    expect(screen.getByText('Ключевые слова')).toBeInTheDocument();
    expect(screen.getByText('переключить')).toBeInTheDocument();
    expect(screen.getByText('или')).toBeInTheDocument();
    expect(screen.getByText('отказаться')).toBeInTheDocument();
  });

  it('renders additional section for exact phrases', () => {
    const nodeWithExact = makeNode({
      id: '2',
      name: 'Точный запрос',
      display_tokens: [
        { text: 'точная фраза', type: 'PHRASE', channel: 'CLIENT', word_distance: 0, is_error: false, is_exact: true },
      ],
    });
    render(<QueryTab selectedNode={nodeWithExact} />);
    expect(screen.getByText('Дополнительно')).toBeInTheDocument();
  });

  it('hides attributes section when no attributes', () => {
    const nodeNoAttrs = makeNode({ id: '3', name: 'Без атрибутов' });
    render(<QueryTab selectedNode={nodeNoAttrs} />);
    expect(screen.queryByText('Атрибуты записи')).not.toBeInTheDocument();
  });
});
