/**
 * BlurFade — MagicUI-style animation component.
 * Fades in from blur + slight translate to clear state.
 * Uses framer motion (motion/react) + IntersectionObserver.
 *
 * @see https://magicui.design/docs/components/blur-fade
 */

import { useRef, type ReactNode } from 'react';
import { motion, useInView } from 'motion/react';
import { cn } from '@/lib/utils';

interface BlurFadeProps {
  /** Content to animate */
  children: ReactNode;
  /** Delay before animation starts (seconds) */
  delay?: number;
  /** Duration of the animation (seconds) */
  duration?: number;
  /** Direction of appearance (which side it slides from) */
  direction?: 'up' | 'down' | 'left' | 'right';
  /** Whether to trigger animation on scroll into view */
  inView?: boolean;
  /** Amount of blur in the initial state */
  blur?: string;
  /** Additional CSS classes */
  className?: string;
  /** Whether to render the animation (for conditional mounting) */
  visible?: boolean;
}

/** Convert direction to initial Y/X offset */
function getTranslateValues(direction: BlurFadeProps['direction']): {
  y: number;
  x: number;
} {
  switch (direction) {
    case 'up':
      return { y: 6, x: 0 };
    case 'down':
      return { y: -6, x: 0 };
    case 'left':
      return { y: 0, x: 6 };
    case 'right':
      return { y: 0, x: -6 };
    default:
      return { y: 6, x: 0 };
  }
}

export function BlurFade({
  children,
  delay = 0,
  duration = 0.4,
  direction = 'up',
  inView = false,
  blur = '6px',
  className,
  visible = true,
}: BlurFadeProps) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: '0px' });

  const { y, x } = getTranslateValues(direction);

  // Determine if we should animate: either inView-triggered and visible, or just visible
  const shouldAnimate = inView ? isInView && visible : visible;

  return (
    <motion.div
      ref={ref}
      className={cn(className)}
      initial={{
        opacity: 0,
        filter: `blur(${blur})`,
        y,
        x,
      }}
      animate={
        shouldAnimate
          ? {
              opacity: 1,
              filter: 'blur(0px)',
              y: 0,
              x: 0,
            }
          : {
              opacity: 0,
              filter: `blur(${blur})`,
              y,
              x,
            }
      }
      transition={{
        duration,
        delay,
        ease: 'easeOut',
      }}
    >
      {children}
    </motion.div>
  );
}
