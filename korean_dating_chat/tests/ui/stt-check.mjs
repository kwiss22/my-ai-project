// STT 음성 입력 검증.
const PORT = process.env.PORT || 8080;
// Playwright/chromium 에서는 webkitSpeechRecognition 객체가 없으므로
// 우리는 (a) 토글 버튼 상태 전환, (b) 미지원 안내, (c) 코드 시뮬레이션으로 onresult 콜백을 검증.
import { chromium } from './_playwright.mjs';

const failures = [];
function check(name, cond, detail) {
    if (cond) console.log('  ✓ ' + name);
    else { failures.push(name + (detail ? ' — ' + detail : '')); console.log('  ✗ ' + name + (detail ? ' — ' + detail : '')); }
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 420, height: 820 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => failures.push('pageerror: ' + e.message));

await page.goto(`http://127.0.0.1:${PORT}/chat`, { waitUntil: 'networkidle' });
await page.evaluate(async () => {
    try { await window.KDateStorage?.saveProfile?.({ nickname: 'Test', level: 'intermediate', interests: ['kpop'], currentCharacter: 'jiwoo' }); } catch (e) {}
    document.getElementById('onboarding-step1').style.display = 'none';
    document.getElementById('onboarding-step2').style.display = 'none';
    document.getElementById('character-selection').style.display = 'none';
    if (typeof selectCharacter === 'function') await selectCharacter('jiwoo');
});
await page.waitForTimeout(800);

console.log('\n=== Initial toggle state: empty input → mic visible, send hidden ===');
let s = await page.evaluate(() => ({
    sendDisp: getComputedStyle(document.getElementById('send-btn')).display,
    voiceDisp: getComputedStyle(document.getElementById('voice-btn')).display,
    voiceLabel: document.getElementById('voice-btn').getAttribute('aria-label'),
    voicePressed: document.getElementById('voice-btn').getAttribute('aria-pressed'),
}));
check('initial: send button hidden', s.sendDisp === 'none', `display=${s.sendDisp}`);
check('initial: voice button visible', s.voiceDisp !== 'none', `display=${s.voiceDisp}`);
check('voice button has aria-label', /음성/.test(s.voiceLabel), s.voiceLabel);
check('voice button aria-pressed=false', s.voicePressed === 'false');

console.log('\n=== Typing in input → mic hides, send shows ===');
await page.locator('#user-input').fill('안녕하세요');
await page.waitForTimeout(100);
s = await page.evaluate(() => ({
    sendDisp: getComputedStyle(document.getElementById('send-btn')).display,
    voiceDisp: getComputedStyle(document.getElementById('voice-btn')).display,
}));
check('typing: send button visible', s.sendDisp !== 'none', `display=${s.sendDisp}`);
check('typing: voice button hidden', s.voiceDisp === 'none', `display=${s.voiceDisp}`);

console.log('\n=== Clearing input → mic comes back ===');
await page.locator('#user-input').fill('');
await page.waitForTimeout(100);
s = await page.evaluate(() => ({
    sendDisp: getComputedStyle(document.getElementById('send-btn')).display,
    voiceDisp: getComputedStyle(document.getElementById('voice-btn')).display,
}));
check('clearing input: send hidden again', s.sendDisp === 'none');
check('clearing input: voice visible again', s.voiceDisp !== 'none');

console.log('\n=== Unsupported browser path: toast appears ===');
// Chromium does NOT have webkitSpeechRecognition by default. Confirm.
const supported = await page.evaluate(() => 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window);
console.log('  (Chromium webkitSpeechRecognition available?', supported, ')');

if (!supported) {
    // Tap mic; should show "지원하지 않아요" toast
    await page.locator('#voice-btn').click();
    await page.waitForTimeout(400);
    const toast = await page.evaluate(() => document.getElementById('toast')?.textContent || '');
    check('unsupported browser: toast shown', /지원하지 않/.test(toast), `toast="${toast}"`);
    // Button should NOT enter recording state when unsupported
    const recording = await page.evaluate(() => document.getElementById('voice-btn').classList.contains('recording'));
    check('unsupported: button does not enter recording state', !recording);
}

