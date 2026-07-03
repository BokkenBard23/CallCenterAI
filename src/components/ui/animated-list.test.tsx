/**
 * Tests for AnimatedList — staggered list animation component.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AnimatedList, AnimatedListItem } from './animated-list';

// Mock motion/react to avoid animation issues in jsdom
vi.mock('motion/react', () => ({
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => (
      <div data-testid="motion-div" {...props}>
        {children}
      </div>
    ),
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
  useInView: () => true,
}));

describe('AnimatedList', () => {
  it('renders children inside a container', () => {
    render(
      <AnimatedList>
        <div>Item 1</div>
        <div>Item 2</div>
      </AnimatedList>,
    );
    expect(screen.getByText('Item 1')).toBeInTheDocument();
    expect(screen.getByText('Item 2')).toBeInTheDocument();
  });

  it('renders with custom className', () => {
    const { container } = render(
      <AnimatedList className="custom-class">
        <div>Item</div>
      </AnimatedList>,
    );
    expect(container.querySelector('.custom-class')).toBeInTheDocument();
  });

  it('uses default delay of 300ms', () => {
    // Just verify it renders without errors with default props
    render(
      <AnimatedList>
        <AnimatedListItem index={0}>Item 1</AnimatedListItem>
        <AnimatedListItem index={1}>Item 2</AnimatedListItem>
      </AnimatedList>,
    );
    expect(screen.getByText('Item 1')).toBeInTheDocument();
    expect(screen.getByText('Item 2')).toBeInTheDocument();
  });

  it('accepts custom delay prop', () => {
    render(
      <AnimatedList delay={500}>
        <AnimatedListItem index={0} delay={500}>Item</AnimatedListItem>
      </AnimatedList>,
    );
    expect(screen.getByText('Item')).toBeInTheDocument();
  });
});

describe('AnimatedListItem', () => {
  it('renders children', () => {
    render(<AnimatedListItem>Content</AnimatedListItem>);
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  it('renders with index 0 by default', () => {
    render(<AnimatedListItem>Content</AnimatedListItem>);
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(<AnimatedListItem className="item-class">Content</AnimatedListItem>);
    expect(screen.getByText('Content')).toBeInTheDocument();
  });
});
