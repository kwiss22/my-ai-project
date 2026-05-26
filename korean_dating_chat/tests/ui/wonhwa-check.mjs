// 원화 5명 통합 검증:
const PORT = process.env.PORT || 8080;
//  - 캐릭터 카드 11장 모두 렌더링
//  - 원화 카드 5장: 클래스, 한자 tagline, 그룹 배지
//  - 이미지 onerror 폴백 동작 (이미지 파일 없을 때 SVG로 전환)
//  - 시나리오 인트로 11명 키 다 존재
//  - 미션 opener/success 5명 키 다 존재 (서버 응답)
import { chromium } from './_playwright.mjs';

const failures = [];
function check(name, cond, detail) {
    if (cond) console.log('  ✓ ' + name);
    else { failures.push(name + (detail ? ' — ' + detail : '')); console.log('  ✗ ' + name + (detail ? ' — ' + detail : '')); }
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1024, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => failures.push('pageerror: ' + e.message));

await page.goto(`http://127.0.0.1:${PORT}/chat`, { waitUntil: 'networkidle' });

// 캐릭터 선택 화면 띄우기
await page.evaluate(async () => {
    try { await window.KDateStorage?.saveProfile?.({ nickname: 'TestUser', level: 'intermediate', interests: ['kpop'] }); } catch (e) {}
    document.getElementById('onboarding-step1').style.display = 'none';
    document.getElementById('onboarding-step2').style.display = 'none';
    document.getElementById('character-selection').style.display = 'block';
    if (typeof renderCharacterCards === 'function') renderCharacterCards();
});
await page.waitForTimeout(500);

console.log('\n=== 캐릭터 카드 11장 렌더링 ===');
const cards = await page.$$('.character-card');
check(`11개 카드 (실제: ${cards.length})`, cards.length === 11);

const expectedIds = ['jiwoo', 'taeo', 'leo', 'jihoon', 'juno', 'hyunwoo', 'sua', 'minseo', 'serin', 'harin', 'yuna'];
for (const id of expectedIds) {
    const exists = await page.$(`.character-card.${id}`);
    check(`  카드 ${id} 존재`, !!exists);
}

console.log('\n=== 원화 5명 그룹 배지 + tagline ===');
for (const id of ['sua', 'minseo', 'serin', 'harin', 'yuna']) {
    const badge = await page.$eval(`.character-card.${id} .hwarang-badge`, el => el.textContent).catch(() => null);
    check(`  ${id} 배지=WONHWA`, badge === 'WONHWA', `got: ${badge}`);
}

const expectedTags = {
    sua: '사군이충 · 忠',
    minseo: '살생유택 · 擇',
    serin: '임전무퇴 · 勇',
    harin: '교우이신 · 信',
    yuna: '사친이효 · 孝',
};
for (const [id, expected] of Object.entries(expectedTags)) {
    const tag = await page.$eval(`.character-card.${id}`, el => {
        const div = el.querySelector('div:last-child');
        return div ? div.textContent.trim() : null;
    });
    check(`  ${id} tagline 정확`, tag === expected, `expected="${expected}" got="${tag}"`);
}

// 현우 tagline 도 임전무퇴 · 勇 (退 → 勇 수정 확인)
const hyunwooTag = await page.$eval('.character-card.hyunwoo', el => {
    const divs = el.querySelectorAll('div');
    return Array.from(divs).map(d => d.textContent).find(t => t.includes('임전무퇴'));
});
check('현우 tagline = 임전무퇴 · 勇', /임전무퇴 · 勇/.test(hyunwooTag), hyunwooTag);

console.log('\n=== 이미지 onerror 폴백 (PNG 없을 때 SVG 자동 전환) ===');
// 원화 PNG 가 실제로는 static/ 에 없을 가능성 — onerror 가 발동되는지 확인
await page.waitForTimeout(1500);  // 이미지 로드 시도 시간
const fallbackInfo = await page.evaluate(() => {
    const result = {};
    for (const id of ['sua', 'minseo', 'serin', 'harin', 'yuna']) {
        const img = document.querySelector(`.character-card.${id} img`);
        if (!img) { result[id] = 'NO_IMG'; continue; }
        result[id] = {
            src: img.src.substring(0, 50),
            isSvg: img.src.startsWith('data:image/svg'),
            naturalWidth: img.naturalWidth,
            complete: img.complete,
        };
    }
    return result;
});
for (const [id, info] of Object.entries(fallbackInfo)) {
    // 이미지가 PNG로 로드 성공했거나, 폴백 SVG로 전환됐어야 함 (둘 다 OK)
    const ok = info.naturalWidth > 0 || info.isSvg;
    check(`  ${id} 이미지 OK (PNG 로드 또는 SVG 폴백)`, ok,
        info.isSvg ? 'SVG fallback' : info.naturalWidth > 0 ? `PNG ${info.naturalWidth}px` : 'BROKEN');
}

console.log('\n=== 시나리오 인트로: 11명 키 다 존재 ===');
// /scenario/start 로 각 캐릭터 × 한 시나리오 호출해서 intro_message 비어있지 않음 확인
for (const id of expectedIds) {
    const r = await page.evaluate(async (charId) => {
        const resp = await fetch('/scenario/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ character: charId, scenario_id: 'confession' })
        });
        return resp.ok ? await resp.json() : { error: resp.status };
    }, id);
    const intro = r && r.intro_message;
    check(`  /scenario/start confession × ${id} 인트로 있음`, !!intro && intro.length > 5,
        intro ? intro.substring(0, 30) : `error=${r?.error}`);
}

console.log('\n=== 일일 미션 opener: 11명 다 응답 ===');
for (const id of expectedIds) {
    const r = await page.evaluate(async (charId) => {
        const resp = await fetch('/start-mission', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ character: charId })
        });
        return resp.ok ? await resp.json() : { error: resp.status };
    }, id);
    const opener = r && r.opener;
    check(`  ${id} 미션 opener 있음`, !!opener && opener.length > 5,
        opener ? opener.substring(0, 40) : `no opener`);
}

console.log('\n=== 페이지 에러 없음 ===');
check('pageerror 0', failures.filter(f => f.startsWith('pageerror')).length === 0);

await page.screenshot({ path: '/tmp/wonhwa-cards.png', fullPage: false });
await browser.close();

console.log('\n=========================');
if (failures.length === 0) { console.log('ALL CHECKS PASSED'); process.exit(0); }
else { console.log(`FAILURES (${failures.length}):`); failures.forEach(f => console.log('  - ' + f)); process.exit(1); }
