import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PhraseSuggestionsModal } from './PhraseSuggestionsModal';
import type { DictionarySuggestion } from '../../types/api';

describe('PhraseSuggestionsModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing visible when open=false', () => {
    render(
      <PhraseSuggestionsModal
        open={false}
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onAddSuggestion={() => undefined}
      />,
    );
    expect(screen.queryByText('AI подсказки фраз')).toBeNull();
  });

  it('renders prompt when dictName is null', () => {
    render(
      <PhraseSuggestionsModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName={null}
        onAddSuggestion={() => undefined}
      />,
    );
    expect(screen.getByText(/Выберите словарь/i)).toBeInTheDocument();
  });

  it('renders suggestions list after fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          suggestions: [
            { phrase: 'хочу отменить', channel: 'CLIENT', distance: 2 },
            { phrase: 'не работает', channel: 'OPERATOR', distance: 1 },
          ],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <PhraseSuggestionsModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onAddSuggestion={() => undefined}
      />,
    );
    await screen.findByText('хочу отменить');
    expect(screen.getByText('не работает')).toBeInTheDocument();
    expect(screen.getByText(/Добавить все \(2\)/)).toBeInTheDocument();
  });

  it('renders empty state when 0 suggestions', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ suggestions: [] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <PhraseSuggestionsModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onAddSuggestion={() => undefined}
      />,
    );
    await screen.findByText(/0 подсказок/);
  });

  it('marks suggestion as added on click', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          suggestions: [{ phrase: 'помогите', channel: 'CLIENT', distance: 0 }],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onAdd = vi.fn().mockResolvedValue(undefined);

    render(
      <PhraseSuggestionsModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onAddSuggestion={onAdd}
      />,
    );
    const addBtn = await screen.findByLabelText(/Добавить: помогите/);
    await fireEvent.click(addBtn);
    expect(onAdd).toHaveBeenCalledWith({
      phrase: 'помогите',
      channel: 'CLIENT',
      distance: 0,
    } satisfies DictionarySuggestion);
    await waitFor(() =>
      expect(screen.getByText('Добавлено')).toBeInTheDocument(),
    );
  });

  it('renders error InlineAlert on API failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'fail' }), { status: 500 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <PhraseSuggestionsModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onAddSuggestion={() => undefined}
      />,
    );
    await screen.findByText('AI временно недоступен');
  });
});
