"use strict";

/**
 * Supply Chain Decision Support dashboard.
 *
 * Fetches the deterministic analysis from the JSON API and renders a
 * filterable, exportable view. It never changes analysis results; the
 * explanation panel only displays text produced by the backend.
 */

const ENDPOINTS = {
  summary: "/summary",
  inventory: "/inventory",
  recommendations: "/recommendations",
  explanation: "/explanation",
  predictStockout: "/predict-stockout",
};

const RISK_PRIORITY = {
  CRITICAL: 1,
  HIGH: 2,
  MEDIUM: 3,
  LOW: 4,
};

const state = {
  inventory: [],
  recommendations: [],
  summary: null,
  facilityRegion: new Map(),
  filters: {
    region: "",
    medicine: "",
    risk: "",
    search: "",
  },
  loaded: false,
};

const els = {};

function byId(id) {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing dashboard element: #${id}`);
  }
  return element;
}

function cacheElements() {
  els.errorBanner = byId("error-banner");
  els.dataBadge = byId("data-badge");
  els.refreshButton = byId("refresh-button");

  els.kpiFacilities = byId("kpi-facilities");
  els.kpiCritical = byId("kpi-critical");
  els.kpiHigh = byId("kpi-high");
  els.kpiExpiry = byId("kpi-expiry");
  els.kpiCandidates = byId("kpi-candidates");

  els.filterRegion = byId("filter-region");
  els.filterMedicine = byId("filter-medicine");
  els.filterRisk = byId("filter-risk");
  els.filterSearch = byId("filter-search");
  els.clearFilters = byId("clear-filters");
  els.viewStatus = byId("view-status");

  els.riskHead = byId("risk-head");
  els.riskBody = byId("risk-body");
  els.riskEmpty = byId("risk-empty");
  els.riskTable = byId("risk-table");
  els.exportInventory = byId("export-inventory");

  els.recommendationBody = byId("recommendation-body");
  els.recommendationEmpty = byId("recommendation-empty");
  els.recommendationTable = byId("recommendation-table");
  els.exportRecommendations = byId("export-recommendations");

  els.explainButton = byId("explain-button");
  els.explanationStatus = byId("explanation-status");
  els.guardrailWarnings = byId("guardrail-warnings");
  els.explanationOutput = byId("explanation-output");
  els.explanationEmpty = byId("explanation-empty");

  els.mlForm = byId("ml-form");
  els.mlFacility = byId("ml-facility");
  els.mlMedicine = byId("ml-medicine");
  els.mlCurrentStock = byId("ml-current-stock");
  els.mlMonthlyConsumption = byId("ml-monthly-consumption");
  els.mlLeadTime = byId("ml-lead-time");
  els.mlExpiry = byId("ml-expiry");
  els.mlTrend = byId("ml-trend");
  els.mlHistory = byId("ml-history");
  els.mlReplenishment = byId("ml-replenishment");
  els.mlMonth = byId("ml-month");
  els.mlPredict = byId("ml-predict");
  els.mlStatus = byId("ml-status");
  els.mlResult = byId("ml-result");
  els.mlEmpty = byId("ml-empty");
  els.mlModelInfo = byId("ml-model-info");
  els.mlDeterministicBody = byId("ml-deterministic-body");
  els.mlPredictionBody = byId("ml-prediction-body");
  els.mlDecisionBody = byId("ml-decision-body");

  els.governanceNote = byId("governance-note");
  els.assumptionsList = byId("assumptions-list");

  els.lastUpdated = byId("last-updated");
  els.main = byId("main");
}

/* ------------------------------------------------------------------ */
/* Formatting helpers                                                  */
/* ------------------------------------------------------------------ */

const dayFormat = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 1,
});

