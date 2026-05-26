// 접근성(focus trap, ESC, ARIA, 키보드 활성화) 검증.
const PORT = process.env.PORT || 8080;
// 실패 조건은 throw 로 즉시 실패시키고 명확한 에러 메시지를 출력.
import { chromium } from './_playwright.mjs';

const failures = [];
function check(name, cond, detail) {
    if (cond) {
        console.log('  ✓ ' + name);
    } else {
        failures.push(name + (detail ? ' — ' + detail : ''));
        console.log('  ✗ ' + name + (detail ? ' — ' + detail : ''));
    }
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 420, height: 820 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => { failures.push('pageerror: ' + e.message); });

await page.goto(`http://127.0.0.1:${PORT}/chat`, { waitUntil: 'networkidle' });

// Skip onboarding
await page.evaluate(async () => {
    try {
        await window.KDateStorage?.saveProfile?.({
            nickname: 'Test', level: 'intermediate', interests: ['kpop'], currentCharacter: 'jiwoo',
        });
    } catch (e) {}
    document.getElementById('onboarding-step1').style.display = 'none';
    document.getElementById('onboarding-step2').style.display = 'none';
    document.getElementById('character-selection').style.display = 'none';
    if (typeof selectCharacter === 'function') await selectCharacter('jiwoo');
});
await page.waitForTimeout(800);

console.log('\n=== ARIA attributes on modal overlays ===');
const overlayIds = [
    'levelup-modal-overlay',
    'mission-success-overlay',
    'scenario-complete-overlay',
    'share-modal-overlay',
    'vocab-modal-overlay',
    'settings-modal-overlay',
    'intimacy-modal-overlay',
    'history-modal-overlay',
    'scenario-sheet-overlay',
    'nav-sheet-overlay',
];
for (const id of overlayIds) {
    const info = await page.evaluate((id) => {
        const el = document.getElementById(id);
        if (!el) return null;
        return {
            role: el.getAttribute('role'),
            modal: el.getAttribute('aria-modal'),
            label: el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'),
            hidden: el.getAttribute('aria-hidden'),
        };
    }, id);
    check(`${id} has dialog role`, info && (info.role === 'dialog' || info.role === 'alertdialog'),
        info ? `role=${info.role}` : 'missing');
    check(`${id} has aria-modal`, info && info.modal === 'true');
    check(`${id} has accessible name`, info && info.label, info && !info.label ? 'no aria-label or aria-labelledby' : '');
    check(`${id} starts aria-hidden=true`, info && info.hidden === 'true');
}

console.log('\n=== Open nav sheet: aria-hidden flips, focus moves inside ===');
await page.evaluate(() => openNavSheet());
await page.waitForTimeout(150);
let s = await page.evaluate(() => {
    const el = document.getElementById('nav-sheet-overlay');
    const af = document.activeElement;
    return {
        hidden: el.getAttribute('aria-hidden'),
        focusInside: el.contains(af),
        focusedTag: af ? af.tagName : null,
    };
});
check('nav-sheet aria-hidden becomes false', s.hidden === 'false');
check('focus moves inside nav-sheet on open', s.focusInside, `focused=${s.focusedTag}`);

console.log('\n=== ESC closes nav sheet, focus returns to trigger ===');
// Open nav sheet from real trigger to test focus restoration
await page.evaluate(() => closeNavSheet());
await page.waitForTimeout(150);
await page.evaluate(() => {
    const btn = document.querySelector('button[onclick="openNavSheet()"]');
    btn.focus();
    btn.click();
});
await page.waitForTimeout(200);
await page.keyboard.press('Escape');
await page.waitForTimeout(200);
s = await page.evaluate(() => {
    const el = document.getElementById('nav-sheet-overlay');
    const af = document.activeElement;
    return {
        hidden: el.getAttribute('aria-hidden'),
        shown: el.classList.contains('show'),
        focusedOnTrigger: af && af.getAttribute('onclick') === 'openNavSheet()',
        focusedTag: af ? af.tagName : null,
    };
});
check('nav-sheet closes on ESC', !s.shown && s.hidden === 'true');
check('focus returns to trigger button after ESC close', s.focusedOnTrigger, `focused=${s.focusedTag}`);

