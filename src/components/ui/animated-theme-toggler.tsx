/**
 * AnimatedThemeToggler — theme toggle with View Transitions API animation.
 *
 * Features:
 *   - Circle-reveal animation when View Transitions API is available (Chrome 111+)
 *   - Graceful fallback: instant toggle on browsers without View Transitions
 *   - DS Icon components (Icons.HalfMoon / Icons.Sun) instead of lucide-react
 *   - Works with the useTheme hook (localStorage persistence handled externally)
 *   - Respects prefers-reduced-motion
 */

import { useCallback, useRef } from 'react';
import { Button, Icon } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { Theme } from '../../hooks/useTheme';

interface AnimatedThemeTogglerProps {
  /** Current theme ('light' or 'dark') */
  theme: Theme;
  /** Callback to toggle the theme */
  onThemeChange: () => void;
}

/**
 * Check if View Transitions API is supported.
 * Requires 'startViewTransition' on document.
 */
function supportsViewTransitions(): boolean {
  return typeof document !== 'undefined' && 'startViewTransition' in document;
}

/**
 * Check if user prefers reduced motion.
 */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function AnimatedThemeToggler({ theme, onThemeChange }: AnimatedThemeTogglerProps) {
  const toggleRef = useRef<HTMLButtonElement>(null);

  const handleToggle = useCallback(() => {
    // If View Transitions API is available and user doesn't prefer reduced motion,
    // animate the theme change with a circle reveal from the toggle button position.
    if (supportsViewTransitions() && !prefersReducedMotion()) {
      const button = toggleRef.current;
      if (button) {
        const rect = button.getBoundingClientRect();
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;

        // Calculate the maximum radius to cover the entire viewport
        const maxRadius = Math.hypot(
          Math.max(x, window.innerWidth - x),
          Math.max(y, window.innerHeight - y),
        );

        // Set CSS custom properties for the clip-path animation
        document.documentElement.style.setProperty('--theme-transition-x', `${x}px`);
        document.documentElement.style.setProperty('--theme-transition-y', `${y}px`);
        document.documentElement.style.setProperty('--theme-transition-max-radius', `${maxRadius}px`);
      }

      // Use View Transitions API with circle clip-path
      (document as unknown as { startViewTransition: (cb: () => void) => { finished: Promise<void> } })
        .startViewTransition(() => {
          onThemeChange();
        });
    } else {
      // Fallback: instant toggle without animation
      onThemeChange();
    }
  }, [onThemeChange]);

  const isLight = theme === 'light';
  const ariaLabel = isLight ? 'Включить тёмную тему' : 'Включить светлую тему';

  return (
    <Button
      ref={toggleRef}
      variant="outlined"
      size="small"
      onClick={handleToggle}
      aria-label={ariaLabel}
    >
      {isLight ? (
        <Icon iconName={Icons.HalfMoon} />
      ) : (
        <Icon iconName={Icons.Sun} />
      )}
    </Button>
  );
}


