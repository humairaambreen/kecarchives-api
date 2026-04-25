import asyncio
import base64
import random
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/ai", tags=["ai"])

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# HuggingFace Inference API — new 2025 router endpoint
# Uses FLUX.1-schnell (fast, free tier)
# Get token: huggingface.co → Settings → Access Tokens → New token (read + inference)
# Add to .env: HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
HF_URL   = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

COLLEGE_CONTEXT = (
    "Krishna Engineering College (KEC), Bhilai, Chhattisgarh — a premier engineering college "
    "known for academic excellence, innovation, technical events, and a vibrant campus culture."
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class EnhancePostRequest(BaseModel):
    topic: str

class EnhancePostResponse(BaseModel):
    content: str

class ImagePromptRequest(BaseModel):
    post_content: str

class ImagePromptResponse(BaseModel):
    image_prompt: str

class GenerateImageRequest(BaseModel):
    prompt: str

class GenerateImageResponse(BaseModel):
    image_base64: str


# ── Groq ──────────────────────────────────────────────────────────────────────

async def call_groq(system: str, user: str, max_tokens: int = 600, temperature: float = 0.85) -> str:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY not set. Get a free key at https://console.groq.com",
        )
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            GROQ_URL,
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
        )
    if res.status_code == 429:
        raise HTTPException(status_code=429, detail="Groq rate limit — wait a moment and try again.")
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Groq error {res.status_code}: {res.text[:300]}")
    text = res.json()["choices"][0]["message"]["content"].strip()
    if not text:
        raise HTTPException(status_code=502, detail="Groq returned an empty response.")
    return text


# ── Fallback image prompt ─────────────────────────────────────────────────────

def _fallback_image_prompt(text: str) -> str:
    lower = text.lower()
    if "fresher"   in lower: return "college freshers welcome party, excited students, colorful stage decorations, auditorium, warm lighting"
    if "farewell"  in lower: return "college farewell ceremony, emotional graduates, flowers and streamers, auditorium, warm lighting"
    if "holi"      in lower: return "students celebrating holi with colorful powder, college campus, joyful atmosphere, vibrant colors"
    if "convocation" in lower or "graduation" in lower: return "graduation ceremony, students in caps and gowns, college auditorium, celebratory atmosphere"
    if any(w in lower for w in ["sport", "cricket", "football"]): return "college sports day, students competing on field, energetic atmosphere, natural lighting"
    if any(w in lower for w in ["hackathon", "tech", "coding"]):  return "students at hackathon, laptops and whiteboards, modern lab, collaborative energy"
    if any(w in lower for w in ["cultural", "fest", "dance", "music"]): return "college cultural fest, students performing on stage, colorful lights, enthusiastic crowd"
    return "engineering college students, campus celebration, professional photography, vibrant atmosphere"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/enhance-post", response_model=EnhancePostResponse)
async def enhance_post(body: EnhancePostRequest):
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="topic is required")

    system = (
        f"You are the official social media content writer for {COLLEGE_CONTEXT} "
        "You write polished, warm, and professional posts for the college community."
    )
    user = f"""Write a professional social media post based on this input:
"{body.topic.strip()}"

Requirements:
- Start with a strong attention-grabbing opening line
- Naturally mention Krishna Engineering College, Bhilai or KEC Bhilai (NOT Ghaziabad, NOT AKTU)
- Warm, celebratory, professional tone for faculty, students, parents, and alumni
- 150-200 words
- End with 4-6 hashtags: #KECBhilai #KrishnaEngineeringCollege #KECFamily #Bhilai #Chhattisgarh
- Max 2-3 emojis if they genuinely add value
- No asterisks or markdown formatting

Return ONLY the post text. No preamble, no labels, no quotes."""

    content = await call_groq(system, user, max_tokens=600, temperature=0.85)
    return EnhancePostResponse(content=content)


