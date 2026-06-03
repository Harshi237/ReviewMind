/**
 * dashboard.js – Main dashboard controller
 * Reads package/period from sessionStorage, calls all three model APIs,
 * and populates every section of the dashboard.
 */

// ── Global state ─────────────────────────────────────────────────────────────
let STATE = {
  packageName:    null,
  period:         '30d',
  analyzeResult:  null,
  trendsData:     null,
  prioritiesData: null,
  emergingData:   null,
};

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {

  STATE.packageName = sessionStorage.getItem('rma_package');
  STATE.period      = sessionStorage.getItem('rma_period') || '30d';

  const stored = sessionStorage.getItem('rma_analyzeResult');
  if (stored) {
    try { STATE.analyzeResult = JSON.parse(stored); } catch(e) {}
  }

  const urlParams = new URLSearchParams(window.location.search);
  const urlPkg    = urlParams.get('pkg');
  if (urlPkg) {
    STATE.packageName = urlPkg;
    sessionStorage.setItem('rma_package', urlPkg);
  }

  if (STATE.packageName) {
    document.getElementById('topbarPackage').textContent = STATE.packageName;
    document.getElementById('periodSelect').value = STATE.period;
    setupSidebarNav();
    await loadDashboard();
  } else {
    showNoData();
    setupSidebarNav();
  }
});

// ── Sidebar navigation ────────────────────────────────────────────────────────
function setupSidebarNav() {
  document.querySelectorAll('.nav-item[data-section]').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      const section = link.dataset.section;
      document.querySelectorAll('.nav-item').forEach(l => l.classList.remove('active'));
      link.classList.add('active');
      const el = document.getElementById(section);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      // Close sidebar on mobile
      document.getElementById('sidebar').classList.remove('open');
    });
  });
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// ── Loading state ──────────────────────────────────────────────────────────────
function showLoading(text = 'Loading dashboard…') {
  document.getElementById('loadingText').textContent = text;
  document.getElementById('loadingOverlay').classList.remove('d-none');
  document.getElementById('dashboardContent').classList.add('d-none');
  document.getElementById('noDataState').classList.add('d-none');
}

function hideLoading() {
  document.getElementById('loadingOverlay').classList.add('d-none');
}

function showNoData() {
  document.getElementById('noDataState').classList.remove('d-none');
  document.getElementById('dashboardContent').classList.add('d-none');
  hideLoading();
  // Pre-fill package name if we have one
  const qp = document.getElementById('quickPackage');
  if (qp && STATE.packageName && !qp.value) qp.value = STATE.packageName;
}

function showDashboard() {
  document.getElementById('dashboardContent').classList.remove('d-none');
  document.getElementById('noDataState').classList.add('d-none');
  hideLoading();
}

// ── Main loader ───────────────────────────────────────────────────────────────
async function loadDashboard() {
  showLoading('Loading dashboard…');

  try {
    document.getElementById('loadingText').textContent = 'Fetching trends and priorities…';

    const [trendsResult, prioritiesResult, emergingResult] = await Promise.allSettled([
      Api.getTrends(STATE.packageName, STATE.period),
      Api.getPriorities(STATE.packageName, STATE.period),
      Api.getEmerging(STATE.packageName, STATE.period),
    ]);

    if (trendsResult.status === 'fulfilled') {
      STATE.trendsData = trendsResult.value;
    } else {
      console.warn('Trends API failed:', trendsResult.reason?.message);
    }

    if (prioritiesResult.status === 'fulfilled') {
      STATE.prioritiesData = prioritiesResult.value;
    } else {
      console.warn('Priorities API failed:', prioritiesResult.reason?.message);
    }

    if (emergingResult.status === 'fulfilled') {
      STATE.emergingData = emergingResult.value;
    } else {
      console.warn('Emerging API failed:', emergingResult.reason?.message);
    }

    if (!STATE.trendsData && !STATE.prioritiesData) {
      showNoData();
      const msg = document.getElementById('noDataMsg');
      if (msg) msg.textContent = 'Could not load data. Wait a moment and click Analyze again.';
      return;
    }

    renderAll();
    showDashboard();

  } catch (err) {
    console.error('Dashboard load error:', err);
    showNoData();
  }
}

// ── Render all sections ────────────────────────────────────────────────────────
function renderAll() {
  renderOverview();
  renderAnalysis();
  renderTrends();
  renderPriorities();
  renderReports();
}

