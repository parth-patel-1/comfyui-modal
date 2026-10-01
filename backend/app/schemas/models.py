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
