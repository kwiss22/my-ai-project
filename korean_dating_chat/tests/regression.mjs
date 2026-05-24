// 통합 회귀 — 한 서버 인스턴스에서 모든 핵심 flow 연속 검증.
// 각 섹션 시작 시 /admin/test-reset 으로 깨끗한 상태.
//
// 단일 환경:
//   DAILY_FREE_QUOTA=5
//   STRIPE_WEBHOOK_SECRET=whsec_local_test_123
//   STRIPE_TRIAL_DAYS=7
//   ADMIN_EMAILS=admin@example.com
//   RATELIMIT_BYPASS_TOKEN=test_bypass
//   ALERT_TEST_SINK=1
//   ALERT_SLACK_WEBHOOK_URL=http://127.0.0.1:9876/webhook (optional Slack mock)
//   ENV_ALLOW_TEST_RESET=1
//
// 실행: tests/run.sh

import http from 'node:http';
import { execSync } from 'node:child_process';
import fs from 'node:fs';

const PORT = parseInt(process.env.PORT || '8080', 10);
const failures = [];
let totalChecks = 0;
function check(name, cond, detail) {
    totalChecks++;
    if (cond) console.log('  \x1b[32m✓\x1b[0m ' + name);
    else { failures.push(name + (detail ? ' — ' + detail : '')); console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' — ' + detail : '')); }
}
function section(title) { console.log('\n\x1b[1m=== ' + title + ' ===\x1b[0m'); }

function req(method, path, body, cookie = '') {
    return new Promise((resolve, reject) => {
        const headers = { 'Content-Type': 'application/x-www-form-urlencoded',
                          'X-RateLimit-Bypass': 'test_bypass' };
        if (cookie) headers['Cookie'] = cookie;
        if (body && typeof body === 'object' && !(body instanceof URLSearchParams) && !body.includes) {
            headers['Content-Type'] = 'application/json';
            body = JSON.stringify(body);
        }
        if (body) headers['Content-Length'] = Buffer.byteLength(body);
        const r = http.request({ host: '127.0.0.1', port: PORT, path, method, headers }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                let json = null; try { json = JSON.parse(data); } catch (e) {}
                resolve({ status: res.statusCode, json, raw: data, setCookie: res.headers['set-cookie'] || [],
                          retryAfter: res.headers['retry-after'] });
            });
        });
        r.on('error', reject);
        if (body) r.write(body);
        r.end();
    });
}

const SIMULATE = '/home/user/my-ai-project/korean_dating_chat/tools/billing_simulate.py';
function sim(args) {
    const cmd = `STRIPE_WEBHOOK_SECRET=whsec_local_test_123 WEBHOOK_URL=http://127.0.0.1:${PORT}/billing/webhook python3 ${SIMULATE} ${args}`;
    try {
        const out = execSync(cmd, { encoding: 'utf-8', timeout: 10000 });
        return { ok: /→ 200/.test(out), out };
    } catch (e) { return { ok: false, out: e.stdout || e.message }; }
}
function simInvoice(eventType, customer, attemptCount = 1, amount = 499) {
    const py = [
        "import json, sys, os",
        "sys.path.insert(0, '/home/user/my-ai-project/korean_dating_chat/tools')",
        "import billing_simulate as s",
        `obj = {'object':'invoice','customer':'${customer}','attempt_count':${attemptCount},'amount_due':${amount},'amount_paid':${amount}}`,
        `body = json.dumps(s._event('${eventType}', obj)).encode()`,
        "sig = s._sign(body, 'whsec_local_test_123')",
        `print(s._post(os.getenv('WEBHOOK_URL', 'http://127.0.0.1:${PORT}/billing/webhook'), body, sig))`,
    ].join('\n');
    const tmpFile = `/tmp/sim_${Date.now()}_${Math.random().toString(36).slice(2)}.py`;
    fs.writeFileSync(tmpFile, py);
    try {
        return execSync(`python3 ${tmpFile}`, { encoding: 'utf-8', timeout: 10000 });
    } catch (e) { return e.stdout || e.message; }
    finally { try { fs.unlinkSync(tmpFile); } catch (e) {} }
}

async function reset() {
    const r = await req('POST', '/admin/test-reset', '');
    if (r.status !== 200) {
        console.error('test-reset 실패. ENV_ALLOW_TEST_RESET=1 확인:', r.raw);
        process.exit(2);
    }
}
function getCookie(setCookieArr) {
    return setCookieArr.find(c => c.startsWith('kdate_session='))?.split(';')[0] || '';
}

