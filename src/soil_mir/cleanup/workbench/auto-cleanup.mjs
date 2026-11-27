class AutoCleanup {
  constructor(workbench) {
    this.workbench = workbench;
    this.el = workbench.el;
    this.dialog = this.el("auto-dialog");
    this.mode = "setup";
    this.pending = false;
    const click = (id, callback) => { this.el(id).onclick = callback; };
    click("auto-cleanup", () => {
      if (workbench.busy || !this.config) return;
      if (this.config.report) this.report();
      else this.setup();
      if (!this.dialog.open) this.dialog.showModal();
    });
    click("auto-new", () => this.setup());
    click("auto-close", () => this.dialog.close());
    this.dialog.oncancel = event => {
      if (this.pending || this.mode === "progress") event.preventDefault();
    };
    click("auto-select-all", () => this.selectAll(true));
    click("auto-unselect-all", () => this.selectAll(false));
    this.el("auto-property-list").onchange = () => this.buttons();
    this.el("auto-output").oninput = () => this.buttons();
    click("auto-browse", () => {
      this.pending = true;
      this.message("Choose the output folder in the system picker…");
      this.buttons();
      workbench.send({kind: "auto-browse"});
    });
    click("auto-run", () => {
      const selected = this.selected().map(input => input.value);
      const path = this.el("auto-output").value.trim();
      if (!selected.length || !path || workbench.busy) return;
      this.pending = true;
      this.show("progress");
      this.renderResults([]);
      this.message("Preparing automatic cleanup…");
      workbench.send({kind: "auto-start", selected, path});
    });
    click("auto-stop", () => {
      this.el("auto-stop").disabled = true;
      workbench.send({kind: "auto-stop"});
    });
    click("auto-export", () => {
      this.dialog.close();
      workbench.showStage("Export");
    });
  }

  choices() {
    return [...this.el("auto-property-list").querySelectorAll("input:not([disabled])")];
  }

  selected() {
    return this.choices().filter(input => input.checked);
  }

  selectAll(checked) {
    for (const input of this.choices()) input.checked = checked;
    this.buttons();
  }

  buttons() {
    const checked = this.selected().length;
    this.el("auto-properties").disabled = this.pending;
    this.el("auto-output").readOnly = this.pending;
    this.el("auto-browse").disabled = this.pending;
    this.el("auto-select-all").disabled = this.pending || checked === this.choices().length;
    this.el("auto-unselect-all").disabled = this.pending || checked === 0;
    this.el("auto-run").disabled = this.pending || !checked || !this.el("auto-output").value.trim();
    this.el("auto-close").disabled = this.pending || this.mode === "progress";
  }

  message(text = "", error = false) {
    const status = this.el("auto-status");
    if (status.textContent !== text) status.textContent = text;
    status.hidden = !text;
    status.classList.toggle("error", error);
  }

  show(mode) {
    this.mode = mode;
    this.el("auto-setup").hidden = mode !== "setup";
    this.el("auto-results").hidden = mode === "setup";
    this.el("auto-run").hidden = mode !== "setup";
    this.el("auto-stop").hidden = mode !== "progress";
    this.el("auto-stop").disabled = true;
    this.el("auto-new").hidden = mode !== "results" || !this.config.properties.some(item => !item.skip);
    this.el("auto-export").hidden = mode !== "results";
    this.buttons();
  }

  setup(preserve = false) {
    const previous = preserve ? new Set(this.selected().map(input => input.value)) : new Set();
    const choices = this.config.properties.map(({property, skip}) => {
      const label = document.createElement("label");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.value = property;
      check.checked = !skip && previous.has(property);
      check.disabled = skip;
      const name = document.createElement("span");
      name.textContent = property;
      label.append(check, name);
      if (skip) {
        const reason = document.createElement("small");
        reason.textContent = "Skipped · Existing A/B work";
        label.append(reason);
      }
      return label;
    });
    this.el("auto-property-list").replaceChildren(...choices);
    if (!preserve) this.el("auto-output").value = this.config.parent;
    this.show("setup");
    this.message(this.choices().length ? "" : "All properties already have Half A or Half B work.");
  }

  renderResults(results, progress, path = "") {
    const body = this.el("auto-result-rows");
    const labels = {queued: "Queued", skipped: "Skipped · Existing A/B work",
      "not-selected": "Not selected", "not-run": "Not run", completed: "Completed", failed: "Failed"};
    body.replaceChildren();
    const location = this.el("auto-result-path");
    location.hidden = !path;
    location.textContent = path ? "Session copy · " + path : "";
    const stages = new Map(this.config.properties.map(item => [item.property, item.stage]));
    for (const item of results) {
      const row = body.insertRow();
      row.dataset.property = item.property;
      row.dataset.status = item.status;
      row.insertCell().textContent = item.property;
      const status = row.insertCell();
      status.textContent = progress?.property === item.property && item.status === "queued"
        ? progress.stage : labels[item.status] ?? item.status;
      if (item.error) {
        status.classList.add("error");
        status.append(document.createElement("br"), document.createTextNode(item.error));
      }
      for (const half of ["A", "B"]) {
        const cell = row.insertCell();
        const counts = item.counts?.[half];
        if (!counts) {
          cell.textContent = "—";
          continue;
        }
        for (const text of [plural(counts.candidate_spectra, "candidate spectrum", "candidate spectra"),
          plural(counts.samples, "sample", "samples"), plural(counts.excluded_spectra, "excluded spectrum", "excluded spectra")]) {
          const detail = document.createElement("div");
          detail.textContent = text;
          cell.append(detail);
        }
      }
      const actions = row.insertCell();
      if (progress || !["completed", "skipped", "failed"].includes(item.status)) continue;
      const currentStage = stages.get(item.property) ?? "PCA";
      const targets = currentStage === "B" ? ["A", "B"] : [currentStage];
      for (const stage of targets) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = stage === "PCA" ? "Review PCA" : "Review Half " + stage;
        button.setAttribute("aria-label", item.property + " · " + button.textContent);
        button.onclick = () => {
          this.dialog.close();
          this.workbench.send({kind: "auto-review", name: item.property, targetStage: stage,
            automatic: item.status === "completed" && stage !== "PCA"});
        };
        actions.append(button);
      }
    }
  }

  report() {
    const saved = this.config.report;
    this.show("results");
    const rows = saved.results.map(row =>
      saved.in_progress && row.status === "queued" ? {...row, status: "not-run"} : row);
    this.renderResults(rows, null, this.workbench.data.source);
    const readiness = this.workbench.data.exportOverview.ready ? "Ready to export." : "Review or finish the remaining properties before exporting.";
    const status = saved.in_progress ? "Opened the last saved batch checkpoint. "
      : saved.stopped ? "Automatic cleanup stopped. " : "Automatic cleanup finished. ";
    this.message(status + readiness);
  }

  update(data) {
    clearTimeout(this.poll);
    this.config = data.autoCleanup;
    this.el("auto-cleanup").hidden = !this.config;
    const progress = data.autoProgress;
    const feedback = data.autoFeedback;
    if (progress) {
      this.pending = true;
      this.show("progress");
      this.renderResults(progress.results, progress, progress.path);
      this.message(progress.stopping ? progress.message + " · Stop requested" : progress.message);
      this.el("auto-stop").disabled = progress.stopping;
      if (!this.dialog.open) this.dialog.showModal();
      this.poll = setTimeout(() => {
        if (this.dialog.isConnected && !this.workbench.busy) {
          this.workbench.sendEvent("action", {kind: "auto-poll", poll: progress.poll + 1});
        }
      }, 750);
      return;
    }
    this.pending = false;
    if (this.mode === "progress") {
      if (feedback?.error) this.setup(true);
      else if (this.config?.report) this.report();
    }
    if (feedback?.path) this.el("auto-output").value = feedback.path;
    if (feedback?.error) this.message(feedback.error, true);
    else if (feedback && "path" in feedback) this.message();
    this.buttons();
  }
}
