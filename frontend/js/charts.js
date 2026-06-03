/**
 * charts.js – Chart.js rendering helpers for Review Mind AI dashboard.
 * All chart instances are stored so they can be destroyed/redrawn on refresh.
 */

const Charts = (() => {

  // Registry of Chart instances
  const _instances = {};

  // Colour palette
  const COLORS = {
    purple:  '#7c3aed',
    purpleL: 'rgba(124,58,237,.15)',
    green:   '#059669',
    greenL:  'rgba(5,150,105,.15)',
    red:     '#dc2626',
    redL:    'rgba(220,38,38,.15)',
    yellow:  '#d97706',
    yellowL: 'rgba(217,119,6,.15)',
    blue:    '#2563eb',
    blueL:   'rgba(37,99,235,.15)',
    gray:    '#9ca3af',
  };

  const SENTIMENT_COLORS = [COLORS.green, COLORS.red, COLORS.yellow];
  const FEEDBACK_COLORS  = [COLORS.red, '#f97316', COLORS.purple, COLORS.green, COLORS.blue];

  function _destroy(id) {
    if (_instances[id]) {
      _instances[id].destroy();
      delete _instances[id];
    }
  }

  // ── Sentiment Pie ─────────────────────────────────────────────────────────
  function renderSentimentPie(positive, negative, neutral) {
    _destroy('sentimentPieChart');
    const ctx = document.getElementById('sentimentPieChart').getContext('2d');
    _instances['sentimentPieChart'] = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Positive', 'Negative', 'Neutral'],
        datasets: [{
          data: [positive, negative, neutral],
          backgroundColor: SENTIMENT_COLORS,
          borderWidth: 0,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        cutout: '65%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { padding: 16, font: { size: 12 } }
          },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.label}: ${ctx.raw}%`
            }
          }
        }
      }
    });
  }

  // ── Feedback Type Bar ─────────────────────────────────────────────────────
  function renderFeedbackBar(counts) {
    _destroy('feedbackBarChart');
    const ctx = document.getElementById('feedbackBarChart').getContext('2d');
    const labels = ['Bug Reports', 'Complaints', 'Suggestions', 'Positive', 'General'];
    const data   = [
      counts.bugReports || 0,
      counts.complaints || 0,
      counts.suggestions || 0,
      counts.positiveFeedback || 0,
      counts.generalFeedback || 0,
    ];
    _instances['feedbackBarChart'] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Reviews',
          data,
          backgroundColor: FEEDBACK_COLORS,
          borderRadius: 6,
          borderSkipped: false,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false } },
          y: {
            beginAtZero: true,
            grid: { color: '#f3f4f6' },
            ticks: { precision: 0 }
          }
        }
      }
    });
  }

  // ── Top Issues Horizontal Bar ─────────────────────────────────────────────
  function renderTopIssues(issues) {
    _destroy('topIssuesChart');
    const ctx = document.getElementById('topIssuesChart').getContext('2d');
    const labels = issues.map(i => i.issue);
    const data   = issues.map(i => i.count);

    _instances['topIssuesChart'] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Mentions',
          data,
          backgroundColor: COLORS.purpleL,
          borderColor: COLORS.purple,
          borderWidth: 1.5,
          borderRadius: 6,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: '#f3f4f6' },
            ticks: { precision: 0 }
          },
          y: { grid: { display: false } }
        }
      }
    });
  }

  // ── Feedback Doughnut (Trends section) ───────────────────────────────────
  function renderFeedbackDoughnut(counts) {
    _destroy('feedbackDoughnutChart');
    const ctx = document.getElementById('feedbackDoughnutChart').getContext('2d');
    const labels = ['Bug Reports', 'Complaints', 'Suggestions', 'Positive', 'General'];

    // Filter zero values for cleaner chart
  // Filter zero values for cleaner chart
  const allValues = [
    counts.bugReports      || 0,
    counts.complaints      || 0,
    counts.suggestions     || 0,
    counts.positiveFeedback|| 0,
    counts.generalFeedback || 0,
  ];
  const filtered = labels
    .map((l, i) => ({ label: l, value: allValues[i], color: FEEDBACK_COLORS[i] }))
    .filter(d => d.value > 0);

    _instances['feedbackDoughnutChart'] = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: filtered.map(d => d.label),
        datasets: [{
          data: filtered.map(d => d.value),
          backgroundColor: filtered.map(d => d.color),
          borderWidth: 0,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        cutout: '60%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { padding: 12, font: { size: 12 } }
          }
        }
      }
    });
  }

  function data_has(arr, i) { return true; } // unused – kept for safety

  // ── Feature Requests Bar ──────────────────────────────────────────────────
  function renderFeaturesChart(features) {
    _destroy('featuresChart');
    if (!features || features.length === 0) return;
    const ctx = document.getElementById('featuresChart').getContext('2d');

    _instances['featuresChart'] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: features.map(f => f.feature),
        datasets: [{
          label: 'Requests',
          data: features.map(f => f.requests),
          backgroundColor: COLORS.blueL,
          borderColor: COLORS.blue,
          borderWidth: 1.5,
          borderRadius: 6,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: '#f3f4f6' },
            ticks: { precision: 0 }
          },
          y: { grid: { display: false } }
        }
      }
    });
  }

  return {
    renderSentimentPie,
    renderFeedbackBar,
    renderTopIssues,
    renderFeedbackDoughnut,
    renderFeaturesChart,
  };
})();