// ============================================================
section('Section 1 — 인증/Quota 기본');
// ============================================================
await reset();
let r = await req('GET', '/me');
check('미인증 /me 200', r.status === 200 && r.json?.authenticated === false);
check('  cap = 5', r.json?.quota?.cap === 5);
check('  trial_days = 7', r.json?.trial_days === 7);
check('  billing_enabled (webhook 설정됐지만 STRIPE_SECRET 없음 → false)',
    r.json?.billing_enabled === false);

r = await req('POST', '/chat', 'message=hi&character=jiwoo');
check('미인증 /chat → 401 paywall=login', r.status === 401 && r.json?.paywall === 'login');

const login = await req('POST', '/auth/dev-login', { provider_user_id: 'u1', email: 'admin@example.com' });
const adminCookie = getCookie(login.setCookie);
check('dev-login 200', login.status === 200);
check('admin email 인식', login.json?.user_id);

for (let i = 1; i <= 5; i++) {
    await req('POST', '/chat', `message=t${i}&character=jiwoo`, adminCookie);
}
r = await req('GET', '/me', null, adminCookie);
check('5번 후 quota.used = 5', r.json?.quota?.used === 5);

r = await req('POST', '/chat', 'message=t6&character=jiwoo', adminCookie);
check('6번째 → 402 paywall=quota', r.status === 402 && r.json?.paywall === 'quota');

// ============================================================
section('Section 2 — 구독 lifecycle (시뮬레이터)');
// ============================================================
await reset();
const sub = await req('POST', '/auth/dev-login', { provider_user_id: 'sub-u', email: 'sub@example.com' });
const subCookie = getCookie(sub.setCookie);
const subUid = sub.json?.user_id;

sim(`checkout --user-id ${subUid} --customer cus_lcc --subscription sub_lcc`);
r = await req('GET', '/me', null, subCookie);
check('checkout 직후 active=true (24h grace)', r.json?.subscription?.active === true);

sim(`sub-update --customer cus_lcc --subscription sub_lcc --status trialing --days 7 --created`);
r = await req('GET', '/me', null, subCookie);
check('trialing 상태', r.json?.subscription?.status === 'trialing');
check('  unlimited = true', r.json?.quota?.unlimited === true);

sim(`sub-update --customer cus_lcc --subscription sub_lcc --status active --days 30`);
r = await req('GET', '/me', null, subCookie);
check('trial → active 전환', r.json?.subscription?.status === 'active');

sim(`sub-update --customer cus_lcc --subscription sub_lcc --status past_due --days 25`);
r = await req('GET', '/me', null, subCookie);
check('past_due 도 active 취급 (grace)', r.json?.subscription?.status === 'past_due' && r.json?.subscription?.active === true);

// cancel-subscription 서버 endpoint
await req('POST', '/billing/cancel-subscription', '', subCookie);
r = await req('GET', '/me', null, subCookie);
check('cancel_at_period_end = true', r.json?.subscription?.cancel_at_period_end === true);

sim(`sub-delete --customer cus_lcc --subscription sub_lcc`);
r = await req('GET', '/me', null, subCookie);
check('완전 해지 후 active=false', r.json?.subscription?.active === false);

// ============================================================
section('Section 3 — Rate limit');
// ============================================================
await reset();
const rl = await req('POST', '/auth/dev-login', { provider_user_id: 'rl-u', email: 'admin@example.com' });
const rlCookie = getCookie(rl.setCookie);

// /billing/checkout 5/min — bypass 헤더 없이 raw 호출로 검증
const rawReq = (path, body, cookie) => new Promise((resolve) => {
    const headers = { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) };
    if (cookie) headers['Cookie'] = cookie;
    const r = http.request({ host: '127.0.0.1', port: PORT, path, method: 'POST', headers }, (res) => {
        let d = ''; res.on('data', c => d += c); res.on('end', () => resolve({ status: res.statusCode }));
    });
    r.write(body); r.end();
});
let ok503 = 0, blocked = 0;
for (let i = 1; i <= 7; i++) {
    const rr = await rawReq('/billing/checkout', '{}', rlCookie);
    if (rr.status === 429) blocked++;
    else if (rr.status === 503) ok503++;
}
check(`checkout 5번 통과, 2번 차단 (ok503=${ok503} blocked=${blocked})`, ok503 === 5 && blocked === 2);
await reset();

// ============================================================
section('Section 4 — /admin/stats + /admin/events');
// ============================================================
const admin = await req('POST', '/auth/dev-login', { provider_user_id: 'adm', email: 'admin@example.com' });
const aCookie = getCookie(admin.setCookie);

