# React + Vite + Beeline Design System

Минимальный шаблон приложения: шапка (`Header`) и переключение светлой/тёмной темы на `@beeline/design-system-react` и `@beeline/design-tokens`.

## Требования

- **Node.js** 18+ (для текущего `pdfjs-dist` в зависимостях DS уместно 20+)
- Доступ к реестру npm с пакетами `@beeline/*` (шаблон [`npmrc.example`](npmrc.example); при `install` пайплайна в **пустую** папку копируется в `.npmrc`)

## Команды

| Команда | Назначение |
| -------- | ------------ |
| `npm install` | Установка зависимостей |
| `npm run dev` | Режим разработки (Vite) |
| `npm run build` | Сборка для продакшена |
| `npm run preview` | Просмотр production-сборки |
| `npm run test` | Тесты (Vitest + Testing Library) |
| `npm run test:coverage` | Тесты с покрытием |
| `npm run lint` | ESLint |

## Точки настройки

- Имя продукта в шапке: константа [`APP_PRODUCT_NAME`](src/App.tsx) в `src/App.tsx`.
- Контент страницы: элемент `<main className="app-main">` в том же файле.

## Стек

- React 18, TypeScript, Vite 7
- `@beeline/design-system-react`, `@beeline/design-tokens`
- Vitest, jsdom, `@testing-library/react`
