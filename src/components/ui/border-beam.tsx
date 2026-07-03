/**
 * BorderBeam — animated border beam effect from MagicUI.
 * Renders an animated beam that travels along the border of its parent.
 *
 * Parent must have: position: relative; overflow: hidden;
 *
 * @see https://magicui.design/docs/components/border-beam
 */

import { cn } from '@/lib/utils';

export interface BorderBeamProps {
  /** Size of the beam in pixels */
  size?: number;
  /** Duration of one full cycle in seconds */
  duration?: number;
  /** Delay before animation starts in seconds */
  delay?: number;
  /** Starting color of the beam gradient */
  colorFrom?: string;
  /** Ending color of the beam gradient */
  colorTo?: string;
  /** Reverse animation direction */
  reverse?: boolean;
  /** Width of the beam line */
  borderWidth?: number;
  /** Initial offset position */
  initialOffset?: number;
  /** Additional CSS class */
  className?: string;
}

export function BorderBeam({
  size = 50,
  duration = 6,
  delay = 0,
  colorFrom = '#ffaa40',
  colorTo = '#9c40ff',
  reverse = false,
  borderWidth = 1,
  initialOffset = 0,
  className,
}: BorderBeamProps) {
  return (
    <div
      className={cn('pointer-events-none absolute inset-0', className)}
      style={{
        // Use CSS custom properties for the animation
        ['--border-beam-size' as string]: `${size}px`,
        ['--border-beam-duration' as string]: `${duration}s`,
        ['--border-beam-delay' as string]: `${delay}s`,
        ['--border-beam-color-from' as string]: colorFrom,
        ['--border-beam-color-to' as string]: colorTo,
        ['--border-beam-reverse' as string]: reverse ? '1' : '0',
        ['--border-beam-border-width' as string]: `${borderWidth}px`,
        ['--border-beam-initial-offset' as string]: `${initialOffset}px`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          overflow: 'hidden',
          borderRadius: 'inherit',
          pointerEvents: 'none',
        }}
      >
        {/* The beam element uses offset-path animation */}
        <div
          style={{
            position: 'absolute',
            width: `var(--border-beam-size)`,
            height: `var(--border-beam-size)`,
            background: `linear-gradient(90deg, ${colorFrom}, ${colorTo})`,
            borderRadius: '50%',
            filter: 'blur(6px)',
            opacity: 0.8,
            animation: `border-beam-spin var(--border-beam-duration) linear var(--border-beam-delay) infinite${reverse ? ' reverse' : ''}`,
            offsetPath: 'rect(0 auto auto 0 round 8px)',
            offsetDistance: `calc(var(--border-beam-initial-offset, 0px))`,
          }}
        />
      </div>
      <style>{`
        @keyframes border-beam-spin {
          from { offset-distance: 0%; }
          to { offset-distance: 100%; }
        }
      `}</style>
    </div>
  );
}
