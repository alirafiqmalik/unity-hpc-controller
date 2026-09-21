/**
 * Late binding for refresh().
 *
 * A page module calls refresh() after it writes to the controller, and app.js
 * imports every page module to render it. Importing app.js back from a page
 * would close that loop, so app.js registers the real function here instead.
 */

let current = async () => {};

/** app.js calls this once, at start-up. */
export function setRefresh(fn) {
  current = fn;
}

/** Re-read every endpoint and re-render. */
export function refresh(opts) {
  return current(opts);
}
