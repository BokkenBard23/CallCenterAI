import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ConditionsTable } from './ConditionsTable';
import type { EditorCondition } from './types';
import type { SearchFilterValue } from './SearchFilterBar';

const noop = () => undefined;

const baseConditions: EditorCondition[] = [
  {
    text: 'привет',
    word_distance: 2,
    word_count: 1,
    channel_constraint: 'CLIENT',
    without_list: [],
    is_exact: false,
    logic_operator: 'И',
    open_brackets: 1,
    close_brackets: 1,
  },
  {
    text: 'ошибка',
    word_distance: 0,
    word_count: 1,
    channel_constraint: 'OPERATOR',
    without_list: [],
    is_exact: true,
    logic_operator: 'НЕ',
    open_brackets: 0,
    close_brackets: 0,
  },
];

const emptyFilter: SearchFilterValue = { text: '', channel: '' };

describe('ConditionsTable', () => {
  it('renders rows from conditions without crashing', () => {
    const { container } = render(
      <ConditionsTable
        conditions={baseConditions}
        rowStates={{}}
        filter={emptyFilter}
        onUpdateField={noop}
        onAddCondition={noop}
        onRemoveCondition={noop}
        onDuplicateCondition={noop}
        onMoveCondition={noop}
      />,
    );
    // Table should have rendered table rows (not the empty state).
    expect(container.querySelectorAll('tr').length).toBeGreaterThan(1);
    // Add condition button only appears in ready state (not empty).
    expect(screen.getByText('Добавить условие')).toBeInTheDocument();
  });

  it('renders empty state when conditions list is empty', () => {
    render(
      <ConditionsTable
        conditions={[]}
        rowStates={{}}
        filter={emptyFilter}
        onUpdateField={noop}
        onAddCondition={noop}
        onRemoveCondition={noop}
        onDuplicateCondition={noop}
        onMoveCondition={noop}
      />,
    );
    expect(screen.getByText(/Нет условий/i)).toBeInTheDocument();
  });

  it('renders "Добавить условие" button', () => {
    render(
      <ConditionsTable
        conditions={baseConditions}
        rowStates={{}}
        filter={emptyFilter}
        onUpdateField={noop}
        onAddCondition={noop}
        onRemoveCondition={noop}
        onDuplicateCondition={noop}
        onMoveCondition={noop}
      />,
    );
    expect(screen.getByText('Добавить условие')).toBeInTheDocument();
  });

  it('renders header columns', () => {
    render(
      <ConditionsTable
        conditions={baseConditions}
        rowStates={{}}
        filter={emptyFilter}
        onUpdateField={noop}
        onAddCondition={noop}
        onRemoveCondition={noop}
        onDuplicateCondition={noop}
        onMoveCondition={noop}
      />,
    );
    expect(screen.getByText('Phrase')).toBeInTheDocument();
    expect(screen.getByText('Channel')).toBeInTheDocument();
    expect(screen.getByText('WD')).toBeInTheDocument();
  });

  it('renders multiple table body rows for multiple conditions', () => {
    const { container } = render(
      <ConditionsTable
        conditions={baseConditions}
        rowStates={{}}
        filter={emptyFilter}
        onUpdateField={noop}
        onAddCondition={noop}
        onRemoveCondition={noop}
        onDuplicateCondition={noop}
        onMoveCondition={noop}
      />,
    );
    // Expect 1 header row + 2 data rows = 3 <tr> elements minimum.
    const dataRows = container.querySelectorAll('tbody tr');
    expect(dataRows.length).toBeGreaterThanOrEqual(2);
  });
});
