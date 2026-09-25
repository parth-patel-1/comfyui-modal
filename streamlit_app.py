"""Streamlit UI for the e-commerce product-shot generator (LangGraph + LLM + ComfyUI).

Run:
    streamlit run streamlit_app.py

Tabs:
    1. Product Shoot  - the full image pipeline (uploads -> analysis -> persona
                        -> plan -> generation -> vision QA -> manifest), with
                        every interrupt rendered as a real UI widget.
    2. Video Studio   - MiniMax H3 text-to-video / image-to-video clips.
    3. Results        - browse past runs from output/ecom/*/manifest.json.

Settings (sidebar) default from the environment / .env:
    ECOM_LLM_BASE_URL, ECOM_LLM_API_KEY, ECOM_TEXT_MODEL, ECOM_VISION_MODEL,
    COMFYUI_URL
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import streamlit as st

from ecom_app.comfyui import ComfyUIClient
from ecom_app.graph import build_graph
from ecom_app.llm import LLMClient
from ecom_app.mock_llm import MockLLM
from ecom_app.runner import PipelineRunner, VideoJob
from ecom_app.video import (
    FRAME_PRESETS,
    RESOLUTIONS,
    build_video_workflow,
    draft_video_prompt,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_COMFYUI_URL = "https://patelparth268268--comfyui.modal.run"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); never overrides real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        os.environ.setdefault(key, value)


load_dotenv()

st.set_page_config(
    page_title="E-commerce Product Studio",
    page_icon="\U0001f4f8",
    layout="wide",
)


# ---------------------------------------------------------------------------
# session state
# ---------------------------------------------------------------------------
def _init_session() -> None:
    ss = st.session_state
    ss.setdefault("runner", PipelineRunner())
    ss.setdefault("video_job", VideoJob())
    ss.setdefault("graph_key", None)
    ss.setdefault("graph", None)
    ss.setdefault("llm", None)
    ss.setdefault("comfy", None)
    ss.setdefault("last_result", None)
    ss.setdefault("video_prefill_profile", None)
    ss.setdefault("video_prefill_prompt", "")
    ss.setdefault("upload_dir", "")


_init_session()


# ---------------------------------------------------------------------------
# graph / client construction (rebuilt only when settings change)
# ---------------------------------------------------------------------------
def build_stack(mode: str, base_url: str, api_key: str, text_model: str,
                vision_model: str, comfy_url: str):
    key = (mode, base_url, api_key, text_model, vision_model, comfy_url)
    ss = st.session_state
    if ss.graph_key != key:
        if mode == "Dry run (no API, no GPU)":
            llm = MockLLM()
        elif mode == "Mock LLM (GPU, canned answers)":
            llm = MockLLM()
        else:
            llm = LLMClient(
                base_url=base_url,
                api_key=api_key,
                text_model=text_model,
                vision_model=vision_model or None,
            )
        comfy = ComfyUIClient(comfy_url)
        ss.graph = build_graph(llm, comfy)
        ss.llm = llm
        ss.comfy = comfy
        ss.graph_key = key
    return ss.graph, ss.llm, ss.comfy


def ping_comfy(url: str, timeout: int = 12) -> str:
    """Best-effort server check that never waits for a cold start."""
    import requests
    try:
        r = requests.get(f"{url.rstrip('/')}/api/object_info", timeout=timeout)
        return f"\u2705 server up (HTTP {r.status_code})"
    except requests.Timeout:
        return "\u23f3 no response quickly -- the container is probably cold-starting; try again in a few minutes"
    except requests.RequestException as e:
        return f"\u26a0\ufe0f unreachable right now ({type(e).__name__}) -- will retry automatically on first use"


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("\u2699\ufe0f Studio settings")
    mode = st.radio(
        "Mode",
        ["Live (LLM + GPU)", "Mock LLM (GPU, canned answers)", "Dry run (no API, no GPU)"],
        help="Live uses your OpenAI-compatible LLM endpoint and the Modal GPU. "
             "Mock LLM keeps the GPU but answers with canned LLM JSON. "
             "Dry run is fully offline (placeholder images).",
    )
    base_url = st.text_input("LLM base URL", os.environ.get("ECOM_LLM_BASE_URL", ""))
    api_key = st.text_input("LLM API key", os.environ.get("ECOM_LLM_API_KEY", ""), type="password")
    text_model = st.text_input("Text model", os.environ.get("ECOM_TEXT_MODEL", "gpt-4o"))
    vision_model = st.text_input("Vision model", os.environ.get("ECOM_VISION_MODEL", ""))
    comfy_url = st.text_input("ComfyUI server", os.environ.get("COMFYUI_URL", DEFAULT_COMFYUI_URL))
    if st.button("Ping ComfyUI server"):
        st.write(ping_comfy(comfy_url))
    st.caption(
        "The Modal container auto-scales to zero after ~5 min idle; the first "
        "request cold-starts it (a few minutes). Video cold-starts take longer "
        "(~42 GB of models)."
    )

live = mode.startswith("Live")
dry = mode.startswith("Dry")

# ---------------------------------------------------------------------------
# tabs
# ---------------------------------------------------------------------------
tab_shoot, tab_video, tab_results = st.tabs(["\U0001f4f8 Product shoot", "\U0001f3ac Video studio", "\U0001f4c2 Results"])
runner: PipelineRunner = st.session_state.runner
vjob: VideoJob = st.session_state.video_job


# ---------------------------------------------------------------------------
# tab 1: product shoot
# ---------------------------------------------------------------------------
def _show_log(logs: list) -> None:
    st.code("\n".join(logs[-40:]) or "(starting...)", language="console")


def _render_interrupt(runner: PipelineRunner) -> None:
    intr = runner.interrupt or {}
    itype = intr.get("type", "question")
    st.divider()

    if itype == "clarify":
        st.subheader("\U0001f9ea Quick questions before planning")
        st.caption("Answer to steer the shoot, or leave blank to let the LLM use its best judgment.")
        with st.form("clarify_form"):
            answers = []
            for i, q in enumerate(intr.get("questions", []), 1):
                a = st.text_input(f"Q{i}. {q}", key=f"clarify_{i}")
                answers.append(a)
            if st.form_submit_button("Submit answers", type="primary"):
                final = [a.strip() or "not specified by the seller; use your best judgment" for a in answers]
                runner.answer(final)
                st.rerun()

    elif itype == "model_gate":
        st.subheader("\U0001f9d1 This product needs a human model")
        choice = st.radio("Model source", ["Generate a consistent AI model", "I'll upload my own model photo"],
                          horizontal=True)
        up = None
        if choice.endswith("my own model photo"):
            up = st.file_uploader("Model photo", type=["png", "jpg", "jpeg", "webp"], key="gate_up")
        if st.button("Continue", type="primary"):
            if choice.endswith("my own model photo"):
                if up is None:
                    st.warning("upload a photo first")
                else:
                    dest = Path(st.session_state.upload_dir or "output/_ui_uploads") / ("gate_model_" + up.name.replace("/", "_"))
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(up.getvalue())
                    runner.answer(str(dest))
                    st.rerun()
            else:
                runner.answer("generate")
                st.rerun()

    elif itype == "persona_review":
        st.subheader("\U0001f469 Review the AI model persona")
        st.caption("This exact person will appear in every model shot.")
        img = intr.get("image_path")
        if img and Path(img).is_file():
            st.image(img, width=320, caption="persona")
        st.write(intr.get("question", ""))
        c1, c2 = st.columns(2)
        if c1.button("\u2705 Approve persona", type="primary", use_container_width=True):
            runner.answer("yes")
            st.rerun()
        feedback = c2.text_input("...or describe what to change and regenerate:",
                                 key="persona_feedback")
        if c2.button("\U0001f504 Regenerate", disabled=not feedback.strip(), use_container_width=True):
            runner.answer(feedback.strip())
            st.rerun()

    elif itype == "plan_approval":
        st.subheader("\U0001f5bc\ufe0f Approve the shot plan")
        st.caption("Nothing is generated until you approve.")
        for s in intr.get("shots", []):
            with st.expander(f"{s['id']}. {s['title']}"):
                st.write(s.get("prompt", ""))
        c1, c2 = st.columns(2)
        if c1.button("\u2705 Approve & generate", type="primary", use_container_width=True):
            runner.answer("yes")
            st.rerun()
        if c2.button("\u274c Cancel", use_container_width=True):
            runner.answer("cancel")
            st.rerun()

    else:
        st.subheader("\u2753 The pipeline has a question")
        st.write(intr.get("question", str(intr)))
        a = st.text_input("Your reply")
        if st.button("Send", type="primary", disabled=not a.strip()):
            runner.answer(a.strip())
            st.rerun()


def _show_result(result: dict) -> None:
    ok_i, bad_i = "✅", "❌"
    results = result.get("results", [])
    if not results:
        st.warning("Cancelled before generation - no images produced.")
        _show_log(runner.logs)
        return
    profile = result.get("product_profile") or {}
    st.success(
        f"Done - {len(results)} image(s) for '{profile.get('name', 'product')}' "
        f"| vision QA: "
        + ", ".join(f"shot {n['shot_id']} {ok_i if n['passed'] else bad_i}" for n in result.get("review_notes", []))
    )
    cols = st.columns(min(4, max(1, len(results))))
    for i, r in enumerate(results):
        with cols[i % len(cols)]:
            p = r.get("local_path", "")
            if p and Path(p).is_file():
                st.image(p, caption=f"shot {r['shot_id']}: {Path(p).name}", use_container_width=True)
    persona = result.get("persona") or {}
    if persona.get("local_path") and Path(persona["local_path"]).is_file():
        with st.expander("\U0001f469 AI model persona"):
            pc1, pc2 = st.columns([1, 2])
            pc1.image(persona["local_path"], width=280)
            pc2.write(persona.get("description", ""))
    with st.expander("\U0001f50d QA review notes"):
        for n in result.get("review_notes", []):
            st.write(f"shot {n['shot_id']}: {ok_i + ' PASS' if n['passed'] else bad_i + ' FAIL'} - {n['notes']}")
    mpath = result.get("manifest_path")
    if mpath and Path(mpath).is_file():
        st.download_button("\u2b07\ufe0f Download manifest.json", data=Path(mpath).read_text(encoding="utf-8"),
                           file_name="manifest.json", mime="application/json")
        st.caption(f"Images + manifest: `{Path(mpath).parent}`")


with tab_shoot:
    st.header("Generate premium product images")
    st.caption(
        "Upload raw seller photos + a description. The pipeline analyzes the "
        "photos, merges a product profile, (optionally) creates a consistent AI "
        "model, plans the shots, generates them on ComfyUI and vision-QA reviews "
        "each result."
    )

    left, right = st.columns([1.15, 1])
    with left:
        uploads = st.file_uploader(
            "Product photos",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            help="1-3 raw photos give the best results (front, back, detail).",
        )
        description = st.text_area(
            "Product description",
            height=110,
            placeholder="e.g. EcoBin medium dustbin garbage bags on a roll: black "
            "odourless plastic, 13 litre, 19x21 inch, 120 bags with detachable "
            "thread seal, leak-proof, for home and office bins",
            help="One free-text description mentioning everything you know "
                 "(name, category, size, features, materials). The LLM extracts "
                 "the structured profile from it.",
        )
    with right:
        num_images = st.slider("Number of images", 1, 8, 4)
        style = st.text_input("Style", "premium studio + lifestyle mix")
        platform = st.selectbox(
            "Target platform",
            ["amazon/flipkart", "amazon", "flipkart", "myntra", "shopify", "instagram"],
        )
        auto_approve = st.checkbox(
            "Auto-approve everything (hands-off)",
            value=False,
            help="No interruptions: clarify questions are auto-answered, the "
                 "persona and the shot plan are approved automatically.",
        )
        with st.expander("Advanced"):
            model_policy = st.radio("Human model policy", ["auto", "ask"], horizontal=True,
                                    help="'ask' pauses when a human model is needed so you can upload one.")
            model_photo = st.file_uploader("Your own model photo (optional)", type=["png", "jpg", "jpeg", "webp"])
            output_dir = st.text_input("Output folder", "output/ecom")

    col_start, col_reset, _ = st.columns([1, 1, 3])
    start_clicked = col_start.button(
        "\U0001f680 Start shoot", type="primary", disabled=runner.status in ("running", "waiting"),
        use_container_width=True,
    )
    reset_clicked = col_reset.button("Reset", disabled=runner.status in ("running", "waiting"))

    if reset_clicked:
        runner.reset()
        st.session_state.last_result = None
        st.rerun()

    if start_clicked:
        problems = []
        if not uploads:
            problems.append("upload at least one product photo")
        if not description.strip():
            problems.append("write a product description")
        if live and (not base_url or not api_key):
            problems.append("fill in the LLM base URL and API key in the sidebar (or switch to Mock/Dry mode)")
        if problems:
            st.error(" / ".join(problems))
        else:
            run_id = uuid.uuid4().hex[:8]
            up_dir = ROOT / "output" / "_ui_uploads" / run_id
            up_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for f in uploads:
                dest = up_dir / f.name.replace("/", "_")
                dest.write_bytes(f.getvalue())
                paths.append(str(dest))
            model_photo_path = ""
            if model_photo is not None:
                mp = up_dir / ("model_photo_" + model_photo.name.replace("/", "_"))
                mp.write_bytes(model_photo.getvalue())
                model_photo_path = str(mp)
            st.session_state.upload_dir = str(up_dir)
            state = {
                "image_paths": paths,
                "description": description.strip(),
                "num_images": int(num_images),
                "style": style,
                "target_platform": platform,
                "model_policy": model_policy,
                "user_model_photo": model_photo_path or None,
                "auto_approve": bool(auto_approve),
                "dry_run": bool(dry),
                "comfyui_url": comfy_url,
                "output_dir": output_dir,
            }
            graph, _llm, _comfy = build_stack(mode, base_url, api_key, text_model, vision_model, comfy_url)
            config = {"configurable": {"thread_id": f"ecom-ui-{run_id}"}}
            try:
                runner.start(graph, config, state)
                st.session_state.last_result = None
            except Exception as e:
                st.error(f"could not start: {e}")
            st.rerun()

    # ---- live status ------------------------------------------------------
    if runner.status == "running":
        with st.status("Pipeline running...", expanded=False):
            st.write("Follow the log below; new lines appear automatically.")
        _show_log(runner.logs)
    elif runner.status == "waiting":
        _render_interrupt(runner)
    elif runner.status == "error":
        st.error(f"Pipeline failed: {runner.error}")
        _show_log(runner.logs)
    elif runner.status == "done":
        result = runner.result or {}
        st.session_state.last_result = result
        _show_result(result)


# ---------------------------------------------------------------------------
# tab 2: video studio
# ---------------------------------------------------------------------------
with tab_video:
    st.header("Generate a product video (MiniMax H3)")
    if dry:
        st.info("Dry run mode uses placeholder images only - switch to Live or Mock LLM mode to render a real video.")
    else:
        st.caption(
            "Text-to-video, or animate a still (first frame). The Modal container "
            "cold-loads ~42 GB of video models on the first render - expect a few "
            "minutes of warm-up."
        )

        profile = st.session_state.video_prefill_profile or ((st.session_state.last_result or {}).get("product_profile") or {})
        if profile and not st.session_state.video_prefill_prompt:
            st.success(f"Product profile loaded: {profile.get('name', '')} - use the draft button below.")

        vp_left, vp_right = st.columns([1.3, 1])
        with vp_left:
            vprompt = st.text_area(
                "Video prompt",
                height=180,
                value=st.session_state.video_prefill_prompt,
                key="vprompt",
                help="Describe the look, the camera move and the timeline. Keep "
                     "the product faithful: exact colors/materials, no text overlays.",
            )
            draft_cols = st.columns(2)
            if draft_cols[0].button("\U0001f916 Draft prompt with LLM", disabled=not profile, use_container_width=True,
                                    help="Needs a product profile from a shoot (or the Results tab button)."):
                _graph, llm, _comfy = build_stack(mode, base_url, api_key, text_model, vision_model, comfy_url)
                with st.spinner("Drafting video prompt..."):
                    try:
                        drafted = draft_video_prompt(llm, profile)
                        st.session_state.video_prefill_prompt = drafted
                        st.rerun()
                    except Exception as e:
                        st.error(f"draft failed: {e}")
            if draft_cols[1].button("\U0001f5d1\ufe0f Clear prompt", use_container_width=True):
                st.session_state.video_prefill_prompt = ""
                st.rerun()

        with vp_right:
            res_label = st.radio("Resolution", list(RESOLUTIONS.keys()), horizontal=True)
            width, height = RESOLUTIONS[res_label]
            vsec = st.slider("Duration (seconds @ 24 fps)", 2, 5, 5)
            vsteps = st.slider("Steps", 8, 40, 20)
            vseed = st.number_input("Seed (-1 = random)", -1, 2**31 - 1, -1)

        vcol_start, vcol_stop, _ = st.columns([1, 1, 3])
        start_image = None
        with st.expander("\U0001f5bc\ufe0f Animate a still image (optional, image-to-video)"):
            src = st.radio("First frame source", ["None (pure text-to-video)", "Upload", "From last shoot"], horizontal=True)
            up_img = None
            last_paths = [r.get("local_path", "") for r in (st.session_state.last_result or {}).get("results", []) if r.get("local_path")]
            if src == "Upload":
                up_img = st.file_uploader("First-frame image", type=["png", "jpg", "jpeg", "webp"], key="v_up")
            elif src == "From last shoot":
                if last_paths:
                    pick = st.selectbox("Generated image", last_paths)
                    st.image(pick, width=200)
                    up_img = pick
                else:
                    st.caption("No shoot results in this session yet.")

        vstart = vcol_start.button(
            "\U0001f3ac Render video", type="primary",
            disabled=(vjob.status == "running" or dry or not vprompt.strip()),
            use_container_width=True,
        )
        if vjob.status == "running":
            vcol_stop.button("(job in progress)", disabled=True)

        if vstart:
            _graph, _llm, comfy = build_stack(mode, base_url, api_key, text_model, vision_model, comfy_url)
            server_ref = None
            if up_img is not None:
                if hasattr(up_img, "getvalue"):  # UploadedFile -> save to disk first
                    tmp = Path(st.session_state.upload_dir or "output/_ui_uploads") / (
                        "vframe_" + up_img.name.replace("/", "_")
                    )
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_bytes(up_img.getvalue())
                    server_ref = comfy.upload_image(str(tmp))
                else:  # local path from the last shoot
                    server_ref = comfy.upload_image(up_img)
            wf = build_video_workflow(
                vprompt.strip(),
                width=width,
                height=height,
                frames=FRAME_PRESETS[vsec],
                steps=vsteps,
                seed=None if vseed < 0 else int(vseed),
                start_image=server_ref,
            )
            out_dir = ROOT / "output" / "video" / time.strftime("%Y%m%d-%H%M%S")
            out_dir.mkdir(parents=True, exist_ok=True)
            vjob.start(comfy, wf, out_dir)
            st.rerun()

        if vjob.status == "running":
            with st.status("Rendering video... (cold start can take several minutes)", expanded=True):
                st.code("\n".join(vjob.logs[-12:]) or "(submitting...)", language="console")
        elif vjob.status == "error":
            st.error(f"Video render failed: {vjob.error}")
            st.code("\n".join(vjob.logs[-20:]), language="console")
        elif vjob.status == "done" and vjob.files:
            mp4 = Path(vjob.files[0])
            st.success(f"Video ready: `{mp4}` ({mp4.stat().st_size / 1e6:.1f} MB)")
            st.video(str(mp4))
            st.download_button("\u2b07\ufe0f Download MP4", data=mp4.read_bytes(), file_name=mp4.name, mime="video/mp4")

# ---------------------------------------------------------------------------
# tab 3: results browser
# ---------------------------------------------------------------------------
with tab_results:
    st.header("Past runs")
    manifests = sorted((ROOT / "output" / "ecom").glob("*/manifest.json")) if (ROOT / "output" / "ecom").is_dir() else []
    if not manifests:
        st.caption("No past runs yet - generate something in the Product shoot tab.")
    else:
        def _run_label(m: Path) -> str:
            try:
                import json
                data = json.loads(m.read_text(encoding="utf-8"))
                return f"{m.parent.name} ({data.get('created_at', '')[:16]})"
            except Exception:
                return m.parent.name

        sel = st.selectbox("Run", manifests, format_func=_run_label)
        try:
            import json
            mdata = json.loads(sel.read_text(encoding="utf-8"))
        except Exception as e:
            st.error(f"could not read manifest: {e}")
            mdata = {}

        prof = mdata.get("product_profile") or {}
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.subheader(prof.get("name", "(unnamed)"))
            st.caption(f"{prof.get('category', '')} - {mdata.get('created_at', '')}")
        with c2:
            if st.button("\U0001f3ac Use profile in Video Studio", use_container_width=True):
                st.session_state.video_prefill_profile = prof
                st.session_state.video_prefill_prompt = ""
                st.success("Profile loaded - open the Video studio tab and click 'Draft prompt with LLM'.")
        with c3:
            if st.button("\u2b07\ufe0f manifest.json", use_container_width=True):
                st.download_button("Download", data=sel.read_text(encoding="utf-8"), file_name="manifest.json",
                                   mime="application/json")

        results = mdata.get("results", []) or []
        if results:
            rcols = st.columns(min(4, max(1, len(results))))
            for i, r in enumerate(results):
                with rcols[i % len(rcols)]:
                    p = r.get("local_path", "")
                    if p and Path(p).is_file():
                        st.image(p, caption=f"shot {r.get('shot_id', i)}", use_container_width=True)
        persona = mdata.get("persona") or {}
        if persona.get("local_path") and Path(persona["local_path"]).is_file():
            with st.expander("\U0001f469 Persona"):
                pc1, pc2 = st.columns([1, 2])
                pc1.image(persona["local_path"], width=280)
                pc2.write(persona.get("description", ""))
        with st.expander("\U0001f4cb Product profile & shots"):
            st.json(mdata, expanded=False)


# ---------------------------------------------------------------------------
# auto-refresh while anything is running
# ---------------------------------------------------------------------------
if runner.status == "running" or vjob.status == "running":
    time.sleep(2)
    st.rerun()
