# Bun + Vite + React Best Practices

Modern frontend development with Bun runtime, Vite bundler, and React with TypeScript.

---

## Table of Contents

1. [Why Bun + Vite](#1-why-bun--vite)
2. [Project Setup](#2-project-setup)
3. [TypeScript Configuration](#3-typescript-configuration)
4. [Project Structure](#4-project-structure)
5. [React Patterns](#5-react-patterns)
6. [State Management](#6-state-management)
7. [Data Fetching with TanStack Query](#7-data-fetching-with-tanstack-query)
8. [Styling with Tailwind](#8-styling-with-tailwind)
9. [Testing](#9-testing)
10. [Build & Deployment](#10-build--deployment)

---

## 1. Why Bun + Vite

### Bun Advantages

| Feature | Benefit |
|---------|---------|
| All-in-one | Runtime, package manager, bundler, test runner |
| Speed | 4x faster startup than Node.js |
| TypeScript native | Runs .ts files directly |
| npm compatible | Drop-in replacement |

### Why Use Both?

- **Bun**: Fast package management, TypeScript execution, production runtime
- **Vite**: Superior HMR (Hot Module Replacement), mature plugin ecosystem, React Fast Refresh

The combo: `bun` for everything except the dev server, `vite` for development.

---

## 2. Project Setup

### Create New Project

```bash
# Create Vite + React + TypeScript project
bun create vite my-app --template react-ts
cd my-app

# Install dependencies
bun install

# Start dev server
bun run dev
```

### Package.json Scripts

```json
{
  "name": "my-app",
  "scripts": {
    "dev": "bunx --bun vite",
    "build": "bunx vite build",
    "preview": "bunx --bun vite preview",
    "lint": "bunx eslint . --ext ts,tsx",
    "test": "bun test",
    "typecheck": "bunx tsc --noEmit"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.4.0",
    "typescript": "^5.7.0",
    "vite": "^6.1.0"
  }
}
```

### Vite Configuration

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },

  server: {
    port: 5173,
    // Proxy API requests to backend
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },

  build: {
    // Optimize chunks
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          router: ['react-router-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
});
```

---

## 3. TypeScript Configuration

### Strict TypeScript

```json
// tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",

    // Strict settings
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noPropertyAccessFromIndexSignature": true,

    // Path aliases
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    },

    // Other
    "skipLibCheck": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

```json
// tsconfig.node.json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

### Type Patterns

```typescript
// Prefer type over interface for most cases
type User = {
  id: string;
  name: string;
  email: string;
};

// Use interface for extendable types
interface ApiResponse<T> {
  data: T;
  status: number;
}

// Props types
type ButtonProps = {
  variant?: 'primary' | 'secondary' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  children: React.ReactNode;
  onClick?: () => void;
};

// Event handlers
type ClickHandler = React.MouseEventHandler<HTMLButtonElement>;
type ChangeHandler = React.ChangeEventHandler<HTMLInputElement>;

// Utility types
type PartialUser = Partial<User>;
type RequiredUser = Required<User>;
type UserKeys = keyof User;
```

---

## 4. Project Structure

### Feature-Based Structure

```
src/
├── app/
│   ├── App.tsx              # Root component
│   ├── routes.tsx           # Route definitions
│   └── providers.tsx        # Context providers
├── features/
│   ├── auth/
│   │   ├── components/
│   │   │   ├── LoginForm.tsx
│   │   │   └── index.ts
│   │   ├── hooks/
│   │   │   └── useAuth.ts
│   │   ├── api/
│   │   │   └── auth.ts
│   │   └── index.ts         # Public exports
│   └── dashboard/
│       ├── components/
│       ├── hooks/
│       └── index.ts
├── components/              # Shared components
│   ├── ui/
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Card.tsx
│   │   └── index.ts
│   └── layout/
│       ├── Header.tsx
│       ├── Sidebar.tsx
│       └── Layout.tsx
├── hooks/                   # Shared hooks
│   ├── useLocalStorage.ts
│   └── useDebounce.ts
├── lib/                     # Utilities
│   ├── api.ts              # API client
│   ├── utils.ts
│   └── cn.ts               # className utility
├── types/                   # Shared types
│   └── index.ts
├── main.tsx                # Entry point
└── index.css               # Global styles
```

### Barrel Exports

```typescript
// features/auth/index.ts
export { LoginForm } from './components/LoginForm';
export { useAuth } from './hooks/useAuth';
export type { User, AuthState } from './types';

// Usage
import { LoginForm, useAuth } from '@/features/auth';
```

---

## 5. React Patterns

### Functional Components

```tsx
type CardProps = {
  title: string;
  children: React.ReactNode;
  className?: string;
};

export function Card({ title, children, className = '' }: CardProps) {
  return (
    <div className={`rounded-lg border p-4 ${className}`}>
      <h3 className="font-bold text-lg mb-2">{title}</h3>
      {children}
    </div>
  );
}
```

### Compound Components

```tsx
type CardContextType = {
  variant: 'default' | 'outlined';
};

const CardContext = React.createContext<CardContextType | null>(null);

function useCardContext() {
  const context = React.useContext(CardContext);
  if (!context) {
    throw new Error('Card components must be used within Card');
  }
  return context;
}

function Card({ children, variant = 'default' }: { children: React.ReactNode; variant?: 'default' | 'outlined' }) {
  return (
    <CardContext.Provider value={{ variant }}>
      <div className="rounded-lg border p-4">{children}</div>
    </CardContext.Provider>
  );
}

Card.Header = function CardHeader({ children }: { children: React.ReactNode }) {
  return <div className="border-b pb-2 mb-2 font-bold">{children}</div>;
};

Card.Body = function CardBody({ children }: { children: React.ReactNode }) {
  return <div className="py-2">{children}</div>;
};

Card.Footer = function CardFooter({ children }: { children: React.ReactNode }) {
  return <div className="border-t pt-2 mt-2">{children}</div>;
};

// Usage
<Card variant="outlined">
  <Card.Header>Title</Card.Header>
  <Card.Body>Content</Card.Body>
  <Card.Footer>Actions</Card.Footer>
</Card>
```

### Custom Hooks

```typescript
// hooks/useLocalStorage.ts
import { useState, useEffect } from 'react';

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : initialValue;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue] as const;
}

// hooks/useDebounce.ts
import { useState, useEffect } from 'react';

export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

// hooks/useToggle.ts
import { useState, useCallback } from 'react';

export function useToggle(initialValue = false) {
  const [value, setValue] = useState(initialValue);
  const toggle = useCallback(() => setValue(v => !v), []);
  return [value, toggle] as const;
}
```

---

## 6. State Management

### When to Use What

| State Type | Solution |
|------------|----------|
| Server state | TanStack Query |
| Form state | react-hook-form |
| Local UI state | useState |
| Shared UI state | Context or Zustand |
| URL state | React Router |

### Context for Shared State

```tsx
// contexts/ThemeContext.tsx
import { createContext, useContext, useState, useCallback } from 'react';

type Theme = 'light' | 'dark';

type ThemeContextType = {
  theme: Theme;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextType | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>('light');

  const toggleTheme = useCallback(() => {
    setTheme(t => (t === 'light' ? 'dark' : 'light'));
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
}
```

### Zustand for Complex State

```typescript
// stores/appStore.ts
import { create } from 'zustand';

type AppState = {
  sidebarOpen: boolean;
  selectedItemId: string | null;
  toggleSidebar: () => void;
  selectItem: (id: string | null) => void;
};

export const useAppStore = create<AppState>((set) => ({
  sidebarOpen: true,
  selectedItemId: null,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  selectItem: (id) => set({ selectedItemId: id }),
}));

// Usage
function Sidebar() {
  const { sidebarOpen, toggleSidebar } = useAppStore();
  // ...
}
```

---

## 7. Data Fetching with TanStack Query

### Setup

```tsx
// app/providers.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
```

### API Client

```typescript
// lib/api.ts
const API_BASE = '/api';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, error.detail || 'Request failed');
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json();
}

export const api = {
  get: <T>(endpoint: string) => request<T>(endpoint),
  post: <T>(endpoint: string, data: unknown) =>
    request<T>(endpoint, { method: 'POST', body: JSON.stringify(data) }),
  put: <T>(endpoint: string, data: unknown) =>
    request<T>(endpoint, { method: 'PUT', body: JSON.stringify(data) }),
  delete: <T>(endpoint: string) =>
    request<T>(endpoint, { method: 'DELETE' }),
};
```

### Query Hooks

```typescript
// features/items/api/items.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

type Item = {
  id: string;
  name: string;
  description: string;
};

type CreateItemInput = Omit<Item, 'id'>;

// Query keys
export const itemKeys = {
  all: ['items'] as const,
  lists: () => [...itemKeys.all, 'list'] as const,
  detail: (id: string) => [...itemKeys.all, 'detail', id] as const,
};

// Fetch all items
export function useItems() {
  return useQuery({
    queryKey: itemKeys.lists(),
    queryFn: () => api.get<Item[]>('/items'),
  });
}

// Fetch single item
export function useItem(id: string) {
  return useQuery({
    queryKey: itemKeys.detail(id),
    queryFn: () => api.get<Item>(`/items/${id}`),
    enabled: !!id,
  });
}

// Create item
export function useCreateItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateItemInput) => api.post<Item>('/items', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
    },
  });
}

// Update item
export function useUpdateItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Item> }) =>
      api.put<Item>(`/items/${id}`, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: itemKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
    },
  });
}

