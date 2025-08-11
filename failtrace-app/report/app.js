(function(){
  const r = (typeof REPORT === "object" && REPORT) ? REPORT : {};
  const proj = r.project || {};
  const metrics = r.metrics || {};
  const charts = r.charts || {};
  const t = charts.testsOverview || {};
  const ftypes = Array.isArray(charts.failureTypes) ? charts.failureTypes : [];
  const coverage = charts.coverageBars || {};
  const insights = Array.isArray(r.insights) ? r.insights : [];
  const risks = Array.isArray(r.risks) ? r.risks : [];
  const failures = Array.isArray(r.failures) ? r.failures : [];

  // Header
  document.getElementById('projMeta').textContent = (proj.name ? proj.name + " • " : "");
  document.getElementById('runDate').textContent = proj.date || '';

  // KPIs
  document.getElementById('kTotal').textContent = metrics.total ?? 0;
  document.getElementById('kPassed').textContent = t.passed ?? metrics.passed ?? 0;
  document.getElementById('kFailed').textContent = t.failed ?? metrics.failed ?? 0;
  document.getElementById('kSkipped').textContent = t.skipped ?? metrics.skipped ?? 0;

  // Insights
  const insEl = document.getElementById('insights');
  insights.forEach(x=>{
    const d = document.createElement('span');
    d.className = 'pill';
    d.textContent = `${x.title || ''}${x.detail ? ' — ' + x.detail : ''}`.trim();
    insEl.appendChild(d);
  });

  // Risks (global + per-failure severity)
  const riskEl = document.getElementById('risks');
  // Global risks
  risks.forEach(x=>{
    const d = document.createElement('span');
    d.className = `pill ${ (x.level||'').toLowerCase() }`;
    const level = x.level ? `Level: ${x.level}` : '';
    const title = x.title ? ` — ${x.title}` : '';
    const action = x.action ? ` — Action: ${x.action}` : '';
    d.textContent = `${level}${title}${action}`.trim();
    riskEl.appendChild(d);
  });
  // Per-failure risks derived from severity
  failures.forEach(it=>{
    const sev = (it.severity||'').toLowerCase();
    if (!sev) return;
    const d = document.createElement('span');
    d.className = `pill ${sev}`;
    d.textContent = `Level: ${sev} — Test: ${it.title}`;
    riskEl.appendChild(d);
  });

  // Failures table
  const tbody = document.querySelector('#failTable tbody');
  failures.forEach(item=>{
    const tr = document.createElement('tr');

    const fixes = Array.isArray(item.suggested_fixes) ? item.suggested_fixes : [];
    const fixesWrap = document.createElement('div');
    fixesWrap.className = 'fix-list';
    fixes.forEach(s=>{
      const tag = document.createElement('span');
      tag.className = 'fix-badge';
      tag.textContent = s;
      fixesWrap.appendChild(tag);
    });

    const tdTest = document.createElement('td'); tdTest.textContent = item.title || '';
    const tdRoot = document.createElement('td'); tdRoot.textContent = item.root_cause || '';
    const tdLoc  = document.createElement('td'); tdLoc.textContent = item.location || item.file || '';
    const tdErr  = document.createElement('td'); tdErr.textContent = item.message || '';
    const tdFix  = document.createElement('td'); tdFix.appendChild(fixesWrap);

    tr.appendChild(tdTest);
    tr.appendChild(tdRoot);
    tr.appendChild(tdLoc);
    tr.appendChild(tdErr);
    tr.appendChild(tdFix);
    tbody.appendChild(tr);
  });

  // Reasoning (already high-level from renderer)
  document.getElementById('trace').textContent = r.trace || '';

  // Charts
  const ctx1 = document.getElementById('testsOverviewChart').getContext('2d');
  new Chart(ctx1,{
    type:'doughnut',
    data:{
      labels:['Passed','Failed','Skipped'],
      datasets:[{
        data:[
          Number(t.passed||0),
          Number(t.failed||0),
          Number(t.skipped||0)
        ],
        backgroundColor:['#16a34a','#ef4444','#f59e0b']
      }]
    },
    options:{
      responsive:true,
      plugins:{legend:{position:'bottom',labels:{color:'#cfe0f0'}}}
    }
  });

  const ctx2 = document.getElementById('failureTypesChart').getContext('2d');
  const labels = ftypes.map(x=>x.type||'Unknown');
  const data = ftypes.map(x=>Number(x.count||0));
  const palette = [
    '#60a5fa','#f472b6','#34d399','#fbbf24','#c084fc','#f87171',
    '#93c5fd','#fca5a5','#a7f3d0','#fde68a'
  ];
  new Chart(ctx2,{
    type:'bar',
    data:{
      labels,
      datasets:[{
        data,
        backgroundColor: labels.map((_,i)=>palette[i % palette.length]),
        borderWidth: 0
      }]
    },
    options:{
      responsive:true,
      scales:{
        x:{ticks:{color:'#cfe0f0'}},
        y:{ticks:{color:'#cfe0f0'},beginAtZero:true,precision:0}
      },
      plugins:{legend:{display:false}}
    }
  });

  // Coverage Bars (Lines vs Branches)
  const covEl = document.getElementById('coverageChart').getContext('2d');
  new Chart(covEl,{
    type:'bar',
    data:{
      labels:['Lines','Branches'],
      datasets:[{
        data:[
          Number(coverage.lines||0),
          Number(coverage.branches||0)
        ],
        backgroundColor:['#38bdf8','#a78bfa'],
        borderWidth:0
      }]
    },
    options:{
      responsive:true,
      scales:{
        x:{ticks:{color:'#cfe0f0'}},
        y:{ticks:{color:'#cfe0f0'},beginAtZero:true,max:100}
      },
      plugins:{legend:{display:false}}
    }
  });

})();
