/** Shared component types. */

import type { TablerIcon } from '@tabler/icons-react';

/**
 * An icon component from `@tabler/icons-react`.
 *
 * The package's own exported type is used rather than a hand-written call
 * signature: a forward-ref component does not match a plain function type, and
 * every icon in the package is a forward-ref component.
 */
export type IconComponent = TablerIcon;