const scoreFormat = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatDays(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${dayFormat.format(value)} d`;
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return scoreFormat.format(value);
}

function sameText(left, right) {
  return String(left).toLowerCase() === String(right).toLowerCase();
}

function riskPriority(risk) {
  return RISK_PRIORITY[risk] || 99;
}

function clearNode(node) {
  node.replaceChildren();
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const probabilityFormat = new Intl.NumberFormat(undefined, {
  style: "percent",
  maximumFractionDigits: 1,
});

/* ------------------------------------------------------------------ */
/* Filters and URL state                                               */
/* ------------------------------------------------------------------ */

function readFiltersFromUrl() {
  const params = new URLSearchParams(window.location.search);
  state.filters.region = params.get("region") || "";
  state.filters.medicine = params.get("medicine") || "";
  state.filters.risk = params.get("risk") || "";
  state.filters.search = (params.get("q") || "").trim();
}

function syncUrl() {
  const params = new URLSearchParams();
  if (state.filters.region) params.set("region", state.filters.region);
  if (state.filters.medicine) {
    params.set("medicine", state.filters.medicine);
  }
  if (state.filters.risk) params.set("risk", state.filters.risk);
  if (state.filters.search) params.set("q", state.filters.search);

  const query = params.toString();
  const url = query
    ? `${window.location.pathname}?${query}`
    : window.location.pathname;

  window.history.replaceState(null, "", url);
}

function populateSelect(select, values) {
  const firstOption = select.options[0];
  select.replaceChildren(firstOption);

  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((left, right) =>
    left.localeCompare(right),
  );
}

function canonicalValue(value, values) {
  if (!value) {
    return "";
  }
  return values.find((candidate) => sameText(candidate, value)) || "";
}

function populateFilters() {
  const regions = uniqueSorted(
    state.inventory.map((item) => item.region),
  );
  const medicines = uniqueSorted(
    state.inventory.map((item) => item.medicine),
  );
  const risks = Object.keys(RISK_PRIORITY);

  populateSelect(els.filterRegion, regions);
  populateSelect(els.filterMedicine, medicines);

  state.filters.region = canonicalValue(state.filters.region, regions);
  state.filters.medicine = canonicalValue(
    state.filters.medicine,
    medicines,
  );
  state.filters.risk = canonicalValue(state.filters.risk, risks);

  els.filterRegion.value = state.filters.region;
  els.filterMedicine.value = state.filters.medicine;
  els.filterRisk.value = state.filters.risk;
  els.filterSearch.value = state.filters.search;
}

function applyFiltersFromControls() {
  state.filters.region = els.filterRegion.value;
  state.filters.medicine = els.filterMedicine.value;
  state.filters.risk = els.filterRisk.value;
  state.filters.search = els.filterSearch.value.trim();

  syncUrl();
  render();
}

function clearFilters() {
  state.filters = { region: "", medicine: "", risk: "", search: "" };
  els.filterRegion.value = "";
  els.filterMedicine.value = "";
  els.filterRisk.value = "";
  els.filterSearch.value = "";

  syncUrl();
  render();
}

function getFilteredInventory() {
  const filters = state.filters;
  const query = filters.search.toLowerCase();

  return state.inventory.filter((item) => {
    if (filters.region && !sameText(item.region, filters.region)) {
      return false;
    }
    if (filters.medicine && !sameText(item.medicine, filters.medicine)) {
      return false;
    }
    if (filters.risk && !sameText(item.stockout_risk, filters.risk)) {
      return false;
    }
    if (query) {
      const haystack = `${item.facility} ${item.medicine} ${item.region}`;
      if (!haystack.toLowerCase().includes(query)) {
        return false;
      }
    }
    return true;
  });
}

function getFilteredRecommendations() {
  const filters = state.filters;
  const query = filters.search.toLowerCase();

  return state.recommendations.filter((item) => {
    if (filters.medicine && !sameText(item.medicine, filters.medicine)) {
      return false;
    }
    if (
      filters.risk &&
      !sameText(item.destination_stockout_risk, filters.risk)
    ) {
      return false;
    }
    if (filters.region) {
      const regions = [
        state.facilityRegion.get(item.source_facility),
        state.facilityRegion.get(item.destination_facility),
      ];
      const touchesRegion = regions.some(
        (region) => region && sameText(region, filters.region),
      );
      if (!touchesRegion) {
        return false;
      }
    }
    if (query) {
      const haystack = [
        item.medicine,
        item.source_facility,
        item.destination_facility,
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) {
        return false;
      }
    }
    return true;
  });
}

/* ------------------------------------------------------------------ */
/* ML prediction controls                                              */
/* ------------------------------------------------------------------ */

function populateMlControls() {
  populateMonths();

  const facilities = uniqueSorted(
    state.inventory.map((item) => item.facility),
  );
  populateSelect(els.mlFacility, facilities);
  populateMlMedicines();

  els.mlPredict.disabled = !state.loaded;
}

function populateMonths() {
  if (els.mlMonth.options.length > 0) {
    return;
  }

  for (const [index, name] of MONTH_NAMES.entries()) {
    const option = document.createElement("option");
    option.value = String(index + 1);
    option.textContent = name;
    els.mlMonth.appendChild(option);
  }

  els.mlMonth.value = String(new Date().getMonth() + 1);
}

function populateMlMedicines() {
  const facility = els.mlFacility.value;
  const medicines = uniqueSorted(
    state.inventory
      .filter((item) => sameText(item.facility, facility))
      .map((item) => item.medicine),
  );

  populateSelect(els.mlMedicine, medicines);
  syncMlInputsFromSelection();
}

function findInventoryItem(facility, medicine) {
  return state.inventory.find(
    (item) =>
      sameText(item.facility, facility) &&
      sameText(item.medicine, medicine),
  );
}

function syncMlInputsFromSelection() {
  const item = findInventoryItem(
    els.mlFacility.value,
    els.mlMedicine.value,
  );

  if (!item) {
    return;
  }

  els.mlCurrentStock.value = String(item.current_stock);
  els.mlMonthlyConsumption.value = String(item.monthly_consumption);
  els.mlLeadTime.value = String(item.lead_time_days);
  els.mlExpiry.value = String(item.expiry_days);
}

/* ------------------------------------------------------------------ */
/* ML prediction                                                       */
/* ------------------------------------------------------------------ */

function setPredictionStatus(message, isError = false) {
  clearNode(els.mlStatus);
  els.mlStatus.classList.toggle("is-error", isError);

  if (!message) {
    return;
  }

  if (!isError) {
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    spinner.setAttribute("aria-hidden", "true");
    els.mlStatus.appendChild(spinner);
  }

  const text = document.createElement("span");
  text.textContent = message;
  els.mlStatus.appendChild(text);
}

function readNumber(input, label) {
  const raw = String(input.value).trim();

  if (raw === "") {
    throw new Error(`${label} is required.`);
  }

  const value = Number(raw);

  if (!Number.isFinite(value)) {
    throw new Error(`${label} must be a number.`);
  }

  return value;
}

function buildPredictionPayload() {
  const facility = els.mlFacility.value;
  const medicine = els.mlMedicine.value;

  if (!facility || !medicine) {
    throw new Error("Choose a facility and medicine first.");
  }

  const region = state.facilityRegion.get(facility);

  if (!region) {
    throw new Error("Could not resolve the facility region.");
  }

  return {
    facility,
    medicine,
    region,
    current_stock: readNumber(els.mlCurrentStock, "Current stock"),
    monthly_consumption: readNumber(
      els.mlMonthlyConsumption,
      "Monthly consumption",
    ),
    lead_time_days: readNumber(els.mlLeadTime, "Lead time"),
    expiry_days: readNumber(els.mlExpiry, "Remaining shelf life"),
    recent_consumption_trend: readNumber(
      els.mlTrend,
      "Recent consumption trend",
    ),
    historical_stockout_count: Math.round(
      readNumber(els.mlHistory, "Historical stockout count"),
    ),
    replenishment_frequency: readNumber(
      els.mlReplenishment,
      "Replenishments per month",
    ),
    month: Number(els.mlMonth.value),
  };
}

async function requestPrediction() {
  let payload;

  try {
    payload = buildPredictionPayload();
  } catch (error) {
    setPredictionStatus(error.message, true);
    return;
  }

  els.mlPredict.disabled = true;
  const originalLabel = els.mlPredict.textContent;
  els.mlPredict.textContent = "Predicting…";
  setPredictionStatus("Requesting prediction…");

  try {
    const response = await fetch(ENDPOINTS.predictStockout, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      cache: "no-store",
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(await describeError(response));
    }

    const data = await response.json();
    renderPrediction(data);
    setPredictionStatus("");
  } catch (error) {
    els.mlResult.hidden = true;
    els.mlEmpty.hidden = false;
    setPredictionStatus(error.message, true);
  } finally {
    els.mlPredict.disabled = !state.loaded;
    els.mlPredict.textContent = originalLabel;
  }
}

function appendText(parent, tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;

  if (className) {
    node.className = className;
  }

  parent.appendChild(node);
  return node;
}

function predictionLabel(data) {
  return data.predicted_class === 1
    ? "Stockout likely within 30 days"
    : "No stockout expected within 30 days";
}

function renderPrediction(data) {
  els.mlResult.hidden = false;
  els.mlEmpty.hidden = true;

  clearNode(els.mlDeterministicBody);
  clearNode(els.mlPredictionBody);
  clearNode(els.mlDecisionBody);

  const reference = data.deterministic_reference;

  if (reference) {
    const chip = appendText(
      els.mlDeterministicBody,
      "span",
      reference.stockout_risk,
      "chip",
    );
    chip.dataset.risk = reference.stockout_risk;
    appendText(
      els.mlDeterministicBody,
      "p",
      `Days of stock ${formatDays(reference.days_of_stock)} · ` +
        `lead time ${formatDays(reference.lead_time_days)}.`,
    );
    appendText(
      els.mlDeterministicBody,
      "p",
      "Rule-based classification. It stays authoritative.",
      "ml-card-note",
    );
  } else {
    appendText(
      els.mlDeterministicBody,
      "p",
      "No deterministic record matches this facility and medicine.",
    );
  }

  const band = appendText(
    els.mlPredictionBody,
    "span",
    `${data.probability_band} · ${probabilityFormat.format(data.probability)}`,
    "chip",
  );
  band.dataset.risk = data.probability_band;
  appendText(els.mlPredictionBody, "p", predictionLabel(data));
  appendText(
    els.mlPredictionBody,
    "p",
    `Decision threshold ${probabilityFormat.format(data.threshold)}. ` +
      `Model ${data.model_id} v${data.model_version}.`,
    "ml-card-note",
  );

  const mlFlagged = data.predicted_class === 1;
  const deterministicRisk = reference ? reference.stockout_risk : null;
  const deterministicFlagged =
    deterministicRisk === "CRITICAL" || deterministicRisk === "HIGH";

  let recommendation;

  if (deterministicFlagged && mlFlagged) {
    recommendation =
      "Both the deterministic rules and the model flag this pair. " +
      "Prioritize a human review of coverage, pending orders, and " +
      "redistribution options.";
  } else if (deterministicFlagged) {
    recommendation =
      "The deterministic rules flag this pair while the model does not. " +
      "Keep the rule-based risk and verify whether local conditions " +
      "explain the difference.";
  } else if (mlFlagged) {
    recommendation =
      "The model flags this pair while the deterministic rules do not. " +
      "Treat it as a prompt to review the inputs before acting.";
  } else {
    recommendation =
      "Neither signal flags this pair. Continue routine monitoring.";
  }

  appendText(els.mlDecisionBody, "p", recommendation);
  appendText(
    els.mlDecisionBody,
    "p",
    "Decision support only: no order, transfer, or allocation is made " +
      "automatically.",
    "ml-card-note",
  );

  const governance = data.governance || {};
  const notes = [];

  if (governance.note) {
    notes.push(governance.note);
  }

  if (Array.isArray(governance.limitations)) {
    notes.push(...governance.limitations);
  }

  els.mlModelInfo.textContent = notes.join(" ");
}

/* ------------------------------------------------------------------ */
/* Rendering                                                           */
/* ------------------------------------------------------------------ */

function render() {
  if (!state.loaded) {
    return;
  }

  const inventory = getFilteredInventory();
  const recommendations = getFilteredRecommendations();

  renderKpis(inventory, recommendations);
  renderRiskMatrix(inventory);
  renderRecommendations(recommendations);
  renderViewStatus(inventory, recommendations);

  const hasInventory = inventory.length > 0;
  const hasRecommendations = recommendations.length > 0;

  els.exportInventory.disabled = !hasInventory;
  els.exportRecommendations.disabled = !hasRecommendations;
}

function renderKpis(inventory, recommendations) {
  const facilities = new Set(inventory.map((item) => item.facility));

  els.kpiFacilities.textContent = String(facilities.size);
  els.kpiCritical.textContent = String(
    inventory.filter((item) => item.stockout_risk === "CRITICAL").length,
  );
  els.kpiHigh.textContent = String(
    inventory.filter((item) => item.stockout_risk === "HIGH").length,
  );
  els.kpiExpiry.textContent = String(
    inventory.filter(
      (item) => item.expiry_risk === "HIGH" || item.expiry_risk === "MEDIUM",
    ).length,
  );
  els.kpiCandidates.textContent = String(recommendations.length);
}

function renderViewStatus(inventory, recommendations) {
  const total = state.inventory.length;
  const facilities = new Set(inventory.map((item) => item.facility)).size;
  const filters = state.filters;
  const filtered = Boolean(
    filters.region || filters.medicine || filters.risk || filters.search,
  );

  const parts = [
    `Showing ${inventory.length} of ${total} records`,
    `${facilities} ${facilities === 1 ? "facility" : "facilities"}`,
    `${recommendations.length} ${
      recommendations.length === 1 ? "candidate" : "candidates"
    }`,
  ];

  if (filtered) {
    parts.push("filtered");
  }

  els.viewStatus.textContent = parts.join(" · ");
}

function buildFacilityRows(inventory) {
  const rows = new Map();

  for (const item of inventory) {
    if (!rows.has(item.facility)) {
      rows.set(item.facility, {
        facility: item.facility,
        region: item.region,
        items: new Map(),
        worstRisk: "LOW",
      });
    }

    const row = rows.get(item.facility);
    row.items.set(item.medicine, item);

    if (
      riskPriority(item.stockout_risk) < riskPriority(row.worstRisk)
    ) {
      row.worstRisk = item.stockout_risk;
    }
  }

  return [...rows.values()].sort((left, right) => {
    const riskDifference =
      riskPriority(left.worstRisk) - riskPriority(right.worstRisk);
    if (riskDifference !== 0) {
      return riskDifference;
    }
    return left.facility.localeCompare(right.facility);
  });
}

function renderRiskMatrix(inventory) {
  clearNode(els.riskHead);
  clearNode(els.riskBody);

  const hasRows = inventory.length > 0;
  toggleTable(els.riskTable, els.riskEmpty, hasRows);

  if (!hasRows) {
    return;
  }

  const facilities = buildFacilityRows(inventory);
  const medicines = uniqueSorted(inventory.map((item) => item.medicine));

  const headerRow = document.createElement("tr");
  headerRow.appendChild(createHeaderCell("Facility", "col"));

  for (const medicine of medicines) {
    headerRow.appendChild(createHeaderCell(medicine, "col"));
  }

  els.riskHead.appendChild(headerRow);

  for (const facility of facilities) {
    const row = document.createElement("tr");

    const header = document.createElement("th");
    header.scope = "row";

    const facilityName = document.createElement("span");
    facilityName.textContent = facility.facility;
    header.appendChild(facilityName);

    const region = document.createElement("span");
    region.className = "region-cell";
    region.textContent = facility.region;
    header.appendChild(document.createElement("br"));
    header.appendChild(region);

    row.appendChild(header);

    for (const medicine of medicines) {
      const item = facility.items.get(medicine);
      const cell = document.createElement("td");

      if (item) {
        cell.appendChild(createMatrixCell(item));
      } else {
        cell.className = "matrix-empty";
        cell.textContent = "—";
      }

      row.appendChild(cell);
    }

    els.riskBody.appendChild(row);
  }
}

function createHeaderCell(text, scope) {
  const cell = document.createElement("th");
  cell.scope = scope;
  cell.textContent = text;
  return cell;
}

function createMatrixCell(item) {
  const wrapper = document.createElement("div");
  wrapper.className = "matrix-cell";
  wrapper.title = [
    `Current stock: ${item.current_stock}`,
    `Monthly consumption: ${item.monthly_consumption}`,
    `Lead time: ${item.lead_time_days} d`,
    `Target cover: ${item.target_days} d`,
  ].join(" · ");

  const chip = document.createElement("span");
  chip.className = "chip";
  chip.dataset.risk = item.stockout_risk;
  chip.textContent = item.stockout_risk;
  wrapper.appendChild(chip);

  const meta = document.createElement("div");
  meta.className = "matrix-meta";

  const coverage = document.createElement("span");
  coverage.textContent = formatDays(item.days_of_stock);

  const target = document.createElement("span");
  target.className = "matrix-metalabel";
  target.textContent = `/ ${formatDays(item.target_days)}`;

  meta.appendChild(coverage);
  meta.appendChild(target);
  wrapper.appendChild(meta);

  const bar = document.createElement("div");
  bar.className = "mini-bar";
  const fill = document.createElement("span");
  fill.className = `bar-${item.stockout_risk.toLowerCase()}`;
  fill.style.width = `${coveragePercent(item)}%`;
  bar.appendChild(fill);
  wrapper.appendChild(bar);

  const expiry = document.createElement("span");
  expiry.className = "expiry-note";
  expiry.dataset.risk = item.expiry_risk;
  expiry.textContent = `Expiry: ${item.expiry_risk} · ${formatDays(
    item.expiry_days,
  )}`;
  wrapper.appendChild(expiry);

  return wrapper;
}

function coveragePercent(item) {
  const target = Number(item.target_days);
  const days = Number(item.days_of_stock);

  if (!Number.isFinite(target) || target <= 0 || !Number.isFinite(days)) {
    return 0;
  }

  return Math.max(0, Math.min(100, (days / target) * 100));
}

function renderRecommendations(recommendations) {
  clearNode(els.recommendationBody);

  const hasRows = recommendations.length > 0;
  toggleTable(els.recommendationTable, els.recommendationEmpty, hasRows);

  if (!hasRows) {
    return;
  }

  for (const item of recommendations) {
    els.recommendationBody.appendChild(createRecommendationRow(item));
  }
}

function createRecommendationRow(item) {
  const row = document.createElement("tr");

  row.appendChild(textCell(item.medicine));

  const routeCell = document.createElement("td");
  const route = document.createElement("div");
  route.className = "route";

  const source = document.createElement("span");
  source.className = "source";
  source.textContent = item.source_facility;

  const arrow = document.createElement("span");
  arrow.className = "arrow";
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "→";

  const destination = document.createElement("span");
  destination.className = "destination";
  destination.textContent = item.destination_facility;

  route.appendChild(source);
  route.appendChild(arrow);
  route.appendChild(destination);
  routeCell.appendChild(route);
  row.appendChild(routeCell);

  const riskCell = document.createElement("td");
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.dataset.risk = item.destination_stockout_risk;
  chip.textContent = item.destination_stockout_risk;
  riskCell.appendChild(chip);
  row.appendChild(riskCell);

  const transfer = textCell(
    formatDays(item.potential_transfer_days),
    "numeric",
  );
  transfer.title = `Destination gap before allocation: ${formatDays(
    item.destination_gap_days,
  )}`;
  row.appendChild(transfer);

  row.appendChild(
    textCell(formatDays(item.destination_remaining_gap_days), "numeric"),
  );

  const surplus = textCell(formatDays(item.source_surplus_days), "numeric");
  surplus.title = `Remaining source surplus: ${formatDays(
    item.source_remaining_surplus_days,
  )} · Reserve kept: ${formatDays(item.source_reserve_days)}`;
  row.appendChild(surplus);

  const expiry = textCell(formatDays(item.source_expiry_days), "numeric");
  expiry.title = "Remaining shelf life of the source batch";
  row.appendChild(expiry);

  const scoreCell = document.createElement("td");
  scoreCell.className = "numeric";
  const score = document.createElement("span");
  score.className = "score";
  score.textContent = formatScore(item.recommendation_score);
  scoreCell.appendChild(score);
  row.appendChild(scoreCell);

  const reviewCell = document.createElement("td");
  const review = document.createElement("span");
  review.className = "review-required";
  review.textContent = item.requires_human_review ? "Required" : "—";
  reviewCell.appendChild(review);
  row.appendChild(reviewCell);

  return row;
}

function textCell(text, className) {
  const cell = document.createElement("td");
  if (className) {
    cell.className = className;
  }
  cell.textContent = text;
  return cell;
}

function toggleTable(table, emptyState, hasRows) {
  const wrapper = table.closest(".table-wrap");

  table.hidden = !hasRows;
  if (wrapper) {
    wrapper.hidden = !hasRows;
  }
  emptyState.hidden = hasRows;
}

function renderGovernance() {
  if (!state.summary || !state.summary.governance) {
    return;
  }

  const governance = state.summary.governance;

  els.governanceNote.textContent = governance.note || "";

  clearNode(els.assumptionsList);
  for (const assumption of governance.assumptions || []) {
    const item = document.createElement("li");
    item.textContent = assumption;
    els.assumptionsList.appendChild(item);
  }

  if (governance.data_type) {
    const label = governance.data_type;
    els.dataBadge.textContent =
      label.charAt(0).toUpperCase() + label.slice(1) + " data";
  }
}

/* ------------------------------------------------------------------ */
/* Explanation                                                         */
/* ------------------------------------------------------------------ */

function setExplanationStatus(message, isError = false) {
  clearNode(els.explanationStatus);
  els.explanationStatus.classList.toggle("is-error", isError);

  if (!message) {
    return;
  }

  if (!isError) {
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    spinner.setAttribute("aria-hidden", "true");
    els.explanationStatus.appendChild(spinner);
  }

  const text = document.createElement("span");
  text.textContent = message;
  els.explanationStatus.appendChild(text);
}

async function generateExplanation() {
  els.explainButton.disabled = true;
  const originalLabel = els.explainButton.textContent;
  els.explainButton.textContent = "Generating…";

  els.guardrailWarnings.hidden = true;
  clearNode(els.guardrailWarnings);
  els.explanationEmpty.hidden = true;
  setExplanationStatus("Generating explanation…");

  try {
    const response = await fetch(ENDPOINTS.explanation, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(await describeError(response));
    }

    const data = await response.json();

    els.explanationOutput.hidden = false;
    renderExplanation(data.explanation || "", els.explanationOutput);

    const warnings = (data.governance || {}).guardrail_warnings || [];
    if (warnings.length > 0) {
      renderGuardrailWarnings(warnings);
    }

    setExplanationStatus("");
  } catch (error) {
    els.explanationOutput.hidden = true;
    els.explanationEmpty.hidden = false;
    setExplanationStatus(error.message, true);
  } finally {
    els.explainButton.disabled = !state.loaded;
    els.explainButton.textContent = originalLabel;
  }
}

function renderGuardrailWarnings(warnings) {
  clearNode(els.guardrailWarnings);

  const heading = document.createElement("strong");
  heading.textContent = "Guardrail warnings";
  els.guardrailWarnings.appendChild(heading);

  const list = document.createElement("ul");
  for (const warning of warnings) {
    const item = document.createElement("li");
    item.textContent = warning;
    list.appendChild(item);
  }

  els.guardrailWarnings.appendChild(list);
  els.guardrailWarnings.hidden = false;
}

/**
 * Render a small, safe subset of Markdown using DOM nodes.
 *
 * Building nodes with textContent means model output can never inject
 * HTML into the page.
 */
function renderExplanation(text, container) {
  clearNode(container);

  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  let paragraph = [];
  let list = null;
  let listTag = null;
  let codeLines = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) {
      return;
    }
    const node = document.createElement("p");
    renderInline(paragraph.join(" "), node);
    container.appendChild(node);
    paragraph = [];
  };

  const flushList = () => {
    if (list) {
      container.appendChild(list);
      list = null;
      listTag = null;
    }
  };

  const flushCode = () => {
    if (codeLines === null) {
      return;
    }
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = codeLines.join("\n");
    pre.appendChild(code);
    container.appendChild(pre);
    codeLines = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.trim().startsWith("```")) {
      flushParagraph();
      flushList();
      if (codeLines === null) {
        codeLines = [];
      } else {
        flushCode();
      }
      continue;
    }

    if (codeLines !== null) {
      codeLines.push(rawLine);
      continue;
    }

    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = /^#{1,6}\s+(.*)$/.exec(line.trim());
    if (headingMatch) {
      flushParagraph();
      flushList();
      // The panel already provides the h2. Normalising every model
      // heading to h3 keeps the document outline sequential regardless
      // of the levels the model chooses.
      const heading = document.createElement("h3");
      renderInline(headingMatch[1], heading);
      container.appendChild(heading);
      continue;
    }

    const bulletMatch = /^[-*•]\s+(.*)$/.exec(line.trim());
    if (bulletMatch) {
      flushParagraph();
      if (!list || listTag !== "ul") {
        flushList();
        list = document.createElement("ul");
        listTag = "ul";
      }
      const item = document.createElement("li");
      renderInline(bulletMatch[1], item);
      list.appendChild(item);
      continue;
    }

    const numberedMatch = /^\d+[.)]\s+(.*)$/.exec(line.trim());
    if (numberedMatch) {
      flushParagraph();
      if (!list || listTag !== "ol") {
        flushList();
        list = document.createElement("ol");
        listTag = "ol";
      }
      const item = document.createElement("li");
      renderInline(numberedMatch[1], item);
      list.appendChild(item);
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  flushCode();
}

