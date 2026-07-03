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

/**
 * Полифилл DataTransfer для jsdom — нужен для DropZone (drag-and-drop)
 */
if (typeof DataTransfer === 'undefined') {
  (globalThis as unknown as Record<string, unknown>).DataTransfer = class DataTransferPolyfill {
    items: { add: (file: File) => void }[] = [];
    files: File[] = [];

    constructor() {
      const fileList: File[] = [];
      this.files = fileList;
      this.items = {
        add: (file: File) => {
          fileList.push(file);
        },
      } as unknown as typeof this.items;
    }
  };
}

/**
 * Полифилл Element.scrollIntoView для jsdom — нужен DS Stepper
 */
if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    /* noop in jsdom */
  };
}

/**
 * Полифилл IntersectionObserver для jsdom — нужен для:
 * - motion/react (useInView) — BlurFade, NumberTicker
 * - Lazy loading components
 */
if (typeof IntersectionObserver === 'undefined') {
  class IntersectionObserverPolyfill {
    readonly root: Element | null = null;
    readonly rootMargin: string = '';
    readonly thresholds: ReadonlyArray<number> = [];

    constructor(
      private callback: IntersectionObserverCallback,
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      _options?: IntersectionObserverInit,
    ) {}

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    observe(_target: Element): void {
      /* noop in jsdom — report as not intersecting */
    }
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    unobserve(_target: Element): void {
      /* noop */
    }
    disconnect(): void {
      /* noop */
    }
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }

  (globalThis as unknown as Record<string, unknown>).IntersectionObserver =
    IntersectionObserverPolyfill;
}
