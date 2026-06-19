import { lazy, Suspense, useCallback, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Header,
  Icon,
  IconButton,
  Skeleton,
  ThemeProvider,
  Tooltip,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { AnalysisProvider } from './context/AnalysisContext';
import useTheme from './hooks/useTheme';
import './App.scss';

export const APP_PRODUCT_NAME = 'Анализ диалогов';

const UploadPage = lazy(() => import('./pages/UploadPage'));
const ResultsPage = lazy(() => import('./pages/ResultsPage'));
const BatchResultsPage = lazy(() => import('./pages/BatchResultsPage'));
const HistoryPage = lazy(() => import('./pages/HistoryPage'));

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

/** Header icons + history nav — extracted to use useNavigate inside Router */
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
      <Button
        variant="outlined"
        size="small"
        onClick={onToggleTheme}
        aria-label={
          theme === 'light'
            ? 'Включить тёмную тему'
            : 'Включить светлую тему'
        }
      >
        {theme === 'light' ? (
          <Icon iconName={Icons.HalfMoon} />
        ) : (
          <Icon iconName={Icons.Sun} />
        )}
      </Button>
    </>
  );
}

function App() {
  const { theme, toggleTheme } = useTheme();
  const prevThemeRef = useRef(theme);

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

  return (
    <ThemeProvider isRoot theme={theme}>
      <BrowserRouter>
        <AnalysisProvider>
          <div className="app-root" data-theme={theme}>
            <Header
              nameProduct={APP_PRODUCT_NAME}
              nameLogo="logoThemeable"
              iconsList={
                <HeaderIcons theme={theme} onToggleTheme={handleThemeToggle} />
              }
            />
            <main className="app-main">
              <Suspense fallback={<PageSkeleton />}>
                <Routes>
                  <Route path="/" element={<UploadPage />} />
                  <Route path="/results" element={<ResultsPage />} />
                  <Route path="/batch-results/:batchId" element={<BatchResultsPage />} />
                  <Route path="/history" element={<HistoryPage />} />
                </Routes>
              </Suspense>
            </main>
          </div>
        </AnalysisProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
