/**
 * TypingAnimation — MagicUI-style typing effect component.
 * Displays text character by character with optional blinking cursor.
 * Uses framer motion (motion/react) for animation.
 *
 * @see https://magicui.design/docs/components/typing-animation
 */

import { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '@/lib/utils';

interface TypingAnimationProps {
  /** Text to animate typing */
  text: string;
  /** Speed in ms per character. Default: 30 */
  speed?: number;
  /** Show blinking cursor. Default: true */
  showCursor?: boolean;
  /** Blink cursor animation. Default: true */
  blinkCursor?: boolean;
  /** Cursor style. Default: 'line' */
  cursorStyle?: 'line' | 'block' | 'underscore';
  /** Whether to start when element enters viewport. Default: true */
  startOnView?: boolean;
  /** Delay before starting (seconds). Default: 0 */
  delay?: number;
  /** Additional CSS classes */
  className?: string;
  /** Callback when typing completes */
  onComplete?: () => void;
}

/** Max chars to animate — rest appears instantly */
const MAX_ANIMATED_CHARS = 200;

export function TypingAnimation({
  text,
  speed = 30,
  showCursor = true,
  blinkCursor = true,
  cursorStyle = 'line',
  startOnView = true,
  delay = 0,
  className,
  onComplete,
}: TypingAnimationProps) {
  const [displayedLength, setDisplayedLength] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [hasStarted, setHasStarted] = useState(!startOnView);
  const ref = useRef<HTMLSpanElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onCompleteRef = useRef(onComplete);

  // Determine how many chars to animate vs show instantly
  const animatableText = text.slice(0, MAX_ANIMATED_CHARS);
  const instantText = text.slice(MAX_ANIMATED_CHARS);
  const totalAnimatedLength = animatableText.length;

  // Intersection observer for startOnView
  useEffect(() => {
    if (!startOnView || hasStarted) return;

    const element = ref.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          // Apply initial delay
          startTimerRef.current = setTimeout(() => {
            setHasStarted(true);
          }, delay * 1000);
          observer.disconnect();
        }
      },
      { threshold: 0.1 },
    );

    observer.observe(element);

    return () => {
      observer.disconnect();
      if (startTimerRef.current !== null) {
        clearTimeout(startTimerRef.current);
      }
    };
  }, [startOnView, hasStarted, delay]);

  // Keep onComplete ref in sync (in effect, not during render)
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  // Typing effect — runs when hasStarted or text changes
  useEffect(() => {
    if (!hasStarted) return;

    if (animatableText.length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Animation reset: empty text → set state to initial
      setDisplayedLength(0);
      setIsComplete(true);
      onCompleteRef.current?.();
      return;
    }

    // Reset state for fresh start (either new text or initial)
    let currentLength = 0;
    setDisplayedLength(0);
    setIsComplete(false);

    const typeNextChar = () => {
      currentLength += 1;
      setDisplayedLength(currentLength);

      if (currentLength >= totalAnimatedLength) {
        setIsComplete(true);
        onCompleteRef.current?.();
        return;
      }

      timerRef.current = setTimeout(typeNextChar, speed);
    };

    timerRef.current = setTimeout(typeNextChar, speed);

    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, [hasStarted, animatableText, totalAnimatedLength, speed]);

  const displayedText = animatableText.slice(0, displayedLength) + instantText;

  // Cursor character based on style
  const cursorChar = cursorStyle === 'block' ? '█' : cursorStyle === 'underscore' ? '_' : '|';

  return (
    <span ref={ref} className={cn('inline', className)}>
      <span>{displayedText}</span>
      <AnimatePresence>
        {showCursor && (
          <motion.span
            className={cn(
              'inline-block ml-px',
              cursorStyle === 'line' && 'border-r-2 border-current',
              cursorStyle === 'block' && 'text-current',
              cursorStyle === 'underscore' && 'border-b-2 border-current',
            )}
            style={{
              height: cursorStyle === 'line' ? '1em' : undefined,
              width: cursorStyle === 'block' ? '0.6em' : undefined,
            }}
            animate={
              blinkCursor && isComplete
                ? { opacity: [1, 0] }
                : { opacity: 1 }
            }
            transition={
              blinkCursor && isComplete
                ? { duration: 0.5, repeat: Infinity, repeatType: 'reverse' }
                : { duration: 0 }
            }
          >
            {cursorStyle === 'block' ? cursorChar : ''}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
