/**
 * NumberTicker — animated number counter from MagicUI.
 * Animates from startValue to value using spring physics (motion/react).
 *
 * @see https://magicui.design/docs/components/number-ticker
 */

import { useEffect, useRef, type ComponentPropsWithoutRef } from 'react';
import { useInView, useMotionValue, useSpring } from 'motion/react';
import { cn } from '@/lib/utils';

interface NumberTickerProps extends ComponentPropsWithoutRef<'span'> {
  /** Target number to animate to */
  value: number;
  /** Starting number */
  startValue?: number;
  /** Direction of counting */
  direction?: 'up' | 'down';
  /** Delay before animation starts (seconds) */
  delay?: number;
  /** Number of decimal places */
  decimalPlaces?: number;
}

export function NumberTicker({
  value,
  startValue = 0,
  direction = 'up',
  delay = 0,
  className,
  decimalPlaces = 0,
  ...props
}: NumberTickerProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const motionValue = useMotionValue(direction === 'down' ? value : startValue);
  const springValue = useSpring(motionValue, { damping: 60, stiffness: 100 });
  const isInView = useInView(ref, { once: true, margin: '0px' });

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    if (isInView) {
      timer = setTimeout(() => {
        motionValue.set(direction === 'down' ? startValue : value);
      }, delay * 1000);
    }
    return () => {
      if (timer !== null) clearTimeout(timer);
    };
  }, [motionValue, isInView, delay, value, direction, startValue]);

  useEffect(
    () =>
      springValue.on('change', (latest) => {
        if (ref.current) {
          ref.current.textContent = Intl.NumberFormat('ru-RU', {
            minimumFractionDigits: decimalPlaces,
            maximumFractionDigits: decimalPlaces,
          }).format(Number(latest.toFixed(decimalPlaces)));
        }
      }),
    [springValue, decimalPlaces],
  );

  return (
    <span
      ref={ref}
      className={cn('inline-block tabular-nums', className)}
      {...props}
    >
      {startValue}
    </span>
  );
}
