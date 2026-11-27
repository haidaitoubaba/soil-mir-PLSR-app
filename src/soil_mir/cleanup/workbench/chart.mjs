const PALETTE = ["#147a78", "#ad682a", "#7768a6", "#3f759e", "#967d32", "#ae557a", "#457948", "#83665c"];

function ticks(lo, hi, target = 8) {
  const step = (hi - lo) / target;
  const scale = 10 ** Math.floor(Math.log10(step));
  const span = [1, 2, 2.5, 5, 10].find(value => value >= step / scale) * scale;
  const first = Math.ceil(lo / span);
  const last = Math.floor(hi / span);
  return Array.from({length: Math.max(0, last - first + 1)}, (_, i) => {
    const value = (first + i) * span;
    return [value, String(Number(value.toPrecision(6)))];
  });
}

function polygonIncludes(polygon, point) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a.y > point.y) !== (b.y > point.y)
        && point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x) {
      inside = !inside;
    }
  }
  return inside;
}

class PcaChart {
  constructor(canvas, tooltip, pick) {
    this.canvas = canvas;
    this.tooltip = tooltip;
    this.pick = pick;
    this.ctx = canvas.getContext("2d");
    this.view = null;
    this.points = [];
    this.stroke = null;
    this.resize = new ResizeObserver(() => this.draw());
    this.resize.observe(canvas);
    canvas.onpointerdown = event => this.start(event);
    canvas.onpointermove = event => this.move(event);
    canvas.onpointerup = event => this.end(event);
    canvas.onpointercancel = () => { this.stopPan(); this.stroke = null; this.draw(); };
    canvas.onpointerleave = () => { tooltip.hidden = true; };
    canvas.onwheel = event => {
      const point = this.position(event);
      if (!this.inside(point)) return;
      event.preventDefault();
      this.zoom(event.deltaY < 0 ? 0.85 : 1.18, point);
    };
  }

  update(model) {
    if (this.model?.basis !== model.basis) this.view = null;
    this.model = model;
    this.draw();
  }

  position(event) {
    const box = this.canvas.getBoundingClientRect();
    return {x: event.clientX - box.x, y: event.clientY - box.y};
  }

  inside(point) {
    const box = this.plot;
    return box && point.x >= box.left && point.x <= box.right
      && point.y >= box.top && point.y <= box.bottom;
  }

  reset() {
    this.view = null;
    this.draw();
  }

  zoom(factor, point) {
    if (!this.view || !this.plot) return;
    const {left, right, bottom, top} = this.plot;
    const chartX = point ? (point.x - left) / (right - left) : 0.5;
    const chartY = point ? (bottom - point.y) / (bottom - top) : 0.5;
    const [x0, x1, y0, y1] = this.view;
    const dx = (x1 - x0) * (factor - 1);
    const dy = (y1 - y0) * (factor - 1);
    if ((x1 - x0) * factor < 0.001 || (x1 - x0) * factor > 1e4) return;
    this.view = [x0 - dx * chartX, x1 + dx * (1 - chartX),
      y0 - dy * chartY, y1 + dy * (1 - chartY)];
    this.draw();
  }

  dataBounds() {
    const {all, x, y} = this.model;
    const pad = values => {
      const min = Math.min(...values), max = Math.max(...values);
      const amount = Math.max((max - min) * 0.08, 0.25);
      return [min - amount, max + amount];
    };
    const axes = this.model.calibration;
    if (axes) {
      const both = pad(all.flatMap(row => [row[axes.measured], row[axes.prediction]]));
      return [...both, ...both];
    }
    return [...pad(all.map(row => row.scores[x])), ...pad(all.map(row => row.scores[y]))];
  }