function renderInline(text, parent) {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match = pattern.exec(text);

  while (match) {
    if (match.index > lastIndex) {
      parent.appendChild(
        document.createTextNode(text.slice(lastIndex, match.index)),
      );
    }

    const token = match[0];

    if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      parent.appendChild(strong);
    } else {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      parent.appendChild(code);
    }

    lastIndex = match.index + token.length;
    match = pattern.exec(text);
  }

  if (lastIndex < text.length) {
    parent.appendChild(document.createTextNode(text.slice(lastIndex)));
  }
}

/* ------------------------------------------------------------------ */
/* CSV export                                                          */
/* ------------------------------------------------------------------ */

const INVENTORY_COLUMNS = [
  { label: "facility", value: (item) => item.facility },
  { label: "region", value: (item) => item.region },
  { label: "medicine", value: (item) => item.medicine },
  { label: "current_stock", value: (item) => item.current_stock },
  {
    label: "monthly_consumption",
    value: (item) => item.monthly_consumption,
  },
  { label: "lead_time_days", value: (item) => item.lead_time_days },
  { label: "expiry_days", value: (item) => item.expiry_days },
  { label: "days_of_stock", value: (item) => item.days_of_stock },
  { label: "target_days", value: (item) => item.target_days },
  { label: "stockout_risk", value: (item) => item.stockout_risk },
  { label: "expiry_risk", value: (item) => item.expiry_risk },
];

