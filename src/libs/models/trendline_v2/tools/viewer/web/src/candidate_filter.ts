import type { ViewerCandidate } from './contracts.js';

export type FocusSettings = {
  recentBars: number | null;
  minAnchorSpan: number;
  onePerSecondAnchor: boolean;
  maxPerRole: number | null;
};

export type DisplayMode = 'focus' | 'all';

export const DEFAULT_FOCUS_SETTINGS: Readonly<FocusSettings> = Object.freeze({
  recentBars: 100,
  minAnchorSpan: 25,
  onePerSecondAnchor: true,
  maxPerRole: 12,
});

function anchorSpan(candidate: ViewerCandidate): number {
  const [first, second] = candidate.evidence.anchor_source_positions;
  return second - first;
}

function availabilityAge(candidate: ViewerCandidate, lastCandlePosition: number): number {
  return lastCandlePosition - candidate.evidence.confirmation_positions[1];
}

function representativeOrder(left: ViewerCandidate, right: ViewerCandidate): number {
  const intermediateDelta = right.evidence.validated_intermediate_count
    - left.evidence.validated_intermediate_count;
  if (intermediateDelta !== 0) return intermediateDelta;
  const spanDelta = anchorSpan(right) - anchorSpan(left);
  if (spanDelta !== 0) return spanDelta;
  return left.candidate_id.localeCompare(right.candidate_id);
}

function displayOrder(left: ViewerCandidate, right: ViewerCandidate): number {
  const confirmationDelta = right.evidence.confirmation_positions[1]
    - left.evidence.confirmation_positions[1];
  if (confirmationDelta !== 0) return confirmationDelta;
  return representativeOrder(left, right);
}

function roleFocusCandidates(
  candidates: readonly ViewerCandidate[],
  role: ViewerCandidate['role'],
  lastCandlePosition: number,
  settings: FocusSettings,
): ViewerCandidate[] {
  const eligible = candidates.filter((candidate) => {
    if (candidate.role !== role) return false;
    if (
      settings.recentBars !== null
      && availabilityAge(candidate, lastCandlePosition) > settings.recentBars
    ) return false;
    return anchorSpan(candidate) >= settings.minAnchorSpan;
  });

  const representatives = settings.onePerSecondAnchor
    ? [...eligible.reduce((groups, candidate) => {
      const key = candidate.anchors[1].anchor_id;
      const current = groups.get(key);
      if (current === undefined || representativeOrder(candidate, current) < 0) {
        groups.set(key, candidate);
      }
      return groups;
    }, new Map<string, ViewerCandidate>()).values()]
    : [...eligible];

  representatives.sort(displayOrder);
  return settings.maxPerRole === null
    ? representatives
    : representatives.slice(0, settings.maxPerRole);
}

export function selectFocusCandidates<T extends ViewerCandidate>(
  candidates: readonly T[],
  lastCandlePosition: number,
  settings: FocusSettings = DEFAULT_FOCUS_SETTINGS,
): T[] {
  const support = roleFocusCandidates(candidates, 'support', lastCandlePosition, settings);
  const resistance = roleFocusCandidates(candidates, 'resistance', lastCandlePosition, settings);
  return [...support, ...resistance] as T[];
}

export function selectDisplayCandidates<T extends ViewerCandidate>(
  mode: DisplayMode,
  candidates: readonly T[],
  lastCandlePosition: number,
  settings: FocusSettings = DEFAULT_FOCUS_SETTINGS,
): readonly T[] {
  return mode === 'all' ? candidates : selectFocusCandidates(candidates, lastCandlePosition, settings);
}

export function displayCounts(
  candidates: readonly ViewerCandidate[],
): { total: number; support: number; resistance: number } {
  return {
    total: candidates.length,
    support: candidates.filter((candidate) => candidate.role === 'support').length,
    resistance: candidates.filter((candidate) => candidate.role === 'resistance').length,
  };
}
