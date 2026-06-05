"""
원화(WONHWA) 캐릭터 스티커 생성 — Imagen 4 (google-genai)
화랑/지우 스티커와 동일한 웹툰 스타일, 멤버별 외모 프롬프트로 일관성 확보.
감정 6종(화랑과 동일): cheer, heart, laugh, shy, think, wink

사용:
    python generate_wonhwa_stickers.py            # MEMBERS_TO_RUN 만 생성
"""
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
OUTPUT_DIR = Path(__file__).parent / "static" / "stickers"
OUTPUT_DIR.mkdir(exist_ok=True)

# 멤버별 외모/분위기 (캐릭터 설정 기반). 화랑 스티커와 같은 웹툰 manhwa 스타일.
STICKER_STYLE = (
    "Korean webtoon manhwa illustration style sticker, "
    "{persona}, "
    "upper body portrait, thick white outline border sticker style, "
    "plain white background, clean flat illustration, "
    "no text, no watermark, high quality, "
    "{emotion}"
)

MEMBERS = {
    "sua": (
        "elegant Korean K-pop girl group leader named Sua, 26 years old, "
        "calm refined charismatic beauty, long sleek straight dark brown hair, "
        "graceful mature feminine face, gentle confident almond eyes, soft natural makeup, "
        "wearing an elegant cream knit sweater or soft beige blazer"
    ),
}

# 감정 6종 — 화랑 세트와 동일 ID
EMOTIONS = {
    "cheer": "one hand gently raised in a soft encouraging fist, warm supportive smile, calm fighting spirit pose",
    "heart": "making a small heart shape with both hands near chest, gentle loving smile, soft affectionate expression",
    "laugh": "elegant soft laughter, one hand lightly covering mouth, eyes curved warmly, refined cheerful expression",
    "shy":   "faint blush on cheeks, gaze lowered gently, composed shy smile, subtle embarrassed expression",
    "think": "one hand resting lightly on chin, thoughtful calm expression looking slightly upward, contemplative",
    "wink":  "gentle playful wink with one eye, subtle confident smile, light teasing expression",
}

# 이번 실행 대상 (수아 먼저)
MEMBERS_TO_RUN = ["sua"]


def generate(member: str, emotion: str, persona: str, emo_prompt: str) -> bool:
    sticker_id = f"{member}_{emotion}"
    out = OUTPUT_DIR / f"{sticker_id}.png"
    if out.exists():
        print(f"  [SKIP] {sticker_id}.png exists")
        return True
    prompt = STICKER_STYLE.format(persona=persona, emotion=emo_prompt)
    print(f"  Generating {sticker_id} ...")
    try:
        resp = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="1:1"),
        )
        if resp.generated_images:
            data = resp.generated_images[0].image.image_bytes
            out.write_bytes(data)
            print(f"  [OK] {out.name} ({len(data)//1024}KB)")
            return True
        print(f"  [FAIL] no image for {sticker_id}")
        return False
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "depleted" in err.lower():
            print(f"  [BILLING] Imagen credits depleted — add credits at https://ai.studio/")
        print(f"  [ERROR] {sticker_id}: {e}")
        return False


def main():
    ok = 0
    total = 0
    for member in MEMBERS_TO_RUN:
        persona = MEMBERS[member]
        print(f"\n=== {member} ===")
        for emotion, emo_prompt in EMOTIONS.items():
            total += 1
            if generate(member, emotion, persona, emo_prompt):
                ok += 1
            time.sleep(2)  # rate-limit 여유
    print(f"\nDone: {ok}/{total} stickers")


if __name__ == "__main__":
    main()
