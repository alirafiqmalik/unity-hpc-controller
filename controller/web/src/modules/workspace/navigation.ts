/** Stable workspace identities in URLs. Only meaningful target filters survive. */
export const sharedKeys = ['experiment', 'execution', 'variant', 'stage', 'attempt', 'purpose', 'campaign', 'collection', 'artifact'] as const;
export const sectionKeys: Record<string, readonly string[]> = {
  overview: ['collection', 'campaign'],
  experiments: ['workflow', 'readiness', 'archived', 'search', 'new', 'repeat', 'adopt'],
  runs: [...sharedKeys, 'view', 'state', 'attention', 'date', 'schedule', 'operation', 'stream', 'search', 'offset'],
  results: [...sharedKeys, 'view', 'analysis', 'comparison', 'sample', 'metric', 'offset', 'superseded', 'selection_fingerprint', 'completeness', 'currency', 'outcome', 'harness', 'limitation', 'capped', 'recovered', 'missing'],
  files: [...sharedKeys, 'root', 'path', 'preview', 'name', 'kind', 'location', 'changed', 'offset', 'transfer', 'integrity', 'preview_offset', 'version', 'listing_version', 'preview_version'],
  settings: ['section', 'maintenance'],
  review: [],
};
export const workspaceLink = (slug: string, section: string, scope: Record<string, unknown> = {}) => {
  const query = new URLSearchParams();
  const allowed = sectionKeys[section] ?? sharedKeys;
  for (const [key, value] of Object.entries(scope)) {
    if (allowed.includes(key) && value !== undefined && value !== null && value !== '') query.set(key, String(value));
  }
  return `/projects/${encodeURIComponent(slug)}/${section}${query.size ? `?${query}` : ''}`;
};