// 활성 구독자 + 결제 실패 + 위조 webhook 생성
sim(`checkout --user-id ${admin.json?.user_id} --customer cus_adm --subscription sub_adm`);
sim(`sub-update --customer cus_adm --subscription sub_adm --status active --days 30 --created`);
simInvoice('invoice.payment_failed', 'cus_adm', 3);  // critical
// 위조 서명
await new Promise((resolve) => {
    const body = JSON.stringify({type:'x'});
    const r = http.request({host:'127.0.0.1', port:PORT, path:'/billing/webhook', method:'POST',
        headers:{'Content-Type':'application/json', 'Content-Length':Buffer.byteLength(body),
                 'Stripe-Signature':'t=1,v1=dead'}},
        (res) => { res.on('data',()=>{}); res.on('end',()=>resolve()); });
    r.write(body); r.end();
});
await new Promise(r => setTimeout(r, 300));  // alert async dispatch 대기

r = await req('GET', '/admin/stats', null, aCookie);
check('admin/stats 200', r.status === 200);
check('  subscribers.active = 1', r.json?.subscribers?.active === 1);
check('  revenue.mrr > 0', r.json?.revenue?.estimated_mrr_usd > 0);
check('  events_7d.by_severity.critical >= 1', (r.json?.events_7d?.by_severity?.critical || 0) >= 1);

r = await req('GET', '/admin/events?severity=critical', null, aCookie);
check('critical 필터 동작', r.status === 200 && r.json?.count >= 1);
const critKinds = r.json.events.map(e => e.kind);
check('  webhook.signature_invalid 포함', critKinds.includes('webhook.signature_invalid'));
check('  payment.failed (attempt=3) 포함', critKinds.includes('payment.failed'));

r = await req('GET', '/admin/alerts-health', null, aCookie);
check('alerts-health 응답', r.status === 200 && r.json?.channels?.test_sink === true);

r = await req('GET', '/admin/alerts-test', null, aCookie);
check('alerts-test sink 비어 있지 않음', (r.json?.sink?.length || 0) >= 1);

// ============================================================
section('Section 5 — 계정 삭제 + 권한');
// ============================================================
await reset();
const del = await req('POST', '/auth/dev-login', { provider_user_id: 'd-u', email: 'd@example.com' });
const dCookie = getCookie(del.setCookie);

r = await req('POST', '/auth/delete-account', '', dCookie);
check('delete-account 200', r.status === 200);
r = await req('GET', '/me', null, dCookie);
check('삭제 후 /me 미인증', r.json?.authenticated === false);

// 비관리자 → admin 차단
const noadmin = await req('POST', '/auth/dev-login', { provider_user_id: 'noad', email: 'noadmin@x.com' });
const noadminCookie = getCookie(noadmin.setCookie);
r = await req('GET', '/admin/stats', null, noadminCookie);
check('비관리자 admin/stats → 403', r.status === 403);
r = await req('GET', '/admin/events', null, noadminCookie);
check('비관리자 admin/events → 403', r.status === 403);

// ============================================================
section('Section 6 — STT/TTS 미설정 시 그레이스풀 fallback');
// ============================================================
await reset();
r = await req('POST', '/transcribe', '');
// 미인증이라 401? rate-limit 통과 후 STT 핸들러까지 도달하면 Azure 미설정 시 503
// rate-limit bypass 가 켜져있고 인증 안 됐는데 — chatbot.py 의 transcribe 는 인증 안 받음. 그냥 Azure 키 없으면 503.
check('미인증 transcribe → 503 (Azure 미설정)', r.status === 503);

// ============================================================
section('Section 7 — 환경 진단');
// ============================================================
const a = await req('POST', '/auth/dev-login', { provider_user_id: 'env', email: 'admin@example.com' });
const envCookie = getCookie(a.setCookie);
r = await req('GET', '/admin/alerts-health', null, envCookie);
check('alerts MIN_SEVERITY = critical', r.json?.min_severity === 'critical');
check('alerts dedup = 300', r.json?.dedup_seconds === 300);

// ============================================================
console.log('\n========================================');
console.log(`총 ${totalChecks} 체크 · 실패 ${failures.length}`);
if (failures.length === 0) {
    console.log('\x1b[32mALL CHECKS PASSED\x1b[0m');
    process.exit(0);
} else {
    console.log('\x1b[31mFAILURES:\x1b[0m');
    failures.forEach(f => console.log('  - ' + f));
    process.exit(1);
}
