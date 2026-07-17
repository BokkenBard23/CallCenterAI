/**
 * Tests for PageBreadcrumbs — shared breadcrumb trail for sub-pages.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { PageBreadcrumbs } from './PageBreadcrumbs';

function renderWithRouter(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('PageBreadcrumbs', () => {
  it('renders Главная and current page label', () => {
    renderWithRouter(<PageBreadcrumbs currentPage="Результаты" />);
    expect(screen.getByText('Главная')).toBeInTheDocument();
    expect(screen.getByText('Результаты')).toBeInTheDocument();
  });

  it('marks current page item with aria-current=page', () => {
    renderWithRouter(<PageBreadcrumbs currentPage="История" />);
    const current = screen.getByText('История');
    expect(current).toHaveAttribute('aria-current', 'page');
  });

  it('renders middle items when provided', () => {
    renderWithRouter(
      <PageBreadcrumbs
        currentPage="Сессия 123"
        middleItems={[{ label: 'SpeechLab', to: '/speechlab' }]}
      />,
    );
    expect(screen.getByText('Главная')).toBeInTheDocument();
    expect(screen.getByText('SpeechLab')).toBeInTheDocument();
    expect(screen.getByText('Сессия 123')).toBeInTheDocument();
  });

  it('renders without middle items', () => {
    renderWithRouter(<PageBreadcrumbs currentPage="Словари" />);
    expect(screen.getByText('Главная')).toBeInTheDocument();
    expect(screen.getByText('Словари')).toBeInTheDocument();
    // Only 2 items
    const links = screen.getAllByRole('link');
    // Главная is a link (clickable); Словари is a span.
    expect(links.length).toBeGreaterThanOrEqual(1);
  });
});
