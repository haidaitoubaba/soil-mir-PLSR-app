const REVIEW_COLUMNS = [
  ["sample", "Sample"], ["file", "File Name"], ["group", "Group"],
  ["reference", "Reference Value"], ["status", "Status"], ["neighbor", "Nearest File"],
  ["distance", "Nearest Distance"], ["same_sample", "Same Sample Neighbour"],
];
const CALIBRATION_COLUMNS = [
  ...REVIEW_COLUMNS.slice(0, 5),
  ["prediction", "Calibration Prediction"], ["transformed_reference", "Transformed Reference"],
  ["transformed_prediction", "Transformed Prediction"], ["residual", "Transformed Residual"],
  ["studentised", "Studentised Residual"], ["leverage", "Leverage"],
  ["candidate", "Concentration Candidate"], ["diagnostic_rank", "Diagnostic Rank"],
];
const FULL_COLUMNS = [
  ...REVIEW_COLUMNS.slice(0, 5),
  ["half", "Half"], ["decision_stage", "Exclusion stage"], ["reason", "Reason"], ["comment", "Comment"],
];

function makeList(list, values) {
  list.replaceChildren(...values.map(value => {
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }));
  list.hidden = values.length === 0;
}

function plural(count, one, many) {
  return count + " " + (count === 1 ? one : many);
}

function conciseNumber(value) {
  return Number.isFinite(value) ? String(Number(value.toPrecision(4))) : "N/A";
}

function calibrationMetrics(rows, axes) {
  const n = rows.length;
  if (!n) return "";
  const measured = rows.map(row => row[axes.measured]);
  const mean = measured.reduce((sum, value) => sum + value, 0) / n;
  const sst = measured.reduce((sum, value) => sum + (value - mean) ** 2, 0);
  const sse = rows.reduce((sum, row) => sum + (row[axes.measured] - row[axes.prediction]) ** 2, 0);
  const rmse = Math.sqrt(sse / n);
  measured.sort((a, b) => a - b);
  const percentile = fraction => {
    const i = (n - 1) * fraction, low = Math.floor(i), high = Math.ceil(i);
    return measured[low] + (i - low) * (measured[high] - measured[low]);
  };
  const values = [
    ["R²", n > 1 && sst > 0 ? 1 - sse / sst : NaN], ["RMSE", rmse],
    ["RPD", n > 1 && rmse > 0 ? Math.sqrt(sst / (n - 1)) / rmse : NaN],
    ["RPIQ", rmse > 0 ? (percentile(.75) - percentile(.25)) / rmse : NaN],
  ];
  return "Calibration · displayed spectra (n=" + n + ")  ·  "
    + values.map(([label, value]) => label + " = " + conciseNumber(value)).join("  |  ");
}

class Workbench {
  constructor(root) {
    this.root = root;
    this.el = id => root.querySelector("#" + id);
    this.tab = "plot";
    this.stage = "PCA";
    this.selected = new Set();
    this.sort = {column: "file", ascending: true};
    this.media = matchMedia("(prefers-color-scheme: dark)");
    this.chart = new PcaChart(this.el("pca-chart"), this.el("tooltip"),
      (files, clear) => this.toggleSelection(files, clear));
    this.bind();
    this.newSession = new NewSession(this);
    this.autoCleanup = new AutoCleanup(this);
  }