// ── OVERVIEW ──────────────────────────────────────────────────────────────────
function renderOverview() {
  const td = STATE.trendsData;
  if (!td) return;

  document.getElementById('overviewPeriodLabel').textContent = `Last ${td.period}`;

  // Stat cards
  document.getElementById('statTotal').textContent    = td.totalReviews.toLocaleString();
  document.getElementById('statPositive').textContent = `${td.sentiment.positive}%`;
  document.getElementById('statNegative').textContent = `${td.sentiment.negative}%`;
  document.getElementById('statNeutral').textContent  = `${td.sentiment.neutral}%`;

  // Change indicators
  if (td.sentiment.change) {
    setChangeEl('changePositive', td.sentiment.change.positive);
    setChangeEl('changeNegative', td.sentiment.change.negative);
    setChangeEl('changeNeutral',  td.sentiment.change.neutral);
  }

  // Charts
  Charts.renderSentimentPie(td.sentiment.positive, td.sentiment.negative, td.sentiment.neutral);
  Charts.renderFeedbackBar(td.feedbackTypes);
}

function setChangeEl(id, value) {
  const el = document.getElementById(id);
  if (!el || value === undefined) return;
  const abs   = Math.abs(value).toFixed(1);
  const up    = value > 0;
  el.textContent = `${up ? '▲' : '▼'} ${abs}pp`;
  el.className = `stat-change ${up ? 'up' : 'down'}`;
}

// ── ANALYSIS (Model 1) ─────────────────────────────────────────────────────────
function renderAnalysis() {
  const td = STATE.trendsData;
  const ar = STATE.analyzeResult;

  // Top issues chart from trends data
  if (td && td.topIssues && td.topIssues.length) {
    Charts.renderTopIssues(td.topIssues);
  }

  // Reviews table from analyzeResult (Model 1 response)
  if (ar && ar.reviews && ar.reviews.length) {
    document.getElementById('reviewTableSub').textContent = `${ar.reviews.length} reviews`;
    renderReviewsTable(ar.reviews);
  } else {
    document.getElementById('reviewsTableBody').innerHTML =
      '<tr><td colspan="6" class="text-center text-muted py-4">No review data available. Run an analysis first.</td></tr>';
  }
}

function renderReviewsTable(reviews) {
  const tbody = document.getElementById('reviewsTableBody');
  if (!reviews.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No reviews.</td></tr>';
    return;
  }

  tbody.innerHTML = reviews.slice(0, 50).map(r => {
    const date     = r.date ? r.date.substring(0, 10) : '—';
    const text     = escHtml(truncate(r.review, 80));
    const summary  = escHtml(r.summary || '—');
    const sentBadge= sentimentBadge(r.sentiment);
    const stars    = '★'.repeat(r.score || 0) + '☆'.repeat(5 - (r.score || 0));

    return `<tr>
      <td class="text-muted" style="white-space:nowrap">${date}</td>
      <td>${text}</td>
      <td>${sentBadge}</td>
      <td><span class="text-muted" style="font-size:12px">${escHtml(r.feedbackType || '—')}</span></td>
      <td style="color:#f59e0b;font-size:13px;white-space:nowrap">${stars}</td>
      <td style="font-size:12px;color:#6b7280">${summary}</td>
    </tr>`;
  }).join('');
}

// ── TRENDS (Model 2) ──────────────────────────────────────────────────────────
function renderTrends() {
  const td = STATE.trendsData;
  const ed = STATE.emergingData;

  if (td) {
    document.getElementById('trendSummaryText').textContent = td.trendSummary || 'No summary available.';
    Charts.renderFeedbackDoughnut(td.feedbackTypes);

    // Sentiment change indicators
    if (td.sentiment.change) {
      renderChangeVal('changePos', td.sentiment.change.positive, 'positive');
      renderChangeVal('changeNeg', td.sentiment.change.negative, 'negative');
      renderChangeVal('changeNeu', td.sentiment.change.neutral,  'neutral');
    }
  }

  // Emerging issues
  const container = document.getElementById('emergingIssuesList');
  if (ed && ed.issues && ed.issues.length) {
    container.innerHTML = ed.issues.map(issue => `
      <div class="emerging-item">
        <div>
          <div class="emerging-name">${escHtml(issue.issue)}</div>
          <div class="emerging-meta">Recent: ${issue.recentCount} · Previous: ${issue.previousCount}</div>
        </div>
        <span class="trend-badge ${issue.trend.toLowerCase()}">${issue.trend}</span>
      </div>
    `).join('');
  } else {
    container.innerHTML = '<div class="text-muted text-center py-4" style="font-size:13px">No emerging issues detected in this period.</div>';
  }
}

function renderChangeVal(id, value, type) {
  const el = document.getElementById(id);
  if (!el) return;
  const sign = value >= 0 ? '+' : '';
  el.textContent = `${sign}${value}pp`;
}

