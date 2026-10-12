/* TrumpApprovalByState — local dashboard prototype.
   Data source: docs/data/state_approval.json (published static snapshot).
   Geography: us-atlas projected topojson (Census-derived). */
(() => {
  "use strict";

  const DATA_PATH = "./data/state_approval.json";
  const MAP_PATH = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-albers-10m.json";
  const CIVIQS = "https://civiqs.com/results/approve_president_trump_2025";
  const METRIC_LABELS = {net:"Overall net approval", republican:"Republican net approval", democratic:"Democratic net approval"};
  // FEC official 2024 results: states where Trump received more statewide votes than Harris.
  // Michigan and Wisconsin were won with less than 50% of all presidential votes.
  // This is a statewide outcome, even in Maine and Nebraska (which divide electoral votes).
  const TRUMP_2024_WON_STATES = new Set([
    "AL", "AK", "AZ", "AR", "FL", "GA", "ID", "IN", "IA", "KS", "KY",
    "LA", "MI", "MS", "MO", "MT", "NE", "NV", "NC", "ND", "OH", "OK",
    "PA", "SC", "SD", "TN", "TX", "UT", "WV", "WI", "WY"
  ]);
  const state = {records: [], byName: new Map(), features: [], metric:"net", selected:"Pennsylvania", search:"", sortColumn:null, sortDirection:"asc"};
  const $ = id => document.getElementById(id);

  // Every map mode measures approval minus disapproval within its population.
  function value(d, metric = state.metric) {
    if (metric === "republican") return d.republicanApprove - d.republicanDisapprove;
    if (metric === "democratic") return d.democraticApprove - d.democraticDisapprove;
    return d.approve - d.disapprove;
  }
  function signed(n) {
    const x = Object.is(n, -0) ? 0 : n;
    return `${x > 0 ? "+" : ""}${Number.isInteger(x) ? x : x.toFixed(1)}`;
  }
  function pct(n) { return `${n}%`; }
  function groupValues(r) {
    if (state.metric === "republican") return {
      approve: r.republicanApprove, disapprove: r.republicanDisapprove,
      neither: r.republicanNeither, approveDisplay: r.republicanApproveDisplay,
      disapproveDisplay: r.republicanDisapproveDisplay,
      neitherDisplay: r.republicanNeitherDisplay,
      label: "Republicans", source: r.republicanSourceUrl
    };
    if (state.metric === "democratic") return {
      approve: r.democraticApprove, disapprove: r.democraticDisapprove,
      neither: r.democraticNeither, approveDisplay: r.democraticApproveDisplay,
      disapproveDisplay: r.democraticDisapproveDisplay,
      neitherDisplay: r.democraticNeitherDisplay,
      label: "Democrats", source: r.democraticSourceUrl
    };
    return {
      approve: r.approve, disapprove: r.disapprove, neither: r.neither,
      approveDisplay: r.approveDisplay, disapproveDisplay: r.disapproveDisplay,
      neitherDisplay: r.neitherDisplay, label: "All registered voters", source: r.sourceUrl
    };
  }
  // Round halves away from zero, including -97.5 to -98.
  function roundNet(n) {
    return Math.sign(n) * Math.round(Math.abs(n));
  }
  function displayMetric(r, metric = state.metric) {
    return `${signed(roundNet(value(r, metric)))}%`;
  }
  function formatDate(value) {
    if (!value) return "Unknown";
    const parsed = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("en-US", {month:"long",day:"numeric",year:"numeric",timeZone:"UTC"});
  }
  // Each party map uses its own clearly labeled, data-driven range to show
  // relatively small within-party differences. The overall map is diverging.
  function partyRange(metric) {
    const values = state.records.map(r => value(r, metric));
    const low = Math.min(...values), high = Math.max(...values);
    return [low, high];
  }
  function ramp(v, metric) {
    if (metric === "net") {
      return d3.scaleLinear()
        .domain([-65, -30, 0, 20])
        .range(["#896348", "#c8ad96", "#dbe5e7", "#258175"])
        .clamp(true)(v);
    }
    const [low, high] = partyRange(metric);
    const t = high === low ? .5 : Math.max(0, Math.min(1, (v - low) / (high - low)));
    return metric === "republican"
      ? d3.interpolateRgbBasis(["#fcece8", "#e69a80", "#a74439"])(t)
      : d3.interpolateRgbBasis(["#edf1fa", "#a6b8e5", "#394e96"])(t);
  }
  function validateRecords(raw) {
    if (!Array.isArray(raw) || raw.length !== 50) throw new Error(`Expected 50 records; got ${Array.isArray(raw) ? raw.length : "invalid JSON"}.`);
    const seen = new Set();
    const rows = raw.map((r, i) => {
      const name = String(r.state || "").trim();
      const abbr = String(r.state_abbr || "").trim();
      if (!name || !/^[A-Z]{2}$/.test(abbr) || seen.has(name)) throw new Error(`Invalid/duplicate state at row ${i + 1}: ${name}`);
      const number = (field) => {
        const val = Number(r[field]);
        if (r[field] === null || r[field] === undefined || !Number.isFinite(val) || val < 0 || val > 100) {
          throw new Error(`${name}: invalid ${field}`);
        }
        return val;
      };
      const groups = [
        ["", "approve", "disapprove", "neither"],
        ["republican_", "republican_approve", "republican_disapprove", "republican_neither"],
        ["democratic_", "democratic_approve", "democratic_disapprove", "democratic_neither"]
      ];
      for (const [group, app, dis, neither] of groups) {
        if (Math.abs(number(app) + number(dis) + number(neither) - 100) > 2) throw new Error(`${name}: ${group || "overall"} values do not total ~100%`);
      }
      seen.add(name);
      const disp = (key, val) => r[key] != null ? String(r[key]) : val === 0.5 ? "<1%" : `${val}%`;
      return {
        state: name, abbr,
        approve: number("approve"), disapprove: number("disapprove"), neither: number("neither"),
        approveDisplay: disp("approve_display", number("approve")),
        disapproveDisplay: disp("disapprove_display", number("disapprove")),
        neitherDisplay: disp("neither_display", number("neither")),
        republicanApprove: number("republican_approve"), republicanDisapprove: number("republican_disapprove"), republicanNeither: number("republican_neither"),
        republicanApproveDisplay: disp("republican_approve_display", number("republican_approve")),
        republicanDisapproveDisplay: disp("republican_disapprove_display", number("republican_disapprove")),
        republicanNeitherDisplay: disp("republican_neither_display", number("republican_neither")),
        democraticApprove: number("democratic_approve"), democraticDisapprove: number("democratic_disapprove"), democraticNeither: number("democratic_neither"),
        democraticApproveDisplay: disp("democratic_approve_display", number("democratic_approve")),
        democraticDisapproveDisplay: disp("democratic_disapprove_display", number("democratic_disapprove")),
        democraticNeitherDisplay: disp("democratic_neither_display", number("democratic_neither")),
        trump2024Votes: (() => { const v = Number(r.trump_2024_votes); if (!Number.isInteger(v) || v < 0) throw new Error(`${name}: invalid Trump 2024 votes`); return v; })(),
        total2024Votes: (() => { const v = Number(r.total_2024_presidential_votes); if (!Number.isInteger(v) || v <= 0) throw new Error(`${name}: invalid 2024 presidential vote total`); return v; })(),
        trump2024Share: (() => { const v = Number(r.trump_2024_vote_share_pct); if (!Number.isFinite(v) || v < 0 || v > 100) throw new Error(`${name}: invalid Trump 2024 vote share`); return v; })(),
        fec2024SourceUrl: r.fec_2024_source_url,
        reportDate: r.report_date, retrievedAt: r.retrieved_at_utc,
        sourceUrl: r.source_url, republicanSourceUrl: r.republican_source_url, democraticSourceUrl: r.democratic_source_url
      };
    });
    for (const row of rows) {
      const computed = 100 * row.trump2024Votes / row.total2024Votes;
      if (row.trump2024Votes > row.total2024Votes || Math.abs(computed - row.trump2024Share) > 0.011) {
        throw new Error(`${row.state}: 2024 vote share doesn't match official vote counts`);
      }
    }
    const dates = new Set(rows.map(r => r.reportDate));
    if (dates.size !== 1 || ![...dates][0]) throw new Error("State reporting dates are inconsistent or missing.");
    return rows;
  }
  function showError(message) {$("error").textContent = message;$("error").hidden = false;}
  function setMetric(metric) {
    if (!METRIC_LABELS[metric]) return;
    state.metric = metric;
    document.querySelectorAll(".metric-btn").forEach(b => {const active = b.dataset.metric === metric;b.classList.toggle("is-active",active);b.setAttribute("aria-pressed",String(active));});
    renderMapColors();renderLegend();renderDetail();
  }
  function choose(name) {
    if (!state.byName.has(name)) return;
    state.selected = name;
    d3.selectAll(".state-path").classed("is-selected", d => d.properties.name === name);
    renderDetail();renderTable();
  }
  function renderMap() {
    const svg = d3.select("#us-map");
    const path = d3.geoPath(); // us-atlas states-albers-10m is already projected to 975 x 610.
    svg.selectAll("path").data(state.features.filter(f => state.byName.has(f.properties.name))).join("path")
      .attr("class","state-path")
      .attr("d",path)
      .attr("tabindex",0)
      .attr("role","button")
      .attr("aria-label",d => `${d.properties.name}, select state`)
      .on("mouseenter",function(event,d){ showTooltip(event,d.properties.name); })
      .on("mousemove",function(event,d){ moveTooltip(event); })
      .on("mouseleave",() => {$("tooltip").hidden=true;})
      .on("click",(event,d) => choose(d.properties.name))
      .on("keydown",(event,d) => {if(event.key==="Enter" || event.key===" "){event.preventDefault();choose(d.properties.name);}});
    $("map-loading").hidden = true;
    renderMapColors();
  }
  function showTooltip(event, name) {
    const r = state.byName.get(name);
    if (!r) return;
    const group = groupValues(r);
    const tooltip = $("tooltip");
    tooltip.replaceChildren();
    const heading = document.createElement("b");
    heading.textContent = name;
    tooltip.appendChild(heading);
    for (const line of [
      `${METRIC_LABELS[state.metric]}: ${displayMetric(r)}`,
      `Approve: ${group.approveDisplay} · Disapprove: ${group.disapproveDisplay}`,
      `Trump's 2024 vote share: ${r.trump2024Share.toFixed(2)}%`
    ]) {
      const span = document.createElement("span");
      span.textContent = line;
      span.style.display = "block";
      tooltip.appendChild(span);
    }
    tooltip.hidden = false;
    moveTooltip(event);
  }
  function moveTooltip(event) {
    const frame = $("map-frame");const box = frame.getBoundingClientRect();const tip = $("tooltip");
    const x = Math.max(0,Math.min(event.clientX-box.left+12, box.width-tip.offsetWidth-3));
    const y = Math.max(0,Math.min(event.clientY-box.top-50, box.height-tip.offsetHeight));
    tip.style.left = `${x}px`;tip.style.top = `${y}px`;
  }
  function renderMapColors() {
    d3.selectAll(".state-path").attr("fill",d => ramp(value(state.byName.get(d.properties.name)),state.metric))
      .classed("is-selected",d => d.properties.name === state.selected);
  }
  function renderLegend() {
    $("legend-label").textContent = `${METRIC_LABELS[state.metric]} (percentage points)`;
    let ticks;
    if (state.metric === "net") {
      $("legend-ramp").style.background = "linear-gradient(90deg,#896348,#c8ad96,#dbe5e7,#258175)";
      ticks = ["−65", "−30", "0", "+20"];
    } else {
      const [low, high] = partyRange(state.metric);
      $("legend-ramp").style.background = `linear-gradient(90deg,${[0,.25,.5,.75,1].map(t => ramp(low + t*(high-low), state.metric)).join(",")})`;
      ticks = [signed(roundNet(low)), signed(roundNet((low + high)/2)), signed(roundNet(high))];
    }
    $("legend-ticks").replaceChildren();
    ticks.forEach(t => { const el = document.createElement("span"); el.textContent = t; $("legend-ticks").appendChild(el); });
  }
  function setTableSort(column) {
    if (!["state", "overall", "republican", "democratic", "trump2024"].includes(column)) return;
    if (state.sortColumn === column) {
      state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
    } else {
      state.sortColumn = column;
      state.sortDirection = column === "state" ? "asc" : "desc";
    }
    renderTable();
  }
  function renderTable() {
    const query = state.search.trim().toLowerCase();
    const rows = state.records.filter(r =>
      r.state.toLowerCase().includes(query) || r.abbr.toLowerCase().includes(query)
    );

    // Before a column is clicked, list states alphabetically.
    const column = state.sortColumn;
    const direction = state.sortDirection === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      if (column === "state" || column === null) {
        return a.state.localeCompare(b.state) * (column === null ? 1 : direction);
      }
      const difference = column === "trump2024"
        ? a.trump2024Share - b.trump2024Share
        : value(a, column === "overall" ? "net" : column) - value(b, column === "overall" ? "net" : column);
      return difference * direction || a.state.localeCompare(b.state);
    });

    document.querySelectorAll(".data-table thead th[data-sort-column]").forEach(th => {
      const active = th.dataset.sortColumn === column;
      th.setAttribute("aria-sort", active ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none");
      th.querySelector(".sort-indicator").textContent = active ? (state.sortDirection === "asc" ? "↑" : "↓") : "↕";
      const btn = th.querySelector(".table-sort-btn");
      btn.setAttribute("aria-label", `${btn.textContent.replace(/[↕↑↓]/g, "").trim()}: sort ${active && state.sortDirection === "desc" ? "ascending" : active && state.sortDirection === "asc" ? "descending" : th.dataset.sortColumn === "state" ? "A to Z" : "highest to lowest"}`);
    });

    $("shown-count").textContent = `${rows.length} shown`;
    const body = $("state-tbody");
    body.replaceChildren();
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.classList.toggle("is-selected", r.state === state.selected);
      tr.setAttribute("aria-label", `Select ${r.state}`);
      for (const text of [
        `${r.state} (${r.abbr})`,
        displayMetric(r, "net"),
        displayMetric(r, "republican"),
        displayMetric(r, "democratic"),
        `${r.trump2024Share.toFixed(2)}%`
      ]) {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      }
      tr.addEventListener("click", () => choose(r.state));
      tr.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          choose(r.state);
        }
      });
      body.appendChild(tr);
    }
  }
  function renderDetail() {
    const r = state.byName.get(state.selected);
    if (!r) return;
    const group = groupValues(r);
    $("detail-title").textContent = r.state;
    $("detail-abbr").textContent = r.abbr;
    $("detail-date").textContent = `Civiqs reporting date: ${formatDate(r.reportDate)}`;
    $("detail-big").textContent = displayMetric(r);
    $("detail-big-caption").textContent = `${METRIC_LABELS[state.metric]} (percentage points)`;
    for (const key of ["approve", "disapprove", "neither"]) {
      $(`detail-${key}`).textContent = group[`${key}Display`];
      $(`bar-${key}`).style.width = `${group[key]}%`;
    }
    const approvalPopulation = state.metric === "republican"
      ? "Republican registered voters"
      : state.metric === "democratic"
        ? "Democratic registered voters"
        : "registered voters";
    $("detail-group").textContent = `Estimated approval among ${approvalPopulation}`;
    $("detail-2024-result").textContent = TRUMP_2024_WON_STATES.has(r.abbr) ? "won" : "lost";
    $("detail-2024-state").textContent = r.state;
    $("detail-2024-share").textContent = `${r.trump2024Share.toFixed(2)}%`;
    $("detail-2024-source").href = r.fec2024SourceUrl || "https://www.fec.gov/documents/5645/2024presgeresults.xlsx";
    const base = group.source || CIVIQS;
    const source = new URL(base);
    source.searchParams.set("home_state", r.state);
    $("detail-source").href = source.toString();
  }
  async function init() {
    $("state-search").addEventListener("input",e=>{state.search=e.target.value;renderTable();});
    document.querySelectorAll(".table-sort-btn").forEach(button => button.addEventListener("click", () => setTableSort(button.dataset.sort)));
    document.querySelectorAll(".metric-btn").forEach(b=>b.addEventListener("click",()=>setMetric(b.dataset.metric)));
    try {
      const response=await fetch(DATA_PATH,{cache:"no-store"});
      if (!response.ok) throw new Error(`Could not load ${DATA_PATH} (HTTP ${response.status}). Run: python scripts/prepare_preview.py`);
      state.records=validateRecords(await response.json());
      state.byName=new Map(state.records.map(r=>[r.state,r]));
      if(!state.byName.has(state.selected))state.selected=state.records[0].state;
      $("source-date").textContent=`Civiqs date: ${formatDate(state.records[0].reportDate)}`;
      $("states-count").textContent=`${state.records.length} states`;
      const retrieval = state.records[0].retrievedAt;
      $("retrieved-at").textContent = retrieval ? `Snapshot: ${new Date(retrieval).toLocaleDateString("en-US")}` : "Local snapshot";
      renderLegend();renderTable();renderDetail();
      if(typeof d3==="undefined" || typeof topojson==="undefined") throw new Error("Map libraries did not load. Check your internet connection; this prototype uses the jsDelivr CDN for map libraries.");
      const topology=await d3.json(MAP_PATH);
      if(!topology || !topology.objects || !topology.objects.states) throw new Error("Could not read the U.S. state boundary map.");
      state.features=topojson.feature(topology,topology.objects.states).features;
      const mapped=new Set(state.features.map(f=>f.properties.name));
      const missing=state.records.filter(r=>!mapped.has(r.state));
      if(missing.length)throw new Error(`Geographic features missing for: ${missing.map(r=>r.state).join(", ")}`);
      renderMap();
    } catch(error) {
      $("map-loading").textContent="Map unavailable";
      showError(error.message || String(error));
      console.error(error);
    }
  }
  document.addEventListener("DOMContentLoaded",init);
})();
