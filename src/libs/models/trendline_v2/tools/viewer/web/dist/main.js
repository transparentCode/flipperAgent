import { CandlestickSeries, createChart, } from 'lightweight-charts';
import { PAYLOAD_SCHEMA_VERSION, isDiagnosticPayload, } from './contracts.js';
import { loadPayload } from './payload.js';
import { candidateDetail, TrendlinePrimitive } from './trendline_primitive.js';
import { DEFAULT_FOCUS_SETTINGS, DEFAULT_NEAREST_SETTINGS, displayCounts, selectDisplayCandidates, } from './candidate_filter.js';
function element(selector) {
    const value = document.querySelector(selector);
    if (value === null)
        throw new Error(`missing viewer element: ${selector}`);
    return value;
}
export function diagnosticCandidates(payload) {
    return payload.lines.map((line) => ({
        candidate_id: line.selection_id,
        role: 'support',
        diagnosticSide: line.side,
        start_time: line.anchors[0].time,
        end_time: line.projection_time,
        start_price: line.anchors[0].price,
        end_price: line.projection_price,
        anchors: [
            {
                anchor_id: line.lineage_id,
                pivot_time: line.anchors[0].time,
                confirmation_time: line.anchors[0].time,
                price: line.anchors[0].price,
            },
            {
                anchor_id: line.selection_id,
                pivot_time: line.anchors[1].time,
                confirmation_time: line.anchors[1].time,
                price: line.anchors[1].price,
            },
        ],
        evidence: {
            candidate_id: line.selection_id,
            extrema_kind: 'low',
            anchor_source_positions: [0, 1],
            confirmation_positions: [0, 1],
            validated_intermediate_count: 0,
            body_violation_count: 0,
            coordinate_system_version: 'diagnostic_geometry_v1',
            plateau_policy_version: 'diagnostic_geometry_v1',
            schema_version: 'diagnostic_v1',
            evidence_id: line.selection_id,
        },
    }));
}
function candleData(candle) {
    return {
        time: candle.time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
    };
}
export function diagnosticSeriesData(payload) {
    if (payload.candles.length < 2)
        throw new Error('diagnostic payload needs two candles for interval inference');
    const realCandles = payload.candles.map(candleData);
    const previous = payload.candles[payload.candles.length - 2].time;
    const last = payload.candles[payload.candles.length - 1].time;
    const interval = last - previous;
    if (!Number.isSafeInteger(interval) || interval <= 0)
        throw new Error('diagnostic candle interval is invalid');
    const maxProjectionTime = Math.max(...payload.lines.map((line) => line.projection_time));
    const whitespace = [];
    for (let time = last + interval; time <= maxProjectionTime; time += interval) {
        whitespace.push({ time: time });
    }
    return [...realCandles, ...whitespace];
}
function diagnosticLineDetail(line) {
    const side = line.side === 'contender' ? 'Contender' : 'Control';
    const reachability = line.reachable_at_96h ? 'reachable' : 'not reachable';
    return [
        `${side} — ${reachability} — ${line.geometry_projected_distance_atr_96h.toFixed(3)} ATR`,
        `${line.role} · ${line.lineage_id}`,
        `selection ${line.selection_id}`,
        `anchors ${line.anchors[0].time} @ ${line.anchors[0].price} → ${line.anchors[1].time} @ ${line.anchors[1].price}`,
        `projection ${line.projection_time} @ ${line.projection_price}`,
        `initial ${line.initial_distance_atr.toFixed(4)} ATR · 96h ${line.geometry_projected_distance_atr_96h.toFixed(4)} ATR`,
        `reachable at 96h ${line.reachable_at_96h}`,
        `R5 ${line.attribution_class} · ${line.cross_budget_class}`,
    ].join(' · ');
}
async function bootstrap() {
    const container = element('#chart');
    const summary = element('#trial-summary');
    const statusBanner = element('#status-banner');
    const displayDisclaimer = element('#display-disclaimer');
    const displaySummary = element('#display-summary');
    const detail = element('#hover-detail');
    const densityControls = element('#density-controls');
    const displayMode = element('#display-mode');
    const nearestBudgetControl = element('#nearest-budget-control');
    const nearestBudget = element('#nearest-budget');
    const recentAge = element('#recent-age');
    const minimumSpan = element('#min-span');
    const maximumPerRole = element('#max-role');
    const uniqueAnchor = element('#unique-anchor');
    const resetFocus = element('#reset-focus');
    const supportToggle = element('#show-support');
    const resistanceToggle = element('#show-resistance');
    const anchorsToggle = element('#show-anchors');
    const fitButton = element('#fit-content');
    nearestBudget.value = `${DEFAULT_NEAREST_SETTINGS.maxPerRole}`;
    const payload = await loadPayload();
    const diagnostic = isDiagnosticPayload(payload) ? payload : null;
    const providerPayload = payload.schema_version === PAYLOAD_SCHEMA_VERSION ? payload : null;
    const rawCandidates = diagnostic !== null
        ? diagnosticCandidates(diagnostic)
        : providerPayload.candidates;
    const rawCounts = displayCounts(rawCandidates);
    summary.textContent = diagnostic
        ? `${diagnostic.asset} · ${diagnostic.timeframe} · checkpoint ${diagnostic.checkpoint_index} · ${diagnostic.lines.length} selected lines`
        : `${payload.asset} · ${payload.timeframe} · ${providerPayload.candles.length} bars · ${providerPayload.candidates.length} candidates`;
    densityControls.hidden = diagnostic !== null;
    statusBanner.dataset.status = diagnostic ? 'diagnostic' : providerPayload.status;
    statusBanner.textContent = diagnostic
        ? 'Diagnostic view — not a promoted production selector'
        : providerPayload.reason === null ? `provider status: ${providerPayload.status}` : `provider status: ${providerPayload.status} · reason: ${providerPayload.reason}`;
    const chart = createChart(container, {
        autoSize: true,
        layout: {
            background: { color: '#131e20' },
            textColor: '#c8d9d2',
            attributionLogo: true,
        },
        grid: {
            vertLines: { color: '#20332f' },
            horzLines: { color: '#20332f' },
        },
        timeScale: { borderColor: '#365149', timeVisible: true },
        rightPriceScale: { borderColor: '#365149' },
    });
    const series = chart.addSeries(CandlestickSeries, {
        upColor: '#65d6a5',
        downColor: '#e8a36f',
        borderVisible: false,
        wickUpColor: '#65d6a5',
        wickDownColor: '#e8a36f',
    });
    series.setData(diagnostic === null ? payload.candles.map(candleData) : diagnosticSeriesData(diagnostic));
    const primitive = new TrendlinePrimitive(rawCandidates);
    series.attachPrimitive(primitive);
    function readFocusSettings() {
        const recentBars = recentAge.value === 'all' ? null : Number(recentAge.value);
        const maxPerRole = maximumPerRole.value === 'all' ? null : Number(maximumPerRole.value);
        return {
            recentBars,
            minAnchorSpan: Number(minimumSpan.value),
            onePerSecondAnchor: uniqueAnchor.checked,
            maxPerRole,
        };
    }
    function readNearestSettings() {
        const maxPerRole = Number(nearestBudget.value);
        if (maxPerRole !== 5 && maxPerRole !== 10)
            throw new Error('nearest budget is invalid');
        return { maxPerRole };
    }
    function setFormControlState(control, enabled) {
        control.disabled = !enabled;
        const container = control instanceof HTMLButtonElement ? control : control.parentElement;
        if (container !== null)
            container.hidden = !enabled;
    }
    function updateControlState() {
        const mode = displayMode.value;
        const nearest = diagnostic === null && mode === 'nearest';
        const focus = diagnostic === null && mode === 'focus';
        nearestBudget.disabled = !nearest;
        nearestBudgetControl.hidden = !nearest;
        setFormControlState(recentAge, focus);
        setFormControlState(minimumSpan, focus);
        setFormControlState(maximumPerRole, focus);
        setFormControlState(uniqueAnchor, focus);
        setFormControlState(resetFocus, focus);
    }
    function updateDisclaimer() {
        if (diagnostic !== null) {
            displayDisclaimer.textContent = 'Diagnostic view — provider lines shown without density filtering';
            return;
        }
        const mode = displayMode.value;
        displayDisclaimer.textContent = mode === 'nearest'
            ? 'Display-only proximity view — not a quality or prediction signal; provider output unchanged'
            : mode === 'focus'
                ? 'Display-only filtering — provider output unchanged'
                : 'Raw provider output — no display filtering';
    }
    function displayedCandidates() {
        if (diagnostic !== null)
            return rawCandidates;
        const mode = displayMode.value;
        return selectDisplayCandidates({
            mode,
            candidates: rawCandidates,
            lastCandle: providerPayload.candles[providerPayload.candles.length - 1],
            lastCandlePosition: providerPayload.candles.length - 1,
            focusSettings: readFocusSettings(),
            nearestSettings: readNearestSettings(),
        });
    }
    function updateDisplaySummary(candidates) {
        const counts = displayCounts(candidates);
        if (diagnostic !== null) {
            displaySummary.textContent = `Showing ${counts.total} of ${rawCounts.total} diagnostic lines — density controls unavailable`;
            return;
        }
        if (displayMode.value === 'all') {
            displaySummary.textContent = [
                `Showing all ${rawCounts.total} raw provider candidates`,
                'High visual density expected',
                `Support ${counts.support} of ${rawCounts.support}`,
                `Resistance ${counts.resistance} of ${rawCounts.resistance}`,
            ].join(' · ');
            return;
        }
        if (displayMode.value === 'nearest') {
            const settings = readNearestSettings();
            displaySummary.textContent = [
                `Showing ${counts.total} of ${rawCounts.total} candidates`,
                `Support ${counts.support} of ${rawCounts.support}`,
                `Resistance ${counts.resistance} of ${rawCounts.resistance}`,
                `Nearest now: latest completed candle range · one per second anchor · max ${settings.maxPerRole}/role`,
            ].join(' · ');
            return;
        }
        const settings = readFocusSettings();
        const recentText = settings.recentBars === null ? 'all' : `${settings.recentBars}`;
        const roleCapText = settings.maxPerRole === null ? 'all' : `${settings.maxPerRole}`;
        displaySummary.textContent = [
            `Showing ${counts.total} of ${rawCounts.total} candidates`,
            `Support ${counts.support} of ${rawCounts.support}`,
            `Resistance ${counts.resistance} of ${rawCounts.resistance}`,
            `Focus: confirmation age ≤${recentText} bars · span ≥${settings.minAnchorSpan} bars · ${settings.onePerSecondAnchor ? 'unique second anchor' : 'all second anchors'} · max ${roleCapText}/role`,
        ].join(' · ');
    }
    function updateDisplay() {
        const candidates = displayedCandidates();
        primitive.setCandidates(candidates);
        updateDisclaimer();
        updateDisplaySummary(candidates);
    }
    updateControlState();
    updateDisplay();
    chart.timeScale().fitContent();
    function updateVisibility() {
        primitive.setVisibility({
            support: supportToggle.checked,
            resistance: resistanceToggle.checked,
            anchors: anchorsToggle.checked,
        });
    }
    displayMode.addEventListener('change', () => {
        updateControlState();
        updateDisplay();
    });
    nearestBudget.addEventListener('change', updateDisplay);
    for (const control of [recentAge, minimumSpan, maximumPerRole, uniqueAnchor]) {
        control.addEventListener('change', updateDisplay);
    }
    resetFocus.addEventListener('click', () => {
        displayMode.value = 'focus';
        recentAge.value = `${DEFAULT_FOCUS_SETTINGS.recentBars}`;
        minimumSpan.value = `${DEFAULT_FOCUS_SETTINGS.minAnchorSpan}`;
        maximumPerRole.value = `${DEFAULT_FOCUS_SETTINGS.maxPerRole}`;
        uniqueAnchor.checked = DEFAULT_FOCUS_SETTINGS.onePerSecondAnchor;
        updateControlState();
        updateDisplay();
    });
    function selectedFromEvent(param) {
        if (param.point == null) {
            detail.textContent = 'Hover a finite candidate segment for evidence.';
            return;
        }
        const hit = primitive.hitTest(param.point.x, param.point.y);
        const candidate = hit === null ? null : rawCandidates.find((item) => item.candidate_id === hit.externalId) ?? null;
        if (candidate === null) {
            detail.textContent = 'Hover a finite candidate segment for evidence.';
            return;
        }
        if (diagnostic !== null) {
            const line = diagnostic.lines.find((item) => item.selection_id === candidate.candidate_id);
            detail.textContent = line === undefined ? 'Diagnostic line not found.' : diagnosticLineDetail(line);
            return;
        }
        detail.textContent = candidateDetail(candidate, providerPayload);
    }
    supportToggle.addEventListener('change', updateVisibility);
    resistanceToggle.addEventListener('change', updateVisibility);
    anchorsToggle.addEventListener('change', updateVisibility);
    fitButton.addEventListener('click', () => chart.timeScale().fitContent());
    chart.subscribeCrosshairMove(selectedFromEvent);
    chart.subscribeClick((param) => {
        if (param.point == null)
            return;
        const hit = primitive.hitTest(param.point.x, param.point.y);
        primitive.select(hit?.externalId ?? null);
        selectedFromEvent(param);
    });
}
if (typeof document !== 'undefined') {
    void bootstrap().catch((error) => {
        const statusBanner = document.querySelector('#status-banner');
        if (statusBanner === null)
            return;
        statusBanner.dataset.status = 'failed';
        statusBanner.textContent = `viewer failed closed: ${error instanceof Error ? error.message : String(error)}`;
    });
}