// ── PRIORITIES (Model 3) ───────────────────────────────────────────────────────
function renderPriorities() {
  const pd = STATE.prioritiesData;
  if (!pd) {
    document.getElementById('priorityTableBody').innerHTML =
      '<tr><td colspan="7" class="text-center text-muted py-4">No priority data available.</td></tr>';
    document.getElementById('recommendationsList').innerHTML =
      '<div class="text-muted text-center py-4">No recommendations available.</div>';
    return;
  }

  renderPositiveHighlights(pd.positiveHighlights || []);
  renderPriorityTable(pd.topPriorityIssues || []);
  renderRecommendations(pd.recommendations || []);
  Charts.renderFeaturesChart(pd.topFeatureRequests || []);
}

function renderPositiveHighlights(highlights) {
  const container = document.getElementById('positiveHighlightsList');
  if (!container) return;

  if (!highlights.length) {
    container.innerHTML = '<div class="text-muted" style="font-size:13px">No positive highlights detected in this period.</div>';
    return;
  }

  container.innerHTML = highlights.map(h => `
    <span class="positive-chip">
      <i class="bi bi-star-fill" style="font-size:11px"></i>
      ${escHtml(h.highlight)}
      <span class="chip-count">${h.count}</span>
    </span>
  `).join('');
}

function renderPriorityTable(issues) {
  const tbody = document.getElementById('priorityTableBody');
  if (!issues.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No priority issues found.</td></tr>';
    return;
  }

  tbody.innerHTML = issues.map((issue, idx) => {
    const rankClass  = idx === 0 ? 'gold' : idx === 1 ? 'silver' : idx === 2 ? 'bronze' : '';
    const scorePct   = Math.round(issue.priorityScore);
    const growthSign = issue.growthPercent >= 0 ? '+' : '';
    const growthCls  = issue.growthPercent > 10 ? 'up' : issue.growthPercent < -10 ? 'down' : 'flat';

    return `<tr>
      <td><span class="rank-badge ${rankClass}">${issue.rank}</span></td>
      <td>
        <div style="font-weight:600;font-size:13px">${escHtml(issue.issue)}</div>
        ${issue.cluster && issue.cluster !== issue.issue ? `<div style="font-size:11px;color:#9ca3af">${escHtml(issue.cluster)}</div>` : ''}
      </td>
      <td>
        <div class="score-bar-wrap">
          <div class="score-bar"><div class="score-bar-fill" style="width:${scorePct}%"></div></div>
          <span class="score-num">${scorePct}</span>
        </div>
      </td>
      <td><span class="severity-badge severity-${issue.severity.toLowerCase()}">${issue.severity}</span></td>
      <td>
        <div style="font-weight:600">${issue.affectedUsers}</div>
        <div style="font-size:11px;color:#9ca3af">${issue.affectedPercent}% of reviews</div>
      </td>
      <td><span class="growth-badge growth-${growthCls}">${growthSign}${issue.growthPercent}%</span></td>
      <td style="font-size:12px;color:#6b7280">${escHtml(issue.feedbackType)}</td>
    </tr>`;
  }).join('');
}

function renderRecommendations(recs) {
  const container = document.getElementById('recommendationsList');
  if (!recs.length) {
    container.innerHTML = '<div class="text-muted text-center py-4">No recommendations generated.</div>';
    return;
  }

  const urgencyIcon = {
    Immediate: { icon: 'bi-exclamation-triangle-fill', cls: 'urgency-immediate' },
    Soon:      { icon: 'bi-clock-fill',                cls: 'urgency-soon'      },
    Monitor:   { icon: 'bi-eye-fill',                  cls: 'urgency-monitor'   },
    Backlog:   { icon: 'bi-bookmark-fill',             cls: 'urgency-backlog'   },
  };

  const urgencyBadgeColor = {
    Immediate: 'background:#fee2e2;color:#991b1b',
    Soon:      'background:#ffedd5;color:#9a3412',
    Monitor:   'background:#fef3c7;color:#92400e',
    Backlog:   'background:#f3f4f6;color:#4b5563',
  };

  container.innerHTML = recs.map(rec => {
    const ui = urgencyIcon[rec.urgency] || urgencyIcon.Backlog;
    const ub = urgencyBadgeColor[rec.urgency] || urgencyBadgeColor.Backlog;
    return `
      <div class="rec-item">
        <div class="rec-urgency-icon ${ui.cls}">
          <i class="bi ${ui.icon}"></i>
        </div>
        <div class="rec-body">
          <div class="rec-header">
            <span class="rec-issue">${escHtml(rec.issue)}</span>
            <span class="rec-urgency-badge" style="${ub}">${rec.urgency}</span>
          </div>
          <div class="rec-action">${escHtml(rec.action)}</div>
          <div class="rec-reason">${escHtml(rec.reason)}</div>
        </div>
      </div>`;
  }).join('');
}

