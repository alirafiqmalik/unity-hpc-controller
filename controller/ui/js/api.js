/** The one JSON client for the controller API. */

/**
 * Call the controller. Throws on a non-2xx answer, with the API message.
 * @param {string} path
 * @param {RequestInit} [opts]
 */
export async function api(path, opts) {
  const r = await fetch(path, { headers: { 'content-type': 'application/json' }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
