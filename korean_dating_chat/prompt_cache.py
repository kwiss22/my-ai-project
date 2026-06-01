"""Gemini Prompt Caching — 캐릭터 페르소나 explicit 캐시.

각 캐릭터의 시스템 프롬프트를 Gemini API 에 미리 캐시 등록 → 매 요청마다 다시
전송하지 않고 캐시 참조만으로 처리. 캐시된 input 토큰은 통상 가격의 ~25% 만 청구.

캐시 lifecycle:
  - 첫 요청 시 lazy create (per character × model)
  - TTL 안에 재사용 → 캐시 hit (저렴)
  - TTL 경과 → 다음 요청 시 재생성
  - 캐시 생성 실패 → None 반환. 호출자는 system_instruction 직접 전달 fallback.
  - 업스트림 cache miss (예: 캐시 GC) → invalidate(character) 호출 시 캐시 재발급

ENV:
  PROMPT_CACHE_ENABLED        '1' (기본) 또는 '0' — 캐싱 비활성화
  PROMPT_CACHE_TTL_SECONDS    캐시 수명 (기본 3600s = 1시간)
  PROMPT_CACHE_MIN_TOKENS     최소 토큰. 미만이면 캐싱 못 함 (Gemini 2.5 Flash: 1024)
"""
import os
import time
from threading import Lock

ENABLED = os.getenv('PROMPT_CACHE_ENABLED', '1') == '1'
TTL_SECONDS = int(os.getenv('PROMPT_CACHE_TTL_SECONDS', '3600'))
MIN_TOKENS = int(os.getenv('PROMPT_CACHE_MIN_TOKENS', '1024'))

_CACHES = {}   # {(model, character): {'name': str, 'expires_at': float}}
_LOCK = Lock()


def _estimate_tokens(text):
    # Gemini tokenizer 부르지 않고 빠른 근사 — 한·영 mix 평균 ~4 chars/token.
    return len(text) // 4


def get_or_create(client, types_module, model, character_id, system_instruction):
    """캐시 lookup or create. 캐시 이름(예: 'cachedContents/xxx') 반환, 실패 시 None.

    호출자는 None 이면 system_instruction 을 직접 config 에 전달 (기존 흐름).
    """
    if not ENABLED or not client or not character_id or not system_instruction:
        return None
    if _estimate_tokens(system_instruction) < MIN_TOKENS:
        return None

    now = time.time()
    key = (model, character_id)

    with _LOCK:
        cached = _CACHES.get(key)
        if cached and cached['expires_at'] > now + 60:
            return cached['name']

    # API 호출은 lock 밖에서 — 다른 캐릭터 캐시 생성과 직렬화 불필요
    try:
        cache = client.caches.create(
            model=model,
            config=types_module.CreateCachedContentConfig(
                system_instruction=system_instruction,
                ttl=f'{TTL_SECONDS}s',
            ),
        )
    except Exception as e:
        print(f"[PromptCache] create failed (model={model}, char={character_id}): {e}")
        return None

    name = getattr(cache, 'name', None)
    if not name:
        return None
    with _LOCK:
        _CACHES[key] = {'name': name, 'expires_at': now + TTL_SECONDS}
    return name


def invalidate(model=None, character_id=None):
    """업스트림 캐시 expired/missing 일 때 로컬 엔트리 제거 → 다음 요청 재생성.

    args 모두 None 이면 전체 flush.
    """
    with _LOCK:
        if model is None and character_id is None:
            _CACHES.clear()
            return
        for key in list(_CACHES.keys()):
            if (model is None or key[0] == model) and (character_id is None or key[1] == character_id):
                del _CACHES[key]


def stats():
    """관측용 — 현재 보유한 캐시 수."""
    with _LOCK:
        return {
            'enabled': ENABLED,
            'count': len(_CACHES),
            'entries': [
                {'model': k[0], 'character': k[1], 'expires_in_s': max(0, int(v['expires_at'] - time.time()))}
                for k, v in _CACHES.items()
            ],
        }
