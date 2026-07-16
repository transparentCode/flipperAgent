const ALL = 'ALL';

function matchesFilter(filter, value) {
  return filter === undefined || filter === null || filter === ALL || filter === value;
}

function markerTime(marker) {
  return Number(marker.time);
}

export function eventMarkers(events, selectedCase = null, viewer = {}) {
  const markers = events.map((event) => ({
    time: event.time,
    position: event.event_type === 'BREACH_STARTED' || event.event_type === 'BREAK_CONFIRMED'
      ? 'aboveBar'
      : 'belowBar',
    color: event.event_type === 'FALSE_BREAKOUT' ? viewer.pending_border_color : viewer.text_color,
    shape: event.event_type === 'BREAK_CONFIRMED' ? 'arrowUp' : 'circle',
    text: event.event_type,
  }));
  if (selectedCase) {
    markers.push(
      {
        time: Math.floor(Date.parse(selectedCase.outcome_window.start) / 1000),
        position: 'aboveBar',
        color: viewer.pending_border_color,
        shape: 'square',
        text: 'OUTCOME_START',
      },
      {
        time: Math.floor(Date.parse(selectedCase.outcome_window.end) / 1000),
        position: 'aboveBar',
        color: viewer.pending_border_color,
        shape: 'square',
        text: 'OUTCOME_END',
      },
    );
  }

  // Carry source order explicitly. Equal timestamps must preserve deterministic
  // lifecycle order, including same-bar events and outcome-window markers.
  return markers
    .map((marker, sourceIndex) => ({ marker, sourceIndex }))
    .sort((left, right) => markerTime(left.marker) - markerTime(right.marker) || left.sourceIndex - right.sourceIndex)
    .map(({ marker }) => marker);
}

export function filterCasebookCases(cases, filters = {}) {
  return cases.filter((item) => (
    matchesFilter(filters.fold, item.fold)
    && matchesFilter(filters.side, item.side)
    && (
      filters.completion === undefined
      || filters.completion === null
      || filters.completion === ALL
      || (filters.completion === 'COMPLETED' && item.fold_local_outcome.completed)
      || (filters.completion === 'RIGHT_CENSORED' && item.fold_local_outcome.right_censored)
    )
    && matchesFilter(filters.lifecycle, item.horizon_lifecycle_class)
    && matchesFilter(filters.close, item.close_location)
  ));
}

export function selectCasebookCase(casebook, filters = {}, previousCaseId = '') {
  const available = filterCasebookCases(casebook.cases, filters);
  const selected = available.find((item) => item.case_id === previousCaseId) ?? available[0] ?? null;
  return { available, selected };
}

export function casebookMetrics(selected) {
  if (!selected) return null;
  const pooledQuality = selected.pooled_outcome.quality_reference_atr ?? null;
  const foldLocalQuality = selected.fold_local_outcome.quality_reference_atr ?? null;
  const excessQuality = selected.comparison?.excess_quality ?? null;
  return {
    pooledQuality,
    foldLocalQuality,
    excessQuality,
    text: `${selected.case_id.slice(0, 12)} · ${selected.fold} · ${selected.side} · pooled ${pooledQuality ?? 'censored'} · fold-local ${foldLocalQuality ?? 'censored'}${excessQuality === null ? ' · no persisted comparison' : ` · excess ${excessQuality}`}`,
  };
}

export function casebookOutcomeRange(selected) {
  if (!selected) return null;
  return {
    from: Math.floor(Date.parse(selected.creation_event.timestamp) / 1000),
    to: Math.floor(Date.parse(selected.outcome_window.end) / 1000),
  };
}

export function casebookState(
  casebook,
  filters = {},
  previousCaseId = '',
  viewer = {},
  mode = 'overview',
) {
  const { available, selected } = selectCasebookCase(casebook, filters, previousCaseId);
  const focus = mode === 'focus';
  const selectedForView = focus ? selected : null;
  return {
    mode: focus ? 'focus' : 'overview',
    available,
    selected: selectedForView,
    selectedCaseId: selectedForView?.case_id ?? null,
    zones: selectedForView ? [selectedForView.zone] : available.map((item) => item.zone),
    events: selectedForView ? selectedForView.events : [],
    markers: selectedForView
      ? eventMarkers(selectedForView.events, selectedForView, viewer)
      : [],
    metrics: casebookMetrics(selectedForView),
    visibleRange: casebookOutcomeRange(selectedForView),
  };
}

export function casebookMarkers(state, eventsEnabled) {
  return state.mode === 'focus' && eventsEnabled ? state.markers : [];
}

export function casebookNoticeText(casebook) {
  return `${casebook.notice} Disposition: ${casebook.disposition}. ${casebook.case_count} cases; pooled and fold-local outcomes are shown separately.`;
}
