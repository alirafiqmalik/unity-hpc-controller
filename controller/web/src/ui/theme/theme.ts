/**
 * The two themes, in the `twenty-ui` shape.
 *
 * A component never names a hex value. It reads a semantic token off the
 * Emotion theme — `theme.background.secondary`, `theme.font.color.tertiary`,
 * `theme.border.color.medium` — and the same component is then correct in both
 * themes. `theme.spacing(n)` is `n × 4px`, which is the only spacing unit.
 */

import { COLOR, GRAY_SCALE, type ThemeColor } from './colors';

const SPACING_MULTIPLICATOR = 4;

/** `spacing(2)` is `8px`; `spacing(2, 3)` is `8px 12px`. */
const spacing = (...args: number[]): string =>
  args.map((n) => `${n * SPACING_MULTIPLICATOR}px`).join(' ');

const FONT = {
  family: "'Inter', -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
  familyMono: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  size: {
    xxs: '10px',
    xs: '11px',
    sm: '12px',
    md: '13px',
    lg: '16px',
    xl: '20px',
    xxl: '28px',
  },
  weight: {
    regular: 400,
    medium: 500,
    semiBold: 600,
    bold: 700,
  },
} as const;

const BORDER_RADIUS = {
  xs: '2px',
  sm: '4px',
  md: '8px',
  lg: '12px',
  xl: '16px',
  rounded: '999px',
} as const;

const ICON = {
  size: { sm: 14, md: 16, lg: 20, xl: 24 },
  stroke: { sm: 1.5, md: 1.8, lg: 2 },
} as const;

const ANIMATION = {
  duration: { instant: '0.06s', fast: '0.12s', normal: '0.2s' },
  clickable: 'background 0.12s ease, border-color 0.12s ease, color 0.12s ease',
} as const;

/** A tag's pair: the tint it sits on, and the text that stays readable on it. */
type TagPalette = Record<ThemeColor, string>;

const tagPalette = (step: 10 | 80): TagPalette =>
  Object.fromEntries(
    Object.entries(COLOR).map(([name, ramp]) => [name, ramp[step]]),
  ) as TagPalette;

const tagText = (step: 40 | 60): TagPalette =>
  Object.fromEntries(
    Object.entries(COLOR).map(([name, ramp]) => [name, ramp[step]]),
  ) as TagPalette;

/** Everything both themes share. */
const COMMON = {
  font: FONT,
  icon: ICON,
  animation: ANIMATION,
  color: COLOR,
  grayScale: GRAY_SCALE,
  spacing,
  spacingMultiplicator: SPACING_MULTIPLICATOR,
  /** The left navigation drawer, open and collapsed. */
  navigationDrawer: { width: '232px', collapsedWidth: '60px' },
  /** The right side panel that shows one job or one project. */
  sidePanel: { width: '460px' },
  pageHeader: { height: '52px' },
  table: { rowHeight: '34px', headerHeight: '32px' },
  zIndex: { drawer: 40, header: 30, sidePanel: 60, overlay: 55, modal: 80, toast: 90 },
} as const;