// Delete item
export function useDeleteItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.delete(`/items/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
    },
  });
}
```

### Optimistic Updates

```typescript
export function useToggleComplete() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, completed }: { id: string; completed: boolean }) =>
      api.put(`/items/${id}`, { completed }),

    onMutate: async ({ id, completed }) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: itemKeys.lists() });

      // Snapshot previous value
      const previous = queryClient.getQueryData<Item[]>(itemKeys.lists());

      // Optimistically update
      queryClient.setQueryData<Item[]>(itemKeys.lists(), (old) =>
        old?.map((item) =>
          item.id === id ? { ...item, completed } : item
        )
      );

      return { previous };
    },

    onError: (err, variables, context) => {
      // Rollback on error
      if (context?.previous) {
        queryClient.setQueryData(itemKeys.lists(), context.previous);
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: itemKeys.lists() });
    },
  });
}
```

---

## 8. Styling with Tailwind

### Setup

```bash
bun add -d tailwindcss postcss autoprefixer
bunx tailwindcss init -p
```

```javascript
// tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#f0f9ff',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
        },
      },
    },
  },
  plugins: [],
};
```

```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

### className Utility

```typescript
// lib/cn.ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Usage
<div className={cn(
  'p-4 rounded-lg',
  isActive && 'bg-primary-500 text-white',
  className
)} />
```

### Component Variants

```tsx
// components/ui/Button.tsx
import { cn } from '@/lib/cn';

type ButtonProps = {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  className?: string;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

const variants = {
  primary: 'bg-primary-600 text-white hover:bg-primary-700',
  secondary: 'bg-gray-200 text-gray-800 hover:bg-gray-300',
  danger: 'bg-red-600 text-white hover:bg-red-700',
  ghost: 'hover:bg-gray-100',
};

const sizes = {
  sm: 'px-3 py-1.5 text-sm',
  md: 'px-4 py-2',
  lg: 'px-6 py-3 text-lg',
};

export function Button({
  variant = 'primary',
  size = 'md',
  disabled = false,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'rounded-md font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2',
        variants[variant],
        sizes[size],
        disabled && 'opacity-50 cursor-not-allowed',
        className
      )}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
```

---

## 9. Testing

### Vitest Setup

```typescript
// vite.config.ts
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
```

```typescript
// src/test/setup.ts
import '@testing-library/jest-dom';
```

### Component Tests

```tsx
// features/items/components/__tests__/ItemCard.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ItemCard } from '../ItemCard';

describe('ItemCard', () => {
  const mockItem = {
    id: '1',
    name: 'Test Item',
    description: 'Test description',
  };

  it('renders item name', () => {
    render(<ItemCard item={mockItem} />);
    expect(screen.getByText('Test Item')).toBeInTheDocument();
  });

  it('calls onDelete when delete button clicked', async () => {
    const onDelete = vi.fn();
    render(<ItemCard item={mockItem} onDelete={onDelete} />);

    await userEvent.click(screen.getByRole('button', { name: /delete/i }));

    expect(onDelete).toHaveBeenCalledWith('1');
  });
});
```

### Testing with Providers

```tsx
// src/test/utils.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { render } from '@testing-library/react';

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(ui: React.ReactElement) {
  const queryClient = createTestQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>
  );
}
```

---

## 10. Build & Deployment

### Production Build

```bash
# Build for production
bun run build

# Preview production build
bun run preview
```

### Environment Variables

```bash
# .env.development
VITE_API_URL=/api
VITE_APP_TITLE=My App (Dev)

# .env.production
VITE_API_URL=https://api.example.com
VITE_APP_TITLE=My App
```

```typescript
// Access in code
const apiUrl = import.meta.env.VITE_API_URL;
const title = import.meta.env.VITE_APP_TITLE;
```

### Docker Build

```dockerfile
# Dockerfile
FROM oven/bun:1 AS builder

WORKDIR /app
COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .
RUN bun run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

```nginx
# nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Quick Reference

```bash
# Create project
bun create vite my-app --template react-ts
cd my-app && bun install

# Development
bun run dev

# Build
bun run build

# Test
bun test

# Lint
bun run lint

# Type check
bun run typecheck
```

---

## Resources

- [Bun Documentation](https://bun.sh/docs)
- [Vite Documentation](https://vitejs.dev/)
- [React Documentation](https://react.dev/)
- [TanStack Query](https://tanstack.com/query)
- [Tailwind CSS](https://tailwindcss.com/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
