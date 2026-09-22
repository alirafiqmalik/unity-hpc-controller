/**
 * The raw palette. Nothing in the app reads this file directly.
 *
 * `theme.ts` maps these values onto the semantic tokens a component uses
 * (`theme.background.secondary`, `theme.font.color.tertiary`, and so on), once
 * for the dark theme and once for the light one. The shape follows
 * `twenty-ui`: a neutral grey ramp for every surface, plus a hue ramp per
 * accent colour, where a lower number is lighter.
 */

/**
 * Surfaces, borders and text. Neutral on purpose: the data carries the hue.
 *
 * Deliberately not `as const`. A literal type here would make
 * `THEME_DARK.background.primary` the literal `'#171717'`, and `THEME_LIGHT`
 * could then never satisfy `Theme`. These are strings; the theme is the type.
 */
export const GRAY_SCALE = {
  gray0: '#ffffff',
  gray10: '#fafafa',
  gray15: '#f5f5f5',
  gray20: '#ebebeb',
  gray25: '#e3e3e3',
  gray30: '#d6d6d6',
  gray35: '#c9c9c9',
  gray40: '#b3b3b3',
  gray45: '#999999',
  gray50: '#818181',
  gray55: '#666666',
  gray60: '#4c4c4c',
  gray70: '#3b3b3b',
  gray75: '#2e2e2e',
  gray80: '#242424',
  gray85: '#1d1d1d',
  gray90: '#171717',
  gray95: '#101010',
  gray100: '#000000',
};

/**
 * One hue, five steps.
 *
 * `10` is a background tint, `40` is the readable base, `80` is the deep end.
 * A chart line takes `40`, a tag background takes `10` in the light theme and
 * `80` in the dark one, and its text takes the opposite end.
 */
type Ramp = {
  readonly 10: string;
  readonly 20: string;
  readonly 40: string;
  readonly 60: string;
  readonly 80: string;
};

export const COLOR: Record<string, Ramp> = {
  blue: { 10: '#eaf1fe', 20: '#c5d9fb', 40: '#4a8cf7', 60: '#1961ed', 80: '#16295c' },
  turquoise: { 10: '#e3f8f5', 20: '#b6ece4', 40: '#37cfb8', 60: '#00a894', 80: '#0d3f39' },
  sky: { 10: '#e5f6fb', 20: '#bce8f4', 40: '#38bdd8', 60: '#0e97b4', 80: '#123c47' },
  green: { 10: '#e6f7ee', 20: '#bfead4', 40: '#34d399', 60: '#12946a', 80: '#10382a' },
  yellow: { 10: '#fdf5e3', 20: '#fae7b6', 40: '#fbbf24', 60: '#c58900', 80: '#3f3213' },
  orange: { 10: '#fdeee4', 20: '#fad4ba', 40: '#f98c3f', 60: '#d1620f', 80: '#412616' },
  red: { 10: '#fdecec', 20: '#f9cfcf', 40: '#f87171', 60: '#d92d2d', 80: '#451c1c' },
  pink: { 10: '#fdebf4', 20: '#f9c9e1', 40: '#ec5aa5', 60: '#c81e72', 80: '#42162f' },
  purple: { 10: '#f1edfd', 20: '#d9cdfa', 40: '#a78bfa', 60: '#7546e0', 80: '#2c1f52' },
  gray: {
    10: GRAY_SCALE.gray20,
    20: GRAY_SCALE.gray30,
    40: GRAY_SCALE.gray50,
    60: GRAY_SCALE.gray60,
    80: GRAY_SCALE.gray80,
  },
};

/** The colour names a `Tag` or a `Chip` accepts. */
export type ThemeColor = keyof typeof COLOR;

export const THEME_COLORS = Object.keys(COLOR) as ThemeColor[];

/**
 * The series order a chart assigns from.
 *
 * Five hues that stay apart at a one-pixel stroke and keep their order across
 * both themes, so a series does not change colour when a sibling is hidden.
 */
export const CHART_SERIES_COLORS = [
  COLOR.green[40],
  COLOR.blue[40],
  COLOR.purple[40],
  COLOR.yellow[40],
  COLOR.red[40],
] as const;
