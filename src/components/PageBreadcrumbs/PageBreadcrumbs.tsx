/**
 * PageBreadcrumbs — shared "Главная › <Current Page>" trail for sub-pages.
 *
 * Renders a DS `Breadcrumbs` with a consistent shape:
 *   - First item: "Главная" — navigates to `/` via SPA router (the
 *     Breadcrumbs `value` API only renders display items, so we use the
 *     `children` API + RouterLink to make the home item clickable).
 *   - Last item: current page label — non-clickable (`currentPage`).
 *
 * Usage:
 *   <PageBreadcrumbs currentPage="Результаты" />
 *
 * Routes without breadcrumbs (per design-spec-chunk-1):
 *   - `/` (home / dashboard) — NavBar already provides top-level nav.
 *
 * The NavBar above the page already provides primary navigation; this
 * component is supplemental wayfinding. The "Главная" item is clickable
 * so users have an alternate one-click return path.
 */

import { memo, useMemo, type ReactNode } from 'react';
import { Breadcrumbs, Box } from '@beeline/design-system-react';
import RouterLink from '../RouterLink';
import './PageBreadcrumbs.css';

export interface PageBreadcrumbsProps {
  /** Label of the current page (last breadcrumb item). */
  currentPage: string;
  /** Optional aria-label for the breadcrumbs nav container. */
  ariaLabel?: string;
  /** Optional extra middle items between "Главная" and current page. */
  middleItems?: readonly { label: string; to?: string }[];
  /** Optional children rendered after the breadcrumb trail. */
  children?: ReactNode;
}

interface BreadcrumbItem {
  label: string;
  /** When `true`, item is rendered as the current page (non-clickable). */
  currentPage?: boolean;
  /** When provided, item is clickable and navigates to this route. */
  to?: string;
}

function PageBreadcrumbsBase({
  currentPage,
  ariaLabel = 'Хлебные крошки',
  middleItems,
  children,
}: PageBreadcrumbsProps) {
  const items = useMemo<BreadcrumbItem[]>(() => {
    const list: BreadcrumbItem[] = [
      { label: 'Главная', to: '/' },
      ...(middleItems ?? []),
      { label: currentPage, currentPage: true },
    ];
    return list;
  }, [currentPage, middleItems]);

  return (
    <Box className="page-breadcrumbs" style={{ marginBottom: 'var(--sizeSpacingX3, 12px)' }}>
      <Breadcrumbs aria-label={ariaLabel}>
        {items.map((item, idx) => {
          const isLast = idx === items.length - 1;
          // Clickable middle items with a `to` route → RouterLink (SPA nav).
          if (item.to && !isLast) {
            return (
              <RouterLink
                key={`${item.label}-${idx}`}
                to={item.to}
                ariaLabel={item.label}
              >
                {item.label}
              </RouterLink>
            );
          }
          // Current page (last item) or items without `to` → static text.
          return (
            <span key={`${item.label}-${idx}`} aria-current={item.currentPage ? 'page' : undefined}>
              {item.label}
            </span>
          );
        })}
        {children}
      </Breadcrumbs>
    </Box>
  );
}

export const PageBreadcrumbs = memo(PageBreadcrumbsBase);
export default PageBreadcrumbs;
