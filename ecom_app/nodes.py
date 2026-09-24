"""LangGraph node functions for the e-commerce photoshoot flow.

``make_nodes(llm, comfy)`` closes over the LLM and ComfyUI clients and returns
the node callables wired into the graph. Human-in-the-loop questions use
``interrupt()``; the driver (CLI today, web UI later) resumes with the answer.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from langgraph.types import interrupt

from . import prompts
from .schemas import ImageAnalysis, PersonaSpec, ProductProfile, ReviewResult, ShotPlan
from .workflow_factory import (
    EDIT_SAVE_NODE,
    T2I_SAVE_NODE,
    build_edit_workflow,
    build_t2i_workflow,
)

logger = logging.getLogger("ecom_app.nodes")

# 1x1 transparent PNG, used for --dry-run placeholder images.
_PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea72d99650000000049454e44ae426082"
)


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _slug(text: str | None) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "product").lower()).strip("-")
    return s or "product"


def _write_placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PLACEHOLDER_PNG)


def make_nodes(llm, comfy):
    """Builds the node callables, closing over the LLM and ComfyUI clients."""

    # ---- 0. LLM-parse the seller's free-text description -----------------
    def parse_description(state: dict) -> dict:
        info = state.get("product_info") or {}
        desc = (state.get("description") or "").strip()
        if info.get("name") or not desc:
            return {"product_info": info}  # programmatic callers may pass product_info directly
        data = llm.chat_json(
            task="parse",
            system=prompts.PARSE_DESCRIPTION_SYSTEM,
            user=json.dumps({"description": desc}),
        )
        info = {
            "name": (data.get("name") or "").strip() or "Product",
            "category": (data.get("category") or "").strip() or "general",
            "dimensions": (data.get("dimensions") or "").strip(),
            "features": [str(f).strip() for f in (data.get("features") or []) if str(f).strip()],
            "materials": (data.get("materials") or "").strip(),
            "needs_human_model": bool(data.get("needs_human_model")),
        }
        _log(f"description parsed: {info['name']} | {info['category']} | "
             f"{len(info['features'])} feature(s) | needs model: {info['needs_human_model']}")
        return {"product_info": info}

    # ---- 1. validate inputs, prepare output dir -------------------------
    def load_inputs(state: dict) -> dict:
        paths = [Path(p) for p in state["image_paths"]]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise ValueError(f"image file(s) not found: {missing}")
        slug = _slug((state.get("product_info") or {}).get("name"))
        out_dir = Path(state["output_dir"]) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        _log(f"inputs ok: {len(paths)} image(s); output -> {out_dir}")
        return {"output_dir": str(out_dir), "slug": slug}

    # ---- 2. vision-LLM analysis of every uploaded photo -----------------
    def analyze_images(state: dict) -> dict:
        info = state.get("product_info") or {}
        analyses = []
        for p in state["image_paths"]:
            _log(f"analyzing {Path(p).name} ...")
            data = llm.chat_json(
                task="analyze",
                system=prompts.ANALYZE_IMAGE_SYSTEM,
                user=json.dumps({
                    "product_name_hint": info.get("name", ""),
                    "category_hint": info.get("category", ""),
                    "image_file": Path(p).name,
                }),
                images=[p],
            )
            data["image_path"] = str(p)
            analyses.append(ImageAnalysis(**data).model_dump())
            _log(f"  -> {data.get('subject', '?')} | angle={data.get('photo_angle', '?')} "
                 f"| needs model: {data.get('needs_human_model')}")
        return {"image_analyses": analyses}

    # ---- 3. merge analyses + seller info into the canonical profile -----
    def build_profile(state: dict) -> dict:
        payload = {
            "user_provided_product_info": state.get("product_info") or {},
            "image_analyses": state.get("image_analyses", []),
            "defaults": {
                "style": state.get("style"),
                "target_platform": state.get("target_platform"),
            },
            "clarifications": state.get("clarification_qa", []),
        }
        data = llm.chat_json(task="profile", system=prompts.PROFILE_SYSTEM, user=json.dumps(payload))
        data.setdefault("name", state.get("product_info", {}).get("name", "product"))
        profile = ProductProfile(**data).model_dump()
        _log(f"profile: {profile['name']} | {profile['category']} | needs model: {profile['needs_human_model']}")
        return {"product_profile": profile, "needs_model": bool(profile.get("needs_human_model"))}

    # ---- 4. LLM asks whatever is still missing (one batched interrupt) --
    def clarify_loop(state: dict) -> dict:
        data = llm.chat_json(
            task="clarify",
            system=prompts.CLARIFY_SYSTEM,
            user=json.dumps({
                "profile": state["product_profile"],
                "seller_provided": state.get("product_info", {}),
                "defaults": {
                    "num_images": state.get("num_images") or 4,
                    "style": state.get("style"),
                    "target_platform": state.get("target_platform"),
                },
            }),
        )
        questions = [q for q in (data.get("questions") or []) if str(q).strip()][:3]
        if not questions:
            _log("clarify: LLM has no further questions")
            return {"clarification_qa": []}
        if state.get("auto_approve"):
            # hands-off mode: never block on input; tell the LLM to use its judgment
            qa = [{"question": q, "answer": "not specified by the seller; use your best judgment"}
                  for q in questions]
            _log(f"clarify: {len(questions)} question(s) auto-answered (--auto-approve)")
        else:
            answers = interrupt({
                "type": "clarify",
                "question": "A few quick questions before planning the shoot:",
                "questions": questions,
            })
            if isinstance(answers, str):
                answers = [answers]
            qa = [{"question": q, "answer": str(a)} for q, a in zip(questions, list(answers))]
            for item in qa:
                _log(f"clarify: {item['question']} -> {item['answer']}")
        # merge the new answers back into the profile
        merged = llm.chat_json(
            task="profile",
            system=prompts.PROFILE_SYSTEM,
            user=json.dumps({
                "user_provided_product_info": state.get("product_info") or {},
                "image_analyses": state.get("image_analyses", []),
                "defaults": {"style": state.get("style"), "target_platform": state.get("target_platform")},
                "clarifications": qa,
            }),
        )
        merged.setdefault("name", state["product_profile"]["name"])
        profile = ProductProfile(**merged).model_dump()
        return {
            "clarification_qa": qa,
            "product_profile": profile,
            "needs_model": bool(profile.get("needs_human_model")),
        }

    # ---- 5. model needed? user photo, or generate one -------------------
    def decide_model(state: dict) -> dict:
        if not state.get("needs_model"):
            _log("no human model needed for this product")
            return {"model_source": "none", "persona": None}
        user_photo = state.get("user_model_photo")
        if user_photo:
            if not Path(user_photo).is_file():
                raise ValueError(f"--model-photo not found: {user_photo}")
            _log("using seller-provided model photo")
            return {
                "model_source": "user",
                "persona": {
                    "description": "the exact same model shown in the uploaded reference photo <image2>",
                    "local_path": str(user_photo),
                    "source": "user",
                    "seed": None,
                },
            }
        if state.get("model_policy", "auto") == "ask":
            answer = interrupt({
                "type": "model_gate",
                "question": (
                    "This product needs a human model for the shoot. Reply with a file "
                    "path to your own model photo, or 'generate' to create a consistent "
                    "AI model:"
                ),
            })
            ans = str(answer).strip()
            if ans and ans.lower() not in ("generate", "g", "no") and Path(ans).is_file():
                _log(f"using seller-provided model photo: {ans}")
                return {
                    "model_source": "user",
                    "persona": {
                        "description": "the exact same model shown in the uploaded reference photo <image2>",
                        "local_path": ans,
                        "source": "user",
                        "seed": None,
                    },
                }
        _log("model source: generate an AI persona")
        return {"model_source": "generate"}

    # ---- 6. generate the persona reference image (t2i) ------------------
    def generate_persona(state: dict) -> dict:
        attempts = int(state.get("persona_attempts", 0)) + 1
        spec = PersonaSpec(**llm.chat_json(
            task="persona",
            system=prompts.PERSONA_SYSTEM,
            user=json.dumps({
                "product_profile": state["product_profile"],
                "seller_feedback_on_previous_attempt": state.get("persona_feedback") or "",
            }),
        ))
        seed = random.randint(1, 2**31 - 1)
        dest = Path(state["output_dir"]) / "persona.png"
        if state.get("dry_run"):
            _log(f"[dry-run] would generate persona (attempt {attempts}, seed {seed})")
            _write_placeholder(dest)
        else:
            wf = build_t2i_workflow(
                prompt=spec.prompt,
                negative_prompt=spec.negative_prompt,
                width=spec.width,
                height=spec.height,
                seed=seed,
                filename_prefix=f"ecom/{state['slug']}/persona",
            )
            _log(f"generating persona (attempt {attempts}, seed {seed}) ...")
            _, files = comfy.generate(wf, T2I_SAVE_NODE, state["output_dir"])
            files[0].replace(dest)
        persona = {
            "description": spec.description,
            "prompt": spec.prompt,
            "local_path": str(dest),
            "seed": seed,
            "source": "generated",
        }
        return {"persona": persona, "persona_attempts": attempts}

    # ---- 7. seller approves / asks to regenerate the persona ------------
    def persona_review(state: dict) -> dict:
        if state.get("auto_approve") or state.get("dry_run"):
            _log("persona auto-approved")
            return {"persona_approved": True}
        persona = state["persona"]
        answer = interrupt({
            "type": "persona_review",
            "question": (
                "Here is the model persona that will appear in ALL model shots.\n"
                f"Description: {persona['description']}\n"
                f"Image: {persona['local_path']}\n"
                "Reply 'yes' to approve, or describe what to change to regenerate."
            ),
            "image_path": persona["local_path"],
        })
        ans = str(answer).strip().lower()
        if ans in ("yes", "y", "ok", "approve", "approved", ""):
            return {"persona_approved": True}
        return {"persona_approved": False, "persona_feedback": str(answer)}

    # ---- 8. LLM plans the full shot list --------------------------------
    def plan_shots(state: dict) -> dict:
        num = int(state.get("num_images") or 4)
        persona = state.get("persona") or {}
        data = llm.chat_json(
            task="plan",
            system=prompts.PLAN_SYSTEM,
            user=json.dumps({
                "product_profile": state["product_profile"],
                "clarifications": state.get("clarification_qa", []),
                "num_images": num,
                "style": state.get("style"),
                "target_platform": state.get("target_platform"),
                "persona_description": persona.get("description", ""),
                "num_product_photos": len(state["image_paths"]),
            }),
        )
        plan = ShotPlan(**data)
        base_seed = random.randint(1, 2**31 - 1)
        shots = []
        for i, shot in enumerate(plan.shots[:num]):
            shot.id = i + 1
            shot.seed = base_seed + i
            persona_path = persona.get("local_path") if shot.uses_persona else None
            max_product = 2 if persona_path else 3  # the edit workflow has 3 ref slots total
            refs = list(state["image_paths"])[:max_product] if shot.uses_product_ref else []
            if persona_path:
                refs = refs + [persona_path]
            shot.reference_images = refs
            shot.workflow = "edit" if refs else "t2i"
            shots.append(shot.model_dump())
        _log(f"shot plan: {len(shots)} shots (base seed {base_seed})")
        return {"shot_plan": shots}

    # ---- 9. seller approves the plan before any GPU spend ---------------
    def present_plan(state: dict) -> dict:
        lines = []
        for s in state["shot_plan"]:
            kind = "img2img" if s["workflow"] == "edit" else "t2i"
            lines.append(f"  {s['id']}. [{kind}] {s['title']} ({s['purpose']})")
        summary = "Planned shots:\n" + "\n".join(lines)
        if state.get("auto_approve"):
            _log(summary + "\nplan auto-approved")
            return {"plan_approved": True}
        answer = interrupt({
            "type": "plan_approval",
            "question": summary + "\nApprove this plan? Reply 'yes' to generate, anything else to cancel.",
            "shots": [
                {"id": s["id"], "title": s["title"], "prompt": s["prompt"]}
                for s in state["shot_plan"]
            ],
        })
        approved = str(answer).strip().lower() in ("yes", "y", "ok", "approve", "go")
        _log(f"plan {'approved' if approved else 'cancelled'} by user")
        return {"plan_approved": approved}

    # ---- 10. upload refs once, build one ComfyUI workflow per shot ------
    def prepare_payloads(state: dict) -> dict:
        upload_map = dict(state.get("upload_map") or {})
        if state.get("dry_run"):
            # no uploads; map refs to their basenames so workflow building works
            for s in state["shot_plan"]:
                for r in s["reference_images"]:
                    upload_map.setdefault(r, Path(r).name)
        else:
            all_refs = sorted({r for s in state["shot_plan"] for r in s["reference_images"]})
            for local in all_refs:
                if local not in upload_map:
                    upload_map[local] = comfy.upload_image(local)
        jobs = []
        for s in state["shot_plan"]:
            prefix = f"ecom/{state['slug']}/shot_{s['id']:02d}_{_slug(s['title'])}"
            if s["workflow"] == "edit":
                server_refs = [upload_map[r] for r in s["reference_images"]]
                wf = build_edit_workflow(
                    prompt=s["prompt"],
                    negative_prompt=s["negative_prompt"],
                    reference_images=server_refs,
                    seed=s["seed"],
                    filename_prefix=prefix,
                )
                save_node = EDIT_SAVE_NODE
            else:
                wf = build_t2i_workflow(
                    prompt=s["prompt"],
                    negative_prompt=s["negative_prompt"],
                    width=1024,
                    height=1024,
                    seed=s["seed"],
                    filename_prefix=prefix,
                )
                save_node = T2I_SAVE_NODE
            jobs.append({"shot": s, "workflow": wf, "save_node": save_node})
        _log(f"prepared {len(jobs)} ComfyUI job(s)")
        return {"jobs": jobs, "upload_map": upload_map}

    # ---- 11. render every shot ------------------------------------------
    def generate_images(state: dict) -> dict:
        out_dir = Path(state["output_dir"])
        results = []
        for job in state["jobs"]:
            s = job["shot"]
            dest = out_dir / f"{s['id']:02d}_{_slug(s['title'])}.png"
            if state.get("dry_run"):
                _log(f"[dry-run] would generate shot {s['id']} '{s['title']}'")
                _write_placeholder(dest)
                prompt_id = "dry-run"
            else:
                _log(f"generating shot {s['id']}/{len(state['jobs'])} '{s['title']}' (seed {s['seed']}) ...")
                prompt_id, files = comfy.generate(job["workflow"], job["save_node"], out_dir)
                files[0].replace(dest)
            results.append({
                "shot_id": s["id"],
                "title": s["title"],
                "local_path": str(dest),
                "prompt_id": prompt_id,
                "workflow": s["workflow"],
                "seed": s["seed"],
            })
            _log(f"  -> {dest.name}")
        return {"results": results}

    # ---- 12. vision-QA every image; regenerate failures once ------------
    def review_results(state: dict) -> dict:
        notes = []
        attempts = int(state.get("regen_attempts", 0))
        results = list(state["results"])
        shots_by_id = {s["id"]: s for s in state["shot_plan"]}
        upload_map = state.get("upload_map") or {}
        for idx, res in enumerate(results):
            shot = shots_by_id[res["shot_id"]]
            brief = {"title": shot["title"], "purpose": shot["purpose"], "prompt": shot["prompt"]}
            data = llm.chat_json(
                task="review",
                system=prompts.REVIEW_SYSTEM,
                user=json.dumps({
                    "shot_brief": brief,
                    "product": state["product_profile"].get("name"),
                }),
                images=[res["local_path"]],
            )
            review = ReviewResult(**data)
            _log(f"review shot {res['shot_id']}: {'PASS' if review.passed else 'FAIL'} ({review.notes})")
            if not review.passed and not state.get("dry_run") and attempts < 2:
                attempts += 1
                new_seed = random.randint(1, 2**31 - 1)
                new_prompt = review.revised_prompt or shot["prompt"]
                _log(f"  regenerating shot {res['shot_id']} (attempt {attempts}, seed {new_seed})")
                prefix = f"ecom/{state['slug']}/shot_{shot['id']:02d}_{_slug(shot['title'])}_v{attempts}"
                if shot["workflow"] == "edit":
                    wf = build_edit_workflow(
                        prompt=new_prompt,
                        negative_prompt=shot["negative_prompt"],
                        reference_images=[upload_map[r] for r in shot["reference_images"]],
                        seed=new_seed,
                        filename_prefix=prefix,
                    )
                    save_node = EDIT_SAVE_NODE
                else:
                    wf = build_t2i_workflow(
                        prompt=new_prompt,
                        negative_prompt=shot["negative_prompt"],
                        width=1024, height=1024,
                        seed=new_seed,
                        filename_prefix=prefix,
                    )
                    save_node = T2I_SAVE_NODE
                prompt_id, files = comfy.generate(wf, save_node, state["output_dir"])
                files[0].replace(Path(res["local_path"]))
                res.update({"prompt_id": prompt_id, "seed": new_seed})
                shot["prompt"] = new_prompt
                results[idx] = res
                data2 = llm.chat_json(
                    task="review",
                    system=prompts.REVIEW_SYSTEM,
                    user=json.dumps({
                        "shot_brief": {**brief, "prompt": new_prompt},
                        "product": state["product_profile"].get("name"),
                    }),
                    images=[res["local_path"]],
                )
                review = ReviewResult(**data2)
                _log(f"  re-review shot {res['shot_id']}: {'PASS' if review.passed else 'FAIL'} ({review.notes})")
            notes.append({"shot_id": res["shot_id"], "passed": review.passed, "notes": review.notes})
        return {"review_notes": notes, "results": results, "regen_attempts": attempts}

    # ---- 13. manifest ----------------------------------------------------
    def finalize(state: dict) -> dict:
        manifest = {
            "product_profile": state.get("product_profile"),
            "persona": state.get("persona"),
            "clarifications": state.get("clarification_qa", []),
            "plan_approved": state.get("plan_approved", False),
            "shots": state.get("shot_plan", []),
            "results": state.get("results", []),
            "review_notes": state.get("review_notes", []),
            "comfyui_url": state.get("comfyui_url"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        path = Path(state["output_dir"]) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _log(f"manifest -> {path}")
        return {"manifest_path": str(path)}

    return {
        "parse_description": parse_description,
        "load_inputs": load_inputs,
        "analyze_images": analyze_images,
        "build_profile": build_profile,
        "clarify_loop": clarify_loop,
        "decide_model": decide_model,
        "generate_persona": generate_persona,
        "persona_review": persona_review,
        "plan_shots": plan_shots,
        "present_plan": present_plan,
        "prepare_payloads": prepare_payloads,
        "generate_images": generate_images,
        "review_results": review_results,
        "finalize": finalize,
    }

