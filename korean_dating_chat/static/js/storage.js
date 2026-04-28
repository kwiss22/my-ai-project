/**
 * K-Dating Chat — Client-side persistence layer
 *
 * IndexedDB-backed storage for:
 *   - conversations (messages per character)
 *   - characters    (per-character intimacy / unlocked content)
 *   - vocab         (extracted Korean words, prepped for future SRS)
 *   - profile       (singleton user profile)
 *   - missions      (per-date mission completion)
 *   - meta          (streak, misc singletons)
 *
 * All functions return Promises. Safe to call before initStorage() resolves
 * — they queue on the same open() call.
 */
(function (global) {
  'use strict';

  const DB_NAME = 'kdate_chat_db';
  const DB_VERSION = 1;

  const STORE = {
    CONVERSATIONS: 'conversations',
    CHARACTERS: 'characters',
    VOCAB: 'vocab',
    PROFILE: 'profile',
    MISSIONS: 'missions',
    META: 'meta',
  };

  let dbPromise = null;

  function openDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      if (!global.indexedDB) {
        reject(new Error('IndexedDB not supported'));
        return;
      }
      const req = global.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = req.result;
        const oldVersion = e.oldVersion || 0;

        if (oldVersion < 1) {
          // conversations: one row per message, indexed by character+time
          const conv = db.createObjectStore(STORE.CONVERSATIONS, {
            keyPath: 'id',
            autoIncrement: true,
          });
          conv.createIndex('by_character', 'characterId', { unique: false });
          conv.createIndex('by_char_time', ['characterId', 'timestamp'], { unique: false });
          conv.createIndex('by_session', 'sessionId', { unique: false });

          // characters: one row per character, key = characterId
          db.createObjectStore(STORE.CHARACTERS, { keyPath: 'id' });

          // vocab: one row per word; word is unique
          const vocab = db.createObjectStore(STORE.VOCAB, {
            keyPath: 'id',
            autoIncrement: true,
          });
          vocab.createIndex('by_word', 'word', { unique: true });
          vocab.createIndex('by_seen', 'firstSeenAt', { unique: false });

          // profile: singleton (key = 'me')
          db.createObjectStore(STORE.PROFILE, { keyPath: 'id' });

          // missions: one row per YYYY-MM-DD
          db.createObjectStore(STORE.MISSIONS, { keyPath: 'date' });

          // meta: misc singletons (streak, etc.)
          db.createObjectStore(STORE.META, { keyPath: 'id' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error('IndexedDB blocked'));
    });
    return dbPromise;
  }

  function tx(storeNames, mode) {
    return openDB().then((db) => db.transaction(storeNames, mode));
  }

  function reqPromise(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function put(storeName, value) {
    return tx([storeName], 'readwrite').then((t) => {
      const store = t.objectStore(storeName);
      return reqPromise(store.put(value));
    });
  }

  function getOne(storeName, key) {
    return tx([storeName], 'readonly').then((t) => {
      const store = t.objectStore(storeName);
      return reqPromise(store.get(key));
    });
  }

  function getAll(storeName) {
    return tx([storeName], 'readonly').then((t) => {
      const store = t.objectStore(storeName);
      return reqPromise(store.getAll());
    });
  }

  function clearStore(storeName) {
    return tx([storeName], 'readwrite').then((t) => {
      return reqPromise(t.objectStore(storeName).clear());
    });
  }

  // ==========================================================================
  // Profile
  // ==========================================================================
  async function getProfile() {
    const p = await getOne(STORE.PROFILE, 'me');
    return p || { id: 'me', nickname: '', level: '', interests: [], currentCharacter: 'jiwoo' };
  }
  async function saveProfile(patch) {
    const current = await getProfile();
    const merged = Object.assign({}, current, patch, { id: 'me', updatedAt: Date.now() });
    await put(STORE.PROFILE, merged);
    return merged;
  }

  // ==========================================================================
  // Characters (intimacy, etc.)
  // ==========================================================================
  async function getCharacter(characterId) {
    const c = await getOne(STORE.CHARACTERS, characterId);
    return (
      c || {
        id: characterId,
        intimacy: 0,
        lastChatAt: 0,
        unlockedStickers: [],
      }
    );
  }
  async function saveCharacter(characterId, patch) {
    const current = await getCharacter(characterId);
    const merged = Object.assign({}, current, patch, { id: characterId });
    await put(STORE.CHARACTERS, merged);
    return merged;
  }
  async function addIntimacy(characterId, delta) {
    const c = await getCharacter(characterId);
    const next = Math.max(0, (c.intimacy || 0) + (delta || 0));
    return saveCharacter(characterId, { intimacy: next, lastChatAt: Date.now() });
  }
  async function getAllCharacters() {
    return getAll(STORE.CHARACTERS);
  }

  // ==========================================================================
  // Conversations
  // ==========================================================================
  /**
   * Append a message to a character's conversation.
   * @param {string} characterId
   * @param {'user'|'model'} role
   * @param {string} text
   * @param {string} [sessionId]  optional grouping id (one date-based session)
   * @param {object} [extra]      any extra metadata stored alongside
   */
  async function addMessage(characterId, role, text, sessionId, extra) {
    const row = {
      characterId,
      role,
      text: String(text == null ? '' : text),
      timestamp: Date.now(),
      sessionId: sessionId || todayKey(),
    };
    if (extra && typeof extra === 'object') Object.assign(row, extra);
    return put(STORE.CONVERSATIONS, row);
  }

  /**
   * Fetch last N messages for a given character, oldest-first.
   * If sessionId is provided, only messages from that session are returned
   * (use this to keep scenarios/onboarding isolated from ordinary chat).
   */
  async function getRecentMessages(characterId, limit, sessionId) {
    const cap = Math.max(1, limit || 30);
    const t = await tx([STORE.CONVERSATIONS], 'readonly');
    const store = t.objectStore(STORE.CONVERSATIONS);
    const idx = store.index('by_char_time');

    // Walk the index in reverse (newest first) for efficiency, collect up to cap.
    return new Promise((resolve, reject) => {
      const lower = [characterId, 0];
      const upper = [characterId, Number.MAX_SAFE_INTEGER];
      const range = IDBKeyRange.bound(lower, upper);
      const cursorReq = idx.openCursor(range, 'prev');
      const collected = [];
      cursorReq.onsuccess = () => {
        const cursor = cursorReq.result;
        if (cursor && collected.length < cap) {
          const v = cursor.value;
          if (!sessionId || v.sessionId === sessionId) {
            collected.push(v);
          }
          cursor.continue();
        } else {
          collected.reverse(); // oldest-first
          resolve(collected);
        }
      };
      cursorReq.onerror = () => reject(cursorReq.error);
    });
  }

  /**
   * Return conversation history in Gemini `contents` format for a character,
   * last N messages. Each entry: { role, parts: [{ text }] }.
   * If sessionId is provided, only that session's messages are returned.
   */
  async function getHistoryForGemini(characterId, limit, sessionId) {
    const rows = await getRecentMessages(characterId, limit, sessionId);
    return rows.map((r) => ({
      role: r.role === 'model' ? 'model' : 'user',
      parts: [{ text: r.text || '' }],
    }));
  }

  /**
   * Group messages for a character by YYYY-MM-DD + sessionId.
   * Returns object keyed "date_sessionId" matching prior /sessions API shape
   * so the existing history UI can keep working with minimal changes.
   */
  async function getGroupedSessions() {
    const all = await getAll(STORE.CONVERSATIONS);
    // Buffer pairs: iterate in timestamp order, pair user->model.
    all.sort((a, b) => a.timestamp - b.timestamp);
    const sessions = {};
    let pending = null; // last unpaired user message

    for (const m of all) {
      const date = new Date(m.timestamp).toISOString().slice(0, 10);
      const sid = m.sessionId || date;
      const key = `${date}_${sid}`;
      if (!sessions[key]) {
        sessions[key] = {
          date,
          session_id: sid,
          character: m.characterId,
          count: 0,
          first_message: '',
          last_time: '',
          messages: [],
        };
      }
      const s = sessions[key];
      s.character = m.characterId;
      s.last_time = formatTime(m.timestamp);

      if (m.role === 'user') {
        pending = { msg: m, session: s };
      } else if (m.role === 'model' && pending && pending.session === s) {
        const pair = {
          timestamp: formatTimestamp(pending.msg.timestamp),
          user: pending.msg.text,
          ai: m.text,
          session_id: sid,
          character: m.characterId,
        };
        s.messages.push(pair);
        s.count += 1;
        if (!s.first_message) {
          s.first_message =
            pending.msg.text.length > 30
              ? pending.msg.text.slice(0, 30) + '...'
              : pending.msg.text;
        }
        pending = null;
      }
    }

    // Sort by date+time desc
    const sortedKeys = Object.keys(sessions).sort((a, b) => {
      const A = sessions[a];
      const B = sessions[b];
      return (B.date + B.last_time).localeCompare(A.date + A.last_time);
    });
    const out = {};
    for (const k of sortedKeys) out[k] = sessions[k];
    return out;
  }

  async function clearCharacterConversation(characterId) {
    const t = await tx([STORE.CONVERSATIONS], 'readwrite');
    const store = t.objectStore(STORE.CONVERSATIONS);
    const idx = store.index('by_character');
    return new Promise((resolve, reject) => {
      const req = idx.openCursor(IDBKeyRange.only(characterId));
      req.onsuccess = () => {
        const cursor = req.result;
        if (cursor) {
          cursor.delete();
          cursor.continue();
        } else {
          resolve();
        }
      };
      req.onerror = () => reject(req.error);
    });
  }

  async function clearAllConversations() {
    return clearStore(STORE.CONVERSATIONS);
  }

  // ==========================================================================
  // Vocab
  // ==========================================================================
  /**
   * Add vocab entries, deduping by `word`. New entries only.
   * @param {Array<{word,meaning,romanization}>} entries
   * @param {string} characterId  who said it
   * @param {string} [context]    the AI message text it was extracted from
   */
  async function addVocab(entries, characterId, context) {
    if (!Array.isArray(entries) || entries.length === 0) return [];
    const t = await tx([STORE.VOCAB], 'readwrite');
    const store = t.objectStore(STORE.VOCAB);
    const idx = store.index('by_word');
    const added = [];

    await Promise.all(
      entries
        .filter((e) => e && e.word)
        .map(
          (e) =>
            new Promise((resolve) => {
              const lookup = idx.get(String(e.word));
              lookup.onsuccess = () => {
                if (lookup.result) {
                  resolve();
                  return;
                }
                const row = {
                  word: String(e.word),
                  meaning: String(e.meaning || ''),
                  romanization: String(e.romanization || ''),
                  characterId: characterId || null,
                  context: String(context || '').slice(0, 500),
                  firstSeenAt: Date.now(),
                  reviewCount: 0,
                  nextReviewAt: Date.now(),
                  easeFactor: 2.5,
                };
                const putReq = store.add(row);
                putReq.onsuccess = () => {
                  added.push(row);
                  resolve();
                };
                putReq.onerror = () => resolve(); // ignore unique conflicts
              };
              lookup.onerror = () => resolve();
            })
        )
    );

    return added;
  }

  async function getAllVocab() {
    return getAll(STORE.VOCAB);
  }

  async function getVocabCount() {
    const t = await tx([STORE.VOCAB], 'readonly');
    return reqPromise(t.objectStore(STORE.VOCAB).count());
  }

  // ==========================================================================
  // Missions
  // ==========================================================================
  async function getMissionState(date) {
    const key = date || todayKey();
    const m = await getOne(STORE.MISSIONS, key);
    return m || { date: key, missionId: null, completed: false };
  }

  async function markMissionCompleted(missionId, characterId) {
    const today = todayKey();
    const row = {
      date: today,
      missionId,
      completed: true,
      completedAt: Date.now(),
      characterId: characterId || null,
    };
    await put(STORE.MISSIONS, row);
    await bumpStreak(today);
    return row;
  }

  // ==========================================================================
  // Streak (meta singleton)
  // ==========================================================================
  async function getStreak() {
    const m = await getOne(STORE.META, 'streak');
    return m || { id: 'streak', currentStreak: 0, longestStreak: 0, lastActiveDate: null };
  }

  async function bumpStreak(todayStr) {
    const today = todayStr || todayKey();
    const s = await getStreak();
    if (s.lastActiveDate === today) return s;

    const yesterday = offsetDate(today, -1);
    const next = Object.assign({}, s);
    if (s.lastActiveDate === yesterday) {
      next.currentStreak = (s.currentStreak || 0) + 1;
    } else {
      next.currentStreak = 1;
    }
    next.longestStreak = Math.max(next.longestStreak || 0, next.currentStreak);
    next.lastActiveDate = today;
    next.id = 'streak';
    await put(STORE.META, next);
    return next;
  }

  // ==========================================================================
  // Migration from legacy localStorage
  // ==========================================================================
  async function migrateFromLocalStorage(currentCharacter) {
    const MIGRATED_KEY = 'kdate_migrated_v1';
    if (!global.localStorage) return { migrated: false, reason: 'no localStorage' };
    if (global.localStorage.getItem(MIGRATED_KEY) === '1') {
      return { migrated: false, reason: 'already migrated' };
    }

    const report = { migrated: true, items: {} };

    // Heart points -> current character intimacy
    const hp = parseInt(global.localStorage.getItem('heartPoints') || '0', 10);
    if (hp > 0) {
      await saveCharacter(currentCharacter || 'jiwoo', { intimacy: hp });
      report.items.heartPoints = hp;
    }

    // Vocab list
    try {
      const raw = global.localStorage.getItem('vocabList');
      if (raw) {
        const list = JSON.parse(raw);
        if (Array.isArray(list) && list.length) {
          await addVocab(list, null, '');
          report.items.vocabList = list.length;
        }
      }
    } catch (_) { /* ignore */ }

    // Profile bits
    const birthday = global.localStorage.getItem('user_birthday') || '';
    const mbti = global.localStorage.getItem('user_mbti') || '';
    if (birthday || mbti) {
      await saveProfile({ birthday, mbti });
      report.items.profileBits = { birthday, mbti };
    }

    // Mission completion keys: "mission-completed-YYYY-MM-DD"
    const missionKeys = [];
    for (let i = 0; i < global.localStorage.length; i++) {
      const k = global.localStorage.key(i);
      if (k && k.startsWith('mission-completed-')) missionKeys.push(k);
    }
    for (const k of missionKeys) {
      const date = k.replace('mission-completed-', '');
      await put(STORE.MISSIONS, {
        date,
        missionId: null,
        completed: true,
        completedAt: Date.now(),
        characterId: null,
      });
    }
    if (missionKeys.length) report.items.missions = missionKeys.length;

    global.localStorage.setItem(MIGRATED_KEY, '1');
    return report;
  }

  // ==========================================================================
  // Utilities
  // ==========================================================================
  function todayKey(d) {
    const date = d || new Date();
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function offsetDate(isoStr, dayDelta) {
    const [y, m, d] = isoStr.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + dayDelta);
    return todayKey(dt);
  }

  function formatTime(ms) {
    const d = new Date(ms);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${hh}:${mm}:${ss}`;
  }

  function formatTimestamp(ms) {
    return `${todayKey(new Date(ms))} ${formatTime(ms)}`;
  }

  // ==========================================================================
  // Public API
  // ==========================================================================
  const api = {
    // lifecycle
    init: openDB,
    migrateFromLocalStorage,

    // profile
    getProfile,
    saveProfile,

    // character
    getCharacter,
    saveCharacter,
    addIntimacy,
    getAllCharacters,

    // conversation
    addMessage,
    getRecentMessages,
    getHistoryForGemini,
    getGroupedSessions,
    clearCharacterConversation,
    clearAllConversations,

    // vocab
    addVocab,
    getAllVocab,
    getVocabCount,

    // missions + streak
    getMissionState,
    markMissionCompleted,
    getStreak,
    bumpStreak,

    // utilities
    todayKey,
  };

  global.KDateStorage = api;
})(window);
