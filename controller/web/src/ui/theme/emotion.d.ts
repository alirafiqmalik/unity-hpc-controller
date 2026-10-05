/** Give `styled` and the `css` prop the real theme type, not `{}`. */
import '@emotion/react';
import type { Theme as UnityTheme } from './theme';

declare module '@emotion/react' {
  export interface Theme extends UnityTheme {}
}
