const TERMINAL_STATUSES = new Set(['BROKEN', 'EXPIRED']);

function seconds(value) {
  return Math.floor(new Date(value).getTime() / 1000);
}

export function zoneVisibleAt(zone, time) {
  const timestamp = typeof time === 'number' ? time : seconds(time);
  const start = seconds(zone.visible_from);
  const end = zone.visible_until === null ? null : seconds(zone.visible_until);
  return timestamp >= start && (end === null || timestamp <= end);
}

export function zoneDetail(zone) {
  return {
    zone_id: zone.zone_id,
    side: zone.side,
    final_status: zone.final_status,
    lower_bound: zone.lower_bound,
    center: zone.center,
    upper_bound: zone.upper_bound,
    visible_from: zone.visible_from,
    visible_until: zone.visible_until,
    touch_count: zone.touch_count,
    fakeout_count: zone.fakeout_count,
    pending_count: zone.pending_count ?? zone.pending_breach_count,
  };
}

function colorFor(zone, viewer) {
  if (TERMINAL_STATUSES.has(zone.final_status)) {
    return zone.side === 'SUPPORT'
      ? viewer.support_border_color
      : viewer.resistance_border_color;
  }
  if (zone.final_status === 'BREACH_PENDING') return viewer.pending_border_color;
  return zone.side === 'SUPPORT'
    ? viewer.support_border_color
    : viewer.resistance_border_color;
}

class ZoneRenderer {
  constructor(source) { this.source = source; }

  draw(target) {
    const source = this.source;
    target.useMediaCoordinateSpace((scope) => {
      const context = scope.context;
      const { horizontalPixelRatio, verticalPixelRatio, mediaSize } = scope;
      context.save();
      for (const zone of source.visibleZones()) {
        const timeScale = source.chart.timeScale();
        const xStartCoordinate = timeScale.timeToCoordinate(seconds(zone.visible_from));
        const xEndCoordinate = zone.visible_until === null
          ? mediaSize.width / horizontalPixelRatio
          : timeScale.timeToCoordinate(seconds(zone.visible_until));
        const yLower = source.series.priceToCoordinate(zone.lower_bound);
        const yUpper = source.series.priceToCoordinate(zone.upper_bound);
        const yCenter = source.series.priceToCoordinate(zone.center);
        if (xStartCoordinate === null || xEndCoordinate === null || yCenter === null) continue;
        const xStart = xStartCoordinate * horizontalPixelRatio;
        const xEnd = xEndCoordinate * horizontalPixelRatio;
        const color = colorFor(zone, source.payload.viewer);
        context.globalAlpha = TERMINAL_STATUSES.has(zone.final_status)
          ? source.payload.viewer.terminal_opacity
          : 1;
        context.strokeStyle = color;
        context.fillStyle = zone.side === 'SUPPORT'
          ? source.payload.viewer.support_fill_color
          : source.payload.viewer.resistance_fill_color;
        context.lineWidth = source.payload.viewer.zone_line_width * horizontalPixelRatio;
        if (zone.render_kind === 'BAND' && yLower !== null && yUpper !== null) {
          const top = Math.min(yLower, yUpper) * verticalPixelRatio;
          const height = Math.abs(yUpper - yLower) * verticalPixelRatio;
          context.fillRect(xStart, top, Math.max(0, xEnd - xStart), height);
          context.strokeRect(xStart, top, Math.max(0, xEnd - xStart), height);
        } else {
          const y = yCenter * verticalPixelRatio;
          context.beginPath();
          context.moveTo(xStart, y);
          context.lineTo(Math.max(xStart, xEnd), y);
          context.stroke();
        }
      }
      context.restore();
    });
  }
}

class ZonePaneView {
  constructor(source) { this.source = source; }
  renderer() { return new ZoneRenderer(this.source); }
  zOrder() { return 'bottom'; }
}

export class ZonePrimitive {
  constructor(payload) {
    this.payload = payload;
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  attached({ chart, series, requestUpdate }) {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews() { return [new ZonePaneView(this)]; }

  visibleZones() {
    return this.payload.zones.filter((zone) => (
      zone.final_status !== 'BROKEN' && zone.final_status !== 'EXPIRED'
    ) || this.payload.viewer.show_terminal_by_default);
  }

  hitTest(x, y) {
    if (!this.series) return null;
    for (const zone of this.visibleZones()) {
      const timeScale = this.chart.timeScale();
      const left = timeScale.timeToCoordinate(seconds(zone.visible_from));
      const right = zone.visible_until === null
        ? timeScale.width()
        : timeScale.timeToCoordinate(seconds(zone.visible_until));
      const center = this.series.priceToCoordinate(zone.center);
      if (left === null || right === null || center === null) continue;
      const tolerance = 8;
      const inX = x >= Math.min(left, right) && x <= Math.max(left, right);
      const inY = zone.render_kind === 'LINE'
        ? Math.abs(y - center) <= tolerance
        : (() => {
          const lower = this.series.priceToCoordinate(zone.lower_bound);
          const upper = this.series.priceToCoordinate(zone.upper_bound);
          return lower !== null && upper !== null && y >= Math.min(lower, upper) && y <= Math.max(lower, upper);
        })();
      if (inX && inY) return { externalId: zone.zone_id, zOrder: 0, detail: zoneDetail(zone) };
    }
    return null;
  }
}
