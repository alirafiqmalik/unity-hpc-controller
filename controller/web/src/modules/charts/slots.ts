/**
 * Axis labels for the time slots the usage API returns.
 *
 * A slot is a full UTC stamp such as `2026-09-22T01:00:00Z`. Printed whole it
 * is wider than the space between two ticks, so Recharts drops all but two of
 * them and the axis stops describing the window. Within one day the date is
 * the same on every tick and carries no information, so it goes; across days
 * the day is what tells them apart, so it stays.
 */

const parse = (slot: string): Date | null => {
  const at = Date.parse(slot);
  return Number.isNaN(at) ? null : new Date(at);
};

const pad = (value: number): string => String(value).padStart(2, '0');

/**
 * A tick formatter for one set of slots.
 *
 * It is built once per slot list rather than per tick, because whether the
 * date is needed is a property of the whole window, not of one label.
 */
export const slotTicks = (slots: string[]): ((slot: string) => string) => {
  const days = new Set<string>();
  for (const slot of slots) {
    const at = parse(slot);
    if (at) days.add(at.toISOString().slice(0, 10));
  }
  const oneDay = days.size <= 1;

  return (slot: string): string => {
    const at = parse(slot);
    // Not a stamp the API produced — a plain label. Show it as it is.
    if (!at) return slot;
    const time = `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}`;
    if (oneDay) return time;
    return `${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())} ${time}`;
  };
};

/** The full stamp, for the tooltip, where there is room for it. */
export const slotTitle = (slot: string): string => {
  const at = parse(slot);
  if (!at) return slot;
  return `${at.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
};
