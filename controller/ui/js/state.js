/** The one mutable store, plus the selectors that read it. */

export const state = {
  page: 'overview', hours: 24, jfilter: 'all',
  health: null, cluster: null, queue: null, usage: null,
  jobs: [], events: [], projects: [], error: null, drawerSlug: null,
};

/** The live cluster block, or an empty stand-in when no snapshot arrived. */
export function live() {
  return (state.cluster && state.cluster.live) || { available: false, latest: {}, trend: [] };
}

/** The newest sample in the live block. */
export function latest() {
  return live().latest || {};
}
