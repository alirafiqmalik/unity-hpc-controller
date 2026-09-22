/**
 * The theme provider, and the colour-scheme choice behind it.
 *
 * The choice is `dark`, `light` or `system`. It is kept in `localStorage`,
 * which can throw in a private window, so every access is guarded and the app
 * falls back to the system setting.
 */

import { Global, ThemeProvider, css } from '@emotion/react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { THEME_DARK, THEME_LIGHT, type ColorScheme, type Theme } from './theme';

const STORAGE_KEY = 'unity-hpc.color-scheme';

const readStored = (): ColorScheme => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'dark' || raw === 'light' || raw === 'system') return raw;
  } catch {
    // No storage. The system setting decides.
  }
  return 'system';
};

const writeStored = (value: ColorScheme): void => {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // No storage. The choice holds until the page reloads.
  }
};

const prefersDark = (): boolean => {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return true;
  }
};

type ColorSchemeContextValue = {
  colorScheme: ColorScheme;
  resolved: 'dark' | 'light';
  setColorScheme: (next: ColorScheme) => void;
  toggleColorScheme: () => void;
};

const ColorSchemeContext = createContext<ColorSchemeContextValue>({
  colorScheme: 'system',
  resolved: 'dark',
  setColorScheme: () => {},
  toggleColorScheme: () => {},
});

/** Read or change the colour scheme from anywhere in the tree. */
export const useColorScheme = (): ColorSchemeContextValue =>
  useContext(ColorSchemeContext);

const globalStyles = (theme: Theme) => css`
  *,
  *::before,
  *::after {
    box-sizing: border-box;
  }

  html,
  body,
  #root {
    height: 100%;
  }

  body {
    margin: 0;
    background: ${theme.background.primary};
    color: ${theme.font.color.primary};
    font-family: ${theme.font.family};
    font-size: ${theme.font.size.md};
    font-variant-numeric: tabular-nums;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }

  h1,
  h2,
  h3,
  h4,
  p,
  figure {
    margin: 0;
  }

  button,
  input,
  select,
  textarea {
    font: inherit;
    color: inherit;
  }

  a {
    color: inherit;
    text-decoration: none;
  }

  code,
  pre {
    font-family: ${theme.font.familyMono};
  }

  /* One scrollbar style everywhere, so a panel does not jump between themes. */
  * {
    scrollbar-width: thin;
    scrollbar-color: ${theme.border.color.strong} transparent;
  }

  *::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  *::-webkit-scrollbar-thumb {
    background: ${theme.border.color.medium};
    border-radius: ${theme.border.radius.rounded};
  }

  *::-webkit-scrollbar-thumb:hover {
    background: ${theme.border.color.strong};
  }

  *::-webkit-scrollbar-track {
    background: transparent;
  }

  /* A keyboard user must always see where the focus is. */
  :focus-visible {
    outline: 2px solid ${theme.accent.primary};
    outline-offset: 1px;
  }

  @media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
      animation-duration: 0.001ms !important;
      transition-duration: 0.001ms !important;
    }
  }
`;

export const AppThemeProvider = ({ children }: { children: ReactNode }) => {
  const [colorScheme, setStored] = useState<ColorScheme>(readStored);
  const [systemDark, setSystemDark] = useState<boolean>(prefersDark);

  useEffect(() => {
    let query: MediaQueryList;
    try {
      query = window.matchMedia('(prefers-color-scheme: dark)');
    } catch {
      return;
    }
    const listen = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener('change', listen);
    return () => query.removeEventListener('change', listen);
  }, []);

  const setColorScheme = useCallback((next: ColorScheme) => {
    setStored(next);
    writeStored(next);
  }, []);

  const resolved: 'dark' | 'light' =
    colorScheme === 'system' ? (systemDark ? 'dark' : 'light') : colorScheme;

  const toggleColorScheme = useCallback(
    () => setColorScheme(resolved === 'dark' ? 'light' : 'dark'),
    [resolved, setColorScheme],
  );

  const theme = resolved === 'dark' ? THEME_DARK : THEME_LIGHT;

  const value = useMemo(
    () => ({ colorScheme, resolved, setColorScheme, toggleColorScheme }),
    [colorScheme, resolved, setColorScheme, toggleColorScheme],
  );

  useEffect(() => {
    document.documentElement.style.colorScheme = resolved;
  }, [resolved]);

  return (
    <ColorSchemeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <Global styles={globalStyles(theme)} />
        {children}
      </ThemeProvider>
    </ColorSchemeContext.Provider>
  );
};