  draw() {
    if (!this.model || !this.canvas.clientWidth || !this.canvas.clientHeight) return;
    const width = this.canvas.clientWidth, height = this.canvas.clientHeight;
    const ratio = window.devicePixelRatio || 1;
    if (this.canvas.width !== Math.round(width * ratio)
        || this.canvas.height !== Math.round(height * ratio)) {
      this.canvas.width = Math.round(width * ratio);
      this.canvas.height = Math.round(height * ratio);
    }
    const {ctx} = this;
    const style = getComputedStyle(this.canvas);
    const color = name => style.getPropertyValue("--" + name).trim();
    const {all, visible, selected, x, y, variance, colour, calibration} = this.model;
    const left = 58, right = width - 13, top = 14, bottom = height - 52;
    this.plot = {left, right, top, bottom};
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.fillStyle = color("surface");
    ctx.fillRect(0, 0, width, height);
    if (!all.length) {
      this.points = [];
      ctx.fillStyle = color("muted");
      ctx.font = "14px -apple-system, sans-serif";
      ctx.textAlign = "center";
      const message = calibration ? "Calculate Half " + calibration.half + " to see the calibration plot."
        : "No PCA scores are saved for this property.";
      ctx.fillText(message, width / 2, height / 2);
      return;
    }
    if (right - left < 100 || bottom - top < 60) return;
    this.view ??= this.dataBounds();
    const [x0, x1, y0, y1] = this.view;
    const toX = value => left + (value - x0) / (x1 - x0) * (right - left);
    const toY = value => bottom - (value - y0) / (y1 - y0) * (bottom - top);
    ctx.font = "12px -apple-system, sans-serif";
    ctx.strokeStyle = color("line");
    ctx.fillStyle = color("ink");
    ctx.lineWidth = 1;
    const rule = (a, b, c, d) => { ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); };

    ctx.textAlign = "center";
    for (const [value, label] of ticks(x0, x1)) {
      const px = toX(value);
      rule(px, top, px, bottom);
      ctx.fillText(label, px, bottom + 17);
    }
    ctx.textAlign = "right";
    for (const [value, label] of ticks(y0, y1, 7)) {
      const py = toY(value);
      rule(left, py, right, py);
      ctx.fillText(label, left - 8, py + 4);
    }
    ctx.strokeStyle = color("muted");
    ctx.strokeRect(left, top, right - left, bottom - top);
    ctx.textAlign = "center";
    ctx.font = "14px -apple-system, sans-serif";
    const axisLabel = component => "PC" + (component + 1) + " (" + variance[component].toFixed(2) + "%)";
    ctx.fillText(calibration?.xLabel ?? axisLabel(x), (left + right) / 2, height - 10);
    ctx.save();
    ctx.translate(17, (top + bottom) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(calibration?.yLabel ?? axisLabel(y), 0, 0);
    ctx.restore();

    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, right - left, bottom - top);
    ctx.clip();
    if (calibration) {
      ctx.strokeStyle = color("muted");
      ctx.setLineDash([5, 4]);
      const lo = Math.min(x0, y0), hi = Math.max(x1, y1);
      rule(toX(lo), toY(lo), toX(hi), toY(hi));
      ctx.setLineDash([]);
    }
    const groups = [...new Set(all.map(row => row.group))].sort((a, b) =>
      a.localeCompare(b, undefined, {numeric: true}));
    const treatment = new Map(groups.map((group, i) =>
      [group, PALETTE[i] ?? "hsl(" + ((i * 137.508) % 360) + " 47% 43%)"]));
    const lowReference = Math.min(...all.map(row => row.reference));
    const highReference = Math.max(...all.map(row => row.reference));
    const referenceColor = value => {
      const share = (value - lowReference) / (highReference - lowReference || 1);
      return "hsl(" + (192 - 146 * share) + " 55% 43%)";
    };
    this.points = visible.map(row => ({
      row, x: toX(calibration ? row[calibration.measured] : row.scores[x]),
      y: toY(calibration ? row[calibration.prediction] : row.scores[y]),
    })).filter(point => this.inside(point));
    const drawPoint = (point, highlighted) => {
      const {x: px, y: py, row} = point;
      const fill = colour === "Treatment" ? treatment.get(row.group)
        : colour === "Reference value" ? referenceColor(row.reference)
          : color(row.status === "Candidate" ? "candidate" : "retained");
      if (row.status === "Excluded") {
        ctx.strokeStyle = color("excluded");
        ctx.lineWidth = 1.8;
        rule(px - 4, py - 4, px + 4, py + 4);
        rule(px - 4, py + 4, px + 4, py - 4);
      } else {
        ctx.fillStyle = fill;
        ctx.beginPath();
        if (row.status === "Candidate") {
          ctx.moveTo(px, py - 4.5);
          ctx.lineTo(px + 4.5, py);
          ctx.lineTo(px, py + 4.5);
          ctx.lineTo(px - 4.5, py);
          ctx.closePath();
        } else {
          ctx.arc(px, py, highlighted ? 5 : 3.05, 0, 2 * Math.PI);
        }
        ctx.fill();
      }
      if (highlighted) {
        ctx.beginPath();
        ctx.arc(px, py, 5.8, 0, 2 * Math.PI);
        ctx.strokeStyle = color("marker");
        ctx.lineWidth = 1.9;
        ctx.stroke();
      }
    };
    for (const point of this.points) if (!selected.has(point.row.file)) drawPoint(point, false);
    for (const point of this.points) if (selected.has(point.row.file)) drawPoint(point, true);
    if (this.stroke) {
      const path = this.stroke.path;
      const first = path[0], last = path.at(-1);
      ctx.strokeStyle = color("accent");
      ctx.fillStyle = color("accent");
      ctx.lineWidth = 1.25;
      ctx.setLineDash([5, 3]);
      ctx.beginPath();
      if (this.stroke.mode === "box") ctx.rect(first.x, first.y, last.x - first.x, last.y - first.y);
      else {
        ctx.moveTo(first.x, first.y);
        for (const point of path.slice(1)) ctx.lineTo(point.x, point.y);
        ctx.closePath();
      }
      ctx.globalAlpha = 0.1;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.stroke();
    }
    ctx.restore();

