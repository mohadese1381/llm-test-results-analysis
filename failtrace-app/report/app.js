(function () {
  const r = typeof REPORT === "object" && REPORT ? REPORT : {};
  const proj = r.project || {};
  const metrics = r.metrics || {};
  const charts = r.charts || {};
  const t = charts.testsOverview || {};
  const ftypes = Array.isArray(charts.failureTypes) ? charts.failureTypes : [];
  const insights = Array.isArray(r.insights) ? r.insights : [];
  const failures = Array.isArray(r.failures) ? r.failures : [];
  const bubbles = Array.isArray(charts.riskBubbles) ? charts.riskBubbles : [];

  // Header
  document.getElementById("projName").textContent = proj.name || "—";
  document.getElementById("runDate").textContent = proj.date || "";

  // KPIs
  document.getElementById("kTotal").textContent = metrics.total ?? 0;
  document.getElementById("kPassed").textContent =
    t.passed ?? metrics.passed ?? 0;
  document.getElementById("kFailed").textContent =
    t.failed ?? metrics.failed ?? 0;
  document.getElementById("kSkipped").textContent =
    t.skipped ?? metrics.skipped ?? 0;

  // Insights table
  const insTBody = document.querySelector("#insightsTable tbody");
  insights.forEach((x) => {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    td1.textContent = x.title || "";
    const td2 = document.createElement("td");
    td2.textContent = x.detail || "";
    tr.append(td1, td2);
    insTBody.appendChild(tr);
  });

  // Failures table
  const tbody = document.querySelector("#failTable tbody");
  failures.forEach((item) => {
    const tr = document.createElement("tr");

    const fixes = Array.isArray(item.suggested_fixes)
      ? item.suggested_fixes
      : [];
    const fixesWrap = document.createElement("div");
    fixesWrap.className = "fix-list";
    fixes.forEach((s) => {
      const tag = document.createElement("span");
      tag.className = "fix-badge";
      tag.textContent = s;
      fixesWrap.appendChild(tag);
    });

    let locationText = "";
    if (Array.isArray(item.functions) && item.functions.length) {
      locationText = item.functions.join(", ");
    } else if (item.location) {
      locationText = item.location;
    } else if (item.file) {
      locationText = item.file;
    }

    const tdTest = document.createElement("td");
    tdTest.textContent = item.title || "";
    const tdRoot = document.createElement("td");
    tdRoot.textContent = item.root_cause || "";
    const tdLoc = document.createElement("td");
    tdLoc.textContent = locationText;
    const tdErr = document.createElement("td");
    tdErr.textContent = item.message || "";
    const tdFix = document.createElement("td");
    tdFix.appendChild(fixesWrap);

    tr.append(tdTest, tdRoot, tdLoc, tdErr, tdFix);
    tbody.appendChild(tr);
  });

  // Charts
  const ctx1 = document.getElementById("testsOverviewChart").getContext("2d");
  new Chart(ctx1, {
    type: "doughnut",
    data: {
      labels: ["Passed", "Failed", "Skipped"],
      datasets: [
        {
          data: [
            Number(t.passed || 0),
            Number(t.failed || 0),
            Number(t.skipped || 0),
          ],
          backgroundColor: ["#19a974", "#ef4444", "#f59e0b"],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#cfe0f0" } } },
      layout: { padding: 8 },
    },
  });

  const ctx2 = document.getElementById("failureTypesChart").getContext("2d");
  const labels = ftypes.map((x) => x.type || "Unknown");
  const data = ftypes.map((x) => Number(x.count || 0));
  const palette = [
    "#60a5fa",
    "#f472b6",
    "#34d399",
    "#fbbf24",
    "#c084fc",
    "#f87171",
    "#93c5fd",
    "#fca5a5",
    "#a7f3d0",
    "#fde68a",
  ];
  new Chart(ctx2, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          data,
          backgroundColor: labels.map((_, i) => palette[i % palette.length]),
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#cfe0f0" } },
        y: { ticks: { color: "#cfe0f0" }, beginAtZero: true, precision: 0 },
      },
      plugins: { legend: { display: false } },
      layout: { padding: { top: 6, right: 6, bottom: 6, left: 6 } },
    },
  });

  // Risk bubbles (only Probability, Impact, Risk in tooltip)
  const ctx3 = document.getElementById("riskBubblesChart").getContext("2d");
  const sevColor = (s) => {
    const v = String(s || "").toLowerCase();
    if (v === "high") return "#ef4444";
    if (v === "medium") return "#f59e0b";
    return "#19a974";
  };
  new Chart(ctx3, {
    type: "bubble",
    data: {
      datasets: [
        {
          label: "Risks",
          data: bubbles.map((b) => ({
            x: Number(b.probability || 0),
            y: Number(b.impact || 0),
            r: Number(b.r || 10),
          })),
          backgroundColor: bubbles.map((b) => sevColor(b.risk)),
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          min: 0,
          max: 100,
          title: {
            display: true,
            text: "Failure Probability (%)",
            color: "#cfe0f0",
          },
          ticks: { color: "#cfe0f0" },
          grid: { color: "rgba(207,224,240,0.08)" },
        },
        y: {
          min: 0,
          max: 100,
          title: { display: true, text: "Impact (%)", color: "#cfe0f0" },
          ticks: { color: "#cfe0f0" },
          grid: { color: "rgba(207,224,240,0.08)" },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: () => "", // no title
            label: (ctx) => {
              const item = bubbles[ctx.dataIndex] || {};
              const p = Math.round(Number(item.probability || 0));
              const i = Math.round(Number(item.impact || 0));
              const risk = (item.risk || "").toString().toUpperCase();
              return [`Probability: ${p}%`, `Impact: ${i}%`, `Risk: ${risk}`];
            },
          },
        },
      },
      layout: { padding: { top: 6, right: 6, bottom: 6, left: 6 } },
    },
  });
})();