@router.post("/image-prompt", response_model=ImagePromptResponse)
async def get_image_prompt(body: ImagePromptRequest):
    text = body.post_content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="post_content is required")
    if not settings.groq_api_key:
        return ImagePromptResponse(image_prompt=_fallback_image_prompt(text))

    system = "You are an expert at writing short visual prompts for AI image generation models like FLUX and Stable Diffusion."
    user = f"""Convert this college social media post into a short image generation prompt:
\"\"\"{text[:600]}\"\"\"

Rules:
- Max 20 words
- Describe a real scene: people, setting, lighting, mood
- No text, logos, signs, or banners in the image
- Include one style note like "professional photography" or "cinematic lighting"
- If about freshers/welcome: show a vibrant welcome party scene
- If about farewell: show an emotional graduation/sendoff scene

Examples:
- "students throwing colorful holi powder, college campus courtyard, golden hour, vibrant celebration"
- "freshers welcome night, excited students, colorful stage decorations, auditorium, warm lighting"
- "farewell party, graduating students hugging, emotional smiles, decorated hall, soft bokeh"

Return ONLY the image prompt. No quotes, no explanation."""

    image_prompt = await call_groq(system, user, max_tokens=80, temperature=0.7)
    return ImagePromptResponse(image_prompt=image_prompt)


@router.post("/generate-image", response_model=GenerateImageResponse)
async def generate_image(body: GenerateImageRequest):
    """
    Generates an image via HuggingFace Inference API (FLUX.1-schnell).
    Free tier, no credit card needed.

    Setup:
      1. Sign up at huggingface.co (free)
      2. Go to Settings → Access Tokens → New token
         - Token type: Fine-grained
         - Permissions: check "Make calls to Inference Providers"
      3. Add to .env:  HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
    """
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    if not settings.hf_token:
        raise HTTPException(
            status_code=500,
            detail=(
                "HF_TOKEN not set. Get a free token at huggingface.co → Settings → Access Tokens. "
                "Add HF_TOKEN=hf_... to your .env file."
            ),
        )

    full_prompt = f"{prompt}, high quality, professional photography, detailed, 4k"
    print(f"[generate-image] HF FLUX.1-schnell — {full_prompt[:100]}…")

    # HF sometimes returns 503 on cold start — retry once after waiting
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)
            ) as client:
                res = await client.post(
                    HF_URL,
                    headers={
                        "Authorization": f"Bearer {settings.hf_token}",
                        "Content-Type": "application/json",
                    },
                    json={"inputs": full_prompt},
                )

            print(f"[generate-image] attempt={attempt+1} status={res.status_code} "
                  f"content-type={res.headers.get('content-type', '?')} bytes={len(res.content)}")

            # Model is loading (cold start) — wait and retry once
            if res.status_code == 503:
                if attempt == 0:
                    try:
                        estimated = res.json().get("estimated_time", 20)
                        wait = min(float(estimated), 30)
                    except Exception:
                        wait = 20
                    print(f"[generate-image] Model loading, waiting {wait}s before retry…")
                    await asyncio.sleep(wait)
                    continue
                raise HTTPException(
                    status_code=503,
                    detail="HuggingFace model is still loading. Please try again in 30 seconds.",
                )

            if res.status_code == 429:
                raise HTTPException(status_code=429, detail="HuggingFace rate limit hit. Wait a minute and try again.")

            if res.status_code == 402:
                raise HTTPException(
                    status_code=402,
                    detail="HuggingFace free credits exhausted. Your token's monthly free allowance is used up.",
                )

            if res.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="HuggingFace token is invalid. Check HF_TOKEN in your .env.",
                )

            if res.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"HuggingFace error {res.status_code}: {res.text[:300]}",
                )

            # Success — response is raw image bytes
            content_type = res.headers.get("content-type", "image/jpeg")
            if not content_type.startswith("image/"):
                raise HTTPException(
                    status_code=502,
                    detail=f"HuggingFace returned unexpected content ({content_type}): {res.text[:200]}",
                )

            b64 = base64.b64encode(res.content).decode("utf-8")
            print(f"[generate-image] SUCCESS — {len(b64)} chars base64")
            return GenerateImageResponse(image_base64=f"data:{content_type};base64,{b64}")

        except HTTPException:
            raise
        except httpx.ReadTimeout:
            raise HTTPException(
                status_code=504,
                detail="HuggingFace timed out after 120s. The model may be busy — try again.",
            )
        except httpx.ConnectError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach HuggingFace: {exc}")

    raise HTTPException(status_code=502, detail="Image generation failed after retries.")