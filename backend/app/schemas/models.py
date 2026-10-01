"""Pydantic schemas for the GenStudio API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerationCreate(BaseModel):
    engine: str = Field(pattern="^(image|video)$")
    mode: str = Field(pattern="^(t2i|edit|t2v|i2v)$")
    prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str = ""
    params: dict[str, Any] = {}
    reference_paths: list[str] = []


class GenerationOut(BaseModel):
    id: str
    engine: str
    mode: str
    status: str
    progress: int
    prompt: str
    params: dict[str, Any]
    reference_paths: list[str]
    credits_charged: int
    error: str
    output_paths: list[str]
    created_at: str
    finished_at: str | None

    model_config = {"from_attributes": True}


class UploadTicket(BaseModel):
    """Tells the browser where/how to upload a reference image directly."""

    bucket: str
    path: str
    upload_url: str
    max_bytes: int


class WalletOut(BaseModel):
    balance: int


class StudioConfig(BaseModel):
    site_name: str
    maintenance_mode: bool
    engines: dict[str, Any]
    pricing: dict[str, Any]


# --------------------------------------------------------------------- admin

class AdminCreditsBody(BaseModel):
    delta: int = Field()  # signed; 0 is rejected by the RPC
    note: str = Field("", max_length=300)


class AdminStatusBody(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")


class AdminCreateUserBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field("", max_length=80)
    role: str = Field("user", pattern="^(user|admin)$")
    grant_credits: int = Field(0, ge=0, le=1_000_000)


class AppSettingsUpdate(BaseModel):
    site_name: str | None = Field(None, min_length=1, max_length=80)
    signup_grant_credits: int | None = Field(None, ge=0)
    maintenance_mode: bool | None = None
    max_concurrent_jobs_per_user: int | None = Field(None, ge=1)
    daily_job_cap: int | None = Field(None, ge=1)
    default_negative_prompt_image: str | None = None
    default_negative_prompt_video: str | None = None


class PricingUpdate(BaseModel):
    base_credits: int | None = Field(None, ge=0)
    credits_per_megapixel: float | None = Field(None, ge=0)
    credits_per_ref_image: int | None = Field(None, ge=0)
    credits_per_video_second: float | None = Field(None, ge=0)
    active: bool | None = None


class ModalSettingsUpdate(BaseModel):
    image_gpu: str | None = Field(None, max_length=40)
    video_gpu: str | None = Field(None, max_length=40)
    image_max_containers: int | None = Field(None, ge=1, le=20)
    video_max_containers: int | None = Field(None, ge=1, le=20)
    image_min_containers: int | None = Field(None, ge=0)
    video_min_containers: int | None = Field(None, ge=0)
    scaledown_window_s: int | None = Field(None, ge=10, le=7200)
    max_inputs: int | None = Field(None, ge=1, le=64)
    overhead_factor: float | None = Field(None, ge=1)
    comfyui_version: str | None = Field(None, max_length=40)