// ── REPORTS ───────────────────────────────────────────────────────────────────
function renderReports() {
  const pd = STATE.prioritiesData;
  const td = STATE.trendsData;

  // Executive summary
  const summary = pd?.executiveSummary || td?.trendSummary || 'Run an analysis to generate an executive report.';
  document.getElementById('execSummaryText').textContent = summary;

  // Meta table
  const pkg     = STATE.packageName || '—';
  const period  = pd?.period || td?.period || STATE.period;
  const total   = pd?.totalReviews || td?.totalReviews || 0;
  const genAt   = pd?.generatedAt ? new Date(pd.generatedAt).toLocaleString() : '—';
  const topIssue= pd?.topPriorityIssues?.[0]?.issue || td?.topIssues?.[0]?.issue || '—';
  const severity= pd?.topPriorityIssues?.[0]?.severity || '—';

  document.getElementById('metaPackage').textContent     = pkg;
  document.getElementById('metaPeriod').textContent      = period;
  document.getElementById('metaTotal').textContent       = total.toLocaleString();
  document.getElementById('metaGeneratedAt').textContent = genAt;
  document.getElementById('metaTopIssue').textContent    = topIssue;
  document.getElementById('metaSeverity').innerHTML      = severity !== '—'
    ? `<span class="severity-badge severity-${severity.toLowerCase()}">${severity}</span>`
    : '—';
}

// ── Actions ───────────────────────────────────────────────────────────────────
function downloadReport() {
  const report = {
    packageName:    STATE.packageName,
    period:         STATE.period,
    generatedAt:    new Date().toISOString(),
    trends:         STATE.trendsData,
    priorities:     STATE.prioritiesData,
    emerging:       STATE.emergingData,
  };

  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `reviewmind_${STATE.packageName}_${STATE.period}_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadCSV() {
  const reviews = STATE.analyzeResult?.reviews;
  if (!reviews || !reviews.length) {
    alert('No review data to export. Run an analysis first.');
    return;
  }

  const headers = ['reviewId', 'date', 'score', 'sentiment', 'feedbackType', 'summary', 'review'];
  const rows    = reviews.map(r =>
    headers.map(h => `"${String(r[h] || '').replace(/"/g, '""')}"`).join(',')
  );
  const csv  = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `reviews_${STATE.packageName}_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function refreshAll() {
  await loadDashboard();
}

async function changePeriod() {
  STATE.period = document.getElementById('periodSelect').value;
  sessionStorage.setItem('rma_period', STATE.period);
  await loadDashboard();
}

// Quick analyze from no-data state
async function quickAnalyze() {
  const pkg  = document.getElementById('quickPackage').value.trim();
  const max  = parseInt(document.getElementById('quickMaxReviews').value) || 20;
  const statusEl = document.getElementById('quickStatus');

  if (!pkg) {
    statusEl.innerHTML = '<span style="color:#dc2626">Please enter a package name.</span>';
    return;
  }

  statusEl.innerHTML = '<span style="color:#7c3aed"><span class="spinner-border spinner-border-sm me-1" style="width:12px;height:12px"></span>Fetching and analysing reviews… this may take a minute.</span>';

  try {
    const result = await Api.analyzeApp(pkg, max);
    STATE.packageName   = pkg;
    STATE.analyzeResult = result;
    sessionStorage.setItem('rma_package', pkg);
    sessionStorage.setItem('rma_period', STATE.period);
    sessionStorage.setItem('rma_analyzeResult', JSON.stringify(result));
    document.getElementById('topbarPackage').textContent = pkg;

    statusEl.innerHTML = `<span style="color:#059669">✓ ${result.totalAnalysed} reviews analysed. Loading dashboard…</span>`;

    await loadDashboard();
  } catch (err) {
    statusEl.innerHTML = `<span style="color:#dc2626">Error: ${err.message}</span>`;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(str, len) {
  if (!str) return '';
  return str.length > len ? str.substring(0, len) + '…' : str;
}

function sentimentBadge(sentiment) {
  const map = {
    Positive: 's-positive',
    Negative: 's-negative',
    Neutral:  's-neutral',
  };
  const cls = map[sentiment] || 's-neutral';
  return `<span class="sentiment-badge ${cls}">${escHtml(sentiment)}</span>`;
}
