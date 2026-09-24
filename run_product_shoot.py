#!/usr/bin/env python
"""CLI driver for the LangGraph e-commerce product-image generator.

Real run (needs an OpenAI-compatible LLM endpoint):
  set ECOM_LLM_BASE_URL=https://your-llm-endpoint/v1
  set ECOM_LLM_API_KEY=sk-...
  python run_product_shoot.py --images raw1.jpg raw2.jpg --name "Banarasi silk saree" ^
      --category "apparel/saree" --dimensions "6.3 m x 1.15 m" ^
      --features "pure silk" "gold zari border" --num-images 4

Zero-cost dry run (mock LLM, no GPU, writes placeholder PNGs):
  python run_product_shoot.py --images raw1.jpg --name "Test saree" --dry-run --auto-approve
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from pathlib import Path

from langgraph.types import Command

from ecom_app.comfyui import ComfyUIClient
from ecom_app.graph import build_graph
from ecom_app.llm import LLMClient
from ecom_app.mock_llm import MockLLM

DEFAULT_COMFYUI_URL = "https://patelparth268268--comfyui.modal.run"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate premium e-commerce product images (LangGraph + LLM + ComfyUI)."
    )
    p.add_argument("--images", nargs="+", required=True, help="raw product photo(s), 1-3")
    p.add_argument("--name", required=True, help="product name")
    p.add_argument("--category", default="", help="product category")
    p.add_argument("--dimensions", default="", help="product dimensions")
    p.add_argument("--features", nargs="*", default=[], help="key product features")
    p.add_argument("--materials", default="", help="materials")
    p.add_argument("--num-images", type=int, default=None,
                   help="how many images to generate (default: 4; the LLM plans the shots)")
    p.add_argument("--style", default="premium studio + lifestyle mix")
    p.add_argument("--platform", default="amazon/flipkart")
    p.add_argument("--model-photo", default=None, help="path to your own model photo (optional)")
    p.add_argument("--model-policy", choices=["auto", "ask"], default="auto",
                   help="'ask' pauses to let you upload a model photo when one is needed")
    p.add_argument("--auto-approve", action="store_true",
                   help="skip persona/plan approval questions (hands-off mode)")
    p.add_argument("--base-url", default=os.environ.get("ECOM_LLM_BASE_URL", ""),
                   help="OpenAI-compatible LLM base URL (or ECOM_LLM_BASE_URL)")
    p.add_argument("--api-key", default=os.environ.get("ECOM_LLM_API_KEY", ""),
                   help="LLM API key (or ECOM_LLM_API_KEY)")
    p.add_argument("--text-model", default=os.environ.get("ECOM_TEXT_MODEL", "gpt-4o"))
    p.add_argument("--vision-model", default=os.environ.get("ECOM_VISION_MODEL", ""),
                   help="defaults to --text-model")
    p.add_argument("--comfyui-url", default=os.environ.get("COMFYUI_URL", DEFAULT_COMFYUI_URL))
    p.add_argument("--output-dir", default="output/ecom")
    p.add_argument("--mock-llm", action="store_true",
                   help="use the built-in mock LLM (no API key; ComfyUI still runs)")
    p.add_argument("--dry-run", action="store_true",
                   help="mock LLM + no ComfyUI calls; writes placeholder PNGs")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def build_llm(args):
    if args.mock_llm or args.dry_run:
        return MockLLM()
    if not args.base_url or not args.api_key:
        sys.exit(
            "error: provide --base-url/--api-key (or set ECOM_LLM_BASE_URL / "
            "ECOM_LLM_API_KEY), or use --mock-llm / --dry-run"
        )
    return LLMClient(
        base_url=args.base_url,
        api_key=args.api_key,
        text_model=args.text_model,
        vision_model=args.vision_model or None,
    )


def render_interrupt(value):
    """Print an interrupt payload and collect the seller's answer."""
    itype = value.get("type", "question") if isinstance(value, dict) else "question"
    print("\n" + "=" * 72)
    if itype == "clarify":
        print(value.get("question", "Questions:"))
        answers = []
        for i, q in enumerate(value.get("questions", []), 1):
            answers.append(input(f"  Q{i}. {q}\n  > ").strip())
        print("=" * 72)
        return answers
    if itype == "plan_approval":
        print(value.get("question", ""))
        for s in value.get("shots", []):
            print(f"\n  [{s['id']}] {s['title']}\n      {s['prompt'][:280]}...")
        print("=" * 72)
        return input("  > ").strip()
    print(value.get("question", str(value)) if isinstance(value, dict) else str(value))
    print("=" * 72)
    return input("  > ").strip()


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    llm = build_llm(args)
    comfy = ComfyUIClient(args.comfyui_url)
    graph = build_graph(llm, comfy)

    state = {
        "image_paths": [str(Path(p).resolve()) for p in args.images],
        "product_info": {
            "name": args.name,
            "category": args.category,
            "dimensions": args.dimensions,
            "features": args.features,
            "materials": args.materials,
        },
        "num_images": args.num_images,
        "style": args.style,
        "target_platform": args.platform,
        "model_policy": args.model_policy,
        "user_model_photo": args.model_photo,
        "auto_approve": bool(args.auto_approve),
        "dry_run": bool(args.dry_run),
        "comfyui_url": args.comfyui_url,
        "output_dir": args.output_dir,
    }
    config = {"configurable": {"thread_id": f"ecom-{uuid.uuid4().hex[:8]}"}}
    mode = "DRY RUN" if args.dry_run else ("mock LLM" if args.mock_llm else "live")
    print(f"Running product shoot for '{args.name}' ({mode}) ...")

    result = graph.invoke(state, config)
    while "__interrupt__" in result:
        intr = result["__interrupt__"][0]
        answer = render_interrupt(intr.value)
        result = graph.invoke(Command(resume=answer), config)

    print("\n" + "=" * 72)
    if not result.get("plan_approved", True) and not result.get("results"):
        print("Cancelled before generation. No images produced.")
        return 1
    results = result.get("results", [])
    print(f"DONE - {len(results)} image(s):")
    for r in results:
        print(f"  shot {r['shot_id']}: {r['local_path']}")
    print(f"manifest: {result.get('manifest_path')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
