// 2240AI — k6 API stress test
// Usage:
//   k6 run tests/performance/stress_test.js --duration 30s --vus 10
//   k6 run tests/performance/stress_test.js --duration 60s --vus 20 --env BASE_URL=http://server:8000
//
// Install k6: https://k6.io/docs/get-started/installation/

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

const errorRate = new Rate('errors');
const uploadLatency = new Trend('upload_latency');
const queryLatency = new Trend('query_latency');

export const options = {
  stages: [
    { duration: '10s', target: 5 },   // ramp up
    { duration: '30s', target: 10 },  // steady
    { duration: '10s', target: 0 },   // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'], // 95% of requests < 3s
    errors: ['rate<0.1'],              // error rate < 10%
  },
};

export default function () {
  group('health endpoints', () => {
    const res = http.get(`${BASE_URL}/health`);
    check(res, {
      'health status is 200': (r) => r.status === 200,
    });
    errorRate.add(res.status !== 200);
  });

  group('status query', () => {
    const res = http.get(`${BASE_URL}/api/v1/import/pipelines/nonexistent`);
    check(res, {
      'not-found returns 404': (r) => r.status === 404,
    });
    errorRate.add(res.status !== 404);
    queryLatency.add(res.timings.duration);
  });

  // Simulate PDF upload (small test file)
  group('upload', () => {
    const testPdf = open('/dev/null', 'b') || new Uint8Array(1024); // 1KB placeholder
    const payload = {
      file: http.file(testPdf, 'test.pdf', 'application/pdf'),
    };
    const res = http.post(`${BASE_URL}/api/v1/import/pipeline/upload`, payload);
    check(res, {
      'upload accepted (200 or 422)': (r) => r.status === 200 || r.status === 422,
    });
    errorRate.add(res.status >= 500);
    uploadLatency.add(res.timings.duration);
  });

  sleep(1);
}
