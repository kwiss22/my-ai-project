// Playwright 로더 — local dev VM 의 글로벌 설치와 CI 의 npm install 둘 다 지원.
//
//   - CI (tests/node_modules/playwright 존재): 일반 ESM import 'playwright' 동작
//   - Local dev VM (글로벌 /opt/node22/lib/node_modules/playwright):
//     일반 import 가 실패하면 절대 경로로 폴백.
//
// 각 UI 테스트는: import { chromium } from './_playwright.mjs'
let pw;
try {
    pw = await import('playwright');
} catch (e) {
    // 글로벌 설치 폴백 — local dev 만. CI 에서는 npm install 로 위 경로에 있음.
    pw = await import('/opt/node22/lib/node_modules/playwright/index.js');
}
const mod = pw.default || pw;
export const { chromium, firefox, webkit } = mod;
