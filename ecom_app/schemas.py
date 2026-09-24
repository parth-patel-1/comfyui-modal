"""Pydantic schemas for the e-commerce product-image generator.

These validate LLM JSON outputs at the graph boundaries; the LangGraph state
itself stores plain dicts (``.model_dump()``) so checkpointing stays simple.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ImageAnalysis(BaseModel):
    """Vision-LLM analysis of one uploaded raw product photo."""

    image_path: str = ""
    subject: str = ""
    category: str = ""
    visible_details: list[str] = Field(default_factory=list)
    photo_angle: str = ""
    photo_quality: str = ""
    defects: list[str] = Field(default_factory=list)
    needs_human_model: bool = False
    model_reason: str = ""


class ProductProfile(BaseModel):
    """Canonical merged profile: seller info + image analyses + clarifications."""

    name: str
    category: str = ""
    description: str = ""
    dimensions: str = ""
    features: list[str] = Field(default_factory=list)
    materials: str = ""
    colors: list[str] = Field(default_factory=list)
    brand_tone: str = "premium"
    target_platform: str = "amazon/flipkart"
    needs_human_model: bool = False
    model_notes: str = ""


class PersonaSpec(BaseModel):
    """LLM design for one consistent AI model avatar (frozen identity card)."""

    description: str
    prompt: str
    negative_prompt: str = (
        "cartoon, anime, illustration, deformed, extra fingers, extra limbs, "
        "watermark, text, logo, blurry"
    )
    width: int = 832
    height: int = 1216


class ShotSpec(BaseModel):
    """One planned image. ``reference_images`` and ``seed`` are filled by code,
    ``uses_product_ref``/``uses_persona`` are decided by the LLM."""

    id: int = 0
    title: str
    purpose: str = ""
    prompt: str
    negative_prompt: str = "blurry, low quality, watermark, text, deformed"
    workflow: Literal["edit", "t2i"] = "edit"
    uses_product_ref: bool = True
    uses_persona: bool = False
    reference_images: list[str] = Field(default_factory=list)
    seed: int = 0


class ShotPlan(BaseModel):
    shots: list[ShotSpec]
    notes: str = ""


class ReviewResult(BaseModel):
    """Vision-LLM verdict on one generated image vs its brief."""

    passed: bool
    notes: str = ""
    revised_prompt: str = ""
