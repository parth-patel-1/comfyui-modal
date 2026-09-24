"""Deterministic LLM stand-in for ``--mock-llm`` / ``--dry-run`` runs.

Same interface as ``llm.LLMClient.chat_json``; answers are canned per task so
the full LangGraph flow (including interrupts) can be exercised without an
API key. Nodes always pass a JSON string as ``user`` — the mock parses it and
echoes relevant fields back.
"""

from __future__ import annotations

import json
from pathlib import Path

_PHOTOREAL = (
    ", photorealistic, professional product photography, sharp focus, "
    "high resolution, no text, no watermark"
)


class MockLLM:
    def __init__(self):
        self.calls: list[str] = []

    def chat_json(self, *, task: str, system: str, user: str, images: list | None = None) -> dict:
        self.calls.append(task)
        try:
            payload = json.loads(user)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        handler = getattr(self, f"_{task}", None)
        if handler is None:
            raise ValueError(f"MockLLM has no canned answer for task '{task}'")
        return handler(payload)

    # ------------------------------------------------------------------
    def _analyze(self, p: dict) -> dict:
        name = p.get("product_name_hint") or "product"
        img = Path(p.get("image_file", "photo.jpg")).name
        return {
            "subject": f"{name} (seen in {img})",
            "category": p.get("category_hint") or "apparel/saree",
            "visible_details": ["rich woven pattern", "metallic zari border", "deep red base color"],
            "photo_angle": "front",
            "photo_quality": "decent focus, uneven indoor lighting, cluttered home background",
            "defects": ["cluttered background", "uneven lighting", "mild wrinkles"],
            "needs_human_model": True,
            "model_reason": "sarees are worn; the drape and fall are best shown on a person",
        }

    def _profile(self, p: dict) -> dict:
        info = p.get("user_provided_product_info") or {}
        defaults = p.get("defaults") or {}
        return {
            "name": info.get("name", "Banarasi silk saree"),
            "category": info.get("category", "apparel/saree"),
            "description": (
                "A handwoven Banarasi silk saree with intricate gold zari work and a "
                "rich drape, ideal for weddings and festive occasions."
            ),
            "dimensions": info.get("dimensions", ""),
            "features": info.get("features", ["pure silk", "gold zari border", "handwoven"]),
            "materials": info.get("materials", "silk, metallic zari thread"),
            "colors": ["deep red", "gold"],
            "brand_tone": "festive-premium",
            "target_platform": defaults.get("target_platform", "amazon/flipkart"),
            "needs_human_model": True,
            "model_notes": "Indian woman, elegant, wedding-ready styling",
        }

    def _clarify(self, p: dict) -> dict:
        return {"questions": []}

    def _persona(self, p: dict) -> dict:
        desc = (
            "Indian woman in her late twenties, warm medium skin tone, oval face with "
            "soft features, dark brown eyes, long black hair in a low bun, gentle "
            "confident smile, slim average-height build."
        )
        return {
            "description": desc,
            "prompt": (
                f"Photorealistic full-body studio portrait of {desc} Wearing a plain "
                "fitted ivory blouse, standing in a relaxed 3/4 pose facing the camera, "
                "seamless light grey studio background, soft even lighting, professional "
                "fashion photography, sharp focus, high resolution, no text, no watermark"
            ),
            "negative_prompt": (
                "cartoon, anime, illustration, deformed, extra fingers, extra limbs, "
                "watermark, text, logo, blurry"
            ),
            "width": 832,
            "height": 1216,
        }

    def _plan(self, p: dict) -> dict:
        n = int(p.get("num_images") or 4)
        persona = p.get("persona_description") or "the same woman"
        base = [
            ("hero-packshot", "hero", True, False,
             "Place the product from <image1> on a seamless ivory studio background, keep the product exactly the same, neatly arranged, centered, fills 80% of the frame, soft diffused studio lighting, subtle natural shadow"),
            ("drape-angle", "angle", True, False,
             "Re-present the product from <image1> at a three-quarter angle with elegant folds, keep colors and pattern identical, light grey seamless backdrop, soft studio lighting"),
            ("zari-closeup", "detail", True, False,
             "Extreme close-up of the border and weave texture of the product from <image1>, keep pattern and colors exactly the same, macro photography, crisp detail"),
            ("on-model", "lifestyle", True, True,
             f"Dress the woman from <image2> ({persona}) in the saree from <image1>, traditional drape, festive wedding setting with warm bokeh lights, keep her face, hair and body exactly the same, elegant standing pose"),
            ("side-pose", "angle", True, True,
             f"The same woman from <image2> ({persona}) wearing the saree from <image1>, side profile showing the pallu fall, same festive background, keep her appearance exactly the same"),
            ("flat-lay", "lifestyle", True, False,
             "Elegant flat-lay of the product from <image1> on raw silk fabric with jasmine flowers and gold bangles as subtle props, top-down view, soft window light, keep the product unchanged"),
        ]
        shots = []
        for i in range(n):
            title, purpose, uses_ref, uses_persona, prompt = base[i % len(base)]
            shots.append({
                "title": title,
                "purpose": purpose,
                "prompt": prompt + _PHOTOREAL,
                "negative_prompt": "blurry, low quality, watermark, text, deformed, extra fingers, cartoon",
                "workflow": "edit",
                "uses_product_ref": uses_ref,
                "uses_persona": uses_persona,
            })
        return {"shots": shots, "notes": f"mock plan with {n} shots"}

    def _review(self, p: dict) -> dict:
        return {"passed": True, "notes": "mock review: ok", "revised_prompt": ""}
