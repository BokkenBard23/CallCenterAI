import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AIAnalysisPanel } from './AIAnalysisPanel';

describe('AIAnalysisPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders prompt when dictName is null', () => {
    render(
      <AIAnalysisPanel
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName={null}
      />,
    );
    expect(screen.getByText(/Выберите словарь/i)).toBeInTheDocument();
  });

  it('renders analysis result after fetch', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/providers')) {
        return Promise.resolve(
          new Response(JSON.stringify({ providers: [] }), { status: 200 }),
        );
      }
      if (url.includes('/analyze-ai')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              summary: '## Бизнес-цель\nСловарь выявляет запросы.',
              examples: ['"хочу отменить"', '"не работает"'],
              recommendations: ['Добавить синонимы', 'Уточнить WD'],
              raw_response: '',
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response('', { status: 404 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <AIAnalysisPanel
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
      />,
    );
    const runBtn = screen.getByText('Запустить анализ');
    await fireEvent.click(runBtn);
    await screen.findByText('Сводка');
    expect(screen.getByText('Примеры')).toBeInTheDocument();
    expect(screen.getByText('Рекомендации')).toBeInTheDocument();
    expect(screen.getByText('"хочу отменить"')).toBeInTheDocument();
    expect(screen.getByText('Добавить синонимы')).toBeInTheDocument();
  });

  it('renders error InlineAlert on API failure', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/providers')) {
        return Promise.resolve(
          new Response(JSON.stringify({ providers: [] }), { status: 200 }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ detail: 'fail' }), { status: 500 }),
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <AIAnalysisPanel
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
      />,
    );
    await fireEvent.click(screen.getByText('Запустить анализ'));
    await screen.findByText('AI временно недоступен');
  });

  it('renders idle hint before run', () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ providers: [] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <AIAnalysisPanel
        open
        onClose={() => undefined}
        sessionId="s1"
        dictName="D1"
      />,
    );
    expect(
      screen.getByText(/Нажмите «Запустить анализ»/i),
    ).toBeInTheDocument();
  });
});