console.log('\n=== Simulate supported browser: mock SR + verify state transitions ===');
const sim = await page.evaluate(async () => {
    // Reset cached recognition
    _recognition = null;
    _recognitionActive = false;

    // Install a fake recognition class — override BOTH global names so
    // _ensureRecognition picks ours (Chromium has webkitSpeechRecognition real, may also have SpeechRecognition).
    let lastInstance = null;
    const FakeSR = class FakeSR {
        constructor() {
            this.lang = '';
            this.interimResults = false;
            this.continuous = true;
            this.maxAlternatives = 1;
            this.onresult = null;
            this.onerror = null;
            this.onend = null;
            lastInstance = this;
        }
        start() { this._started = true; }
        stop() {
            if (this.onend) this.onend();
        }
    };
    window.webkitSpeechRecognition = FakeSR;
    window.SpeechRecognition = FakeSR;
    window.__lastSR = () => lastInstance;

    // Tap voice → should start
    toggleVoiceInput();
    const after1 = {
        rec: document.getElementById('voice-btn').classList.contains('recording'),
        pressed: document.getElementById('voice-btn').getAttribute('aria-pressed'),
        label: document.getElementById('voice-btn').getAttribute('aria-label'),
        glow: document.getElementById('user-input').classList.contains('recording-glow'),
    };

    // Fire fake result (interim + final)
    const sr = window.__lastSR();
    sr.onresult({
        resultIndex: 0,
        results: [
            Object.assign([{ transcript: '오늘 ' }], { isFinal: false }),
            Object.assign([{ transcript: '날씨가 좋네요' }], { isFinal: true }),
        ],
    });
    const after2 = {
        inputVal: document.getElementById('user-input').value,
        sendDisp: getComputedStyle(document.getElementById('send-btn')).display,
        voiceDisp: getComputedStyle(document.getElementById('voice-btn')).display,
    };

    // Tap voice again → should stop (onend handler runs)
    toggleVoiceInput();
    // FakeSR.stop() triggers onend synchronously
    const after3 = {
        rec: document.getElementById('voice-btn').classList.contains('recording'),
        pressed: document.getElementById('voice-btn').getAttribute('aria-pressed'),
        glow: document.getElementById('user-input').classList.contains('recording-glow'),
    };

    return { after1, after2, after3, srLang: sr.lang, srInterim: sr.interimResults };
});
check('on start: recording class added', sim.after1.rec);
check('on start: aria-pressed=true', sim.after1.pressed === 'true');
check('on start: aria-label flips to "중지"', /중지/.test(sim.after1.label));
check('on start: input gets recording-glow', sim.after1.glow);
check('SR configured for ko-KR', sim.srLang === 'ko-KR');
check('SR configured with interimResults', sim.srInterim === true);
check('onresult fills input', sim.after2.inputVal && sim.after2.inputVal.includes('날씨가 좋네요'),
    `value="${sim.after2.inputVal}"`);
check('onresult triggers send-btn visibility', sim.after2.sendDisp !== 'none' && sim.after2.voiceDisp === 'none');
check('on stop: recording class removed', !sim.after3.rec);
check('on stop: aria-pressed back to false', sim.after3.pressed === 'false');
check('on stop: glow removed', !sim.after3.glow);

console.log('\n=== visibilitychange handler stops recognition when tab hidden ===');
const visTest = await page.evaluate(async () => {
    _recognition = null;
    _recognitionActive = false;
    let stopped = false;
    const FakeSR2 = class {
        constructor() {}
        start() {}
        stop() { stopped = true; if (this.onend) this.onend(); }
    };
    window.webkitSpeechRecognition = FakeSR2;
    window.SpeechRecognition = FakeSR2;
    toggleVoiceInput();
    const before = _recognitionActive;
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    return { before, stopped, afterActive: _recognitionActive };
});
check('recognition is active before hide', visTest.before);
check('recognition.stop() is called on visibilitychange', visTest.stopped);
check('recognition inactive after hide', !visTest.afterActive);

await page.screenshot({ path: '/tmp/stt-final.png' });
await browser.close();

console.log('\n=========================');
if (failures.length === 0) { console.log('ALL CHECKS PASSED'); process.exit(0); }
else { console.log(`FAILURES (${failures.length}):`); failures.forEach(f => console.log('  - ' + f)); process.exit(1); }