console.log('\n=== Tab is trapped inside open scenario sheet ===');
await page.evaluate(() => openScenarioSheet());
await page.waitForTimeout(200);
// Tab around — should never escape the sheet
let trapped = true;
for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Tab');
    const inside = await page.evaluate(() => {
        const sheet = document.getElementById('scenario-sheet-overlay');
        return sheet.contains(document.activeElement);
    });
    if (!inside) { trapped = false; break; }
}
check('Tab cycle stays inside scenario sheet (25 presses)', trapped);

// Shift+Tab also trapped
for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Shift+Tab');
    const inside = await page.evaluate(() => {
        const sheet = document.getElementById('scenario-sheet-overlay');
        return sheet.contains(document.activeElement);
    });
    if (!inside) { trapped = false; break; }
}
check('Shift+Tab cycle stays inside scenario sheet', trapped);

await page.keyboard.press('Escape');
await page.waitForTimeout(150);

console.log('\n=== Scenario cards are keyboard-activatable (Enter starts scenario) ===');
await page.evaluate(() => openScenarioSheet());
await page.waitForTimeout(200);
// Focus first unlocked scenario card
const focused = await page.evaluate(() => {
    const cards = document.querySelectorAll('.scenario-card:not(.locked)');
    if (!cards.length) return null;
    cards[0].focus();
    return {
        title: cards[0].querySelector('.scenario-card-title')?.textContent,
        role: cards[0].getAttribute('role'),
        tabindex: cards[0].getAttribute('tabindex'),
        label: cards[0].getAttribute('aria-label'),
    };
});
check('scenario card has role=button', focused && focused.role === 'button');
check('scenario card is tabindex=0', focused && focused.tabindex === '0');
check('scenario card has aria-label', focused && focused.label && focused.label.length > 0);

await page.keyboard.press('Enter');
await page.waitForTimeout(400);
const scenarioStarted = await page.evaluate(() => {
    const banner = document.getElementById('scenario-banner');
    return banner && banner.classList.contains('active');
});
check('Enter on scenario card starts scenario', scenarioStarted);

console.log('\n=== Input has accessible label ===');
const input = await page.evaluate(() => {
    const i = document.getElementById('user-input');
    return {
        label: i.getAttribute('aria-label'),
        autocomplete: i.getAttribute('autocomplete'),
    };
});
check('user-input has aria-label', input.label && input.label.length > 0);

console.log('\n=== Messages region marked as log/live ===');
const msgs = await page.evaluate(() => {
    const m = document.getElementById('messages');
    return {
        role: m.getAttribute('role'),
        live: m.getAttribute('aria-live'),
        label: m.getAttribute('aria-label'),
    };
});
check('#messages has role=log', msgs.role === 'log');
check('#messages has aria-live=polite', msgs.live === 'polite');
check('#messages has aria-label', msgs.label && msgs.label.length > 0);

console.log('\n=== Sticker picker button aria-expanded toggles ===');
const e1 = await page.$eval('#sticker-picker-btn', el => el.getAttribute('aria-expanded'));
await page.evaluate(() => toggleStickerPicker());
await page.waitForTimeout(100);
const e2 = await page.$eval('#sticker-picker-btn', el => el.getAttribute('aria-expanded'));
await page.evaluate(() => toggleStickerPicker());
await page.waitForTimeout(100);
const e3 = await page.$eval('#sticker-picker-btn', el => el.getAttribute('aria-expanded'));
check('sticker btn aria-expanded starts false', e1 === 'false');
check('sticker btn aria-expanded=true when opened', e2 === 'true');
check('sticker btn aria-expanded=false when closed', e3 === 'false');

await page.screenshot({ path: '/tmp/a11y-final.png' });
await browser.close();

console.log('\n=========================');
if (failures.length === 0) {
    console.log(`ALL CHECKS PASSED`);
    process.exit(0);
} else {
    console.log(`FAILURES (${failures.length}):`);
    failures.forEach(f => console.log('  - ' + f));
    process.exit(1);
}
