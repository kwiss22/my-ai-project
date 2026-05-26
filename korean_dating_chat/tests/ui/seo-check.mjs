// 404/500 페이지 + sitemap/robots 동적 호스트 + Accept 분기.
import http from 'node:http';

const PORT = parseInt(process.env.PORT || '8080', 10);
const failures = [];
function check(name, cond, detail) {
    if (cond) console.log('  ✓ ' + name);
    else { failures.push(name + (detail ? ' — ' + detail : '')); console.log('  ✗ ' + name + (detail ? ' — ' + detail : '')); }
}

function req(method, path, opts = {}) {
    return new Promise((resolve, reject) => {
        const headers = {};
        if (opts.accept) headers['Accept'] = opts.accept;
        if (opts.host) headers['Host'] = opts.host;
        const r = http.request({ host: '127.0.0.1', port: PORT, path, method, headers }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => resolve({
                status: res.statusCode,
                ct: res.headers['content-type'] || '',
                body: data,
            }));
        });
        r.on('error', reject);
        r.end();
    });
}

console.log('=== 1. 404 — 브라우저 (Accept: text/html) ===');
let r = await req('GET', '/no-such-page', { accept: 'text/html,application/xhtml+xml' });
check('404 상태', r.status === 404);
check('  text/html 응답', /text\/html/.test(r.ct));
check('  "페이지를 찾을 수 없어요" 본문', /페이지를 찾을 수 없어요/.test(r.body));
check('  noindex 메타', /robots.*noindex/i.test(r.body));

console.log('\n=== 2. 404 — fetch (Accept: application/json) ===');
r = await req('GET', '/no-such-page', { accept: 'application/json' });
check('404 상태', r.status === 404);
check('  application/json 응답', /application\/json/.test(r.ct));
const j = (() => { try { return JSON.parse(r.body); } catch { return {}; } })();
check('  error/path 키', j.error === 'not found' && j.path === '/no-such-page');

console.log('\n=== 3. 404 — API 경로 (Accept 무관, 강제 JSON) ===');
r = await req('GET', '/admin/no-such-endpoint', { accept: 'text/html' });
check('  /admin/* 경로 → JSON 강제', /application\/json/.test(r.ct), `ct=${r.ct}`);

r = await req('GET', '/auth/no-such-endpoint', { accept: 'text/html' });
check('  /auth/* 경로 → JSON 강제', /application\/json/.test(r.ct));

console.log('\n=== 4. robots.txt 동적 호스트 ===');
r = await req('GET', '/robots.txt');
check('200 + text/plain', r.status === 200 && /text\/plain/.test(r.ct));
check('  Disallow /admin/ 포함', /Disallow:\s*\/admin\//.test(r.body));
check('  Disallow /billing/ 포함', /Disallow:\s*\/billing\//.test(r.body));
check('  Disallow /auth/ 포함', /Disallow:\s*\/auth\//.test(r.body));
check('  Sitemap 라인 존재', /Sitemap:\s+https?:\/\/.*\/sitemap\.xml/.test(r.body));
// 환경변수 APP_BASE_URL 없으면 request.host_url 가 base — 127.0.0.1:8080 또는 비슷
check('  Sitemap URL 에 kdate.store 하드코딩 X', !/kdate\.store/.test(r.body),
    `body=${r.body.split('\n').filter(l => l.includes('Sitemap')).join('|')}`);

console.log('\n=== 5. sitemap.xml 동적 + 새 페이지 ===');
r = await req('GET', '/sitemap.xml');
check('200 + xml', r.status === 200 && /xml/.test(r.ct));
check('  privacy URL 포함', /<loc>[^<]+\/privacy<\/loc>/.test(r.body));
check('  terms URL 포함', /<loc>[^<]+\/terms<\/loc>/.test(r.body));
check('  하드코딩 kdate.store X (대신 request 호스트 사용)',
    !/kdate\.store/.test(r.body),
    `sample: ${r.body.match(/<loc>[^<]+<\/loc>/)?.[0]}`);

console.log('\n=== 6. Host 헤더로 base url 변경 (CDN/도메인 대응) ===');
r = await req('GET', '/sitemap.xml', { host: 'kdating-chat-abc.run.app' });
const hostMatch = /https?:\/\/kdating-chat-abc\.run\.app\//.test(r.body);
check('Host 헤더로 sitemap base 변경됨', hostMatch,
    `first loc: ${r.body.match(/<loc>([^<]+)<\/loc>/)?.[1]}`);

console.log('\n=========================');
if (failures.length === 0) { console.log('ALL CHECKS PASSED'); process.exit(0); }
else { console.log(`FAILURES (${failures.length}):`); failures.forEach(f => console.log('  - ' + f)); process.exit(1); }
