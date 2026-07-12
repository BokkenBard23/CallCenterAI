import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StatisticsPanel } from './StatisticsPanel';

describe('StatisticsPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing when open=false', () => {
    const { container } = render(
      <StatisticsPanel open={false} sessionId="s1" dictName="D1" />,
    );
    expect(container.textContent).toBe('');
  });

  it('renders prompt when dictName is null', () => {
    render(<StatisticsPanel open sessionId="s1" dictName={null} />);
    expect(screen.getByText(/Выберите словарь/i)).toBeInTheDocument();
  });

  it('renders stats after fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          total_conditions: 42,
          total_words: 180,
          unique_words: 95,
          brackets_count: 8,
          channels_distribution: { ANY: 15, OPERATOR: 12, CLIENT: 15 },
          operators_count: { '': 20, 'И': 8, 'ИЛИ': 5, 'НЕ': 3, 'И НЕ': 4, 'ИЛИ НЕ': 2 },
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(<StatisticsPanel open sessionId="s1" dictName="D1" />);
    await screen.findByText('42');
    expect(screen.getByText('180')).toBeInTheDocument();
    expect(screen.getByText('95')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    // Channels
    expect(screen.getByText(/ANY: 15/)).toBeInTheDocument();
    expect(screen.getByText(/OPERATOR: 12/)).toBeInTheDocument();
    expect(screen.getByText(/CLIENT: 15/)).toBeInTheDocument();
  });

  it('renders error InlineAlert when fetch fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'fail' }), { status: 500 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(<StatisticsPanel open sessionId="s1" dictName="D1" />);
    await screen.findByText('Ошибка загрузки статистики');
  });
});
