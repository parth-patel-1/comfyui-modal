"""OpenAI-compatible LLM client (vision + text) for the e-commerce app.

The seller supplies ``base_url`` + ``api_key`` (any OpenAI-compatible endpoint:
OpenAI, Azure, OpenRouter, vLLM...). Every call returns parsed JSON with one
automatic repair round when the model answers with malformed JSON.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path

logger = logging.getLogger("ecom_app.llm")

# Windows' mimetypes DB often lacks webp; make sure data-URIs get the right type.
mimetypes.add_type("image/webp", ".webp")


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        text_model: str = "gpt-4o",
        vision_model: str | None = None,
        timeout: float = 180.0,
        temperature: float = 0.3,
    ):
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.text_model = text_model
        self.vision_model = vision_model or text_model
        self.temperature = temperature

    @staticmethod
    def _image_part(path: str | Path) -> dict:
        p = Path(path)
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        b64 = base64.b64encode(p.read_bytes()).decode()
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

    def chat_json(self, *, task: str, system: str, user: str, images: list | None = None) -> dict:
        """Call the LLM and return the parsed JSON object.

        ``task`` is a label used for logging (and by MockLLM to pick canned
        answers). ``images`` switches to the vision model and attaches the
        files as base64 data-URIs.
        """
        messages = [{"role": "system", "content": system}]
        if images:
            content = [{"type": "text", "text": user}]
            content += [self._image_part(i) for i in images]
            messages.append({"role": "user", "content": content})
            model = self.vision_model
        else:
            messages.append({"role": "user", "content": user})
            model = self.text_model

        raw = self._complete(model, messages)
        try:
            return _parse_json(raw)
        except ValueError:
            logger.warning("[%s] malformed JSON from LLM; requesting a fix", task)
            messages += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "That was not valid JSON. Reply with ONLY the corrected "
                        "JSON object: no markdown fences, no commentary."
                    ),
                },
            ]
            return _parse_json(self._complete(model, messages))

    def _complete(self, model: str, messages: list) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
        except Exception:
            # some compatible endpoints reject response_format — retry without it
            resp = self._client.chat.completions.create(
                model=model, messages=messages, temperature=self.temperature
            )
        return resp.choices[0].message.content or ""


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data
