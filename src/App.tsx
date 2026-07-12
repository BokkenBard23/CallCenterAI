import { lazy, Suspense, useCallback, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import {
  Box,
  Header,
  IconButton,
  Skeleton,
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

const UploadPage = lazy(() => import('./pages/UploadPage'));
const ResultsPage = lazy(() => import('./pages/ResultsPage'));
const BatchResultsPage = lazy(() => import('./pages/BatchResultsPage'));
const HistoryPage = lazy(() => import('./pages/HistoryPage'));
const SpeechLabPage = lazy(() => import('./pages/SpeechLabPage'));
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
