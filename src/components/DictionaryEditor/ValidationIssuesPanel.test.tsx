import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ValidationIssuesPanel } from './ValidationIssuesPanel';

describe('ValidationIssuesPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing when open=false', () => {
    const { container } = render(
      <ValidationIssuesPanel
        open={false}
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    expect(container.textContent).toBe('');
  });

  it('renders prompt when dictName is null', () => {
    render(
      <ValidationIssuesPanel
        open
        sessionId="s1"
        dictName={null}
        onJumpToCondition={() => undefined}
      />,
    );
    expect(screen.getByText(/Выберите словарь/i)).toBeInTheDocument();
  });

  it('renders loading state then errors + warnings', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [
            { row: 2, severity: 'error', message: 'Пустая фраза' },
          ],
          warnings: [
            { row: 0, severity: 'warning', message: 'Баланс скобок' },
          ],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <ValidationIssuesPanel
        open
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    // Wait for the fetch to settle.
    await screen.findByText('Пустая фраза');
    expect(screen.getByText('Ошибки')).toBeInTheDocument();
    expect(screen.getByText('Предупреждения')).toBeInTheDocument();
    expect(screen.getByText('Баланс скобок')).toBeInTheDocument();
  });

  it('renders success empty state when no issues', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ errors: [], warnings: [] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <ValidationIssuesPanel
        open
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    await screen.findByText('Ошибок не найдено');
  });

  it('renders error InlineAlert when API fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'fail' }), { status: 500 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <ValidationIssuesPanel
        open
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={() => undefined}
      />,
    );
    await screen.findByText('Ошибка валидации');
  });

  it('triggers onJumpToCondition when "Перейти" clicked', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [{ row: 1, severity: 'error', message: 'Пустая фраза' }],
          warnings: [],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onJump = vi.fn();

    render(
      <ValidationIssuesPanel
        open
        sessionId="s1"
        dictName="D1"
        onJumpToCondition={onJump}
      />,
    );
    const goBtn = await screen.findByText('Перейти');
    fireEvent.click(goBtn);
    expect(onJump).toHaveBeenCalledWith(1);
  });
});
