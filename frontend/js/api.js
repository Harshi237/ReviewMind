/**
 * api.js – Centralised API client for Review Mind AI
 * Connects directly to the existing FastAPI backend.
 * No new API logic – only wraps existing endpoints.
 */

const API_BASE = 'http://localhost:8000';

const Api = {

  // ── Health ────────────────────────────────────────────────────────────────
  async health() {
    const res = await fetch(`${API_BASE}/health`);
    return res.json();
  },

  // ── Model 1: POST /api/analyze-app ───────────────────────────────────────
  async analyzeApp(packageName, maxReviews = 20) {
    const res = await fetch(`${API_BASE}/api/analyze-app`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ packageName, maxReviews })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // ── Model 1: POST /api/test-review ───────────────────────────────────────
  async testReview(review) {
    const res = await fetch(`${API_BASE}/api/test-review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // ── Model 2: POST /api/trends ─────────────────────────────────────────────
  async getTrends(packageName, period = '30d') {
    const body = { period };
    if (packageName) body.packageName = packageName;
    const res = await fetch(`${API_BASE}/api/trends`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // ── Model 2: GET /api/trends/emerging ─────────────────────────────────────
  async getEmerging(packageName, period = '30d') {
    let url = `${API_BASE}/api/trends/emerging?period=${period}`;
    if (packageName) url += `&packageName=${encodeURIComponent(packageName)}`;
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // ── Model 3: POST /api/priorities ────────────────────────────────────────
  async getPriorities(packageName, period = '30d', topN = 10) {
    const body = { period, topN };
    if (packageName) body.packageName = packageName;
    const res = await fetch(`${API_BASE}/api/priorities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // ── Model 3: GET /api/priorities/report ───────────────────────────────────
  async getReport(packageName, period = '30d') {
    let url = `${API_BASE}/api/priorities/report?period=${period}`;
    if (packageName) url += `&packageName=${encodeURIComponent(packageName)}`;
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }
};
