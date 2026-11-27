{
  const el = id => document.getElementById(id);
  const property = el("property");
  const xAxis = el("x-axis");
  const yAxis = el("y-axis");
  for (const name of Object.keys(SNAPSHOT.properties)) property.add(new Option(name, name));
  property.value = SNAPSHOT.current;

  const chart = new PcaChart(el("chart"), el("tip"), () => {});
  const percent = value => value.toFixed(2) + "%";
  const axisLabel = (i, value) => "PC" + (i + 1) + " (" + percent(value) + ")";

  function draw() {
    const fit = SNAPSHOT.properties[property.value];
    const x = Number(xAxis.value), y = Number(yAxis.value);
    const subset = el("subset").selectedIndex;
    const visible = fit.rows.filter(row =>
      !subset || row.status === (subset === 1 ? "Retained" : "Excluded"));
    const samples = new Set(visible.map(row => row.sample));
    const excluded = fit.rows.filter(row => row.status === "Excluded").length;
    chart.update({
      basis: [property.value, fit.round, x, y].join("/"),
      all: fit.rows, visible, selected: new Set(),
      x, y, variance: fit.variance, colour: el("colour").value, mode: "pan",
    });
    el("status").textContent = visible.length + " visible spectra · " + samples.size + " samples · "
      + fit.variance.length + " computed PCs · " + excluded + " confirmed exclusions in this basis";
    el("basis").textContent = "PCA fit " + fit.round + (fit.dirty
      ? " · The plotted coordinates use the previous fit. Review decisions require a refit."
      : " · Record filters share the same PCA basis.")
      + (fit.variance.length < 2 ? " Only one valid component is available." : "");
  }

  function selectProperty() {
    const fit = SNAPSHOT.properties[property.value];
    for (const axis of [xAxis, yAxis]) {
      axis.replaceChildren(...fit.variance.map((value, i) => new Option(axisLabel(i, value), i)));
      axis.disabled = fit.variance.length < 2;
    }
    yAxis.selectedIndex = Math.min(1, fit.variance.length - 1);
    const bars = fit.variance.map((value, i) => {
      const container = document.createElement("div");
      container.className = "variance-bar";
      const caption = document.createElement("div");
      caption.className = "variance-label";
      const pc = document.createElement("span");
      pc.textContent = "PC" + (i + 1);
      const number = document.createElement("span");
      number.textContent = percent(value);
      caption.append(pc, number);
      const bar = document.createElement("progress");
      bar.className = "variance-track";
      bar.max = 100;
      bar.value = value;
      bar.setAttribute("aria-label", axisLabel(i, value));
      container.append(caption, bar);
      return container;
    });
    el("variance").replaceChildren(...bars);
    draw();
  }

  property.onchange = selectProperty;
  for (const id of ["x-axis", "y-axis", "colour", "subset"]) el(id).onchange = draw;
  el("reset").onclick = () => chart.reset();
  el("zoom-in").onclick = () => chart.zoom(0.8);
  el("zoom-out").onclick = () => chart.zoom(1.25);
  el("png").onclick = () => {
    const link = document.createElement("a");
    link.download = property.value.replace(/[^\p{L}\p{N}_.-]/gu, "_") + "-PCA.png";
    link.href = chart.canvas.toDataURL("image/png");
    link.click();
  };
  selectProperty();
}
