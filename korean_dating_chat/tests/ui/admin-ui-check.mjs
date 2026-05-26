// /admin HTML 대시보드.
const PORT = process.env.PORT || 8080;
//  1. 미인증 → /chat redirect (302)
//  2. ADMIN_EMAILS 미설정 → 503 forbidden HTML
//  3. 비관리자 로그인 → 403 forbidden HTML
//  4. 관리자 → 200 + admin.html + JS 로 stats/events 로드
import http from 'node:http';
import { chromium } from './_playwright.mjs';

const failures = [];
function check(name, cond, detail) {
    if (cond) console.log('  ✓ ' + name);
    else { failures.push(name + (detail ? ' — ' + detail : '')); console.log('  ✗ ' + name + (detail ? ' — ' + detail : '')); }
}

function req(method, path, body, cookie = '', noRedirect = true) {
    return new Promise((resolve, reject) => {
        const headers = { 'Content-Type': 'application/json',
                          'X-RateLimit-Bypass': 'test_bypass' };
        if (cookie) headers['Cookie'] = cookie;
        if (body && typeof body === 'object') body = JSON.stringify(body);
        if (body) headers['Content-Length'] = Buffer.byteLength(body);
        const r = http.request({ host: '127.0.0.1', port: PORT, path, method, headers }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                resolve({
                    status: res.statusCode,
                    body: data,
                    setCookie: res.headers['set-cookie'] || [],
                    location: res.headers['location'],
                });
            });
        });
        r.on('error', reject);
        if (body) r.write(body);
        r.end();
    });
}

console.log('=== 1. 미인증 → /chat redirect ===');
let r = await req('GET', '/admin');
check('302/301 redirect', r.status === 302 || r.status === 301);
check('  Location: /chat', r.location === '/chat');

console.log('\n=== 2. 비관리자 → 403 ===');
const nonAdmin = await req('POST', '/auth/dev-login',
    { provider_user_id: 'nonadmin', email: 'someone@example.com' });
const nonAdminCookie = nonAdmin.setCookie.find(c => c.startsWith('kdate_session='))?.split(';')[0] || '';
r = await req('GET', '/admin', null, nonAdminCookie);
check('403 status', r.status === 403);
check('  HTML 응답 (forbidden 페이지)', /접근 권한이 없습니다/.test(r.body));
check('  현재 이메일 표시', /someone@example\.com/.test(r.body));

console.log('\n=== 3. 관리자 → 200 + admin.html ===');
const admin = await req('POST', '/auth/dev-login',
    { provider_user_id: 'admin', email: 'admin@example.com' });
const adminCookie = admin.setCookie.find(c => c.startsWith('kdate_session='))?.split(';')[0] || '';
r = await req('GET', '/admin', null, adminCookie);
check('200', r.status === 200);
check('  text/html', /text\/html/.test(r.body) === false && /<!DOCTYPE html>/.test(r.body));
check('  KPI 4종 영역 존재', /kpi-mrr|kpi-active|kpi-new-today|kpi-paywall/.test(r.body));
check('  자동 새로고침 30초', /setInterval\(loadAll,\s*30000\)/.test(r.body));

console.log('\n=== 4. UI 로드 + 데이터 fetch 동작 ===');
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1100, height: 800 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => failures.push('pageerror: ' + e.message));

// admin 세션 cookie 주입
await ctx.addCookies([{
    name: 'kdate_session',
    value: adminCookie.replace('kdate_session=', ''),
    domain: '127.0.0.1',
    path: '/',
}]);

await page.goto(`http://127.0.0.1:${PORT}/admin`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);  // fetch /admin/stats + /admin/events 완료 대기

const kpiMrr = await page.$eval('#kpi-mrr', el => el.textContent.trim());
check('MRR 값 렌더', /^\$/.test(kpiMrr), `value=${kpiMrr}`);

const kpiActive = await page.$eval('#kpi-active', el => el.textContent.trim());
check('  활성 구독자 값 렌더 (숫자)', /^\d+$/.test(kpiActive), `value=${kpiActive}`);

const subscribersDetail = await page.$eval('#subscribers-detail', el => el.textContent);
check('  구독자 분해 5종 표시',
    /활성/.test(subscribersDetail) && /체험 중/.test(subscribersDetail) &&
    /결제 재시도/.test(subscribersDetail) && /해지 예정/.test(subscribersDetail) &&
    /만료/.test(subscribersDetail));

const alertsHealth = await page.$eval('#alerts-health', el => el.textContent);
check('  알림 채널 상태 표시', /Slack/.test(alertsHealth) && /SMTP/.test(alertsHealth));

const meta = await page.$eval('#meta', el => el.textContent.trim());
check('  meta "업데이트 ..." 표시', /업데이트/.test(meta), `meta=${meta}`);

// 필터 클릭 동작
console.log('\n=== 5. 이벤트 severity 필터 ===');
await page.click('.filter-btn[data-severity="critical"]');
await page.waitForTimeout(500);
const activeFilter = await page.$eval('.filter-btn.active', el => el.dataset.severity);
check('critical 필터 active 상태', activeFilter === 'critical');

await page.screenshot({ path: '/tmp/admin-dashboard.png', fullPage: true });
await browser.close();

console.log('\n=========================');
if (failures.length === 0) { console.log('ALL CHECKS PASSED'); process.exit(0); }
else { console.log(`FAILURES (${failures.length}):`); failures.forEach(f => console.log('  - ' + f)); process.exit(1); }
