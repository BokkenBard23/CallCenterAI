/**
 * Utility helpers shared across UI components.
 * Provides `cn` for conditional className merging.
 */

/**
 * Merge class names — filters falsy values and joins with space.
 * Lightweight alternative to clsx + tailwind-merge (no Tailwind in this project).
 */
export function cn(...inputs: (string | undefined | null | false)[]): string {
  return inputs.filter(Boolean).join(' ');
}
