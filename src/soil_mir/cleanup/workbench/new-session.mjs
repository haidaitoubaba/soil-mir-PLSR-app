class NewSession {
  constructor(workbench) {
    this.workbench = workbench;
    this.el = workbench.el;
    this.dialog = this.el("new-session-dialog");
    this.form = this.el("new-session-form");
    this.status = this.el("new-status");
    this.fields = ["workbook", "spectra", "output"];
    this.ready = false;
    this.pending = false;

    const open = () => {
      if (workbench.busy) return;
      this.el("new-session-draft").hidden = !workbench.data.dirtyDraft;
      const defaults = workbench.data.newSessionDefaults;
      if (!this.opened) {
        for (const field of this.fields) this.el("new-" + field).value = defaults?.[field] ?? "";
        this.opened = true;
      }
      this.dialog.showModal();
    };
    for (const id of ["new-session", "start-new-session"]) this.el(id).onclick = open;
    this.el("new-cancel").onclick = () => this.dialog.close();
    this.dialog.oncancel = event => {
      if (this.pending) event.preventDefault();
    };
    this.form.onsubmit = event => {
      event.preventDefault();
      if (!this.pending) {
        this.invalidatePreview();
        this.send("new-inspect", "Checking workbook and OPUS filenames…", this.paths());
      }
    };
    for (const field of this.fields) {
      this.el("new-" + field).oninput = () => this.invalidatePreview();
    }
    for (const button of this.form.querySelectorAll("[data-browse]")) {
      button.onclick = () => this.send("new-browse", "Choose a path in the system picker…", {field: button.dataset.browse});
    }
    this.el("new-create").onclick = () => {
      this.send("new-create", "Verifying the reference workbook…", {...this.paths(), selected: this.selected()});
    };
    this.el("new-property-rows").onchange = () => this.refreshButtons();
    this.el("new-select-all").onclick = () => this.setPropertySelection(true);
    this.el("new-unselect-all").onclick = () => this.setPropertySelection(false);
  }

  paths() {
    return Object.fromEntries(this.fields.map(field => [field, this.el("new-" + field).value.trim()]));
  }

  selected() {
    return Array.from(this.form.querySelectorAll("input[data-property]:checked"), input => input.value);
  }

  selectableProperties() {
    return this.el("new-property-rows").querySelectorAll("input[data-property]:not([disabled])");
  }

  setPropertySelection(checked) {
    for (const input of this.selectableProperties()) input.checked = checked;
    this.refreshButtons();
  }

  invalidatePreview() {
    this.ready = false;
    this.el("new-properties").hidden = true;
    this.message("");
    this.refreshButtons();
  }

  message(text, error = false) {
    this.status.textContent = text;
    this.status.classList.toggle("error", error);
  }

  refreshButtons() {
    for (const field of this.fields) this.el("new-" + field).readOnly = this.pending;
    for (const button of this.form.querySelectorAll("[data-browse], #new-cancel, #new-inspect")) {
      button.disabled = this.pending;
    }
    this.el("new-properties").disabled = this.pending;
    const selected = this.selected().length;
    const inactive = this.pending || !this.ready;
    this.el("new-select-all").disabled = inactive || selected === this.selectableProperties().length;
    this.el("new-unselect-all").disabled = inactive || selected === 0;
    this.el("new-create").disabled = inactive || selected === 0;
  }

  send(kind, message, fields) {
    if (this.pending || this.workbench.busy) return;
    this.pending = true;
    this.message(message);
    this.refreshButtons();
    this.workbench.send({kind, ...fields});
  }

  showPreview(preview) {
    const body = this.el("new-property-rows");
    body.replaceChildren();
    for (const property of preview.properties) {
      const row = body.insertRow();
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.property = "";
      input.value = property.name;
      input.disabled = Boolean(property.error);
      label.append(input, document.createTextNode(property.name));
      row.insertCell().append(label);
      for (const value of [property.samples, property.spectra, property.transform ?? "—", property.units || "—",
        property.excludeCO2 == null ? "—" : (property.excludeCO2 ? "Excluded" : "Kept")]) {
        row.insertCell().textContent = value;
      }
      if (property.error) {
        const issue = body.insertRow().insertCell();
        issue.colSpan = 6;
        issue.className = "new-property-error";
        issue.textContent = property.name + " · " + property.error;
      }
    }
    this.ready = true;
    this.el("new-properties").hidden = false;
    const available = preview.properties.filter(property => !property.error).length;
    this.message(available ? plural(available, "property ready", "properties ready") : "No property is ready. Review the issues above.");
  }

  update(data) {
    clearTimeout(this.poll);
    this.pending = Boolean(data.importProgress);
    if (this.pending) {
      this.message(data.importProgress.message);
      this.poll = setTimeout(() => {
        if (this.dialog.isConnected) {
          this.workbench.sendEvent("action", {kind: "new-poll", poll: data.importProgress.poll + 1});
        }
      }, 750);
    }
    const feedback = data.importFeedback;
    if (feedback?.error) this.message(feedback.error, true);
    if (feedback?.field) {
      if (feedback.path) {
        this.el("new-" + feedback.field).value = feedback.path;
        this.invalidatePreview();
      } else {
        this.message("");
      }
    }
    if (feedback?.preview) this.showPreview(feedback.preview);
    if (feedback?.created) {
      this.dialog.close();
      this.invalidatePreview();
    }
    this.refreshButtons();
  }
}