  bind() {
    const click = (id, handler) => { this.el(id).onclick = handler; };
    click("stage-pca", () => this.showStage("PCA"));
    click("stage-a", () => this.showStage("A"));
    click("stage-b", () => this.showStage("B"));
    click("stage-export", () => this.showStage("Export"));
    click("open-export-folder", () => this.send({kind: "open-export-folder"}));
    click("use-in-plsr", () => {
      if (this.data.exportOverview.handoff?.needsPath) this.sessionDialog("use-in-plsr");
      else this.send({kind: "use-in-plsr"});
    });
    for (const id of ["export-review", "export-cleaned", "locate-workbook"]) {
      click(id, () => this.sessionDialog(id));
    }
    for (const button of this.root.querySelectorAll("[data-tab]")) {
      button.onclick = () => this.showTab(button.dataset.tab);
    }
    click("settings-button", () => {
      const settings = this.el("settings");
      settings.hidden = !settings.hidden;
      this.el("settings-button").setAttribute("aria-expanded", String(!settings.hidden));
    });
    const appearance = this.el("appearance");
    appearance.value = localStorage.getItem("mir-cleanup-pca-theme") || "light";
    const theme = () => {
      this.root.dataset.theme = appearance.value === "system"
        ? (this.media.matches ? "night" : "light") : appearance.value;
      this.chart.draw();
    };
    appearance.onchange = () => {
      localStorage.setItem("mir-cleanup-pca-theme", appearance.value);
      theme();
    };
    this.media.addEventListener("change", theme);
    theme();

    for (const id of ["pc-x", "pc-y", "scale", "colour", "subset", "mode"]) {
      this.el(id).onchange = () => this.refreshView();
    }
    for (const id of ["home", "reset-view"]) click(id, () => this.chart.reset());
    click("zoom-in", () => this.chart.zoom(0.8));
    click("zoom-out", () => this.chart.zoom(1.25));
    click("open-offline", () => this.requestOffline(true));
    click("save-offline", () => this.requestOffline(false));
    click("save-plot", () => {
      this.showTab("plot");
      const anchor = document.createElement("a");
      anchor.href = this.chart.canvas.toDataURL("image/png");
      anchor.download = this.property + (this.stage === "PCA" ? "-PCA.png" : "-Half-" + this.stage + ".png");
      anchor.click();
    });
    for (const id of ["clear-plot", "clear-table"]) click(id, () => this.toggleSelection([], true));
    this.el("filter").oninput = () => this.refreshView();
    click("reset-filters", () => {
      this.el("filter").value = "";
      this.el("subset").selectedIndex = 0;
      this.refreshView();
    });
    this.el("unit").onchange = () => this.renderSelection();
    for (const id of ["open-desktop", "start-open-session"]) {
      click(id, () => this.sessionDialog("open-desktop"));
    }
    click("save-copy", () => this.sessionDialog("save-copy"));
    click("session-browse", () => {
      if (this.busy) return;
      this.setSessionPickerState(true, "Choose session.json in the system picker…");
      this.send({kind: "browse-desktop"});
    });
    this.el("session-dialog").addEventListener("cancel", event => {
      if (this.el("session-browse").disabled) event.preventDefault();
    });
    this.el("session-dialog").addEventListener("close", () => {
      if (this.el("session-dialog").returnValue !== "confirm") return;
      const path = this.el("session-path").value.trim();
      if (this.sessionAction === "open-desktop") this.lastOpenPath = path;
      this.send({kind: this.sessionAction, path});
    });
    window.addEventListener("beforeunload", event => {
      if (!this.root.isConnected || !this.data?.dirtyDraft) return;
      event.preventDefault();
      event.returnValue = true;
    });
    click("exclude", () => this.confirm("exclude"));
    click("restore", () => this.confirm("restore"));
    click("undo", () => this.send({kind: "undo"}));
    click("refit", () => this.send({kind: this.stage === "PCA" ? "refit" : "calculate-" + this.stage.toLowerCase()}));
    click("finish", () => this.send({kind: this.stage === "PCA" ? "finish" : "finish-" + this.stage.toLowerCase()}));
    this.el("confirm").addEventListener("close", () => {
      const action = this.pending;
      this.pending = null;
      if (this.el("confirm").returnValue === "confirm" && action) this.send(action);
    });
    this.root.addEventListener("keydown", event => {
      if (event.key === "Escape" && !this.el("confirm").open
          && this.root.querySelector(".plot-panel:focus-within, .table-panel:focus-within")) {
        this.toggleSelection([], true);
      }
    });
    for (const button of this.root.querySelectorAll(".menu-pop button")) {
      button.addEventListener("click", () => button.closest("details").open = false);
    }
    for (const handle of this.root.querySelectorAll(".split")) this.bindDivider(handle);
  }

