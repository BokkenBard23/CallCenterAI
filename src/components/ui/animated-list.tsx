/**
 * AnimatedList — staggered list animation using framer-motion.
 * Each child item slides in + fades with configurable delay.
 *
 * @see https://magicui.design/docs/components/animated-list
 */

import { type ReactNode } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '@/lib/utils';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

export interface AnimatedListProps {
  /** Content items — wrap each in AnimatedListItem */
  children: ReactNode;
  /** Delay between item appearances in ms (default: 300) */
  delay?: number;
  /** Additional CSS class */
  className?: string;
}

export interface AnimatedListItemProps {
  /** Item content */
  children: ReactNode;
  /** Unique key for AnimatePresence */
  itemKey?: string;
  /** Stagger index — auto-incremented by parent AnimatedList */
  index?: number;
  /** Delay between items in ms (inherited from parent) */
  delay?: number;
  /** Additional CSS class */
  className?: string;
}

// ═══════════════════════════════════════════════════════════
// AnimatedListItem
// ═══════════════════════════════════════════════════════════

export function AnimatedListItem({
  children,
  index = 0,
  delay = 300,
  className,
}: AnimatedListItemProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{
        duration: 0.3,
        delay: (index * delay) / 1000,
        ease: 'easeOut',
      }}
      className={cn(className)}
    >
      {children}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════
// AnimatedList
// ═══════════════════════════════════════════════════════════

/**
 * AnimatedList wraps children and applies staggered entrance animation.
 * Each child should be an AnimatedListItem with an `index` prop.
 */
export function AnimatedList({
  children,
  className,
}: AnimatedListProps) {
  return (
    <AnimatePresence mode="popLayout">
      <div className={cn(className)}>
        {children}
      </div>
    </AnimatePresence>
  );
}
