/**
 * AnimatedCircularProgressBar — SVG-based animated circular progress.
 * Pure CSS/SVG — no runtime dependencies.
 *
 * Uses CSS @keyframes for the initial animation instead of React state,
 * avoiding the set-state-in-effect lint issue.
 *
 * @see https://magicui.design/docs/components/animated-circular-progress-bar
 */

import { cn } from '@/lib/utils';

export interface AnimatedCircularProgressBarProps {
  /** Current value (0–max) */
  value: number;
  /** Maximum value */
  max?: number;
  /** Minimum value */
  min?: number;
  /** Primary (filled arc) color */
  gaugePrimaryColor: string;
  /** Secondary (track) color */
  gaugeSecondaryColor: string;
  /** Additional CSS class */
  className?: string;
}

export function AnimatedCircularProgressBar({
  value,
  max = 100,
  min = 0,
  gaugePrimaryColor,
  gaugeSecondaryColor,
  className,
}: AnimatedCircularProgressBarProps) {
  const circumference = 2 * Math.PI * 45; // radius = 45 in a 100x100 viewBox
  const percent = Math.min(Math.max((value - min) / (max - min), 0), 1);
  const strokeDashoffset = circumference - percent * circumference;

  return (
    <div className={cn('relative inline-flex items-center justify-center', className)}>
      <svg
        width="120"
        height="120"
        viewBox="0 0 100 100"
        style={{ transform: 'rotate(-90deg)' }}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={min}
        aria-valuemax={max}
      >
        {/* Background track */}
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          stroke={gaugeSecondaryColor}
          strokeWidth="8"
          strokeLinecap="round"
        />
        {/* Progress arc — animated from circumference to actual offset via CSS */}
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          stroke={gaugePrimaryColor}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          style={{
            transition: 'stroke-dashoffset 0.5s ease-out',
            // Start fully hidden, then CSS transition reveals progress.
            // The transition property handles the animation on mount.
            animation: `circular-progress-fill 0.5s ease-out forwards`,
          }}
        />
      </svg>
      <span
        style={{
          position: 'absolute',
          fontSize: '1.25rem',
          fontWeight: 600,
          color: gaugePrimaryColor,
        }}
      >
        {Math.round(percent * 100)}%
      </span>
      {/* Inline keyframes for the progress arc animation */}
      <style>{`
        @keyframes circular-progress-fill {
          from { stroke-dashoffset: ${circumference}; }
          to { stroke-dashoffset: ${strokeDashoffset}; }
        }
      `}</style>
    </div>
  );
}