  bindDivider(handle) {
    const side = handle.dataset.side;
    const direction = side === "left" ? 1 : -1;
    const width = () => handle.parentElement.querySelector(side === "left" ? ".properties" : ".selection")
      .getBoundingClientRect().width;
    const resize = value => {
      const minimum = side === "left" ? 135 : 195;
      const other = handle.parentElement.querySelector(side === "left" ? ".selection" : ".properties");
      const maximum = Math.max(minimum, this.root.clientWidth - other.clientWidth - 390);
      const next = Math.round(Math.max(minimum, Math.min(maximum, value)));
      this.root.style.setProperty("--" + side, next + "px");
      handle.setAttribute("aria-valuenow", String(next));
    };
    let origin = null;
    handle.onpointerdown = event => {
      origin = {x: event.clientX, width: width()};
      handle.setPointerCapture(event.pointerId);
    };
    handle.onpointermove = event => {
      if (origin) resize(origin.width + direction * (event.clientX - origin.x));
    };
    handle.onlostpointercapture = () => { origin = null; };
    handle.onkeydown = event => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      resize(width() + direction * (event.key === "ArrowRight" ? 12 : -12));
    };
  }

  update(data, sendEvent) {
    const switchingSession = this.openRevision !== data.openRevision;
    this.data = data;
    this.sendEvent = sendEvent;
    this.busy = false;
    this.openRevision = data.openRevision;
    const hasSession = data.mode === "desktop";
    this.el("session-name").textContent = data.sessionLabel ?? "No session open";
    this.el("session-name").title = data.source ?? "";
    this.el("save-copy").hidden = !hasSession;
    this.el("save-copy").disabled = false;
    this.el("export-review").hidden = !hasSession;
    this.el("export-review").disabled = false;
    this.el("welcome").hidden = hasSession;
    this.el("review-columns").hidden = !hasSession;
    this.el("review-footer").hidden = !hasSession;
    if (hasSession) {
      this.updateReview(data, switchingSession);
    } else {
      const status = this.el("welcome-status");
      status.textContent = data.notice?.message ?? "";
      status.classList.toggle("error", Boolean(data.notice?.error));
    }
    this.finishOffline(data);
    if (data.desktopPick) {
      const {path, error} = data.desktopPick;
      if (path) this.el("session-path").value = path;
      this.setSessionPickerState(false, error, Boolean(error));
      this.el(path ? "session-dialog-action" : "session-browse").focus();
    }
    this.newSession.update(data);
    this.autoCleanup.update(data);
  }

  updateReview(data, switchingSession) {
    const nextProperty = data.activeProperty;
    const switchingProperty = this.property !== nextProperty;
    this.property = nextProperty;
    const navigation = data.reviewNavigation;
    const advance = navigation?.property === nextProperty && this.stageAllowed(navigation.stage);
    const oldStage = this.stage;
    if (switchingSession || switchingProperty || advance) {
      this.stage = advance ? navigation.stage : this.savedStage();
      this.resetPropertyView();
      if (advance && navigation.automatic && this.current.rows.some(row =>
        row.automatic && row.decision_stage === this.stage)) {
        this.el("subset").value = "automatic";
        this.el("settings").hidden = false;
        this.el("settings-button").setAttribute("aria-expanded", "true");
      }
    } else if (!this.stageAllowed(this.stage)) {
      this.stage = this.savedStage();
      this.resetPropertyView();
    }
    this.drawProperties();
    const openPlot = switchingSession || advance || oldStage !== this.stage;
    if (openPlot) this.tab = "plot";
    this.refreshView();
    if (openPlot) this.showTab("plot");
  }

  requestOffline(open) {
    if (this.busy) return;
    let popup = null;
    if (open) {
      popup = window.open("about:blank", "_blank");
      if (!popup) {
        this.el("status").textContent = "The browser blocked the new tab. Use Save offline PCA HTML.";
        return;
      }
      popup.opener = null;
      popup.document.title = "MIR PCA Explorer";
      popup.document.body.textContent = "Preparing the offline PCA plot…";
    }
    this.offlineCounter = (this.offlineCounter ?? 0) + 1;
    const requestId = this.offlineCounter;
    this.offlineRequest = {popup, requestId};
    this.send({kind: "offline-viewer", requestId});
  }

  finishOffline(data) {
    if (!this.offlineRequest) return;
    const {popup, requestId} = this.offlineRequest;
    const result = data.offlineDocument;
    if (requestId !== result?.requestId) {
      if (data.notice?.error) {
        this.offlineRequest = null;
        if (popup && !popup.closed) popup.close();
      }
      return;
    }
    this.offlineRequest = null;
    const url = URL.createObjectURL(new Blob([result.html], {type: "text/html;charset=utf-8"}));
    if (popup) {
      if (!popup.closed) popup.location.replace(url);
    } else {
      const link = document.createElement("a");
      link.download = "PCA_viewer.html";
      link.href = url;
      document.body.append(link);
      link.click();
      link.remove();
    }
    // Leave the Blob available until the new tab has received its document.
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  resetPropertyView() {
    this.selected.clear();
    for (const id of ["filter", "reason", "comment"]) this.el(id).value = "";
    this.el("subset").selectedIndex = 0;
    this.el("unit").value = this.stage === "PCA" ? "spectrum" : "sample";
    this.el("scale").value = "model";
    this.sort = {column: "file", ascending: true};
  }

  stageAllowed(stage) {
    if (stage === "Export") return Boolean(this.data.exportOverview);
    return stage === "PCA" || Boolean(this.current["half" + stage + "State"]);
  }

  savedStage() {
    if (this.data.exportOverview?.ready) return "Export";
    if (this.stageAllowed("B")) return "B";
    return this.stageAllowed("A") ? "A" : "PCA";
  }

  showStage(stage) {
    if (this.busy || this.stage === stage || !this.stageAllowed(stage)) return;
    this.stage = stage;
    this.resetPropertyView();
    this.data.notice = null;
    this.tab = "plot";
    this.refreshView();
    this.showTab("plot");
  }

  sessionDialog(kind) {
    if (this.busy) return;
    this.sessionAction = kind;
    const overview = this.data.exportOverview;
    const options = {
      "open-desktop": ["Open desktop session",
        "Browse for session.json, or paste the path to it or its saved Cleanup session folder. Keep the saved spectra files in the same folder."
          + (this.data.dirtyDraft ? " Opening another session discards the unsaved review edits." : ""),
        this.lastOpenPath ?? "", "Open"],
      "save-copy": ["Save Cleanup review copy",
        "Choose a new folder in an existing location. The original session and previous copies are kept.",
        this.data.suggestedCopy, "Save copy"],
      "export-cleaned": ["Export cleaned dataset",
        "Choose an existing local folder. The export will create a new dated directory inside it.",
        overview?.parent, "Export"],
      "use-in-plsr": ["Use in PLSR",
        "Enter the original OPUS spectra directory for this Cleanup session.",
        overview?.handoff?.path, "Continue to Modeling Data"],
      "export-review": ["Export review Excel",
        "Enter a new .xlsx path for a snapshot of the current review and saved diagnostics.",
        overview?.reviewPath, "Export review"],
      "locate-workbook": ["Locate original reference workbook",
        "Enter the path to the original Excel file. Cleanup will verify it against the session fingerprint.",
        overview?.source, "Verify workbook"],
    };
    const [title, help, path, button] = options[kind];
    this.el("session-dialog-title").textContent = title;
    this.el("session-dialog-help").textContent = help;
    this.el("session-path").value = path ?? "";
    this.el("session-browse").hidden = kind !== "open-desktop";
    this.setSessionPickerState(false);
    this.el("session-dialog-action").textContent = button;
    this.el("session-dialog").returnValue = "";
    this.el("session-dialog").showModal();
    this.el("session-path").select();
  }

  setSessionPickerState(pending, message = "", error = false) {
    for (const id of ["session-browse", "session-dialog-action", "session-dialog-cancel"]) {
      this.el(id).disabled = pending;
    }
    this.el("session-path").readOnly = pending;
    const status = this.el("session-browse-status");
    status.hidden = !message;
    status.textContent = message;
    status.classList.toggle("error", error);
  }

  get current() {
    return this.data.properties[this.property];
  }

  drawProperties() {
    const container = this.el("properties");
    const names = this.data.propertyNames ?? Object.keys(this.data.properties);
    const existing = [...container.children];
    if (existing.length !== names.length || !existing.every((button, i) => button.dataset.property === names[i])) {
      container.replaceChildren(...names.map(name => this.createPropertyButton(name)));
    }
    for (const button of container.children) {
      const active = button.dataset.property === this.property;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      button.lastElementChild.textContent = this.data.propertyStates?.[button.dataset.property] ?? "";
    }
  }

  createPropertyButton(name) {
    const button = document.createElement("button");
    button.setAttribute("aria-label", name);
    button.dataset.property = name;
    const title = document.createElement("span");
    title.textContent = name;
    const phase = document.createElement("small");
    phase.className = "property-phase";
    button.append(title, phase);
    button.onclick = () => {
      if (name !== this.property && !this.busy) this.send({kind: "select-property", name});
    };
    return button;
  }

  showTab(tab) {
    if (this.stage === "Export") return;
    this.tab = tab;
    this.el("plot-panel").hidden = tab !== "plot";
    this.el("table-panel").hidden = tab === "plot";
    this.el("clear-table").hidden = tab === "full";
    for (const button of this.root.querySelectorAll("[data-tab]")) {
      const active = button.dataset.tab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
    this.renderTable();
    this.renderSelection();
    this.chart.draw();
  }

  showStageButtons() {
    for (const stage of ["PCA", "A", "B", "Export"]) {
      const button = this.el("stage-" + stage.toLowerCase());
      const active = stage === this.stage;
      button.classList.toggle("active", active);
      button.disabled = !this.stageAllowed(stage);
      if (active) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    }
    this.el("stage-export").hidden = !this.stageAllowed("Export");
  }

  renderExport() {
    const overview = this.data.exportOverview;
    const rows = overview.rows.map(item => {
      const row = document.createElement("tr");
      for (const key of ["property", "status", "total", "retained", "excluded", "affectedSamples"]) {
        const cell = document.createElement("td");
        cell.textContent = item[key];
        row.append(cell);
      }
      return row;
    });
    this.el("export-rows").replaceChildren(...rows);
    this.el("export-workbook-path").textContent = overview.source;
    this.el("export-workbook-status").textContent = overview.sourceError || "SHA-256 verified";
    this.el("export-workbook-status").classList.toggle("error", Boolean(overview.sourceError));
    this.el("export-intro").textContent = overview.ready
      ? "Every selected property is ready to export."
      : "Complete the remaining reviews and verify the original workbook to enable the export.";
    this.el("latest-export").hidden = !overview.lastExport;
    this.el("latest-export-path").textContent = overview.lastExport ? "Last export · " + overview.lastExport : "";
    this.el("open-export-folder").disabled = !overview.lastExport;
    const canHandoff = Boolean(overview.handoff);
    this.el("export-cleaned").disabled = !overview.ready;
    this.el("export-cleaned").classList.toggle("primary", !canHandoff);
    this.el("use-in-plsr").hidden = !canHandoff;
    this.el("use-in-plsr").disabled = Boolean(this.data.autoProgress || this.data.importProgress);
    this.el("unsaved").hidden = !this.data.dirtyDraft;
    const status = this.el("status");
    status.textContent = this.data.notice?.message || (overview.ready ? "Ready to export" : "Export is pending");
    status.classList.toggle("error", Boolean(this.data.notice?.error));
  }

  refreshView() {
    const exporting = this.stage === "Export";
    this.showStageButtons();
    this.el("export-panel").hidden = !exporting;
    this.el("export-inspector").hidden = !exporting;
    this.el("review-inspector").hidden = exporting;
    this.root.querySelector(".page-heading .tools").hidden = exporting;
    this.root.querySelector(".tabs").hidden = exporting;
    for (const id of ["undo", "refit", "finish"]) this.el(id).hidden = exporting;
    this.el("export-cleaned").hidden = !exporting;
    if (exporting) {
      this.el("stage-title").textContent = "Export overview";
      this.el("property-title").textContent = "Session";
      for (const id of ["plot-panel", "table-panel", "settings", "split-summary"]) this.el(id).hidden = true;
      this.el("settings-button").setAttribute("aria-expanded", "false");
      this.renderExport();
      return;
    }
    const {rows, variance, round, dirty, split, undo, undoStage, calibrations} = this.current;
    const isHalf = this.stage !== "PCA";
    const calibration = calibrations?.[this.stage];
    const halfLabel = "Half " + this.stage;
    this.el("property-title").textContent = this.property;
    this.el("stage-title").textContent = isHalf ? halfLabel + " review" : "PCA review";
    this.el("pc-x-field").hidden = isHalf;
    this.el("pc-y-field").hidden = isHalf;
    this.el("scale-field").hidden = !isHalf;
    this.el("reason-concentration").hidden = !isHalf;
    this.el("reason-concentration").disabled = !isHalf;
    this.el("pca-chart").setAttribute("aria-label", (isHalf ? halfLabel + " calibration" : "PCA score")
      + " scatter plot. Use the Data sheet for keyboard selection.");

    for (const [id, defaultIndex] of [["pc-x", 0], ["pc-y", 1]]) {
      const select = this.el(id);
      const active = Number(select.value || defaultIndex);
      select.replaceChildren(...variance.map((value, index) =>
        new Option("PC" + (index + 1) + " (" + value.toFixed(2) + "%)", String(index))));
      select.value = String(Math.min(active, variance.length - 1));
      select.disabled = variance.length < 2;
    }
    const x = Number(this.el("pc-x").value), y = Number(this.el("pc-y").value);
    const originalScale = this.el("scale").value === "original";
    const units = originalScale ? calibration?.units : (calibration?.transform || "none") + " scale";
    const suffix = units ? " (" + units + ")" : "";
    const axes = isHalf ? {
      half: this.stage,
      measured: originalScale ? "reference" : "transformed_reference",
      prediction: originalScale ? "prediction" : "transformed_prediction",
      xLabel: "Measured" + suffix, yLabel: "Calibration fit" + suffix,
    } : null;
    this.fitted = isHalf
      ? rows.filter(row => row.half === this.stage && Number.isFinite(row.prediction)).map(row => ({
        ...row, status: row.status === "Excluded" ? "Excluded" : row.candidate ? "Candidate" : "Retained",
      }))
      : rows.filter(row => row.scores);
    const subsetControl = this.el("subset");
    const autoOption = subsetControl.querySelector('[value="automatic"]');
    autoOption.hidden = !this.fitted.some(row => row.automatic
      && (!isHalf || row.decision_stage === this.stage));
    if (autoOption.hidden && subsetControl.value === "automatic") subsetControl.value = "all";
    const subset = subsetControl.value;
    const filter = this.el("filter").value.trim().toLowerCase();
    this.el("reset-filters").disabled = !filter && subset === "all";
    this.matches = row => !filter || [row.sample, row.file, row.group, row.status, row.neighbor, row.reason]
      .some(value => String(value ?? "").toLowerCase().includes(filter));
    this.visible = this.fitted.filter(row => this.matches(row)
      && (subset === "all" || (subset === "automatic" ? row.automatic
        : (row.status === "Excluded") === (subset === "excluded"))));
    const allowed = new Set(this.visible.map(row => row.file));
    this.selected = new Set([...this.selected].filter(name => allowed.has(name)));
    this.chart.update({
      basis: [this.property, this.stage, x, y, round, isHalf && originalScale, this.fitted.map(row => row.file).join(",")].join("/"),
      all: this.fitted, visible: this.visible, selected: this.selected, x, y, variance,
      colour: this.el("colour").value, mode: this.el("mode").value, calibration: axes,
    });
    const metrics = this.el("calibration-metrics");
    metrics.hidden = !axes || !this.visible.length;
    metrics.textContent = axes ? calibrationMetrics(this.visible, axes) : "";
    this.el("undo").disabled = !undo || (undoStage ?? "PCA") !== this.stage;
    this.el("refit").textContent = isHalf ? "Calculate " + halfLabel : "Refit PCA";
    this.el("refit").disabled = isHalf ? Boolean(calibration) : !dirty || round >= 3;
    this.el("finish").textContent = isHalf ? "Finish " + halfLabel + " review" : "Finish PCA review / split";
    this.el("finish").disabled = isHalf ? !calibration || calibration.finished : !variance.length || dirty || Boolean(split[0]);
    this.renderTable();
    this.renderSelection();
    this.renderStatus();
  }

  toggleSelection(files, clear = false) {
    if (clear) this.selected.clear();
    for (const name of files) {
      if (this.selected.has(name)) this.selected.delete(name);
      else this.selected.add(name);
    }
    this.chart.draw();
    for (const input of this.el("table-body").querySelectorAll("input[data-file]")) {
      input.checked = this.selected.has(input.dataset.file);
      input.closest("tr").classList.toggle("selected", input.checked);
    }
    this.renderSelection();
  }

  renderTable() {
    if (!this.current || this.tab === "plot") return;
    const full = this.tab === "full";
    const columns = full
      ? (this.stage !== "PCA" ? [...FULL_COLUMNS, ["prediction", "Calibration Prediction"],
        ["diagnostic_rank", "Diagnostic Rank"]] : FULL_COLUMNS)
      : this.stage !== "PCA" ? CALIBRATION_COLUMNS : REVIEW_COLUMNS;
    const records = full ? this.current.rows.filter(this.matches) : this.visible;
    const header = document.createElement("tr");
    if (!full) {
      const check = document.createElement("th");
      check.setAttribute("aria-label", "Selected");
      header.append(check);
    }
    for (const [key, label] of columns) {
      const cell = document.createElement("th");
      cell.scope = "col";
      const title = document.createElement("button");
      title.textContent = label;
      if (this.sort.column === key) cell.setAttribute("aria-sort", this.sort.ascending ? "ascending" : "descending");
      title.onclick = () => {
        this.sort = {column: key, ascending: this.sort.column === key ? !this.sort.ascending : true};
        this.renderTable();
        this.el("table-head").querySelector('[aria-sort] > button')?.focus();
      };
      cell.append(title);
      header.append(cell);
    }
    this.el("table-head").replaceChildren(header);
    const {column, ascending} = this.sort;
    const ordered = [...records].sort((a, b) => {
      const av = a[column] ?? "", bv = b[column] ?? "";
      const order = typeof av === "number" && typeof bv === "number" ? av - bv
        : String(av).localeCompare(String(bv), undefined, {numeric: true});
      return ascending ? order : -order;
    });
    const body = document.createDocumentFragment();
    for (const row of ordered) {
      const tr = document.createElement("tr");
      if (!full) {
        const cell = document.createElement("td");
        const check = document.createElement("input");
        check.type = "checkbox";
        check.dataset.file = row.file;
        check.setAttribute("aria-label", "Select " + row.file);
        check.checked = this.selected.has(row.file);
        tr.classList.toggle("selected", check.checked);
        check.onchange = () => this.toggleSelection([row.file]);
        tr.onclick = event => {
          if (event.target !== check) this.toggleSelection([row.file]);
        };
        cell.append(check);
        tr.append(cell);
      }
      for (const [key] of columns) {
        const cell = document.createElement("td");
        const value = row[key];
        cell.textContent = typeof value === "boolean" ? (value ? "Yes" : "No")
          : typeof value === "number" && this.stage !== "PCA" ? conciseNumber(value) : (value ?? "");
        if (key === "status") {
          cell.dataset.status = value;
          if (value === "Excluded" && row.automatic) cell.textContent = "Auto-excluded";
        }
        tr.append(cell);
      }
      body.append(tr);
    }
    this.el("table-body").replaceChildren(body);
    this.el("table-count").textContent = plural(ordered.length, "record", "records");
  }

  affected() {
    const rows = this.current.rows;
    const picked = rows.filter(row => this.selected.has(row.file));
    const samples = new Set(picked.map(row => row.sample));
    const expanded = this.el("unit").value === "sample" ? rows.filter(row => samples.has(row.sample)) : picked;
    return this.stage === "PCA" ? expanded : expanded.filter(row => row.decision_stage !== "PCA");
  }

  renderSelection() {
    const full = this.tab === "full";
    const count = this.selected.size;
    const rows = !full ? this.affected() : [];
    const sampleCount = new Set(rows.map(row => row.sample)).size;
    this.el("selection-count").textContent = full ? "Full dataset is read-only."
      : count ? plural(count, "spectrum", "spectra") + " selected"
        : plural(this.visible.length, "spectrum", "spectra") + " visible";
    this.el("impact").textContent = rows.length ? plural(sampleCount, "sample", "samples") + " · "
      + plural(rows.length, "spectrum", "spectra") : "";
    makeList(this.el("selected-files"), rows.map(row => row.file));
    const autoSamples = new Set(rows.filter(row => row.automatic && row.decision_stage === this.stage).map(row => row.sample));
    const triggers = this.fitted.filter(row => row.candidate && autoSamples.has(row.sample));
    this.el("automatic-selection").hidden = !autoSamples.size;
    makeList(this.el("automatic-triggers"), triggers.map(row => row.file));
    this.el("decision").hidden = full || !rows.length;
    const locked = this.busy || (this.stage === "PCA" && this.current.round >= 3);
    this.el("exclude").disabled = locked || !rows.some(row => this.stage !== "PCA" || row.decision_stage !== "PCA");
    this.el("restore").disabled = locked || !rows.some(row => row.decision_stage === this.stage);
  }

  renderStatus() {
    const {round, dirty, rows, split, calibrations} = this.current;
    const notice = this.data.notice;
    const isHalf = this.stage !== "PCA";
    const isB = this.stage === "B";
    const calibration = calibrations?.[this.stage];
    const halfLabel = "Half " + this.stage;
    const state = dirty ? "Previous PCA basis · refit required" : "Current PCA basis";
    const excluded = rows.filter(row => row.decision_stage === "PCA").length;
    let label = "PCA fit " + round + " / 3" + (dirty ? " · Refit required" : "");
    let details = "PCA fit " + round + " / 3\n" + state
      + "\n" + plural(excluded, "excluded spectrum", "excluded spectra");

    if (isHalf) {
      label = calibration?.finished ? halfLabel + " review complete" : calibration
        ? halfLabel + " ready for review" : halfLabel + " ready to calculate";
      details = "Calculate " + halfLabel + " using the saved sample split.";
      if (isB && !calibration && calibrations?.A) {
        details += "\nPreprocessing from Half A  " + calibrations.A.preprocessing
          + "\nSelected rank from Half A  " + calibrations.A.selectionRank;
      }
      if (calibration) {
        const {limit} = calibration;
        details = [
          "Preprocessing  " + calibration.preprocessing,
          "Selected rank  " + calibration.selectionRank,
          "Diagnostic rank  " + calibration.diagnosticRank,
          "Transform  " + (calibration.transform || "none"),
          isB ? "Uses Half A preprocessing and selected rank." : "",
          "Opposite-half RMSEP (original units)  " + conciseNumber(calibration.rmsep),
          "Candidate threshold  |studentised residual| > 2.5",
          calibration.diagnosticRank < 15 ? "Diagnostic rank reduced to match the available spectral rank." : "",
          "Exclusions mark the original fit.",
          limit.enabled ? "Concentration limit  " + limit.used + " / " + limit.cap + " samples (" + limit.percent + "%)"
            : "Concentration limit disabled",
        ].filter(line => line !== "").join("\n");
      }
    }
    this.el("model").textContent = details;
    this.el("unsaved").hidden = !this.data.dirtyDraft;
    const status = this.el("status");
    status.textContent = label + (notice ? " · " + notice.message
      : this.data.savedCopy && !this.data.dirtyDraft ? " · Saved copy: " + this.data.savedCopy : "");
    status.classList.toggle("error", Boolean(notice?.error));
    const summary = this.el("split-summary");
    summary.hidden = isHalf ? Boolean(calibration) && !calibration.finished : !split[0];
    const splitLabel = "Half A: " + split[0] + " samples  ·  Half B: " + split[1] + " samples";
    summary.textContent = isHalf && calibration?.finished
      ? halfLabel + " review complete. Save a copy to keep the review."
      : (isB ? "Half A review complete  ·  " : "PCA review complete  ·  ") + splitLabel;
  }

  confirm(kind) {
    const dialog = this.el("confirm");
    dialog.returnValue = "";
    const files = this.affected().filter(row =>
      kind === "exclude" ? this.stage !== "PCA" || row.decision_stage !== "PCA" : row.decision_stage === this.stage);
    if (!files.length) return;
    const verb = kind === "restore" ? "Restore" : "Exclude";
    this.el("confirm-title").textContent = kind === "restore" ? "Confirm restoration" : "Confirm exclusion";
    this.el("confirm-summary").textContent = verb + " " + plural(files.length, "spectrum", "spectra") + " from "
      + plural(new Set(files.map(row => row.sample)).size, "sample", "samples") + " in " + this.property + "?";
    makeList(this.el("confirm-files"), files.map(row => row.file));
    let note;
    if (this.stage === "A") {
      note = "PCA exclusions stay in effect. Half A will need review again; its diagnostic fit is retained.";
      if (this.current.calibrations?.B) note += " Existing Half B work moves to the archive.";
    } else if (this.stage === "B") {
      note = "Half B will need review again. The current diagnostic fit and prior PCA and Half A decisions are retained.";
    } else {
      note = this.current.hasDownstream
        ? "Changing this decision archives existing A/B work in the draft and requires a PCA refit."
        : "Changing this decision requires a PCA refit.";
    }
    this.el("confirm-note").textContent = note;
    this.el("confirm-action").textContent = verb;
    this.pending = {
      kind, files: [...this.selected], unit: this.el("unit").value,
      reason: this.el("reason").value, comment: this.el("comment").value,
    };
    dialog.showModal();
  }

  send(action) {
    if (this.busy) return;
    this.busy = true;
    const loading = {refit: "Refitting PCA…", "open-desktop": "Opening desktop session…",
      "select-property": "Loading property…", "save-copy": "Saving independent copy…",
      "offline-viewer": "Preparing offline PCA…", "calculate-a": "Calculating Half A…",
      "calculate-b": "Calculating Half B…", "export-cleaned": "Generating and verifying the dataset…",
      "export-review": "Exporting review Excel…", "locate-workbook": "Verifying the original workbook…",
      "open-export-folder": "Opening the export folder…", "use-in-plsr": "Verifying the export…"};
    if (action.kind !== "browse-desktop" && !action.kind.startsWith("new-") && !action.kind.startsWith("auto-")) {
      const status = this.el(this.data.mode === "desktop" ? "status" : "welcome-status");
      status.textContent = loading[action.kind] ?? "Updating review…";
      status.classList.remove("error");
    }
    for (const id of ["undo", "refit", "finish", "exclude", "restore", "save-copy",
      "export-review", "export-cleaned", "use-in-plsr", "open-export-folder"]) {
      this.el(id).disabled = true;
    }
    this.sendEvent("action", {...action, stage: this.stage, property: this.property, revision: this.data.revision});
  }
}

export default function ({parentElement, data, setTriggerValue}) {
  const root = parentElement.querySelector(".mir");
  root.workbench ??= new Workbench(root);
  root.workbench.update(data, setTriggerValue);
}
