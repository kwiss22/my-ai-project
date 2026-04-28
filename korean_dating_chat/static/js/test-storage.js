/**
 * K-Dating Chat — IndexedDB storage self-test
 *
 * Usage (in browser devtools console on /chat):
 *   var s=document.createElement('script');
 *   s.src='/static/js/test-storage.js?'+Date.now();
 *   document.body.appendChild(s);
 *
 * Or, after the page is loaded:
 *   await window.KDateStorageTest.runAll()
 *
 * Safety:
 *   - Uses isolated characterIds prefixed with "__test__" so real chat data
 *     (jiwoo / hyunwoo) is never touched.
 *   - Migration test backs up and restores the `kdate_migrated_v1` flag and
 *     any localStorage keys it simulates, so existing migration state is
 *     preserved.
 *   - Every test cleans up its own test rows at the end.
 */
(function (global) {
  'use strict';

  const TEST_A = '__test__alpha';
  const TEST_B = '__test__beta';

  const results = [];
  let passCount = 0;
  let failCount = 0;

  function log(level, ...args) {
    const prefix = '[KDateStorageTest]';
    if (level === 'pass') console.log('%c' + prefix + ' PASS', 'color:#2da160;font-weight:bold', ...args);
    else if (level === 'fail') console.error(prefix + ' FAIL', ...args);
    else if (level === 'group') console.log('%c' + prefix + ' ' + args[0], 'color:#3b82f6;font-weight:bold');
    else console.log(prefix, ...args);
  }

  async function test(name, fn) {
    try {
      await fn();
      results.push({ name, status: 'pass' });
      passCount += 1;
      log('pass', name);
    } catch (e) {
      results.push({ name, status: 'fail', error: e && e.message ? e.message : String(e) });
      failCount += 1;
      log('fail', name, '—', e && e.message ? e.message : e);
      if (e && e.stack) console.error(e.stack);
    }
  }

  function assert(cond, msg) {
    if (!cond) throw new Error(msg || 'assertion failed');
  }

  function eq(a, b, msg) {
    if (a !== b) throw new Error((msg || 'not equal') + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
  }

  function deepEq(a, b, msg) {
    const sa = JSON.stringify(a);
    const sb = JSON.stringify(b);
    if (sa !== sb) throw new Error((msg || 'deep not equal') + ` (got ${sa}, expected ${sb})`);
  }

  async function cleanupTestRows() {
    const S = global.KDateStorage;
    await S.clearCharacterConversation(TEST_A);
    await S.clearCharacterConversation(TEST_B);
    // Remove test characters rows directly
    const db = await S.init();
    await new Promise((resolve, reject) => {
      const t = db.transaction(['characters'], 'readwrite');
      const store = t.objectStore('characters');
      [TEST_A, TEST_B].forEach((id) => store.delete(id));
      t.oncomplete = resolve;
      t.onerror = () => reject(t.error);
    });
  }

  // ==========================================================================
  // Tests
  // ==========================================================================

  async function testInit() {
    const S = global.KDateStorage;
    assert(S, 'window.KDateStorage missing — make sure /static/js/storage.js is loaded');
    const db = await S.init();
    assert(db, 'init() returned no db');
    eq(db.name, 'kdate_chat_db', 'db name');
    const stores = Array.from(db.objectStoreNames);
    ['conversations', 'characters', 'vocab', 'profile', 'missions', 'meta'].forEach((n) => {
      assert(stores.includes(n), `missing object store: ${n}`);
    });
  }

  async function testProfileRoundtrip() {
    const S = global.KDateStorage;
    const original = await S.getProfile();
    try {
      await S.saveProfile({ nickname: '__selftest__', level: 'intermediate', interests: ['kdrama', 'kpop'] });
      const got = await S.getProfile();
      eq(got.nickname, '__selftest__', 'nickname roundtrip');
      eq(got.level, 'intermediate', 'level roundtrip');
      deepEq(got.interests, ['kdrama', 'kpop'], 'interests roundtrip');
      assert(typeof got.updatedAt === 'number', 'updatedAt stamped');
    } finally {
      await S.saveProfile({
        nickname: original.nickname || '',
        level: original.level || '',
        interests: Array.isArray(original.interests) ? original.interests : [],
      });
    }
  }

  async function testCharacterIsolation_D() {
    const S = global.KDateStorage;
    await cleanupTestRows();

    await S.addMessage(TEST_A, 'user', 'A-user-1');
    await S.addMessage(TEST_A, 'model', 'A-model-1');
    await S.addMessage(TEST_B, 'user', 'B-user-1');
    await S.addMessage(TEST_B, 'model', 'B-model-1');
    await S.addMessage(TEST_A, 'user', 'A-user-2');
    await S.addMessage(TEST_A, 'model', 'A-model-2');

    const aMsgs = await S.getRecentMessages(TEST_A, 50);
    const bMsgs = await S.getRecentMessages(TEST_B, 50);

    eq(aMsgs.length, 4, 'A has 4 messages');
    eq(bMsgs.length, 2, 'B has 2 messages');
    assert(
      aMsgs.every((m) => m.characterId === TEST_A),
      'A has no cross-contaminated rows'
    );
    assert(
      bMsgs.every((m) => m.characterId === TEST_B),
      'B has no cross-contaminated rows'
    );
    // ordering: oldest-first
    eq(aMsgs[0].text, 'A-user-1', 'A oldest first');
    eq(aMsgs[aMsgs.length - 1].text, 'A-model-2', 'A newest last');
  }

  async function testSessionIsolation_D2() {
    const S = global.KDateStorage;
    await cleanupTestRows();

    const sNormal = 'normal-sess';
    const sScenario = 'scenario-cafe';

    await S.addMessage(TEST_A, 'user', 'hi', sNormal);
    await S.addMessage(TEST_A, 'model', 'hello', sNormal);
    await S.addMessage(TEST_A, 'user', 'pretend you are a barista', sScenario);
    await S.addMessage(TEST_A, 'model', 'welcome to our cafe', sScenario);
    await S.addMessage(TEST_A, 'user', 'how are you', sNormal);
    await S.addMessage(TEST_A, 'model', 'fine', sNormal);

    const all = await S.getRecentMessages(TEST_A, 50);
    eq(all.length, 6, 'all 6 messages visible without sessionId filter');

    const normalOnly = await S.getRecentMessages(TEST_A, 50, sNormal);
    eq(normalOnly.length, 4, 'normal session isolated');
    assert(
      normalOnly.every((m) => m.sessionId === sNormal),
      'normal-only contains no scenario rows'
    );

    const scenarioOnly = await S.getRecentMessages(TEST_A, 50, sScenario);
    eq(scenarioOnly.length, 2, 'scenario session isolated');
    eq(scenarioOnly[0].text, 'pretend you are a barista', 'scenario ordering oldest first');
  }

  async function testGeminiHistoryShape() {
    const S = global.KDateStorage;
    await cleanupTestRows();
    await S.addMessage(TEST_A, 'user', 'q1');
    await S.addMessage(TEST_A, 'model', 'a1');
    await S.addMessage(TEST_A, 'user', 'q2');

    const contents = await S.getHistoryForGemini(TEST_A, 10);
    eq(contents.length, 3, '3 entries');
    eq(contents[0].role, 'user');
    eq(contents[1].role, 'model');
    assert(Array.isArray(contents[0].parts), 'parts is array');
    eq(contents[0].parts[0].text, 'q1', 'first text correct');
  }

  async function testHistoryLimit() {
    const S = global.KDateStorage;
    await cleanupTestRows();
    for (let i = 0; i < 20; i++) {
      await S.addMessage(TEST_A, i % 2 === 0 ? 'user' : 'model', 'm' + i);
    }
    const last5 = await S.getRecentMessages(TEST_A, 5);
    eq(last5.length, 5, 'limit respected');
    eq(last5[0].text, 'm15', 'oldest of the 5 is m15');
    eq(last5[4].text, 'm19', 'newest is m19');
  }

  async function testIntimacy() {
    const S = global.KDateStorage;
    await cleanupTestRows();
    const start = await S.getCharacter(TEST_A);
    eq(start.intimacy, 0, 'fresh intimacy is 0');
    await S.addIntimacy(TEST_A, 5);
    await S.addIntimacy(TEST_A, 3);
    const mid = await S.getCharacter(TEST_A);
    eq(mid.intimacy, 8, '5+3=8');
    await S.addIntimacy(TEST_A, -20);
    const floored = await S.getCharacter(TEST_A);
    eq(floored.intimacy, 0, 'floors at 0, never negative');
  }

  async function testVocabDedup() {
    const S = global.KDateStorage;
    const before = await S.getAllVocab();
    const beforeSet = new Set(before.map((v) => v.word));
    const uniqWord = '__selftest_word_' + Date.now();
    const added1 = await S.addVocab(
      [{ word: uniqWord, meaning: 'test', romanization: 'teseuteu' }],
      TEST_A,
      'ctx'
    );
    const added2 = await S.addVocab(
      [{ word: uniqWord, meaning: 'dup', romanization: '' }],
      TEST_A,
      'ctx2'
    );
    eq(added1.length, 1, 'first add inserts');
    eq(added2.length, 0, 'second add dedup-skips');

    // cleanup: remove our test vocab entry (it was not in `before`)
    const after = await S.getAllVocab();
    const ours = after.find((v) => v.word === uniqWord);
    if (ours) {
      const db = await S.init();
      await new Promise((resolve, reject) => {
        const t = db.transaction(['vocab'], 'readwrite');
        t.objectStore('vocab').delete(ours.id);
        t.oncomplete = resolve;
        t.onerror = () => reject(t.error);
      });
    }
    assert(!beforeSet.has(uniqWord), 'sanity: test word did not pre-exist');
  }

  async function testGroupedSessions() {
    const S = global.KDateStorage;
    await cleanupTestRows();
    // getGroupedSessions keys by UTC date (toISOString slice), so match that here.
    const today = new Date().toISOString().slice(0, 10);
    const sid = 'grp-test-' + Date.now();
    await S.addMessage(TEST_A, 'user', 'hello there friend', sid);
    await S.addMessage(TEST_A, 'model', 'hi back', sid);
    await S.addMessage(TEST_A, 'user', 'second question', sid);
    await S.addMessage(TEST_A, 'model', 'second answer', sid);

    const grouped = await S.getGroupedSessions();
    const key = `${today}_${sid}`;
    const sess = grouped[key];
    assert(sess, 'session key present');
    eq(sess.count, 2, 'pair count = 2');
    eq(sess.character, TEST_A, 'character stamped');
    assert(sess.first_message.startsWith('hello there friend'), 'first_message preview correct');
    eq(sess.messages.length, 2, 'messages array has 2 pairs');
    eq(sess.messages[0].user, 'hello there friend');
    eq(sess.messages[0].ai, 'hi back');
  }

  async function testMigrationFromLocalStorage_G() {
    const S = global.KDateStorage;
    const LS = global.localStorage;
    if (!LS) throw new Error('no localStorage');

    const MIGRATED_KEY = 'kdate_migrated_v1';

    // Backup existing values so we restore them after the test.
    const backup = {
      migrated: LS.getItem(MIGRATED_KEY),
      heartPoints: LS.getItem('heartPoints'),
      vocabList: LS.getItem('vocabList'),
      user_birthday: LS.getItem('user_birthday'),
      user_mbti: LS.getItem('user_mbti'),
    };
    // Also backup the test character intimacy (we'll overwrite via migration target)
    const originalChar = await S.getCharacter(TEST_A);
    // And profile birthday/mbti
    const originalProfile = await S.getProfile();

    const uniqVocabWord = '__mig_selftest_' + Date.now();

    try {
      LS.removeItem(MIGRATED_KEY);
      LS.setItem('heartPoints', '42');
      LS.setItem(
        'vocabList',
        JSON.stringify([{ word: uniqVocabWord, meaning: 'migration test', romanization: '' }])
      );
      LS.setItem('user_birthday', '1990-01-01');
      LS.setItem('user_mbti', 'INFP');

      const report = await S.migrateFromLocalStorage(TEST_A);
      assert(report.migrated, 'migration returned migrated:true');
      eq(report.items.heartPoints, 42, 'heartPoints reported');
      eq(report.items.vocabList, 1, 'vocabList reported 1');
      assert(report.items.profileBits, 'profileBits present');

      const c = await S.getCharacter(TEST_A);
      eq(c.intimacy, 42, 'intimacy migrated to 42');

      const vocabRows = await S.getAllVocab();
      assert(
        vocabRows.some((v) => v.word === uniqVocabWord),
        'migrated vocab entry present'
      );

      const prof = await S.getProfile();
      eq(prof.birthday, '1990-01-01', 'birthday migrated');
      eq(prof.mbti, 'INFP', 'mbti migrated');

      // Idempotency: second call should be a no-op.
      const report2 = await S.migrateFromLocalStorage(TEST_A);
      assert(!report2.migrated, 'second migration skipped');
      eq(report2.reason, 'already migrated', 'skip reason correct');
    } finally {
      // Restore localStorage to exactly what it was.
      const restore = (k, v) => {
        if (v === null || v === undefined) LS.removeItem(k);
        else LS.setItem(k, v);
      };
      restore(MIGRATED_KEY, backup.migrated);
      restore('heartPoints', backup.heartPoints);
      restore('vocabList', backup.vocabList);
      restore('user_birthday', backup.user_birthday);
      restore('user_mbti', backup.user_mbti);

      // Restore profile birthday/mbti
      await S.saveProfile({
        birthday: originalProfile.birthday || '',
        mbti: originalProfile.mbti || '',
      });

      // Remove the migrated vocab row we inserted
      const vocabRows = await S.getAllVocab();
      const ours = vocabRows.find((v) => v.word === uniqVocabWord);
      if (ours) {
        const db = await S.init();
        await new Promise((resolve, reject) => {
          const t = db.transaction(['vocab'], 'readwrite');
          t.objectStore('vocab').delete(ours.id);
          t.oncomplete = resolve;
          t.onerror = () => reject(t.error);
        });
      }

      // Restore test character row (cleanupTestRows will also nuke it anyway)
      await S.saveCharacter(TEST_A, originalChar);
    }
  }

  async function testStreakBump() {
    const S = global.KDateStorage;
    const original = await S.getStreak();
    try {
      // Reset streak via a direct META write
      const db = await S.init();
      await new Promise((resolve, reject) => {
        const t = db.transaction(['meta'], 'readwrite');
        t.objectStore('meta').put({
          id: 'streak',
          currentStreak: 0,
          longestStreak: original.longestStreak || 0,
          lastActiveDate: null,
        });
        t.oncomplete = resolve;
        t.onerror = () => reject(t.error);
      });

      const today = S.todayKey();
      await S.bumpStreak(today);
      let s = await S.getStreak();
      eq(s.currentStreak, 1, 'first bump sets streak=1');
      eq(s.lastActiveDate, today, 'lastActiveDate set');

      await S.bumpStreak(today);
      s = await S.getStreak();
      eq(s.currentStreak, 1, 'same-day bump idempotent');
    } finally {
      // Restore original streak row
      const db = await S.init();
      await new Promise((resolve, reject) => {
        const t = db.transaction(['meta'], 'readwrite');
        t.objectStore('meta').put(Object.assign({ id: 'streak' }, original));
        t.oncomplete = resolve;
        t.onerror = () => reject(t.error);
      });
    }
  }

  // ==========================================================================
  // Runner
  // ==========================================================================
  async function runAll() {
    passCount = 0;
    failCount = 0;
    results.length = 0;

    log('group', '=== K-Dating Storage Self-Test ===');

    await test('init + object stores', testInit);
    await test('profile roundtrip', testProfileRoundtrip);
    await test('character isolation (D)', testCharacterIsolation_D);
    await test('session isolation / scenario mode (D2)', testSessionIsolation_D2);
    await test('getHistoryForGemini shape', testGeminiHistoryShape);
    await test('recent messages limit', testHistoryLimit);
    await test('intimacy add + floor at 0', testIntimacy);
    await test('vocab dedup by word', testVocabDedup);
    await test('grouped sessions (history view)', testGroupedSessions);
    await test('migration from localStorage (G)', testMigrationFromLocalStorage_G);
    await test('streak bump same-day idempotent', testStreakBump);

    // Final cleanup
    try {
      await cleanupTestRows();
    } catch (e) {
      log('fail', 'cleanup', e);
    }

    const total = passCount + failCount;
    const summary = `Results: ${passCount}/${total} passed, ${failCount} failed`;
    if (failCount === 0) {
      console.log('%c' + summary, 'color:#2da160;font-weight:bold;font-size:14px');
    } else {
      console.log('%c' + summary, 'color:#dc2626;font-weight:bold;font-size:14px');
    }

    // Print a nice table
    try {
      console.table(results);
    } catch (_) {
      console.log(results);
    }

    return { pass: passCount, fail: failCount, total, results: results.slice() };
  }

  global.KDateStorageTest = { runAll };

  // If loaded via <script> tag, auto-run after a short delay so the page settles.
  if (document.currentScript) {
    setTimeout(() => {
      runAll().catch((e) => console.error('[KDateStorageTest] uncaught', e));
    }, 200);
  }
})(window);
