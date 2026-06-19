/**
 * Tests for RestructuredDialogue — parses plain text into chat bubbles.
 * Covers: standard format, bracket format, continuation lines, empty text,
 * unknown speaker, mixed formats.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import RestructuredDialogue from './RestructuredDialogue';

describe('RestructuredDialogue', () => {
  it('parses standard "Speaker: text" format', () => {
    const text = 'Клиент: Привет\nСотрудник: Здравствуйте';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(2);

    expect(bubbles[0].getAttribute('data-speaker')).toBe('Клиент');
    expect(bubbles[0].textContent).toContain('Привет');

    expect(bubbles[1].getAttribute('data-speaker')).toBe('Сотрудник');
    expect(bubbles[1].textContent).toContain('Здравствуйте');
  });

  it('parses "[Speaker]: text" bracket format', () => {
    const text = '[Клиент]: Хочу расторгнуть\n[Сотрудник]: Уточните причину';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0].getAttribute('data-speaker')).toBe('Клиент');
    expect(bubbles[1].getAttribute('data-speaker')).toBe('Сотрудник');
  });

  it('handles continuation lines for same speaker', () => {
    const text = 'Клиент: Первая строка\nВторая строка продолжения\nСотрудник: Ответ';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(2);
    // First bubble should contain both lines
    expect(bubbles[0].textContent).toContain('Первая строка');
    expect(bubbles[0].textContent).toContain('Вторая строка продолжения');
  });

  it('renders empty text without crashing', () => {
    const { container } = render(<RestructuredDialogue text="" />);
    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(0);
  });

  it('renders text without speaker as unknown speaker', () => {
    const text = 'Просто текст без спикера';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].getAttribute('data-speaker')).toBe('');
    expect(bubbles[0].textContent).toContain('Просто текст без спикера');
  });

  it('renders section heading', () => {
    render(<RestructuredDialogue text="Клиент: Тест" />);
    expect(screen.getByText('Реорганизованный диалог')).toBeTruthy();
  });

  it('handles multiple same-speaker turns', () => {
    const text = 'Клиент: Привет\nКлиент: Ещё вопрос';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0].getAttribute('data-speaker')).toBe('Клиент');
    expect(bubbles[1].getAttribute('data-speaker')).toBe('Клиент');
  });

  it('handles Chinese colon character (：)', () => {
    const text = 'Клиент：Привет';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].getAttribute('data-speaker')).toBe('Клиент');
  });

  it('ignores blank lines', () => {
    const text = '\n\nКлиент: Привет\n\n\nСотрудник: Ответ\n\n';
    const { container } = render(<RestructuredDialogue text={text} />);

    const bubbles = container.querySelectorAll('.dialogue-bubble');
    expect(bubbles).toHaveLength(2);
  });
});
