/**
 * The cluster time window.
 *
 * One control, one atom. Overview, Queue, Users and Analytics all render it,
 * and the sync cycle sends the same `hours` to every cluster endpoint, so
 * the four pages describe one span.
 */

import styled from '@emotion/styled';
import { useRecoilState } from 'recoil';

import { Chip, ChipRow } from '../../ui/components/Tag';
import { usageHoursState, type ClusterWindow } from './state';

export const WINDOWS: { hours: ClusterWindow; label: string }[] = [
  { hours: 24, label: '24h' },
  { hours: 168, label: '7d' },
  { hours: 720, label: '30d' },
  { hours: 1440, label: '60d' },
  { hours: 2160, label: '90d' },
];

/** The chip label for a stored window. */
export const windowLabel = (hours: ClusterWindow): string =>
  WINDOWS.find((option) => option.hours === hours)?.label ??
  `${hours}h`;

/** A short note: `last 7d`. */
export const windowPhrase = (hours: ClusterWindow): string =>
  `last ${windowLabel(hours)}`;

/** Reads naturally after a noun: "people in the last 7d". */
export const inWindow = (hours: ClusterWindow): string =>
  `in the last ${windowLabel(hours)}`;

/** Header row when a page has the window chips and other actions. */
export const PageActions = styled.div`
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: ${({ theme }) => theme.spacing(2)};
`;

export const TimeWindowPicker = () => {
  const [hours, setHours] = useRecoilState(usageHoursState);

  return (
    <ChipRow role="radiogroup" aria-label="Time window">
      {WINDOWS.map((option) => (
        <Chip
          key={option.label}
          type="button"
          role="radio"
          aria-checked={hours === option.hours}
          $active={hours === option.hours}
          onClick={() => setHours(option.hours)}
        >
          {option.label}
        </Chip>
      ))}
    </ChipRow>
  );
};
