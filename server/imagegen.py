"""Local image generation for the companion selfie feature.

Nora can text the user a photo of herself. The picture is produced on the
user's OWN machine by a local Stable Diffusion server (Automatic1111 by
default) — nothing about the persona leaves the box except the final image,
which is then delivered as an MMS / WhatsApp media attachment.

SAFE FOR WORK BY CONSTRUCTION
-----------------------------
The outfit, framing and content are fixed here in code. The only thing the
caller (the model) can vary is a benign `setting` string, e.g. "at the nurses'
station". The positive prompt forces full-length hospital scrubs, fully
covered, and a hard negative prompt blocks revealing / NSFW content and
anything age-ambiguous. This tool cannot be steered into suggestive imagery —
that is the entire point of routing selfies through it.

Backends
--------
Automatic1111's `/sdapi/v1/txt2img` is implemented (it's the common local
setup and needs no per-image workflow graph). If you run ComfyUI or something
else, say so and the client here can grow a second backend.
"""

import base64
import os

import httpx

# The persona's fixed physical description, so every selfie looks like the same
# person. Kept deliberately generic and adult; override in .env to taste.
_DEFAULT_APPEARANCE = (
    "a friendly adult woman in her late twenties, shoulder-length brown hair, "
    "light makeup, warm genuine smile"
)

# Everything that keeps the image work-appropriate. This is NOT caller-tunable.
_SFW_OUTFIT = (
    "wearing loose full-length hospital scrubs, long-sleeve scrub top and scrub "
    "trousers, fully clothed and modest, midriff and shoulders completely covered, "
    "hospital lanyard ID badge"
)
_SFW_SCENE = "modern hospital ward in the background, clean clinical lighting"

_NEGATIVE_PROMPT = (
    # keep it clothed / work-appropriate
    "nsfw, nude, nudity, topless, cleavage, exposed midriff, bare belly, bare "
    "shoulders, underwear, lingerie, bikini, swimsuit, revealing clothing, "
    "skin-tight clothing, short skirt, suggestive, sexual, provocative, "
    # hard age safety
    "child, kid, teen, teenager, underage, minor, school uniform, "
    # generic quality
    "extra fingers, deformed hands, deformed face, mutated, lowres, bad anatomy, "
    "watermark, signature, text"
)


def build_sfw_prompt(setting: str) -> tuple[str, str]:
    """Return (positive, negative) prompts for a locked safe-for-work selfie."""
    appearance = os.environ.get("COMPANION_APPEARANCE", _DEFAULT_APPEARANCE).strip()
    setting = (setting or "on a short break at work").strip()
    positive = (
        f"photorealistic candid smartphone selfie of {appearance}, {setting}, "
        f"{_SFW_OUTFIT}, {_SFW_SCENE}, natural pose, high detail, safe for work"
    )
    return positive, _NEGATIVE_PROMPT


async def generate_selfie_png(setting: str) -> bytes:
    """Generate one SFW selfie and return raw PNG bytes.

    Raises RuntimeError with a human-readable reason on any failure (server
    down, wrong backend, empty response) so the tool layer can report it.
    """
    backend = os.environ.get("IMAGEGEN_BACKEND", "a1111").strip().lower()
    if backend not in ("a1111", "automatic1111", "auto1111", "sdwebui"):
        raise RuntimeError(
            f"image backend '{backend}' isn't wired up yet — set IMAGEGEN_BACKEND=a1111 "
            "or ask to add your backend (e.g. ComfyUI)."
        )

    base_url = os.environ.get("IMAGEGEN_URL", "http://127.0.0.1:7860").rstrip("/")
    positive, negative = build_sfw_prompt(setting)

    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "steps": int(os.environ.get("IMAGEGEN_STEPS", "28")),
        "cfg_scale": float(os.environ.get("IMAGEGEN_CFG", "6.5")),
        "width": int(os.environ.get("IMAGEGEN_WIDTH", "512")),
        "height": int(os.environ.get("IMAGEGEN_HEIGHT", "768")),
        "sampler_name": os.environ.get("IMAGEGEN_SAMPLER", "DPM++ 2M Karras"),
        "n_iter": 1,
        "batch_size": 1,
        "send_images": True,
        "save_images": False,
    }
    # Optional explicit checkpoint override.
    model = os.environ.get("IMAGEGEN_MODEL")
    if model:
        payload["override_settings"] = {"sd_model_checkpoint": model}
        payload["override_settings_restore_afterwards"] = False

    timeout = float(os.environ.get("IMAGEGEN_TIMEOUT", "180"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"couldn't reach the image server at {base_url} — is Automatic1111 running "
            "with the API enabled (--api)?"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"image server returned {exc.response.status_code}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"image generation timed out after {timeout:.0f}s (GPU busy or step count too high?)"
        ) from exc

    images = data.get("images") or []
    if not images:
        raise RuntimeError("image server returned no image")

    # A1111 returns bare base64; some builds prefix a data: URI — handle both.
    b64 = images[0].split(",", 1)[-1]
    return base64.b64decode(b64)
