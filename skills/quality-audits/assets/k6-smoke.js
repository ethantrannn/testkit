// testkit k6 smoke/load template. Copy to qa/runs/<RUN_ID>/audits/load/<name>.js and edit ENDPOINTS.
// Run ONLY after `audit_guard.py load <env>` allowed it (never production):
//
//   k6 run qa/runs/R/audits/load/api.js \
//     -e BASE_URL=https://staging.example.com -e VUS=2 -e DURATION=30s \
//     -e P95_MS=800 -e ERROR_RATE=0.01 -e SUMMARY=qa/runs/R/audits/load/api-summary.json
//
// Optional: -e TOKEN_ENV=TESTKIT_API_TOKEN (name of an env var that holds a bearer token; the value
// is read with __ENV and never printed). Defaults are deliberately tiny: 2 VUs for 10s.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = (__ENV.BASE_URL || '').replace(/\/$/, '');
if (!BASE_URL) throw new Error('BASE_URL is required (-e BASE_URL=https://staging.example.com)');

const VUS = parseInt(__ENV.VUS || '2', 10);
const DURATION = __ENV.DURATION || '10s';
const P95_MS = parseInt(__ENV.P95_MS || '800', 10);
const ERROR_RATE = parseFloat(__ENV.ERROR_RATE || '0.01');
const TOKEN = __ENV.TOKEN_ENV ? __ENV[__ENV.TOKEN_ENV] : '';

// Read-only requests by default. Add write requests only when the environment has allow_write: true.
const ENDPOINTS = [
  { name: 'health', method: 'GET', path: '/' },
  // { name: 'list items', method: 'GET', path: '/api/items', expect: 200 },
  // { name: 'search', method: 'GET', path: '/api/search?q=test' },
];

export const options = {
  scenarios: {
    smoke: { executor: 'constant-vus', vus: VUS, duration: DURATION },
  },
  thresholds: {
    http_req_failed: [`rate<${ERROR_RATE}`],
    http_req_duration: [`p(95)<${P95_MS}`],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  noConnectionReuse: false,
  userAgent: 'testkit-k6-smoke',
};

const params = { headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {} };

export default function () {
  for (const e of ENDPOINTS) {
    const res = http.request(e.method, BASE_URL + e.path, e.body || null,
      Object.assign({}, params, { tags: { name: e.name } }));
    check(res, { [`${e.name} status ${e.expect || 200}`]: (r) => r.status === (e.expect || 200) });
  }
  sleep(1);
}

// Writes the machine summary (SUMMARY) and keeps the normal text summary on stdout.
export function handleSummary(data) {
  const out = { stdout: textSummary(data) };
  if (__ENV.SUMMARY) out[__ENV.SUMMARY] = JSON.stringify(data, null, 2);
  return out;
}

function textSummary(data) {
  const m = data.metrics;
  const d = m.http_req_duration ? m.http_req_duration.values : {};
  const f = m.http_req_failed ? m.http_req_failed.values.rate : 0;
  const lines = [
    `testkit k6 smoke — ${BASE_URL} — ${VUS} VUs, ${DURATION}`,
    `requests: ${m.http_reqs ? m.http_reqs.values.count : 0}  rps: ${m.http_reqs ? m.http_reqs.values.rate.toFixed(1) : 0}`,
    `duration ms: avg ${fmt(d.avg)}  p95 ${fmt(d['p(95)'])}  p99 ${fmt(d['p(99)'])}  max ${fmt(d.max)}`,
    `failed: ${(f * 100).toFixed(2)}%`,
    'thresholds:',
  ];
  for (const [name, metric] of Object.entries(m)) {
    for (const [t, r] of Object.entries(metric.thresholds || {})) {
      lines.push(`  ${r.ok ? 'PASS' : 'FAIL'}  ${name} ${t}`);
    }
  }
  return lines.join('\n') + '\n';
}

function fmt(v) { return v === undefined ? 'n/a' : v.toFixed(1); }
