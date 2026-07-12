import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DuplicatesModal } from './DuplicatesModal';

describe('DuplicatesModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing visible when open=false', () => {
    render(
      <DuplicatesModal
        open={false}
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    expect(screen.queryByText('Дубликаты фраз')).toBeNull();
  });

  it('renders prompt when dictName is null', () => {
    render(
      <DuplicatesModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName={null}
        onJumpToCondition={() => undefined}
      />,
    );
    expect(screen.getByText(/Выберите словарь/i)).toBeInTheDocument();
  });

  it('renders empty success state when no duplicates found', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ full: [], soft: [] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <DuplicatesModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    await screen.findByText('Дубликатов не найдено');
  });

  it('renders tabs with counts when duplicates exist', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          full: [{ row_a: 0, row_b: 4, phrase: 'привет', is_exact_a: true, is_exact_b: true }],
          soft: [
            { row_a: 1, row_b: 7, phrase: 'world', is_exact_a: false, is_exact_b: false },
            { row_a: 2, row_b: 6, phrase: 'ошибка', is_exact_a: false, is_exact_b: false },
          ],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <DuplicatesModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    await screen.findByText(/Полные/);
    expect(screen.getByText(/Полные \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Частичные \(2\)/)).toBeInTheDocument();
  });

  it('triggers onJumpToCondition when "Перейти" clicked', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          full: [{ row_a: 0, row_b: 4, phrase: 'привет', is_exact_a: true, is_exact_b: true }],
          soft: [],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onJump = vi.fn();

    render(
      <DuplicatesModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={onJump}
      />,
    );
    const goBtn = await screen.findByText('Перейти');
    fireEvent.click(goBtn);
    expect(onJump).toHaveBeenCalledWith(0);
  });

  it('renders error InlineAlert on API failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'fail' }), { status: 500 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <DuplicatesModal
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    await screen.findByText('Ошибка поиска дубликатов');
  });
});