export const THEME_DARK = {
  ...COMMON,
  name: 'dark' as 'dark' | 'light',
  background: {
    primary: GRAY_SCALE.gray90,
    secondary: GRAY_SCALE.gray85,
    tertiary: GRAY_SCALE.gray80,
    quaternary: GRAY_SCALE.gray75,
    inverted: GRAY_SCALE.gray20,
    danger: COLOR.red[80],
    overlay: 'rgba(0, 0, 0, 0.6)',
    transparent: {
      primary: 'rgba(255, 255, 255, 0.04)',
      secondary: 'rgba(255, 255, 255, 0.07)',
      strong: 'rgba(255, 255, 255, 0.12)',
      danger: 'rgba(248, 113, 113, 0.14)',
    },
  },
  border: {
    color: {
      strong: GRAY_SCALE.gray60,
      medium: GRAY_SCALE.gray70,
      light: GRAY_SCALE.gray75,
      inverted: GRAY_SCALE.gray40,
      danger: COLOR.red[60],
      accent: COLOR.blue[60],
    },
    radius: BORDER_RADIUS,
  },
  font: {
    ...FONT,
    color: {
      primary: GRAY_SCALE.gray15,
      secondary: GRAY_SCALE.gray40,
      tertiary: GRAY_SCALE.gray50,
      light: GRAY_SCALE.gray55,
      inverted: GRAY_SCALE.gray95,
      danger: COLOR.red[40],
    },
  },
  accent: {
    primary: COLOR.blue[40],
    secondary: 'rgba(74, 140, 247, 0.28)',
    tertiary: 'rgba(74, 140, 247, 0.16)',
    quaternary: 'rgba(74, 140, 247, 0.08)',
  },
  tag: { background: tagPalette(80), text: tagText(40) },
  boxShadow: {
    light: '0 1px 2px rgba(0, 0, 0, 0.4)',
    medium: '0 4px 12px rgba(0, 0, 0, 0.45)',
    strong: '0 12px 32px rgba(0, 0, 0, 0.55)',
  },
  chart: {
    grid: GRAY_SCALE.gray75,
    axis: GRAY_SCALE.gray50,
    /** Low to high, for the hour-by-weekday map. */
    sequential: ['#16295c', '#1e3d82', '#2a57ad', '#3a72d4', '#5a92ea', '#86b4f4', '#bcd6fb'],
  },
};

export const THEME_LIGHT: Theme = {
  ...COMMON,
  name: 'light',
  background: {
    primary: GRAY_SCALE.gray0,
    secondary: GRAY_SCALE.gray10,
    tertiary: GRAY_SCALE.gray15,
    quaternary: GRAY_SCALE.gray20,
    inverted: GRAY_SCALE.gray80,
    danger: COLOR.red[10],
    overlay: 'rgba(23, 23, 23, 0.32)',
    transparent: {
      primary: 'rgba(0, 0, 0, 0.03)',
      secondary: 'rgba(0, 0, 0, 0.05)',
      strong: 'rgba(0, 0, 0, 0.09)',
      danger: 'rgba(217, 45, 45, 0.10)',
    },
  },
  border: {
    color: {
      strong: GRAY_SCALE.gray35,
      medium: GRAY_SCALE.gray25,
      light: GRAY_SCALE.gray20,
      inverted: GRAY_SCALE.gray60,
      danger: COLOR.red[40],
      accent: COLOR.blue[60],
    },
    radius: BORDER_RADIUS,
  },
  font: {
    ...FONT,
    color: {
      primary: GRAY_SCALE.gray85,
      secondary: GRAY_SCALE.gray55,
      tertiary: GRAY_SCALE.gray45,
      light: GRAY_SCALE.gray40,
      inverted: GRAY_SCALE.gray10,
      danger: COLOR.red[60],
    },
  },
  accent: {
    primary: COLOR.blue[60],
    secondary: 'rgba(25, 97, 237, 0.20)',
    tertiary: 'rgba(25, 97, 237, 0.10)',
    quaternary: 'rgba(25, 97, 237, 0.05)',
  },
  tag: { background: tagPalette(10), text: tagText(60) },
  boxShadow: {
    light: '0 1px 2px rgba(23, 23, 23, 0.08)',
    medium: '0 4px 12px rgba(23, 23, 23, 0.10)',
    strong: '0 12px 32px rgba(23, 23, 23, 0.16)',
  },
  chart: {
    grid: GRAY_SCALE.gray20,
    axis: GRAY_SCALE.gray45,
    sequential: ['#eaf1fe', '#cfe0fd', '#a9c8fa', '#7aa8f5', '#4a8cf7', '#2b6fe4', '#1961ed'],
  },
};

export type Theme = typeof THEME_DARK;
export type ColorScheme = 'dark' | 'light' | 'system';
