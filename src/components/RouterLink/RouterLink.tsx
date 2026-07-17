/**
 * RouterLink — adapter that bridges DS `LinkRouter` to react-router-dom
 * SPA navigation.
 *
 * Why this exists:
 *   DS `LinkRouter` exposes only an `href` prop, which (with BrowserRouter)
 *   would trigger a full-page reload. For SPA navigation we need to call
 *   `useNavigate()` from react-router-dom and prevent the default anchor
 *   action.
 *
 * Pattern:
 *   <RouterLink to="/speechlab">Открыть</RouterLink>
 *
 * The wrapper renders a DS `LinkRouter` (for visual consistency and DS
 * tokens) and intercepts click events on its content span to call
 * `navigate(to)` while preventing the default `<a href>` navigation.
 */

import { useCallback, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { LinkRouter } from '@beeline/design-system-react';

export interface RouterLinkProps {
  /** SPA route to navigate to on click. */
  to: string;
  /** Link label / content. */
  children: ReactNode;
  /** Optional active state for visual emphasis. */
  isActive?: boolean;
  /** Optional class passed through to DS LinkRouter. */
  className?: string;
  /** Optional aria-label for accessibility. */
  ariaLabel?: string;
}

export default function RouterLink({
  to,
  children,
  isActive,
  className,
  ariaLabel,
}: RouterLinkProps) {
  const navigate = useNavigate();

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      // Only intercept primary, unmodified clicks (left-click, no
      // Ctrl/Cmd/Shift/Middle — let users open-in-new-tab if they want).
      if (e.defaultPrevented) return;
      if (e.button !== 0) return;
      if (e.metaKey || e.altKey || e.ctrlKey || e.shiftKey) return;

      e.preventDefault();
      navigate(to);
    },
    [navigate, to],
  );

  return (
    <LinkRouter href={to} isActive={isActive} className={className}>
      {/* Wrap content in a span that intercepts clicks. We attach the
          handler via onClick (works for keyboard + mouse) and
          preventDefault so the underlying <a href> does not reload the
          page. */}
      <span onClick={handleClick} role="presentation" aria-label={ariaLabel}>
        {children}
      </span>
    </LinkRouter>
  );
}