    const labels = [["Retained", color("retained")], ["Excluded", color("excluded")], ["Selected", color("marker")]];
    if (colour === "Treatment") {
      const limit = Math.max(1, Math.floor((bottom - top - 52) / 18));
      const entries = [...treatment].map(([group, shade]) => ["Treatment " + group, shade]);
      const visible = entries.slice(0, limit);
      if (entries.length > limit) visible.push(["+" + (entries.length - limit) + " treatments", color("muted")]);
      labels.splice(0, 1, ...visible);
    } else if (colour === "Reference value") {
      labels.splice(0, 1, [lowReference.toFixed(2), referenceColor(lowReference)],
        [highReference.toFixed(2), referenceColor(highReference)]);
    }
    if (calibration) {
      if (colour === "Status") labels.splice(1, 0, ["Candidate", color("candidate")]);
      labels.push(["1:1 line", color("muted")]);
    }
    const labelX = left + 10, labelY = top + 10;
    ctx.fillStyle = color("panel");
    ctx.fillRect(labelX, labelY, 112, labels.length * 18 + 12);
    ctx.strokeStyle = color("edge");
    ctx.lineWidth = 1;
    ctx.strokeRect(labelX, labelY, 112, labels.length * 18 + 12);
    ctx.font = "12px -apple-system, sans-serif";
    ctx.textAlign = "left";
    for (const [index, [label, shade]] of labels.entries()) {
      const px = labelX + 12, py = labelY + index * 18 + 14;
      ctx.fillStyle = shade;
      ctx.strokeStyle = shade;
      if (label === "Excluded") {
        rule(px - 3, py - 3, px + 3, py + 3);
        rule(px - 3, py + 3, px + 3, py - 3);
      } else if (label === "Candidate") {
        ctx.beginPath();
        ctx.moveTo(px, py - 4); ctx.lineTo(px + 4, py); ctx.lineTo(px, py + 4);
        ctx.lineTo(px - 4, py); ctx.closePath(); ctx.fill();
      } else if (label === "1:1 line") {
        ctx.setLineDash([2, 2]); rule(px - 5, py, px + 5, py); ctx.setLineDash([]);
      } else {
        ctx.beginPath();
        ctx.arc(px, py, 3.4, 0, 2 * Math.PI);
        if (label === "Selected") ctx.stroke();
        else ctx.fill();
      }
      ctx.fillStyle = color("ink");
      ctx.fillText(label, px + 12, py + 4);
    }
    if (!visible.length) {
      ctx.textAlign = "center";
      ctx.fillText("No spectra match this view.", (left + right) / 2, (top + bottom) / 2);
    }
  }

  nearest(point) {
    let best = null, distance = 9;
    for (const item of this.points) {
      const separation = Math.hypot(item.x - point.x, item.y - point.y);
      if (separation < distance) {
        distance = separation;
        best = item.row;
      }
    }
    return best;
  }

  start(event) {
    const point = this.position(event);
    if (event.button !== 0 || !this.inside(point)) return;
    this.canvas.focus({preventScroll: true});
    if (this.model.mode === "point") {
      const row = this.nearest(point);
      this.pick(row ? [row.file] : [], !row);
      return;
    }
    this.canvas.setPointerCapture(event.pointerId);
    this.tooltip.hidden = true;
    if (this.model.mode === "pan") {
      this.pan = {point, view: [...this.view]};
      this.canvas.classList.add("dragging");
      return;
    }
    this.stroke = {mode: this.model.mode, path: [point, point]};
  }

  move(event) {
    const point = this.position(event);
    if (this.pan) {
      const [x0, x1, y0, y1] = this.pan.view;
      const {left, right, bottom, top} = this.plot;
      const dx = (this.pan.point.x - point.x) * (x1 - x0) / (right - left);
      const dy = (point.y - this.pan.point.y) * (y1 - y0) / (bottom - top);
      this.view = [x0 + dx, x1 + dx, y0 + dy, y1 + dy];
      this.draw();
      return;
    }
    if (this.stroke) {
      if (this.stroke.mode === "box") this.stroke.path[1] = point;
      else this.stroke.path.push(point);
      this.draw();
      return;
    }
    const row = this.inside(point) ? this.nearest(point) : null;
    this.tooltip.hidden = !row;
    if (row) {
      const {x, y, calibration} = this.model;
      const values = calibration
        ? "\nMeasured " + row[calibration.measured].toPrecision(4) + " · Fit "
          + row[calibration.prediction].toPrecision(4) + "\nStudentised residual " + row.studentised.toPrecision(4)
        : "\nPC" + (x + 1) + " " + row.scores[x].toFixed(3) + "  ·  PC"
          + (y + 1) + " " + row.scores[y].toFixed(3)
          + (row.neighbor ? "\nNearest " + row.neighbor + " · distance " + row.distance : "");
      this.tooltip.textContent = row.sample + "  ·  " + row.file + "\nGroup " + row.group
        + "  ·  Reference " + row.reference + values
        + (row.decision_stage ? "\nExcluded in " + row.decision_stage : "");
      this.tooltip.style.left = Math.max(0, Math.min(point.x + 12, this.canvas.clientWidth - 170)) + "px";
      this.tooltip.style.top = Math.max(0, point.y - 64) + "px";
    }
  }

  stopPan() {
    this.pan = null;
    this.canvas.classList.remove("dragging");
  }

  end(event) {
    if (this.pan) this.stopPan();
    if (!this.stroke) return;
    const {path, mode} = this.stroke;
    const first = path[0], last = this.position(event);
    this.stroke = null;
    const width = Math.abs(last.x - first.x), height = Math.abs(last.y - first.y);
    if (mode === "box" && (width < 4 || height < 4)) {
      this.draw();
      return;
    }
    path.push(last);
    const group = this.points.filter(point => mode === "lasso" ? polygonIncludes(path, point) :
      point.x >= Math.min(first.x, last.x) && point.x <= Math.max(first.x, last.x)
      && point.y >= Math.min(first.y, last.y) && point.y <= Math.max(first.y, last.y));
    this.pick(group.map(point => point.row.file), false);
  }
}