const RECOMMENDATION_COLUMNS = [
  { label: "medicine", value: (item) => item.medicine },
  { label: "source_facility", value: (item) => item.source_facility },
  {
    label: "destination_facility",
    value: (item) => item.destination_facility,
  },
  {
    label: "destination_stockout_risk",
    value: (item) => item.destination_stockout_risk,
  },
  {
    label: "potential_transfer_days",
    value: (item) => item.potential_transfer_days,
  },
  {
    label: "destination_gap_days",
    value: (item) => item.destination_gap_days,
  },
  {
    label: "destination_remaining_gap_days",
    value: (item) => item.destination_remaining_gap_days,
  },
  {
    label: "source_surplus_days",
    value: (item) => item.source_surplus_days,
  },
  {
    label: "source_remaining_surplus_days",
    value: (item) => item.source_remaining_surplus_days,
  },
  { label: "source_expiry_days", value: (item) => item.source_expiry_days },
  {
    label: "recommendation_score",
    value: (item) => item.recommendation_score,
  },
  {
    label: "requires_human_review",
    value: (item) => item.requires_human_review,
  },
];

function csvEscape(value) {
  const text = value === null || value === undefined ? "" : String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function downloadCsv(filename, columns, rows) {
  if (rows.length === 0) {
    return;
  }

  const lines = [columns.map((column) => csvEscape(column.label)).join(",")];

  for (const row of rows) {
    lines.push(
      columns
        .map((column) => csvEscape(column.value(row)))
        .join(","),
    );
  }

  const blob = new Blob([`\uFEFF${lines.join("\r\n")}`], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function timestampForFilename() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    "-",
    pad(now.getHours()),
    pad(now.getMinutes()),
  ].join("");
}

function exportInventory() {
  downloadCsv(
    `inventory-${timestampForFilename()}.csv`,
    INVENTORY_COLUMNS,
    getFilteredInventory(),
  );
}

function exportRecommendations() {
  downloadCsv(
    `redistribution-candidates-${timestampForFilename()}.csv`,
    RECOMMENDATION_COLUMNS,
    getFilteredRecommendations(),
  );
}

/* ------------------------------------------------------------------ */
/* Loading and errors                                                  */
/* ------------------------------------------------------------------ */

function setLoading(isLoading) {
  document.body.classList.toggle("is-loading", isLoading);
  els.main.setAttribute("aria-busy", String(isLoading));
  els.refreshButton.disabled = isLoading;
  els.explainButton.disabled = isLoading || !state.loaded;
  els.mlPredict.disabled = isLoading || !state.loaded;

  if (isLoading) {
    els.refreshButton.textContent = "Refreshing…";
  } else {
    els.refreshButton.textContent = "Refresh";
  }
}

function showError(message) {
  els.errorBanner.textContent = message;
  els.errorBanner.hidden = false;
}

function hideError() {
  els.errorBanner.textContent = "";
  els.errorBanner.hidden = true;
}

async function describeError(response) {
  try {
    const body = await response.json();
    if (body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch (error) {
    // Fall through to the generic message.
  }
  return `Request failed with status ${response.status}.`;
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await describeError(response));
  }

  return response.json();
}

async function loadData() {
  setLoading(true);
  hideError();

  try {
    const [summary, inventory, recommendations] = await Promise.all([
      fetchJson(ENDPOINTS.summary),
      fetchJson(ENDPOINTS.inventory),
      fetchJson(ENDPOINTS.recommendations),
    ]);

    state.summary = summary;
    state.inventory = Array.isArray(inventory) ? inventory : [];
    state.recommendations = Array.isArray(recommendations)
      ? recommendations
      : [];
    state.facilityRegion = new Map(
      state.inventory.map((item) => [item.facility, item.region]),
    );
    state.loaded = true;

    populateFilters();
    populateMlControls();
    syncUrl();
    renderGovernance();
    render();

    els.explainButton.disabled = false;
    els.lastUpdated.textContent = `Last updated ${new Date().toLocaleString()}`;
  } catch (error) {
    state.loaded = false;
    els.explainButton.disabled = true;
    els.exportInventory.disabled = true;
    els.exportRecommendations.disabled = true;
    showError(
      `Could not load the analysis: ${error.message} ` +
        "Check that the API is running, then select Refresh.",
    );
  } finally {
    setLoading(false);
  }
}

/* ------------------------------------------------------------------ */
/* Wiring                                                              */
/* ------------------------------------------------------------------ */

let searchTimer = null;

function wireEvents() {
  els.refreshButton.addEventListener("click", loadData);

  els.filterRegion.addEventListener("change", applyFiltersFromControls);
  els.filterMedicine.addEventListener("change", applyFiltersFromControls);
  els.filterRisk.addEventListener("change", applyFiltersFromControls);

  els.filterSearch.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(applyFiltersFromControls, 150);
  });

  els.clearFilters.addEventListener("click", clearFilters);

  els.exportInventory.addEventListener("click", exportInventory);
  els.exportRecommendations.addEventListener(
    "click",
    exportRecommendations,
  );

  els.explainButton.addEventListener("click", generateExplanation);

  els.mlFacility.addEventListener("change", populateMlMedicines);
  els.mlMedicine.addEventListener("change", syncMlInputsFromSelection);
  els.mlForm.addEventListener("submit", (event) => {
    event.preventDefault();
    requestPrediction();
  });
}

function init() {
  cacheElements();
  readFiltersFromUrl();
  wireEvents();
  loadData();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
