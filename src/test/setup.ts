import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

/**
 * Vitest с `globals: false` не предоставляет глобальный `afterEach`, поэтому RTL
 * не подключает авто-cleanup — без этого накапливаются деревья render() и порталы.
 */
afterEach(() => {
  cleanup();
  const portalRoot = document.getElementById('root');
  if (portalRoot) {
    portalRoot.innerHTML = '';
  }
});

/**
 * DS Modal/Dialog/Drawer требуют корневой элемент #root в DOM для порталов
 */
if (!document.getElementById('root')) {
  const root = document.createElement('div');
  root.id = 'root';
  document.body.appendChild(root);
}

/**
 * Полифилл matchMedia для jsdom (используется TablePagination и др. DS-компонентами)
 */
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/**
 * Полифиллы для jsdom-среды, необходимые при импорте
 * @beeline/design-system-react (PDFGallery → pdfjs-dist, Chip → useResizeObserver)
 */
if (typeof DOMMatrix === 'undefined') {
  class DOMMatrixPolyfill {
    a = 1;
    b = 0;
    c = 0;
    d = 1;
    e = 0;
    f = 0;
    is2D = true;
    isIdentity = true;

    static fromString() {
      return new DOMMatrixPolyfill();
    }
    multiply() {
      return this;
    }
    translate() {
      return this;
    }
    scale() {
      return this;
    }
    toString() {
      return 'matrix(1, 0, 0, 1, 0, 0)';
    }
  }

  (globalThis as unknown as Record<string, unknown>).DOMMatrix = DOMMatrixPolyfill;
}

if (typeof ResizeObserver === 'undefined') {
  class ResizeObserverPolyfill {
    observe() {
      /* noop */
    }
    unobserve() {
      /* noop */
    }
    disconnect() {
      /* noop */
    }
  }

  (globalThis as unknown as Record<string, unknown>).ResizeObserver = ResizeObserverPolyfill;
}
