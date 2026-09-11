const EVENT_COLORS = {
  CREATED: '#64d5a2',
  TOUCH_STARTED: '#f5c56b',
  TOUCH_ENDED: '#a8b5c9',
  BREAK_PENDING: '#f4a261',
  BREAK_CLEARED: '#7eb7ff',
  BROKEN: '#f07178',
  EXPIRED: '#9aa6bb',
  SUPERSEDED: '#c78cff',
  TOMBSTONE_PRUNED: '#68758a',
};

export function finiteNumber(value, field) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
    throw new Error(`${field} is not finite`);
  }
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${field} is not finite`);
  return number;
}

export function chartTime(value, field) {
  if (typeof value !== 'string' || !/(?:Z|[+]00:00)$/.test(value)) {
    throw new Error(`${field} is not a valid UTC time`);
  }
  const date = new Date(value);
  const seconds = Math.floor(date.getTime() / 1000);
  if (!Number.isFinite(seconds)) throw new Error(`${field} is not a valid UTC time`);
  return seconds;
}

export function candleRows(rows, field) {
  if (!Array.isArray(rows)) throw new Error(`${field} must be an array`);
  return rows.map((row, index) => {
    const result = {
      time: chartTime(row.bar_close_at, `${field}[${index}].bar_close_at`),
      open: finiteNumber(row.open, `${field}[${index}].open`),
      high: finiteNumber(row.high, `${field}[${index}].high`),
      low: finiteNumber(row.low, `${field}[${index}].low`),
      close: finiteNumber(row.close, `${field}[${index}].close`),
    };
    if (row.volume !== undefined && row.volume !== null) {
      result.volume = finiteNumber(row.volume, `${field}[${index}].volume`);
    }
    return result;
  });
}

export function volumeRows(candles) {
  return candles.map((candle) => ({
    time: candle.time,
    value: Math.max(0, finiteNumber(candle.volume ?? 0, 'candle.volume')),
    color: candle.close >= candle.open ? 'rgba(73, 176, 150, .42)' : 'rgba(239, 103, 112, .42)',
  }));
}

export function latestDisplayedCutoff(rows, fallback = null) {
  if (!Array.isArray(rows) || rows.length === 0) return fallback;
  const cutoff = rows.at(-1)?.bar_close_at;
  return typeof cutoff === 'string' && cutoff ? cutoff : fallback;
}

export function applyInspectionResult(
  overlayInspection,
  nextInspection,
  { passive = false, inspectorOpen = true } = {},
) {
  if (passive) {
    return {
      overlayInspection,
      currentInspection: inspectorOpen ? nextInspection : overlayInspection,
    };
  }
  return {
    overlayInspection: nextInspection,
    currentInspection: nextInspection,
  };
}

function kernelReference(value, version = undefined) {
  if (typeof value !== 'string' || !value) return null;
  const raw = version !== undefined && version !== null && version !== '' && !value.includes('@')
    ? `${value}@${version}`
    : value;
  const separator = raw.lastIndexOf('@');
  if (separator <= 0 || separator === raw.length - 1) {
    return { exact: raw, base: raw, versioned: false };
  }
  return {
    exact: raw,
    base: raw.slice(0, separator),
    versioned: true,
  };
}

function kernelRowReference(row) {
  if (typeof row === 'string') return kernelReference(row);
  return kernelReference(row?.kernel_id, row?.kernel_version);
}

export function kernelMatchesConfiguration(row, enabledKernelIds, configuredKernelIds = undefined) {
  const enabled = enabledKernelIds instanceof Set ? enabledKernelIds : new Set(enabledKernelIds || []);
  if (configuredKernelIds === undefined) {
    return enabled.has(typeof row === 'string' ? row : row?.kernel_id);
  }
  const configured = configuredKernelIds instanceof Set
    ? configuredKernelIds
    : new Set(configuredKernelIds || []);
  if (!configured.size) return true;
  const rowReference = kernelRowReference(row);
  if (!rowReference) return true;
  const matchingConfigured = [...configured]
    .map((reference) => kernelReference(reference))
    .filter((reference) => reference && (
      rowReference.versioned
        ? reference.exact === rowReference.exact
        : reference.base === rowReference.base
    ));
  if (!matchingConfigured.length) return true;
  return matchingConfigured.some((reference) => enabled.has(reference.exact));
}

export function filterKernelRows(rows, enabledKernelIds, configuredKernelIds = undefined) {
  return (Array.isArray(rows) ? rows : []).filter((row) => (
    kernelMatchesConfiguration(row, enabledKernelIds, configuredKernelIds)
  ));
}

export function historyLineageCounts(
  zones,
  renderedRectangles,
  {
    enabledKernelIds = null,
    configuredKernelIds = null,
    visible = true,
    visibleWindow = {},
  } = {},
) {
  const historicalZones = Array.isArray(zones) ? zones : [];
  const enabledZones = filterKernelRows(historicalZones, enabledKernelIds, configuredKernelIds);
  const counts = {
    total: historicalZones.length,
    enabled: enabledZones.length,
    inWindow: 0,
  };
  if (!visible || !Array.isArray(renderedRectangles)) return counts;
  const left = Number.isFinite(visibleWindow?.left) ? visibleWindow.left : 0;
  const right = Number.isFinite(visibleWindow?.right) ? visibleWindow.right : Number.POSITIVE_INFINITY;
  if (!(right > left)) return counts;
  const enabledZoneIds = new Set(enabledZones
    .map((zone) => zone?.zone_id)
    .filter((zoneId) => typeof zoneId === 'string' && zoneId));
  const historyZoneIds = new Set(historicalZones
    .map((zone) => zone?.zone_id)
    .filter((zoneId) => typeof zoneId === 'string' && zoneId));
  const inWindow = new Set();
  for (const rectangle of renderedRectangles) {
    if (!rectangle || !historyZoneIds.has(rectangle.zone_id) || !enabledZoneIds.has(rectangle.zone_id)) continue;
    if (![rectangle.x1, rectangle.x2].every(Number.isFinite)) continue;
    if (rectangle.x2 < left || rectangle.x1 > right) continue;
    inWindow.add(rectangle.zone_id);
  }
  counts.inWindow = inWindow.size;
  return counts;
}

const BAND_HIT_PREFIX = 'sr-band:';

export function bandHitExternalId(memberIds) {
  const ids = Array.isArray(memberIds) ? [...memberIds] : [];
  if (ids.length <= 1) return ids[0] || '';
  return `${BAND_HIT_PREFIX}${encodeURIComponent(JSON.stringify(ids))}`;
}

export function bandHitMemberIds(externalId) {
  if (typeof externalId !== 'string' || !externalId) return [];
  if (!externalId.startsWith(BAND_HIT_PREFIX)) return [externalId];
  try {
    const memberIds = JSON.parse(decodeURIComponent(externalId.slice(BAND_HIT_PREFIX.length)));
    return Array.isArray(memberIds) && memberIds.every((memberId) => typeof memberId === 'string')
      ? memberIds
      : [externalId];
  } catch {
    return [externalId];
  }
}

export function overlappingBandMemberIds(rectangles, x, y) {
  if (!Array.isArray(rectangles) || !Number.isFinite(x) || !Number.isFinite(y)) return [];
  return [...new Set(rectangles
    .filter((rectangle) => rectangle && x >= rectangle.x1 && x <= rectangle.x2 && y >= rectangle.top && y <= rectangle.bottom)
    .flatMap((rectangle) => Array.isArray(rectangle.member_ids) ? rectangle.member_ids : [rectangle.zone_id])
    .filter((zoneId) => typeof zoneId === 'string' && zoneId))].sort();
}

export function intervalData(candles, interval, field) {
  const start = chartTime(interval.entered_at, `${field}.entered_at`);
  const end = interval.exited_at ? chartTime(interval.exited_at, `${field}.exited_at`) : Number.POSITIVE_INFINITY;
  return candles
    .filter((candle) => candle.time >= start && candle.time < end)
    .map((candle) => ({ time: candle.time, value: finiteNumber(interval[field], `${field}.value`) }));
}

export function touchHighlight(candles, episode, zone) {
  return intervalData(
    candles,
    { entered_at: episode.started_at, exited_at: episode.ended_at, center: zone.center },
    'center',
  );
}

function lifecycleEventShape(event) {
  if (event === 'CREATED') return 'arrowUp';
  if (event === 'BROKEN' || event === 'EXPIRED' || event === 'SUPERSEDED') return 'arrowDown';
  return 'circle';
}

export function transitionMarkers(transitions, zonesById = new Map()) {
  return transitions
    .map((transition) => ({
      time: chartTime(transition.event_at, 'transition.event_at'),
      position: zonesById.get(transition.zone_id)?.side === 'SUPPORT' ? 'belowBar' : 'aboveBar',
      color: EVENT_COLORS[transition.event] || '#b8c3d6',
      shape: lifecycleEventShape(transition.event),
      text: '',
      event: transition.event,
      zone_id: transition.zone_id,
    }))
    .sort((left, right) => left.time - right.time);
}

export function aggregateCandidateMarkers(aggregates) {
  return aggregates.map((aggregate) => ({
    time: chartTime(aggregate.available_at, 'candidate.available_at'),
    position: aggregate.side === 'SUPPORT' ? 'belowBar' : 'aboveBar',
    color: aggregate.side === 'SUPPORT' ? '#59c9a5' : '#ed8790',
    shape: 'circle',
    size: .6,
    text: '',
    candidate_count: aggregate.count,
    kernel_id: aggregate.kernel_id,
    side: aggregate.side,
    // A stable key lets the inspector resolve grouped markers without adding
    // member IDs to the chart surface.
    aggregate_key: `${aggregate.available_at}|${aggregate.side}|${aggregate.kernel_id}`,
  }));
}

function numericGeometry(zone) {
  return {
    lower: finiteNumber(zone.lower ?? zone.geometry?.lower, 'zone.lower'),
    upper: finiteNumber(zone.upper ?? zone.geometry?.upper, 'zone.upper'),
  };
}

function toPixelBand(
  zone,
  timeScale,
  series,
  visibleFrom,
  visibleTo,
  coordinateForTime = (time) => timeScale.timeToCoordinate(time),
) {
  try {
    const geometry = numericGeometry(zone);
    if (geometry.lower > geometry.upper) return null;
    let start;
    let end;
    start = finiteNumber(zone.start_time ?? visibleFrom, 'zone.start_time');
    end = finiteNumber(zone.end_time ?? visibleTo, 'zone.end_time');
    if (start > visibleTo || end < start) return null;
    const from = Math.max(start, visibleFrom);
    const displayOpen = zone.display_open === true;
    const rightEdge = displayOpen && typeof timeScale.width === 'function'
      ? timeScale.width()
      : null;
    let to;
    if (displayOpen) {
      to = finiteNumber(rightEdge, 'timeScale.width');
      if (!(to > 0)) return null;
    } else {
      to = Math.min(end, visibleTo);
      if (!(from < to)) return null;
    }
    const x1 = coordinateForTime(from);
    const x2 = displayOpen ? to : coordinateForTime(to);
    const y1 = series.priceToCoordinate(geometry.upper);
    const y2 = series.priceToCoordinate(geometry.lower);
    if ([x1, x2, y1, y2].some((value) => value === null || !Number.isFinite(value))) return null;
    if (displayOpen && !(x2 > x1)) return null;
    return {
      zone_id: zone.zone_id,
      member_ids: [zone.zone_id],
      source_timeframe: zone.source_timeframe,
      kernel_id: zone.kernel_id,
      center: zone.center,
      side: zone.side,
      lifecycle: zone.lifecycle,
      start_time: start,
      end_time: end,
      display_open: displayOpen,
      x1: Math.min(x1, x2),
      x2: Math.max(x1, x2),
      top: Math.min(y1, y2),
      bottom: Math.max(y1, y2),
      lower: geometry.lower,
      upper: geometry.upper,
      historical: zone.historical === true,
    };
  } catch {
    return null;
  }
}

export function projectBands(zones, intervals, candles, cutoff) {
  const times = candles.map((candle) => candle.time).filter(Number.isFinite).sort((a, b) => a - b);
  if (!times.length) return [];
  const cutoffSeconds = typeof cutoff === 'number' ? cutoff : chartTime(cutoff, 'cutoff');
  const visibleFrom = times[0];
  const visibleTo = times.at(-1);
  const zonesById = new Map(zones.map((zone) => [zone.zone_id, zone]));
  const active = intervals.filter((interval) => {
    const start = chartTime(interval.entered_at, 'interval.entered_at');
    const end = interval.exited_at ? chartTime(interval.exited_at, 'interval.exited_at') : Number.POSITIVE_INFINITY;
    return start <= cutoffSeconds && cutoffSeconds < end;
  });
  return active.flatMap((interval) => {
    const zone = zonesById.get(interval.zone_id);
    if (!zone) return [];
    const availability = chartTime(zone.available_at, 'zone.available_at');
    const intervalStart = chartTime(interval.entered_at, 'interval.entered_at');
    // Ceiling to a source close is deliberate: availability can never be
    // painted on a source candle that closed before the zone existed.
    const firstVisible = times.find((time) => time >= Math.max(availability, intervalStart));
    if (firstVisible === undefined || firstVisible > cutoffSeconds) return [];
    return [{
      ...zone,
      lifecycle: interval.lifecycle,
      start_time: firstVisible,
      end_time: Math.min(cutoffSeconds, visibleTo),
      display_open: true,
    }];
  });
}

export function pixelBands(zones, intervals, candles, cutoff, timeScale, series) {
  return pixelBandsFromProjected(projectBands(zones, intervals, candles, cutoff), candles, timeScale, series);
}

export function pixelBandsFromProjected(bands, candles, timeScale, series) {
  if (!Array.isArray(bands)) return [];
  if (!timeScale || !series) return bands;
  const times = candles.map((candle) => candle.time).filter(Number.isFinite);
  if (!times.length) return [];
  return bands
    .map((zone) => toPixelBand(zone, timeScale, series, times[0], times.at(-1)))
    .filter(Boolean);
}

const NONTERMINAL_LIFECYCLES = new Set(['ACTIVE', 'TOUCHED', 'BREAK_PENDING']);

function historyIntervalTime(value, field) {
  return chartTime(value, field);
}

function historyLineageKey(sourceTimeframe, zoneId) {
  return `${sourceTimeframe || ''}\u0000${zoneId}`;
}

function historyIntervalSort(left, right) {
  return left.enteredSeconds - right.enteredSeconds
    || (left.exitedSeconds ?? Number.POSITIVE_INFINITY) - (right.exitedSeconds ?? Number.POSITIVE_INFINITY)
    || left.index - right.index;
}

function newHistoryLifetime(zone, interval) {
  return {
    ...zone,
    zone_id: zone.zone_id,
    lifecycle: interval.lifecycle,
    start_time: Math.max(interval.availableSeconds, interval.enteredSeconds),
    end_time: interval.exitedSeconds,
    display_open: interval.exitedSeconds === null,
    historical: interval.exitedSeconds !== null,
    boundary_times: [],
    intervals: [interval.raw],
    diagnostics: interval.valid ? [] : ['invalid_interval'],
    _lastEntered: interval.enteredSeconds,
    _lastExited: interval.exitedSeconds,
    _lastIndex: interval.index,
    _lastValid: interval.valid,
  };
}

function finalizeHistoryLifetime(lifetime) {
  const result = { ...lifetime };
  delete result._lastEntered;
  delete result._lastExited;
  delete result._lastIndex;
  delete result._lastValid;
  return result;
}

export function projectHistoryLifetimes(history) {
  if (!history || !Array.isArray(history.zones) || !Array.isArray(history.lifecycle_intervals)) return [];
  const zonesById = new Map();
  for (const zone of history.zones) {
    if (!zone || typeof zone.zone_id !== 'string' || !zone.zone_id) continue;
    if (!zonesById.has(zone.zone_id)) zonesById.set(zone.zone_id, []);
    zonesById.get(zone.zone_id).push(zone);
  }
  const intervalsByLineage = new Map();
  for (const [index, raw] of history.lifecycle_intervals.entries()) {
    if (!raw || typeof raw.zone_id !== 'string' || !zonesById.has(raw.zone_id)) continue;
    const candidates = zonesById.get(raw.zone_id);
    const zone = raw.source_timeframe
      ? candidates.find((item) => item.source_timeframe === raw.source_timeframe)
      : candidates.length === 1 ? candidates[0] : null;
    if (!zone) continue;
    if (raw.lifecycle && !NONTERMINAL_LIFECYCLES.has(raw.lifecycle)) continue;
    try {
      const enteredSeconds = historyIntervalTime(raw.entered_at, 'history.interval.entered_at');
      const exitedSeconds = raw.exited_at === null || raw.exited_at === undefined
        ? null
        : historyIntervalTime(raw.exited_at, 'history.interval.exited_at');
      const availableValue = zone.available_at;
      const availableSeconds = availableValue === null || availableValue === undefined
        ? enteredSeconds
        : historyIntervalTime(availableValue, 'history.zone.available_at');
      const interval = {
        raw: { ...raw },
        zone,
        lineageKey: historyLineageKey(zone.source_timeframe || raw.source_timeframe, raw.zone_id),
        index,
        enteredSeconds,
        exitedSeconds,
        availableSeconds,
        valid: exitedSeconds === null || exitedSeconds >= enteredSeconds,
      };
      if (!intervalsByLineage.has(interval.lineageKey)) intervalsByLineage.set(interval.lineageKey, []);
      intervalsByLineage.get(interval.lineageKey).push(interval);
    } catch {
      // A malformed sidecar row cannot be painted or repaired by the viewer.
    }
  }

  const lifetimes = [];
  for (const intervals of intervalsByLineage.values()) {
    const zone = intervals[0].zone;
    intervals.sort(historyIntervalSort);
    let current = null;
    for (const interval of intervals) {
      if (!current) {
        current = newHistoryLifetime(zone, interval);
        continue;
      }
      const previousExit = current._lastExited;
      const contiguous = current._lastValid && interval.valid
        && previousExit !== null && previousExit === interval.enteredSeconds;
      if (contiguous) {
        current.lifecycle = interval.lifecycle;
        current.end_time = interval.exitedSeconds;
        current.display_open = interval.exitedSeconds === null;
        current.historical = interval.exitedSeconds !== null;
        current.boundary_times.push(previousExit);
        current.intervals.push({ ...interval.raw });
        current._lastEntered = interval.enteredSeconds;
        current._lastExited = interval.exitedSeconds;
        current._lastIndex = interval.index;
        current._lastValid = interval.valid;
        continue;
      }
      const overlap = !current._lastValid || !interval.valid
        || previousExit === null || previousExit > interval.enteredSeconds;
      if (overlap) {
        const diagnostic = !current._lastValid || !interval.valid
          ? 'invalid_interval'
          : previousExit === null ? 'open_interval_precedes_later_interval' : 'overlapping_intervals';
        current.diagnostics.push(diagnostic);
        lifetimes.push(finalizeHistoryLifetime(current));
        current = newHistoryLifetime(zone, interval);
        current.diagnostics.push(diagnostic);
      } else {
        lifetimes.push(finalizeHistoryLifetime(current));
        current = newHistoryLifetime(zone, interval);
      }
    }
    if (current) lifetimes.push(finalizeHistoryLifetime(current));
  }
  return lifetimes.sort((left, right) => (
    left.start_time - right.start_time
    || String(left.source_timeframe || '').localeCompare(String(right.source_timeframe || ''))
    || String(left.zone_id).localeCompare(String(right.zone_id))
    || (left.end_time ?? Number.POSITIVE_INFINITY) - (right.end_time ?? Number.POSITIVE_INFINITY)
  ));
}

function sortedCandleTimes(candles) {
  const times = (Array.isArray(candles) ? candles : [])
    .map((candle) => candle?.time);
  if (times.some((time) => !Number.isFinite(time))) return [];
  return times.sort((left, right) => left - right);
}

function chartCoordinate(timeScale, timestamp) {
  try {
    const coordinate = timeScale.timeToCoordinate(timestamp);
    return Number.isFinite(coordinate) ? coordinate : null;
  } catch {
    return null;
  }
}

export function coordinateForLoadedTime(candleTimes, timeScale, timestamp) {
  if (!Array.isArray(candleTimes) || !candleTimes.length
      || !timeScale || typeof timeScale.timeToCoordinate !== 'function'
      || !Number.isFinite(timestamp)) return null;
  if (!Number.isFinite(candleTimes[0]) || !Number.isFinite(candleTimes.at(-1))) return null;
  let low = 0;
  let high = candleTimes.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (candleTimes[middle] < timestamp) low = middle + 1;
    else high = middle;
  }
  const right = low;
  if (right < candleTimes.length && !Number.isFinite(candleTimes[right])) return null;
  if (right < candleTimes.length && candleTimes[right] === timestamp) {
    return chartCoordinate(timeScale, timestamp);
  }
  if (right === 0 || right === candleTimes.length) return null;
  const left = right - 1;
  if (!Number.isFinite(candleTimes[left]) || !Number.isFinite(candleTimes[right])) return null;
  const span = candleTimes[right] - candleTimes[left];
  if (!(span > 0)) return null;
  const leftCoordinate = chartCoordinate(timeScale, candleTimes[left]);
  const rightCoordinate = chartCoordinate(timeScale, candleTimes[right]);
  if (leftCoordinate === null || rightCoordinate === null) return null;
  const fraction = (timestamp - candleTimes[left]) / span;
  const coordinate = leftCoordinate + fraction * (rightCoordinate - leftCoordinate);
  return Number.isFinite(coordinate) ? coordinate : null;
}

export function pixelHistoryBands(
  history,
  candles,
  timeScale,
  series,
  { enabledKernelIds = null, configuredKernelIds = null } = {},
) {
  if (!history || !Array.isArray(history.zones) || !Array.isArray(history.lifecycle_intervals)) return [];
  if (!timeScale || typeof timeScale.timeToCoordinate !== 'function' || !series) return [];
  const times = sortedCandleTimes(candles);
  if (!times.length) return [];
  const visibleFrom = times[0];
  const visibleTo = times.at(-1);
  const coordinateForTime = (value) => coordinateForLoadedTime(times, timeScale, value);
  const lifetimes = projectHistoryLifetimes(history);
  return lifetimes
    .filter((lifetime) => kernelMatchesConfiguration(lifetime, enabledKernelIds, configuredKernelIds))
    .map((lifetime) => {
      const pixel = toPixelBand(
        {
          ...lifetime,
          end_time: lifetime.end_time ?? visibleTo,
          display_open: lifetime.end_time === null,
          historical: lifetime.end_time !== null,
        },
        timeScale,
        series,
        visibleFrom,
        visibleTo,
        coordinateForTime,
      );
      if (!pixel) return null;
      const boundaryTimes = lifetime.boundary_times.filter((time) => time > visibleFrom && time < visibleTo);
      return {
        ...pixel,
        lifetime_start_time: lifetime.start_time,
        lifetime_end_time: lifetime.end_time,
        boundary_times: lifetime.boundary_times,
        boundary_xs: boundaryTimes.map(coordinateForTime).filter(Number.isFinite),
        intervals: lifetime.intervals,
        diagnostics: lifetime.diagnostics,
      };
    })
    .filter(Boolean);
}

function labelNumber(value) {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(number)
    : '—';
}

function compactLabelIdentifier(value) {
  const identifier = typeof value === 'string' ? value : '';
  return identifier.length > 10 ? `${identifier.slice(0, 4)}…${identifier.slice(-4)}` : identifier;
}

function labelSide(side) {
  if (side === 'SUPPORT') return 'S';
  if (side === 'RESISTANCE') return 'R';
  return typeof side === 'string' && side ? side : '—';
}

function humanKernelId(kernelId) {
  return typeof kernelId === 'string' && kernelId ? kernelId.replaceAll('_', ' ') : '';
}

function labelsOverlap(left, right) {
  return left.x < right.x + right.width
    && right.x < left.x + left.width
    && left.y < right.y + right.height
    && right.y < left.y + left.height;
}

function componentMemberIds(component) {
  return [...new Set(component
    .map((rectangle) => rectangle.zone_id)
    .filter((zoneId) => typeof zoneId === 'string' && zoneId))].sort();
}

function labelTimeframe(rectangle) {
  return rectangle.source_timeframe || rectangle.timeframe || '';
}

export function labelRectanglesForDisplay(currentRectangles, historyRectangles, selectedZoneId = null) {
  const current = Array.isArray(currentRectangles) ? currentRectangles : [];
  if (!selectedZoneId || current.some((rectangle) => rectangle?.zone_id === selectedZoneId)) {
    return [...current];
  }
  const selectedHistory = (Array.isArray(historyRectangles) ? historyRectangles : [])
    .filter((rectangle) => rectangle?.zone_id === selectedZoneId);
  return [...current, ...selectedHistory];
}

export function lineageLabelCandidates(rectangles, selectedZoneId = null) {
  if (!Array.isArray(rectangles)) return [];
  const source = rectangles.filter((rectangle) => (
    rectangle
    && typeof rectangle.zone_id === 'string'
    && [rectangle.x1, rectangle.x2, rectangle.top, rectangle.bottom].every(Number.isFinite)
  ));
  const components = [];
  for (const rectangle of source) {
    const matches = components.filter((component) => component.some((member) => (
      labelTimeframe(rectangle) === labelTimeframe(member)
      &&
      rectangle.x1 <= member.x2
      && member.x1 <= rectangle.x2
      && rectangle.top <= member.bottom
      && member.top <= rectangle.bottom
    )));
    if (!matches.length) {
      components.push([rectangle]);
      continue;
    }
    const componentMembers = [rectangle, ...matches.flat()];
    for (const component of matches) components.splice(components.indexOf(component), 1);
    components.push(componentMembers);
  }
  return components.map((component) => {
    const memberIds = componentMemberIds(component);
    const selected = selectedZoneId && memberIds.includes(selectedZoneId);
    const primary = selected
      ? component.find((rectangle) => rectangle.zone_id === selectedZoneId)
      : component.find((rectangle) => rectangle.historical !== true) || component[0];
    const timeframe = labelTimeframe(primary);
    const side = labelSide(primary.side);
    const kernel = humanKernelId(primary.kernel_id);
    const center = labelNumber(primary.center ?? ((Number(primary.lower) + Number(primary.upper)) / 2));
    const range = `${labelNumber(primary.lower)}-${labelNumber(primary.upper)}`;
    const neutral = memberIds.length > 1 && !selected;
    const compact = neutral
      ? `${memberIds.length} lineages`
      : [timeframe, side, center].filter(Boolean).join(' · ');
    const full = selected
      ? [timeframe, side, kernel, range, compactLabelIdentifier(primary.zone_id)].filter(Boolean).join(' · ')
      : neutral
        ? `${memberIds.length} lineages`
        : [timeframe, side, kernel, center].filter(Boolean).join(' · ');
    const x1 = Math.min(...component.map((rectangle) => rectangle.x1));
    const x2 = Math.max(...component.map((rectangle) => rectangle.x2));
    const top = Math.min(...component.map((rectangle) => rectangle.top));
    return {
      zone_id: primary.zone_id,
      member_ids: memberIds,
      selected: Boolean(selected),
      neutral,
      full_text: full || compact,
      compact_text: compact || full,
      x: x1 + 6,
      x2,
      y: top + 13,
      top,
      label_key: `${top}|${memberIds.join('|')}`,
    };
  }).sort((left, right) => (
    Number(right.selected) - Number(left.selected)
    || left.top - right.top
    || left.member_ids.join('|').localeCompare(right.member_ids.join('|'))
  ));
}

export function selectLineageLabels(
  candidates,
  {
    width = Number.POSITIVE_INFINITY,
    height = Number.POSITIVE_INFINITY,
    measureText = (value) => value.length * 7,
    ascent = 9,
    descent = 3,
    padding = 4,
  } = {},
) {
  if (!Array.isArray(candidates)) return [];
  const accepted = [];
  for (const candidate of candidates) {
    const options = [candidate.full_text, candidate.compact_text]
      .filter((value, index, values) => typeof value === 'string' && value && values.indexOf(value) === index);
    let chosen = null;
    for (const value of options) {
      const measured = Number(measureText(value));
      if (!Number.isFinite(measured)) continue;
      const textWidth = measured + padding * 2;
      const anchors = [candidate.x, candidate.x2 - textWidth - padding]
        .filter((anchor, index, values) => Number.isFinite(anchor) && values.indexOf(anchor) === index);
      for (const anchor of anchors) {
        const x = Math.max(0, anchor);
        const box = {
          x,
          y: candidate.y - ascent,
          width: textWidth,
          height: ascent + descent + padding,
          text: value,
          candidate,
        };
        if (x + textWidth > width || box.y < 0 || box.y + box.height > height) continue;
        if (accepted.some((other) => labelsOverlap(box, other))) continue;
        chosen = box;
        break;
      }
      if (chosen) break;
    }
    if (chosen) accepted.push(chosen);
  }
  return accepted;
}

export function visiblePriceRegions(rectangles, visibleWindow = {}) {
  if (!Array.isArray(rectangles)) return 0;
  const left = Number.isFinite(visibleWindow?.left) ? visibleWindow.left : 0;
  const right = Number.isFinite(visibleWindow?.right) ? visibleWindow.right : Number.POSITIVE_INFINITY;
  if (right < left) return 0;
  const visible = rectangles
    .filter((rectangle) => rectangle && rectangle.visible !== false && rectangle.hidden !== true)
    .filter((rectangle) => [rectangle.x1, rectangle.x2, rectangle.top, rectangle.bottom].every(Number.isFinite))
    .filter((rectangle) => rectangle.x2 >= left && rectangle.x1 <= right)
    .map((rectangle) => ({
      paintedTop: Math.floor(rectangle.top),
      paintedBottom: Math.ceil(rectangle.top + Math.max(1, rectangle.bottom - rectangle.top)) - 1,
      zoneId: typeof rectangle.zone_id === 'string' ? rectangle.zone_id : '',
    }))
    .filter((rectangle) => rectangle.paintedBottom >= rectangle.paintedTop)
    .sort((leftRect, rightRect) => (
      leftRect.paintedTop - rightRect.paintedTop
      || leftRect.paintedBottom - rightRect.paintedBottom
      || leftRect.zoneId.localeCompare(rightRect.zoneId)
    ));
  let regions = 0;
  let currentBottom = null;
  for (const rectangle of visible) {
    if (currentBottom === null || rectangle.paintedTop > currentBottom + 1) {
      regions += 1;
      currentBottom = rectangle.paintedBottom;
    } else {
      currentBottom = Math.max(currentBottom, rectangle.paintedBottom);
    }
  }
  return regions;
}

export function bandPriceRange(bands, candleTimes, startTimePoint, endTimePoint) {
  let from;
  let to;
  try {
    from = finiteNumber(startTimePoint, 'startTimePoint');
    to = finiteNumber(endTimePoint, 'endTimePoint');
  } catch {
    return null;
  }
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return null;
  if (!Array.isArray(candleTimes) || !candleTimes.length || to < 0 || from > candleTimes.length - 1) return null;
  const leftIndex = Math.max(0, Math.floor(from));
  const rightIndex = Math.min(candleTimes.length - 1, Math.ceil(to));
  if (leftIndex > rightIndex) return null;
  let visibleFrom;
  let visibleTo;
  try {
    visibleFrom = finiteNumber(candleTimes[leftIndex], 'candleTimes.start');
    visibleTo = finiteNumber(candleTimes[rightIndex], 'candleTimes.end');
  } catch {
    return null;
  }

  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;
  for (const band of Array.isArray(bands) ? bands : []) {
    if (!band || typeof band !== 'object') continue;
    let start;
    let end;
    try {
      start = finiteNumber(band.start_time, 'band.start_time');
      end = finiteNumber(band.end_time, 'band.end_time');
    } catch {
      continue;
    }
    const displayOpen = band.display_open === true;
    if (displayOpen) {
      if (start > end || start > visibleTo) continue;
    } else {
      if (!(start < end) || start > visibleTo || end <= visibleFrom) continue;
    }
    let geometry;
    try {
      geometry = numericGeometry(band);
    } catch {
      continue;
    }
    if (geometry.lower > geometry.upper) continue;
    minValue = Math.min(minValue, geometry.lower);
    maxValue = Math.max(maxValue, geometry.upper);
  }
  return Number.isFinite(minValue) && Number.isFinite(maxValue)
    ? { minValue, maxValue }
    : null;
}

export function navigationState(zone, knownZones, identityMode, reconstructionStart = null) {
  const knownZoneIds = knownZones instanceof Map ? new Set(knownZones.keys()) : knownZones;
  const canNavigate = (target) => Boolean(
    target && knownZoneIds.has(target)
    && !(identityMode === 'WINDOW_RELATIVE' && (
      !knownZoneIds.has(target)
      || (reconstructionStart && knownZones instanceof Map && knownZones.get(target)?.formed_at < reconstructionStart)
    )),
  );
  return {
    predecessor: canNavigate(zone.predecessor_id),
    successor: canNavigate(zone.successor_id),
  };
}

export function asOfInspection(pane, hoveredTime) {
  const cutoff = Number.isFinite(hoveredTime)
    ? hoveredTime
    : chartTime(hoveredTime, 'hovered.cutoff');
  const available = (row) => chartTime(row.available_at ?? row.cutoff, 'available.at') <= cutoff;
  const candidates = (pane.formation?.candidates || []).filter(available);
  const zoneStates = (pane.lifecycle?.zones || []).flatMap((zone) => {
    const intervals = (pane.lifecycle?.intervals || [])
      .filter((interval) => interval.zone_id === zone.zone_id)
      .filter((interval) => {
        const start = chartTime(interval.entered_at, 'interval.entered_at');
        const end = interval.exited_at ? chartTime(interval.exited_at, 'interval.exited_at') : Number.POSITIVE_INFINITY;
        return start <= cutoff && cutoff < end;
      })
      .sort((left, right) => chartTime(left.entered_at, 'interval.entered_at') - chartTime(right.entered_at, 'interval.entered_at'));
    return intervals.length ? [{ zone_id: zone.zone_id, lifecycle: intervals.at(-1).lifecycle, geometry: zone.geometry }] : [];
  });
  const touchEpisodes = (pane.lifecycle?.touch_episodes || []).filter((episode) => {
    const start = chartTime(episode.started_at, 'episode.started_at');
    const end = episode.ended_at ? chartTime(episode.ended_at, 'episode.ended_at') : Number.POSITIVE_INFINITY;
    return start <= cutoff && cutoff < end;
  });
  const transitions = (pane.lifecycle?.transitions || []).filter(
    (transition) => chartTime(transition.event_at, 'transition.event_at') === cutoff,
  );
  return { cutoff, candidates, zoneStates, touchEpisodes, transitions };
}

export function validateSelectedPayload(payload) {
  if (!payload || payload.schema_version !== 2 || !Array.isArray(payload.configured_timeframes) || payload.configured_timeframes.length !== 1) {
    throw new Error('the viewer URL must select exactly one schema-v2 source timeframe');
  }
  const timeframe = payload.configured_timeframes[0];
  if (typeof timeframe !== 'string' || !timeframe.trim() || !payload.panes || Object.keys(payload.panes).length !== 1 || !payload.panes[timeframe]) {
    throw new Error('selected source timeframe is unavailable');
  }
  const pane = payload.panes[timeframe];
  if (Object.keys(pane).sort().join(',') !== 'formation,inspection,lifecycle,source_timeframe' || pane.source_timeframe !== timeframe) {
    throw new Error('selected pane projection is invalid');
  }
  if (!pane.formation || Object.keys(pane.formation).sort().join(',') !== 'candidates,candles,kernel_ids,timeframe' || pane.formation.timeframe !== timeframe || !Array.isArray(pane.formation.candles) || !Array.isArray(pane.formation.candidates) || !Array.isArray(pane.formation.kernel_ids)) {
    throw new Error('selected formation projection is invalid');
  }
  if (!pane.lifecycle || Object.keys(pane.lifecycle).sort().join(',') !== 'candles,kernel_ids,timeframe' || typeof pane.lifecycle.timeframe !== 'string' || !pane.lifecycle.timeframe.trim() || !Array.isArray(pane.lifecycle.candles) || !Array.isArray(pane.lifecycle.kernel_ids)) {
    throw new Error('selected lifecycle projection is invalid');
  }
  if (!pane.inspection || Object.keys(pane.inspection).sort().join(',') !== 'analysis_start,as_of,available_cutoffs,identity_mode,reconstruction_start,window_start' || !Array.isArray(pane.inspection.available_cutoffs)) {
    throw new Error('selected inspection projection is invalid');
  }
  if ('features' in pane.formation || 'zones' in pane.lifecycle || 'intervals' in pane.lifecycle || 'transitions' in pane.lifecycle || 'touch_episodes' in pane.lifecycle || 'markers' in pane.lifecycle || 'zone_bands' in pane.lifecycle) {
    throw new Error('raw evidence is not allowed in the chart payload');
  }
  return payload;
}

export function createRequestGate() {
  let sequence = 0;
  let controller = null;
  return {
    begin() {
      controller?.abort();
      controller = new AbortController();
      const id = ++sequence;
      return { id, signal: controller.signal };
    },
    isCurrent(id) {
      return id === sequence;
    },
    finish(id) {
      if (id === sequence) controller = null;
    },
    cancel() {
      controller?.abort();
      controller = null;
      sequence += 1;
    },
  };
}

export function isCurrentResponse(requestId, currentRequestId) {
  return requestId === currentRequestId;
}

export { EVENT_COLORS };
