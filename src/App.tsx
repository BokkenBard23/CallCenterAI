import { lazy, Suspense, useCallback, useEffect, useRef } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import {
  Box,
  Header,
  IconButton,
  Skeleton,
  Tabs,
  Tab,
  ThemeProvider,
  Tooltip,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { AnalysisProvider } from './context/AnalysisContext';
import { SnackbarProvider } from './context/SnackbarContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AnimatedThemeToggler } from './components/ui/animated-theme-toggler';
import useTheme from './hooks/useTheme';
import './App.scss';

const APP_PRODUCT_NAME = 'Анализ диалогов';

/**
 * NavBar tab descriptor.
 *
 * `route` is the SPA path to navigate to on click.
 * `match` checks whether the current pathname maps to this tab
 *   (e.g. `/speechlab/:sessionId` should still activate the SpeechLab tab).
 */
interface NavTabDescriptor {
  id: string;
  label: string;
  route: string;
  match: (pathname: string) => boolean;
}

const NAV_TABS: readonly NavTabDescriptor[] = [
  {
    id: 'home',
    label: 'Главная',
    route: '/',
    match: (p) => p === '/' || p === '',
  },
  {
    id: 'results',
    label: 'Результаты',
    route: '/results',
    match: (p) => p === '/results' || p.startsWith('/batch-results/'),
  },
  {
    id: 'speechlab',
    label: 'SpeechLab',
    route: '/speechlab',
    match: (p) => p === '/speechlab' || p.startsWith('/speechlab/'),
  },
  {
    id: 'dictionary',
    label: 'Словари',
    route: '/dictionary',
    match: (p) => p.startsWith('/dictionary'),
  },
  {
    id: 'history',
    label: 'История',
    route: '/history',
    match: (p) => p === '/history',
  },
] as const;

const UploadPage = lazy(() => import('./pages/UploadPage'));
const ResultsPage = lazy(() => import('./pages/ResultsPage'));
const BatchResultsPage = lazy(() => import('./pages/BatchResultsPage'));
const HistoryPage = lazy(() => import('./pages/HistoryPage'));
const SpeechLabPage = lazy(() => import('./pages/SpeechLabPage'));
const DictionaryLandingPage = lazy(() => import('./pages/DictionaryLandingPage'));
const DictionaryEditorPage = lazy(() => import('./pages/DictionaryEditorPage'));

function PageSkeleton() {
  return (
    <Box padding="x6">
      <Skeleton variant="title" width="40%" margin={{ bottom: 'x4' } as never} />
      <Skeleton variant="text" width="100%" height={32} />
      <Skeleton variant="text" width="80%" height={32} />
    </Box>
  );
}

/** Duration (ms) to keep the theme-transition class active after a theme change. */
const THEME_TRANSITION_DURATION = 250;

/** Header icons + AnimatedThemeToggler — extracted to use useNavigate inside Router */
function HeaderIcons({ theme, onToggleTheme }: { theme: string; onToggleTheme: () => void }) {
  const navigate = useNavigate();

  return (
    <>
      <Tooltip title="История анализов">
        <IconButton
          iconName={Icons.Clock}
          variant="plain"
          aria-label="История анализов"
          onClick={() => navigate('/history')}
        />
      </Tooltip>
      <AnimatedThemeToggler
        theme={theme as import('./hooks/useTheme').Theme}
        onThemeChange={onToggleTheme}
      />
    </>
  );
}

/**
 * NavBar — DS Tabs-based horizontal navigation bar.
 *
 * `activeTabId` is derived from `useLocation().pathname` so the active tab
 * always reflects the current route (controlled Tabs pattern). Clicking a
 * tab calls `useNavigate(route)` for SPA navigation. The Tabs body is left
 * empty: actual page content is rendered by `<Routes>` below.
 *
 * Layout contract (rule 06 universal pattern — flexbox chain, NOT sticky
 * and NOT calc(100vh - Npx)):
 *   .app-root → flex-direction:column
 *     Header      → flex-shrink:0
 *     NavBar      → flex-shrink:0   (this component)
 *     main        → flex:1, min-height:0, overflow-y:auto
 */
function NavBar() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  // Derive active tab index from current pathname.
  const activeTabIndex = (() => {
    const idx = NAV_TABS.findIndex((t) => t.match(pathname));
    // Default to "Главная" (index 0) when no tab matches (e.g. unknown route).
    return idx === -1 ? 0 : idx;
  })();

  // BUG 1 FIX: Navigation is handled SOLELY by the Tab-level `onClick`
  // handler, NOT by the Tabs `onChange` callback. The DS Tabs `useTabs` hook
  // has a sync useEffect that can fire `onChange` with a stale
  // `selectedTabIndex` prop during the React batch boundary between
  // `setSelectedTabIndex` and `navigate` (which uses useSyncExternalStore).
  // This caused a race condition where `changeTab(0)` was called —
  // navigating back to '/' immediately after clicking any tab.
  //
  // By removing `onChange`, the sync useEffect still updates the internal
  // `_selectedTabIndex` but does NOT trigger navigation. The Tab `onClick`
  // fires unconditionally on user click and calls `navigate(route)` directly.
  //
  // JK1 FIX (visual gate iteration 3): two defensive guards added.
  //  (a) `pathname === route` early-return — avoids spurious duplicate
  //      history pushes when DS Tabs internally fires onClick during sync
  //      useEffect / controlled `selectedTabIndex` changes (e.g. during
  //      dev HMR, React strict-mode double rendering, or accessibility-tree
  //      tooling snapshots).
  //  (b) Removed `key={pathname}` so Tabs is NOT remounted on every
  //      navigation. Remounting caused DS Tabs internal `_selectedTabIndex`
  //      to be reinitialised from `selectedTabIndex` prop on each navigation,
  //      which occasionally fired a stray onClick for the active tab.
  //      Without the remount, internal state stays stable across navigation
  //      and the sync useEffect only fires on real user interaction.
  //
  // The original BUG 1 race-condition protection (no `onChange`) is
  // preserved; this only adds a defensive belt-and-suspenders against
  // synthetic / spurious click events.
  const handleTabClick = useCallback(
    (route: string) => {
      if (pathname === route) return;
      navigate(route);
    },
    [navigate, pathname],
  );

  return (
    <nav className="app-navbar" aria-label="Основная навигация">
      <Tabs selectedTabIndex={activeTabIndex}>
        {NAV_TABS.map((tab) => (
          <Tab
            key={tab.id}
            label={tab.label}
            value={tab.route}
            role="tab"
            onClick={handleTabClick}
          />
        ))}
      </Tabs>
    </nav>
  );
}

