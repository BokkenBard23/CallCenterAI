import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { WordFrequencyBar } from './WordFrequencyBar';

describe('WordFrequencyBar', () => {
  it('renders bars for given word frequencies', () => {
    const { container } = render(
      <WordFrequencyBar
        data={[
          { word: 'привет', count: 12 },
          { word: 'отмена', count: 9 },
          { word: 'спасибо', count: 7 },
        ]}
      />,
    );
    expect(container.textContent).toContain('привет');
    expect(container.textContent).toContain('отмена');
    expect(container.textContent).toContain('спасибо');
    expect(container.textContent).toContain('12');
  });

  it('renders empty state when data is empty', () => {
    const { container } = render(<WordFrequencyBar data={[]} />);
    expect(container.textContent).toContain('Нет данных');
  });

  it('limits items to maxItems', () => {
    const data = Array.from({ length: 20 }, (_, i) => ({ word: `w${i}`, count: 20 - i }));
    const { container } = render(<WordFrequencyBar data={data} maxItems={5} />);
    expect(container.textContent).toContain('w0');
    expect(container.textContent).toContain('w4');
    expect(container.textContent).not.toContain('w5');
  });

  it('renders progressbar roles for a11y', () => {
    const { container } = render(
      <WordFrequencyBar data={[{ word: 'hi', count: 5 }]} />,
    );
    const bars = container.querySelectorAll('[role="progressbar"]');
    expect(bars.length).toBe(1);
    expect(bars[0].getAttribute('aria-valuenow')).toBe('5');
  });
});
