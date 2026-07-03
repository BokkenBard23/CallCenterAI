/**
 * SnackbarContext — global snackbar notification system.
 *
 * Provides `useSnackbar()` hook that returns `{ showSnackbar }`.
 * SnackbarProvider wraps the entire app and renders a single DS Snackbar
 * at the bottom-left (per DS guideline: one at a time).
 *
 * Queue policy: 1 — new snackbar dismisses current, then shows new.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { Snackbar } from '@beeline/design-system-react';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

export interface SnackbarOptions {
  /** Snackbar variant: elastic stretches, fixed has min-width 344px */
  variant?: 'elastic' | 'fixed';
  /** Auto-hide delay in ms. Default: 4000 for success/info, 6000 for error/warning */
  delay?: number;
  /** Horizontal position */
  horizontal?: 'left' | 'center' | 'right';
  /** Vertical position */
  vertical?: 'top' | 'bottom';
  /** Action button inside snackbar */
  action?: { label: string; onClick: () => void };
  /** Show close button */
  closeButton?: boolean;
}

export interface SnackbarContextValue {
  /** Show a snackbar notification. Dismisses any currently visible snackbar. */
  showSnackbar: (message: string, options?: SnackbarOptions) => void;
  /** Close the currently visible snackbar. */
  closeSnackbar: () => void;
}

interface SnackbarEntry {
  message: string;
  options: Required<Omit<SnackbarOptions, 'action'>> & { action?: SnackbarOptions['action'] };
}

// ═══════════════════════════════════════════════════════════
// Context
// ═══════════════════════════════════════════════════════════

const SnackbarContext = createContext<SnackbarContextValue | null>(null);

/**
 * Hook to show snackbar notifications.
 * Must be used within a <SnackbarProvider>.
 *
 * Co-located with provider per React convention (context + hook in same file).
 * react-refresh/only-export-components is suppressed because splitting would
 * create a circular dependency (hook reads context, provider provides it).
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useSnackbar(): SnackbarContextValue {
  const ctx = useContext(SnackbarContext);
  if (!ctx) {
    throw new Error('useSnackbar must be used within a SnackbarProvider');
  }
  return ctx;
}

// ═══════════════════════════════════════════════════════════
// Provider
// ═══════════════════════════════════════════════════════════

interface SnackbarProviderProps {
  children: ReactNode;
}

/** Sequential ID generator for snackbar entries */
let nextId = 0;

export function SnackbarProvider({ children }: SnackbarProviderProps) {
  const [entry, setEntry] = useState<SnackbarEntry | null>(null);
  const [open, setOpen] = useState(false);
  const [snackbarKey, setSnackbarKey] = useState(nextId++);
  const rafIdRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  // Track mounted state to prevent state updates after unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, []);

  const showSnackbar = useCallback(
    (message: string, options?: SnackbarOptions) => {
      // Cancel any pending rAF from a previous showSnackbar call
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }

      // Dismiss current snackbar first, then show new one
      setOpen(false);

      // Use requestAnimationFrame to allow close animation before opening new
      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = null;
        if (!mountedRef.current) return;

        const resolved: SnackbarEntry = {
          message,
          options: {
            variant: options?.variant ?? 'elastic',
            delay: options?.delay ?? 4000,
            horizontal: options?.horizontal ?? 'left',
            vertical: options?.vertical ?? 'bottom',
            closeButton: options?.closeButton ?? true,
            action: options?.action,
          },
        };
        setEntry(resolved);
        setOpen(true);
        setSnackbarKey(nextId++);
      });
    },
    [],
  );

  const handleClose = useCallback(() => {
    setOpen(false);
  }, []);

  const contextValue = useCallback(
    (): SnackbarContextValue => ({ showSnackbar, closeSnackbar: handleClose }),
    [showSnackbar, handleClose],
  )();

  return (
    <SnackbarContext.Provider value={contextValue}>
      {children}
      {entry && (
        <Snackbar
          key={snackbarKey}
          open={open}
          message={entry.message}
          variant={entry.options.variant}
          delay={entry.options.delay}
          horizontal={entry.options.horizontal}
          vertical={entry.options.vertical}
          closeButton={entry.options.closeButton}
          action={entry.options.action}
          onClose={handleClose}
        />
      )}
    </SnackbarContext.Provider>
  );
}