function App() {
  const { theme, toggleTheme } = useTheme();
  const prevThemeRef = useRef(theme);
  const mainRef = useRef<HTMLElement>(null);

  // Add transient transition class on theme change
  useEffect(() => {
    if (prevThemeRef.current !== theme) {
      const root = document.querySelector('.app-root');
      if (root) {
        root.classList.add('app-root--theme-transition');
        const timer = setTimeout(() => {
          root.classList.remove('app-root--theme-transition');
        }, THEME_TRANSITION_DURATION);
        prevThemeRef.current = theme;
        return () => clearTimeout(timer);
      }
      prevThemeRef.current = theme;
    }
  }, [theme]);

  const handleThemeToggle = useCallback(() => {
    toggleTheme();
  }, [toggleTheme]);

  /** Focus management: when skip-nav is used, focus the main content area */
  const handleSkipToContent = useCallback(() => {
    mainRef.current?.focus();
  }, []);

  return (
    <ThemeProvider isRoot theme={theme}>
      <BrowserRouter>
        <SnackbarProvider>
          <AnalysisProvider>
            <div className="app-root" data-theme={theme}>
              {/* Skip-to-content link — first focusable element */}
              <a
                href="#main-content"
                className="skip-nav"
                onClick={handleSkipToContent}
              >
                Перейти к основному содержимому
              </a>

              <Header
                nameProduct={APP_PRODUCT_NAME}
                nameLogo="logoThemeable"
                iconsList={
                  <HeaderIcons theme={theme} onToggleTheme={handleThemeToggle} />
                }
              />
              <NavBar />
              <main
                id="main-content"
                role="main"
                className="app-main"
                tabIndex={-1}
                ref={mainRef}
                aria-label="Основное содержимое приложения"
              >
                <Suspense fallback={<PageSkeleton />}>
                  <Routes>
                    <Route path="/" element={<ErrorBoundary><UploadPage /></ErrorBoundary>} />
                    <Route path="/results" element={<ErrorBoundary><ResultsPage /></ErrorBoundary>} />
                    <Route path="/batch-results/:batchId" element={<ErrorBoundary><BatchResultsPage /></ErrorBoundary>} />
                    <Route path="/history" element={<ErrorBoundary><HistoryPage /></ErrorBoundary>} />
                    <Route path="/speechlab" element={<ErrorBoundary><SpeechLabPage /></ErrorBoundary>} />
                    <Route path="/speechlab/:sessionId" element={<ErrorBoundary><SpeechLabPage /></ErrorBoundary>} />
                    {/* BUG 5 FIX: /dictionary (without sessionId) renders a
                        landing page that redirects to an active session or
                        prompts the user to upload a dictionary. */}
                    <Route path="/dictionary" element={<ErrorBoundary><DictionaryLandingPage /></ErrorBoundary>} />
                    <Route path="/dictionary/:sessionId" element={<ErrorBoundary><DictionaryEditorPage /></ErrorBoundary>} />
                  </Routes>
                </Suspense>
              </main>
            </div>
          </AnalysisProvider>
        </SnackbarProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
