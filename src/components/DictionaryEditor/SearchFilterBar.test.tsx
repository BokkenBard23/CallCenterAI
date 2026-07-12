import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { SearchFilterBar } from './SearchFilterBar';

describe('SearchFilterBar', () => {
  it('renders search input and channel select', () => {
    render(
      <SearchFilterBar
        onChange={vi.fn()}
        matchedCount={0}
        hasRows={false}
      />,
    );
    expect(screen.getByPlaceholderText('Поиск фразы…')).toBeInTheDocument();
  });

  it('shows "Фильтр активен" badge synchronously when text is entered', () => {
    render(
      <SearchFilterBar
        onChange={vi.fn()}
        matchedCount={5}
        hasRows
      />,
    );
    const input = screen.getByPlaceholderText('Поиск фразы…');
    fireEvent.change(input, { target: { value: 'привет' } });
    expect(screen.getByText('Фильтр активен')).toBeInTheDocument();
  });

  it('shows "Ничего не найдено" when filter active and matchedCount is 0', () => {
    render(
      <SearchFilterBar
        onChange={vi.fn()}
        matchedCount={0}
        hasRows
        initialValue={{ text: 'test', channel: '' }}
      />,
    );
    // initialValue seeds text state directly.
    expect(screen.getByDisplayValue('test')).toBeInTheDocument();
    expect(screen.getByText('Фильтр активен')).toBeInTheDocument();
    expect(screen.getByText('Ничего не найдено')).toBeInTheDocument();
  });

  it('does not show clear button when filter is empty', () => {
    render(
      <SearchFilterBar
        onChange={vi.fn()}
        matchedCount={10}
        hasRows
      />,
    );
    expect(screen.queryByText('Очистить')).not.toBeInTheDocument();
  });

  it('calls onChange after debounce when text changes', () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const onChange = vi.fn();
    render(
      <SearchFilterBar
        onChange={onChange}
        matchedCount={5}
        hasRows
      />,
    );
    const input = screen.getByPlaceholderText('Поиск фразы…');
    fireEvent.change(input, { target: { value: 'привет' } });
    expect(onChange).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledWith({ text: 'привет', channel: '' });
    vi.useRealTimers();
  });
});
