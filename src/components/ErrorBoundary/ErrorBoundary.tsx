/**
 * ErrorBoundary — React class component that catches runtime errors
 * within its subtree and displays a fallback UI using Beeline DS components.
 *
 * Each Route in App.tsx is wrapped in its own ErrorBoundary so that
 * an error on one page does not crash the entire application.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, Icon, Typography, Stack } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** Custom fallback UI. If omitted, the default DS-styled fallback is shown. */
  fallback?: ReactNode;
  /** Callback fired when an error is caught. */
  onError?: (error: Error) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo.componentStack);
    this.props.onError?.(error);
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <Stack
          direction="vertical"
          spacing="x4"
          align="center"
          role="alert"
          aria-live="assertive"
          style={{
            padding: 'var(--sizeSpacingX8)',
            textAlign: 'center',
            outline: 'none',
          }}
        >
          <Icon iconName={Icons.WarningCircled} size="large" />
          <Typography variant="h6">Что-то пошло не так</Typography>
          <Typography variant="body2" inactive>
            Произошла ошибка при отображении этой страницы.
          </Typography>
          <Stack direction="horizontal" spacing="x2">
            <Button variant="outlined" onClick={this.handleRetry}>
              Попробовать снова
            </Button>
            <Button variant="primary" onClick={this.handleReload} autoFocus>
              Обновить
            </Button>
          </Stack>
          {this.state.error && (
            <Typography
              variant="caption"
              inactive
            >
              {this.state.error.message}
            </Typography>
          )}
        </Stack>
      );
    }

    return this.props.children;
  }
}
