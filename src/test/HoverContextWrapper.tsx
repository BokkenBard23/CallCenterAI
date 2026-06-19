/**
 * Test wrapper that provides HoverContext for components
 * that use useHoverContext() during tests.
 */
import { type ReactNode } from 'react';
import { HoverProvider } from '../context/HoverContext';

export function HoverContextWrapper({ children }: { children: ReactNode }) {
  return <HoverProvider>{children}</HoverProvider>;
}
