(function () {
  const r = typeof REPORT === "object" && REPORT ? REPORT : {};
  const proj = r.project || {};
  const metrics = r.metrics || {};
  const charts = r.charts || {};
  const t = charts.testsOverview || {};
  const ftypes = Array.isArray(charts.failureTypes) ? charts.failureTypes : [];
  const insights = Array.isArray(r.insights) ? r.insights : [];
  const failures = Array.isArray(r.failures) ? r.failures : [];
  let bubbles = Array.isArray(charts.riskBubbles) ? charts.riskBubbles : [];

  const toPretty = (s) =>
    String(s || "")
      .replace(/::/g, ">")
      .replace(/\//g, ">")
      .replace(/\\/g, ">")
      .replace(/>{2,}/g, ">")
      .replace(/^\s*>|>\s*$/g, "")
      .trim();

  const uniq = (arr) => Array.from(new Set(arr || []));

  const cleanTestTitle = (s) => {
    const str = String(s || "").trim();
    if (!str) return "";
    const byDblColon = str.split("::");
    let last = byDblColon[byDblColon.length - 1] || str;

    if (last.includes("/") || last.includes("\\") || last.includes(">")) {
      const tmp = last.replace(/\\/g, "/").split("/");
      last = tmp[tmp.length - 1] || last;
    }
    if (last.includes(".")) {
      const tmp = last.split(".");
      last = tmp[tmp.length - 1] || last;
    }
    return last.trim();
  };

  const toBullets = (detail) => {
    if (Array.isArray(detail)) {
      return detail.map((x) => String(x || "").trim()).filter(Boolean);
    }
    const s = String(detail || "").trim();
    if (!s) return [];
    const lines = s
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length > 1) return lines;
    const parts = s
      .split(/(?:\s*•\s*|\s*-\s*)/)
      .map((x) => x.trim())
      .filter(Boolean);
    if (parts.length > 1) return parts;
    return [s];
  };

  document.getElementById("projName").textContent = proj.name || "—";
  document.getElementById("runDate").textContent = proj.date || "";

  document.getElementById("kTotal").textContent = metrics.total ?? 0;
  document.getElementById("kPassed").textContent =
    t.passed ?? metrics.passed ?? 0;
  document.getElementById("kFailed").textContent =
    t.failed ?? metrics.failed ?? 0;
  document.getElementById("kSkipped").textContent =
    t.skipped ?? metrics.skipped ?? 0;

  const insTBody = document.querySelector("#insightsTable tbody");
  insights.forEach((x) => {
    const tr = document.createElement("tr");

    const td1 = document.createElement("td");
    td1.textContent = cleanTestTitle(x.title || "");

    const td2 = document.createElement("td");
    const bullets = toBullets(x.detail);
    if (bullets.length > 1) {
      const ul = document.createElement("ul");
      ul.style.margin = "0";
      ul.style.paddingInlineStart = "18px";
      bullets.forEach((b) => {
        const li = document.createElement("li");
        li.textContent = b;
        ul.appendChild(li);
      });
      td2.appendChild(ul);
    } else {
      td2.textContent = bullets[0] || "";
    }

    tr.append(td1, td2);
    insTBody.appendChild(tr);
  });

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

    const layers = item.location_layers || {};
    const lHeu = Array.isArray(layers.heuristic) ? layers.heuristic : [];
    const lGraph = Array.isArray(layers.graph_ranked)
      ? layers.graph_ranked
      : [];
    const lLlm = Array.isArray(layers.llm) ? layers.llm : [];

    let fallbackLocText = "";
    if (!layers || (!lHeu.length && !lGraph.length && !lLlm.length)) {
      let locParts = [];
      if (Array.isArray(item.functions) && item.functions.length) {
        locParts.push("Suggested: " + toPretty(uniq(item.functions).join(", ")));
      }
      if (item.location) {
        locParts.push(toPretty(item.location));
      } else if (item.file) {
        locParts.push(toPretty(item.file));
      }
      fallbackLocText = locParts.join("  |  ");
    }

    const tdTest = document.createElement("td");
    tdTest.textContent = item.title || "";
    const tdRoot = document.createElement("td");
    tdRoot.textContent = item.root_cause || "";

    const tdLoc = document.createElement("td");
    if (fallbackLocText) {
      tdLoc.textContent = fallbackLocText;
    } else {
      const block = document.createElement("div");
      block.style.display = "flex";
      block.style.flexDirection = "column";
      block.style.gap = "6px";

      const makeLayer = (priority, label, arr, color) => {
        if (!arr || !arr.length) return null;
        const wrap = document.createElement("div");
        wrap.style.border = `1px solid ${color}`;
        wrap.style.borderRadius = "8px";
        wrap.style.padding = "6px 8px";

        const title = document.createElement("div");
        title.style.display = "flex";
        title.style.alignItems = "center";
        title.style.gap = "8px";
        title.style.marginBottom = "6px";

        const badge = document.createElement("span");
        badge.textContent = `Priority ${priority}`;
        badge.style.fontSize = "11px";
        badge.style.padding = "2px 6px";
        badge.style.border = `1px solid ${color}`;
        badge.style.borderRadius = "6px";
        badge.style.opacity = "0.9";

        const txt = document.createElement("span");
        txt.textContent = label;
        txt.style.fontSize = "12px";
        txt.style.opacity = "0.85";
        txt.style.whiteSpace = "nowrap"; // keep title in one row

        title.appendChild(badge);
        title.appendChild(txt);

        const list = document.createElement("div");
        list.style.display = "flex";
        list.style.flexDirection = "column";
        list.style.gap = "4px";

        arr.forEach((s) => {
          const line = document.createElement("div");
          line.textContent = toPretty(String(s || ""));
          line.style.fontSize = "12px";
          list.appendChild(line);
        });

        wrap.appendChild(title);
        wrap.appendChild(list);
        return wrap;
      };

      // ⬇️ shorter labels so Priority 1 & 2 stay on one line (like "LLM Suggestion")
      const gBlock = makeLayer(1, "Graph Match", lGraph, "#60a5fa");
      const hBlock = makeLayer(2, "Error Clues", lHeu, "#34d399");
      const lBlock = makeLayer(3, "LLM Suggestion", lLlm, "#f59e0b");

      [gBlock, hBlock, lBlock].forEach((el) => el && block.appendChild(el));
      tdLoc.appendChild(block);
    }

    const tdErr = document.createElement("td");
    tdErr.textContent = item.message || "";
    const tdFix = document.createElement("td");
    tdFix.appendChild(fixesWrap);

    tr.append(tdTest, tdRoot, tdLoc, tdErr, tdFix);
    tbody.appendChild(tr);
  });

  const failWrap = document.getElementById("failWrap");
  if (failWrap) {
    const failRows = tbody.querySelectorAll("tr").length;
    if (failRows <= 4) {
      failWrap.classList.remove("table-wrap--fail-scroll");
      failWrap.classList.add("table-wrap--fail-auto");
    } else {
      failWrap.classList.remove("table-wrap--fail-auto");
      failWrap.classList.add("table-wrap--fail-scroll");
    }
  }

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

  bubbles = bubbles
    .slice()
    .map((b) => {
      const parts = String(b.test_name || "").split("::");
      const onlyMethod = parts.length ? parts[parts.length - 1] : "";
      const rr = Math.max(8, Math.min(Number(b.r || 10), 18));
      return { ...b, __name: onlyMethod, _r: rr };
    })
    .sort((a, b) => a.__name.localeCompare(b.__name));

  const ctx3 = document.getElementById("riskBubblesChart").getContext("2d");
  const sevColor = (s) => {
    const v = String(s || "").toLowerCase();
    if (v === "high") return "#ef4444";
    if (v === "medium") return "#f59e0b";
    return "#19a974";
  };
  const sevBorder = (s) => {
    const v = String(s || "").toLowerCase();
    if (v === "high") return "rgba(239,68,68,0.9)";
    if (v === "medium") return "rgba(245,158,11,0.95)";
    return "rgba(25,169,116,0.9)";
  };

  new Chart(ctx3, {
    type: "bubble",
    data: {
      datasets: [
        {
          data: bubbles.map((b) => ({
            x: Number(b.probability || 0),
            y: Number(b.impact || 0),
            r: Number(b._r || 10),
          })),
          backgroundColor: bubbles.map((b) => sevColor(b.risk)),
          borderColor: bubbles.map((b) => sevBorder(b.risk)),
          borderWidth: 1,
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
            title: (ctx) => {
              const idx = ctx[0]?.dataIndex ?? 0;
              return bubbles[idx]?.__name || "";
            },
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
