import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

describe('test setup', () => {
  it('runs vitest', () => {
    expect(1 + 1).toBe(2)
  })

  it('loads RTL and jest-dom matchers', () => {
    render(<span data-testid="x">ok</span>)
    expect(screen.getByTestId('x')).toBeInTheDocument()
  })
})
