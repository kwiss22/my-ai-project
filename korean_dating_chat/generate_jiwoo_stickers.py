"""
지우 이미지 스티커 생성 스크립트
google-genai SDK의 Imagen 3 사용
"""
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

OUTPUT_DIR = Path(__file__).parent / "static" / "stickers"
OUTPUT_DIR.mkdir(exist_ok=True)

# 공통 스타일 프롬프트 (현우 스티커와 동일한 웹툰 스타일)
BASE_STYLE = (
    "Korean webtoon manhwa illustration style sticker, "
    "cute Korean college girl named Jiwoo, 22 years old, "
    "long dark hair, soft round face, big expressive eyes, "
    "wearing a cozy pastel pink or white knit sweater, "
    "upper body portrait, white thick outline border sticker style, "
    "white or transparent background, clean flat illustration, "
    "no text, no watermark, high quality"
)

STICKERS = [
    {
        "id": "jiwoo_happy",
        "caption": "기분 좋아요~",
        "prompt": f"{BASE_STYLE}, big bright happy smile, eyes curved in joy, arms slightly raised in excitement, cheerful expression",
    },
    {
        "id": "jiwoo_love",
        "caption": "좋아해요",
        "prompt": f"{BASE_STYLE}, making a heart shape with both hands held up near face, soft loving smile, rosy cheeks, sweet romantic expression",
    },
    {
        "id": "jiwoo_shy",
        "caption": "부끄러워요...",
        "prompt": f"{BASE_STYLE}, both hands covering reddened cheeks, eyes looking down shyly, intense blushing, embarrassed expression",
    },
    {
        "id": "jiwoo_coffee",
        "caption": "커피 한 잔 할래요?",
        "prompt": f"{BASE_STYLE}, holding a cute pastel takeout coffee cup with both hands, warm gentle smile, cozy cafe vibe expression",
    },
    {
        "id": "jiwoo_sad",
        "caption": "보고 싶어요",
        "prompt": f"{BASE_STYLE}, sad teary eyes, small pout, one hand resting on cheek, slightly drooping expression, longing and missing someone",
    },
    {
        "id": "jiwoo_cheer",
        "caption": "파이팅!",
        "prompt": f"{BASE_STYLE}, one fist raised up in fighting pose, confident bright smile, energetic cheerful expression, motivating pose",
    },
    {
        "id": "jiwoo_wink",
        "caption": "비밀이에요~",
        "prompt": f"{BASE_STYLE}, playful wink with one eye, finger pressed to lips in shush gesture, mischievous cute smile, secretive expression",
    },
    {
        "id": "jiwoo_hug",
        "caption": "안아줄게요",
        "prompt": f"{BASE_STYLE}, arms stretched wide open for a hug, warm gentle smile, inviting affectionate expression, caring pose",
    },
]


def generate_sticker(sticker: dict) -> bool:
    output_path = OUTPUT_DIR / f"{sticker['id']}.png"
    if output_path.exists():
        print(f"  [SKIP] {sticker['id']}.png already exists")
        return True

    print(f"  Generating {sticker['id']} ({sticker['caption']})...")
    try:
        response = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=sticker["prompt"],
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
            ),
        )
        if response.generated_images:
            img_data = response.generated_images[0].image.image_bytes
            output_path.write_bytes(img_data)
            print(f"  [OK] Saved {output_path.name} ({len(img_data)//1024}KB)")
            return True
        else:
            print(f"  [FAIL] No image returned for {sticker['id']}")
            return False
    except Exception as e:
        print(f"  [ERROR] {sticker['id']}: {e}")
        return False


if __name__ == "__main__":
    print(f"Generating {len(STICKERS)} Jiwoo stickers...\n")
    success = 0
    for sticker in STICKERS:
        ok = generate_sticker(sticker)
        if ok:
            success += 1
        time.sleep(2)  # API rate limit

    print(f"\nDone: {success}/{len(STICKERS)} stickers generated")
    print(f"Output: {OUTPUT_DIR}")
