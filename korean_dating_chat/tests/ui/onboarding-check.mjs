// 온보딩 UX 회귀 — 미인증 사용자 배너 표시·dismiss·로그인 후 사라짐.
const PORT = process.env.PORT || 8080;
import { chromium } from './_playwright.mjs';

const failures = [];
function check(name, cond, detail) {
    if (cond) console.log('  ✓ ' + name);
    else { failures.push(name + (detail ? ' — ' + detail : '')); console.log('  ✗ ' + name + (detail ? ' — ' + detail : '')); }
}

// canonical env 가 이미 떠있다고 가정 (tests/run.sh KEEP_SERVER=1 또는 별도 서버)

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 420, height: 820 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => failures.push('pageerror: ' + e.message));

await page.goto(`http://127.0.0.1:${PORT}/chat`, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

console.log('\n=== 1. 미인증 + 채팅 진입 → 배너 자동 표시 ===');
// 온보딩 스킵 + 캐릭터 선택까지
await page.evaluate(async () => {
    try { await window.KDateStorage?.saveProfile?.({ nickname: 'T', level: 'intermediate', interests: ['kpop'] }); } catch (e) {}
    document.getElementById('onboarding-step1').style.display = 'none';
    document.getElementById('onboarding-step2').style.display = 'none';
    document.getElementById('character-selection').style.display = 'none';
    if (typeof selectCharacter === 'function') await selectCharacter('jiwoo');
});
await page.waitForTimeout(600);

let bannerVisible = await page.$eval('#auth-prompt-banner',
    el => getComputedStyle(el).display !== 'none').catch(() => false);
check('미인증 시 배너 표시', bannerVisible);

const bannerText = await page.$eval('#auth-prompt-banner', el => el.textContent);
check('  배너에 "Google로 1초 가입" 카피', /Google로 1초 가입/.test(bannerText));
check('  배너에 quota 한도 표시', /\d+개 메시지 무료/.test(bannerText));

console.log('\n=== 2. 배너 → 로그인 모달 ===');
await page.locator('.auth-prompt-banner__btn').click();
await page.waitForTimeout(300);
const modalVisible = await page.$eval('#login-modal-overlay',
    el => el.classList.contains('show'));
check('로그인 모달 열림', modalVisible);
const modalText = await page.$eval('#login-modal-overlay', el => el.textContent);
check('  새 카피 "Google로 1초 가입"', /Google로 1초 가입/.test(modalText));
check('  무제한 월 구독 옵션 언급', /무제한 월 구독/.test(modalText));

await page.evaluate(() => closeLoginModal({ target: document.getElementById('login-modal-overlay') }));
await page.waitForTimeout(200);

console.log('\n=== 3. dismiss → 배너 사라짐 + sessionStorage 저장 ===');
await page.locator('.auth-prompt-banner__close').click();
await page.waitForTimeout(200);
bannerVisible = await page.$eval('#auth-prompt-banner',
    el => getComputedStyle(el).display !== 'none').catch(() => false);
check('dismiss 후 배너 hidden', !bannerVisible);
const flag = await page.evaluate(() => sessionStorage.getItem('kdate-auth-banner-dismissed'));
check('  sessionStorage 에 dismiss 기록', flag === '1');

// refreshAuthState 재호출해도 다시 안 나타남
await page.evaluate(() => refreshAuthState());
await page.waitForTimeout(300);
bannerVisible = await page.$eval('#auth-prompt-banner',
    el => getComputedStyle(el).display !== 'none').catch(() => false);
check('  refreshAuthState 후에도 hidden 유지', !bannerVisible);

console.log('\n=== 4. 로그인 후 → 배너 자동 사라짐 ===');
// dismiss 플래그 지우고, 새로 로그인
await page.evaluate(() => {
    sessionStorage.removeItem('kdate-auth-banner-dismissed');
    return refreshAuthState();
});
await page.waitForTimeout(300);
bannerVisible = await page.$eval('#auth-prompt-banner',
    el => getComputedStyle(el).display !== 'none').catch(() => false);
check('dismiss 해제 후 배너 다시 표시', bannerVisible);

// dev login
await page.evaluate(() => loginWithDev());
await page.waitForTimeout(700);
bannerVisible = await page.$eval('#auth-prompt-banner',
    el => getComputedStyle(el).display !== 'none').catch(() => false);
check('로그인 완료 후 배너 자동 hidden', !bannerVisible);

await page.screenshot({ path: '/tmp/onboarding-banner.png' });
await browser.close();

console.log('\n=========================');
if (failures.length === 0) { console.log('ALL CHECKS PASSED'); process.exit(0); }
else { console.log(`FAILURES (${failures.length}):`); failures.forEach(f => console.log('  - ' + f)); process.exit(1); }
