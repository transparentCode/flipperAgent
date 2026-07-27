export const DEFAULT_FOCUS_SETTINGS = Object.freeze({
    recentBars: 100,
    minAnchorSpan: 25,
    onePerSecondAnchor: true,
    maxPerRole: 12,
});
export const DEFAULT_NEAREST_SETTINGS = Object.freeze({
    maxPerRole: 5,
});
function anchorSpan(candidate) {
    const [first, second] = candidate.evidence.anchor_source_positions;
    return second - first;
}
function availabilityAge(candidate, lastCandlePosition) {
    return lastCandlePosition - candidate.evidence.confirmation_positions[1];
}
function compareNumbers(left, right) {
    if (left < right)
        return -1;
    if (left > right)
        return 1;
    return 0;
}
function compareStrings(left, right) {
    if (left < right)
        return -1;
    if (left > right)
        return 1;
    return 0;
}
function requireFinite(value, field) {
    if (!Number.isFinite(value))
        throw new Error(`${field} must be finite`);
    return value;
}
export function projectedLinePriceAt(candidate, timestamp) {
    requireFinite(timestamp, 'projection timestamp');
    const startTime = requireFinite(candidate.start_time, 'candidate start time');
    const endTime = requireFinite(candidate.end_time, 'candidate end time');
    const startPrice = requireFinite(candidate.start_price, 'candidate start price');
    const endPrice = requireFinite(candidate.end_price, 'candidate end price');
    if (endTime <= startTime)
        throw new Error('candidate geometry has non-positive duration');
    const fraction = (timestamp - startTime) / (endTime - startTime);
    const projectedPrice = startPrice + fraction * (endPrice - startPrice);
    return requireFinite(projectedPrice, 'projected line price');
}
export function currentRoleAwareDistance(candidate, candle) {
    const projectedLinePrice = projectedLinePriceAt(candidate, candle.time);
    const low = requireFinite(candle.low, 'candle low');
    const high = requireFinite(candle.high, 'candle high');
    const close = requireFinite(candle.close, 'candle close');
    const rangeDistance = candidate.role === 'support'
        ? Math.max(0, low - projectedLinePrice)
        : Math.max(0, projectedLinePrice - high);
    const closeDistance = Math.abs(close - projectedLinePrice);
    requireFinite(rangeDistance, 'range distance');
    requireFinite(closeDistance, 'close distance');
    return { projectedLinePrice, rangeDistance, closeDistance };
}
function representativeOrder(left, right) {
    const intermediateDelta = right.evidence.validated_intermediate_count
        - left.evidence.validated_intermediate_count;
    if (intermediateDelta !== 0)
        return intermediateDelta;
    const spanDelta = anchorSpan(right) - anchorSpan(left);
    if (spanDelta !== 0)
        return spanDelta;
    return left.candidate_id.localeCompare(right.candidate_id);
}
function displayOrder(left, right) {
    const confirmationDelta = right.evidence.confirmation_positions[1]
        - left.evidence.confirmation_positions[1];
    if (confirmationDelta !== 0)
        return confirmationDelta;
    return representativeOrder(left, right);
}
function nearestOrder(left, right, candle) {
    const leftDistance = currentRoleAwareDistance(left, candle);
    const rightDistance = currentRoleAwareDistance(right, candle);
    let comparison = compareNumbers(leftDistance.rangeDistance, rightDistance.rangeDistance);
    if (comparison !== 0)
        return comparison;
    comparison = compareNumbers(leftDistance.closeDistance, rightDistance.closeDistance);
    if (comparison !== 0)
        return comparison;
    comparison = compareNumbers(right.evidence.confirmation_positions[1], left.evidence.confirmation_positions[1]);
    if (comparison !== 0)
        return comparison;
    comparison = compareNumbers(right.evidence.validated_intermediate_count, left.evidence.validated_intermediate_count);
    if (comparison !== 0)
        return comparison;
    comparison = compareNumbers(anchorSpan(right), anchorSpan(left));
    if (comparison !== 0)
        return comparison;
    return compareStrings(left.candidate_id, right.candidate_id);
}
function roleFocusCandidates(candidates, role, lastCandlePosition, settings) {
    const eligible = candidates.filter((candidate) => {
        if (candidate.role !== role)
            return false;
        if (settings.recentBars !== null
            && availabilityAge(candidate, lastCandlePosition) > settings.recentBars)
            return false;
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
            }, new Map()).values()]
        : [...eligible];
    representatives.sort(displayOrder);
    return settings.maxPerRole === null
        ? representatives
        : representatives.slice(0, settings.maxPerRole);
}
export function selectFocusCandidates(candidates, lastCandlePosition, settings = DEFAULT_FOCUS_SETTINGS) {
    const support = roleFocusCandidates(candidates, 'support', lastCandlePosition, settings);
    const resistance = roleFocusCandidates(candidates, 'resistance', lastCandlePosition, settings);
    return [...support, ...resistance];
}
function roleNearestCandidates(candidates, role, lastCandle, maxPerRole) {
    const representatives = new Map();
    for (const candidate of candidates) {
        if (candidate.role !== role)
            continue;
        const key = candidate.anchors[1].anchor_id;
        const current = representatives.get(key);
        if (current === undefined || nearestOrder(candidate, current, lastCandle) < 0) {
            representatives.set(key, candidate);
        }
    }
    return [...representatives.values()]
        .sort((left, right) => nearestOrder(left, right, lastCandle))
        .slice(0, maxPerRole);
}
export function selectNearestCandidates(candidates, lastCandle, settings = DEFAULT_NEAREST_SETTINGS) {
    if (settings.maxPerRole !== 5 && settings.maxPerRole !== 10) {
        throw new Error('nearest maxPerRole must be 5 or 10');
    }
    const support = roleNearestCandidates(candidates, 'support', lastCandle, settings.maxPerRole);
    const resistance = roleNearestCandidates(candidates, 'resistance', lastCandle, settings.maxPerRole);
    return [...support, ...resistance];
}
export function selectDisplayCandidates(input) {
    if (input.mode === 'all')
        return input.candidates;
    if (input.mode === 'nearest') {
        return selectNearestCandidates(input.candidates, input.lastCandle, input.nearestSettings);
    }
    return selectFocusCandidates(input.candidates, input.lastCandlePosition, input.focusSettings ?? DEFAULT_FOCUS_SETTINGS);
}
export function displayCounts(candidates) {
    return {
        total: candidates.length,
        support: candidates.filter((candidate) => candidate.role === 'support').length,
        resistance: candidates.filter((candidate) => candidate.role === 'resistance').length,
    };
}
