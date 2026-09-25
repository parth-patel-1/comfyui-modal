# ComfyUI on Modal

Host [ComfyUI](https://github.com/Comfy-Org/ComfyUI) on [Modal](https://modal.com) serverless
GPUs and use it as a website from your browser — no local GPU needed.

```
Browser ──> https://<your-workspace>--comfyui.modal.run ──> Modal GPU container ──> ComfyUI web UI
```

Alongside the hosted ComfyUI website, this repo now ships an **e-commerce
product studio** - a Streamlit UI (`streamlit_app.py`) that turns raw product
photos into polished marketplace images (LangGraph + LLM planning,
Qwen-Image-2.1 rendering) and MiniMax H3 clips. See
[E-commerce product studio](#e-commerce-product-studio-streamlit-ui).

## What gets created on your Modal account

| Resource | Name | Purpose |
|---|---|---|
| App | `comfyui-hosting` | The deployed ComfyUI web app |
| Web endpoint | `https://<workspace>--comfyui.modal.run` | The website you open in your browser |
| Volume | `comfyui-models` | Model weights (downloaded once, reused forever) |
| Volume | `comfyui-outputs` | Generated images (persist) |
| Volume | `comfyui-input` | Images you upload for img2img / ControlNet (persist) |
| Volume | `comfyui-user` | Saved workflows & UI settings (persist) |
| Image | (auto-built Docker image) | Debian + Python 3.11 + ComfyUI `v0.37.0` + deps |

Bundled models (downloaded once into the `comfyui-models` volume):

- **Qwen-Image-2.1** (~24 GB, Qwen research license) — a state-of-the-art image
  model that handles **both text-to-image and image editing**, renders text
  crisply, and outputs up to 2K natively. Fits on a 24 GB GPU (A10G).
- **MiniMax H3** (~42 GB) — an omni-modal **text-to-video** model that generates
  video **with native stereo audio** (dialogue, SFX, music) at 24 fps. Runs on
  the A10G via CPU offloading; a 48 GB L40S is noticeably faster.

## Prerequisites

- Python 3.9+ on your PATH — https://python.org (on Windows tick *Add python.exe to PATH*)
- A free Modal account — https://modal.com (includes free monthly compute credits; see
  https://modal.com/pricing)

## Quickstart

**Windows (PowerShell):**

```powershell
cd d:\parth\comfyui_modal
.\launch.ps1
```

**macOS / Linux (Terminal):**

```bash
cd comfyui_modal
chmod +x launch.sh stop.sh
./launch.sh
```

The launcher does everything: creates a local `.venv`, installs the `modal` CLI,
authenticates to Modal (token ID + secret if given, otherwise a one-time browser
sign-in), downloads the bundled models into the volume (one-time, ~66 GB), deploys
the app, and opens the ComfyUI website.

Prefer doing it manually?

```bash
pip install modal
modal token set --token-id ak-... --token-secret as-...   # token auth (non-interactive)
modal run comfyui_app.py             # one-time model download (~66 GB)
modal deploy comfyui_app.py          # deploy -> prints your URL
```

### What to expect

- **First launch:** image build ~5–10 min (installs PyTorch etc., cached afterwards)
  + model download ~66 GB. Total one-time wait ~30–60 min (mostly the download).
- **Every launch afterwards:** a few seconds.
- **Cold starts:** the GPU container scales to zero when idle; the first page load
  after that takes ~30–60 s. Leave it idle and it stops again automatically
  (after `SCALEDOWN_WINDOW_S = 300`).
- **Single GPU container:** the app never runs more than one GPU container
  (`MAX_CONTAINERS = 1`) — extra browser requests queue instead of starting a
  second billed GPU.
- In the ComfyUI UI, open the **templates / template library** and search for
  **"Qwen-Image-2.1"** (shipped with ComfyUI v0.37.0). Use *Qwen Image 2.1* for
  text-to-image, or *Qwen Image 2.1 Image Edit* for instruction-based editing —
  the downloaded files are picked up automatically by the loader nodes
  (`qwen_image_2.1_int8_convrot` in UNETLoader, `qwen3vl_8b_bf16` in CLIPLoader,
  `qwen_image_2.1_vae_bf16` in VAELoader). Template defaults: 25 steps, cfg 1,
  euler + simple scheduler. For 2048×2048 output, set the Resolution Selector's
  megapixel target to ~4 MP (1 MP ≈ 1024×1024).
  Images you generate are stored on the `comfyui-outputs` volume and can be
  downloaded from the UI.
- For video, search the template library for **"MiniMax H3"** (shipped with
  ComfyUI v0.37.0) and use *MiniMax H3: Text to Video* — or drag the ready-made
  `workflows/minimax_h3_t2v.json` onto the canvas (details below). Generated
  MP4s land in the `comfyui-outputs` volume under `video/`.

## Image editing / reference-based generation

Qwen-Image-2.1 is a single model for **both** text-to-image and instruction-based
image editing, so no extra downloads are needed. Ready-made workflows live in
`workflows/`:

| File | Use |
|---|---|
| `workflows/qwen_image_2.1.json` (+ `_api` variant) | Text-to-image |
| `workflows/qwen_image_2.1_edit.json` (+ `_api` variant) | **Edit an existing image, or generate a new image from a reference** |
| `workflows/minimax_h3_t2v.json` (+ `_api` variant) | **Text-to-video with native stereo audio** (MiniMax H3) |

The edit workflow (a flattened, repo-local copy of the official *Qwen Image 2.1
Image Edit* template, using the int8 model files) feeds your input image(s) to
`Text Encode Qwen Image 2.1`, which shows them to the model both as vision
context and as VAE latents — so one workflow covers both cases:

- **Edit an existing image** — *"make the sky in <image1> sunset colored, keep
  everything else unchanged"*
- **Generate a new image from a reference** — *"generate a new fantasy castle in
  the same architectural style as <image1>"*

To use it:

1. Get your image(s) onto the `comfyui-input` volume: drag & drop them onto the
   ComfyUI canvas (then pick them in the *Input Image* nodes), or from your
   machine:
   ```powershell
   modal volume put comfyui-input my_photo.png /
   ```
2. Load the workflow: drag `workflows/qwen_image_2.1_edit.json` into the browser
   window (or *Workflows → Open*), pick your image(s) in the **Input Image**
   nodes, write your instruction in the encode node's prompt (refer to images as
   `<image1>`, `<image2>`, ...), and hit *Queue*.

Notes:

- **Multiple references:** the workflow ships with **Input Image 2** and
  **Input Image 3** pre-wired as `<image2>` / `<image3>` — set their files, or
  remove those two links for single-image runs. E.g. *"put the shirt from
  `<image2>` on the person in `<image1>`"*. Need more? Connect extra
  *Load Image* nodes to the encode node's empty image slots (up to 16 total).
- **Output size** follows the first input image (`<image1>`, aspect ratio
  preserved). `resolution` on the encode node is the total pixel budget for the
  references — **shared across all of them**, so raise it to 2048 when using
  several: 1024 by default, **2048 for native 2K**, 0 = keep original sizes. For
  a fixed custom output size instead, set the *Empty Latent Image* width/height
  and flip the *If/Else Switch* to **true**.
- **Scripts:** POST `workflows/qwen_image_2.1_edit_api.json` to
  `https://<workspace>--comfyui.modal.run/prompt` (first set each `LoadImage`
  node's "image" value to a filename that exists in the input volume, e.g.
  `my_photo.png` uploaded as above; for single-image runs remove the
  `images.image_2` / `images.image_3` inputs and their nodes `13` / `14`), then
  poll `/history/<prompt_id>` and fetch results from `/view`.

## Text-to-video with MiniMax H3

The deployment also downloads **MiniMax H3** (~42 GB in five files): text-to-video
**with synchronized stereo audio** — describe dialogue, sound effects and music in
the prompt and the model renders video and audio in one pass (24 fps, up to ~15 s,
768px-short-edge canvas up to 768×1344).

To use it:

1. Load `workflows/minimax_h3_t2v.json` (drag it into the browser window, or
   *Workflows → Open*). It's a flattened copy of the official *MiniMax H3: Text
   to Video* template with two convenience toggles added.
2. Write your prompt in the **MiniMaxH3ImageToVideo** node — describe shots,
   camera moves **and the audio** in one block (the default prompt shows the
   format, including a per-second timeline).
3. Pick the size in the **Resolution Selector** (0.4 MP = fast preview, 864×480;
   0.98 MP = native quality, 1344×768) and set **Duration (seconds)** — the Math
   Expression node snaps it to the model's 17k+5 frame grid at 24 fps.
4. Hit *Queue*. The MP4 is written by the SaveVideo node under `video/` in the
   `comfyui-outputs` volume.

Notes:

- **Turbo mode:** flip the **Turbo mode** boolean to `true` to switch in the
  turbo LoRA and drop from 20 steps to 8 (~2.5× faster, slight quality
  trade-off). Default is quality mode (no LoRA, 20 steps).
- **Image-to-video:** connect images to the `first_frame` / `last_frame` inputs
  of the MiniMaxH3ImageToVideo node. The Streamlit **Video studio** tab does
  this for you - pick a first frame from an upload or reuse a shot from your
  last run.
- **Sigma shift:** the **ModelSamplingMiniMaxH3** node (video shift 12 / audio
  shift 3) is required — it gives the model its audio-aware sampling schedule.
  Do not swap it for a generic *Model Sampling* node (SD3 / AuraFlow / Flux):
  those strip the audio schedule and sampling crashes with
  `'ModelSamplingAdvanced' object has no attribute 'audio_scale'`.
- **GPU:** works on the default A10G (24 GB) via ComfyUI's automatic CPU
  offloading; set `GPU_CONFIG = "L40S"` in `comfyui_app.py` for ~2–3× faster
  generation.
- **Scripts:** POST `workflows/minimax_h3_t2v_api.json` to `/prompt`, poll
  `/history/<prompt_id>`, fetch the MP4 from `/view`. The **Video studio** tab automates this
  submit-poll-download flow.

## E-commerce product studio (Streamlit UI)

`streamlit_app.py` is a browser UI for the whole pipeline - no workflow editing.
You give it raw product photo(s) plus a short description; an LLM plans the
shoot, reviews AI-generated model personas, and writes the image prompts; and
Qwen-Image-2.1 renders polished marketplace shots with a vision-QA pass. A
**Video studio** tab renders MiniMax H3 clips - text-to-video, or
image-to-video using one of your shots as the first frame.

1. Install the local dependencies (Modal CLI + the studio):
   ```powershell
   pip install -r requirements.txt
   ```
2. Give it an OpenAI-compatible LLM: create a `.env` in the repo root (loaded
   automatically; real environment variables take precedence) or export the
   variables:
   ```powershell
   # .env
   ECOM_LLM_BASE_URL=https://your-llm-endpoint/v1   # OpenAI, OpenRouter, vLLM, ...
   ECOM_LLM_API_KEY=sk-...
   ```
   The same fields are editable in the app's sidebar. The ComfyUI server URL
   defaults to your deployed app and can be overridden with `COMFYUI_URL`.
3. Launch and open http://localhost:8501:
   ```powershell
   streamlit run streamlit_app.py
   ```

The sidebar **Mode** controls how much is real:

| Mode | Behavior |
|---|---|
| Live | Real LLM + real ComfyUI on Modal |
| Mock LLM | Scripted LLM, real ComfyUI (try the UI without an LLM key) |
| Dry run | Scripted LLM + placeholder images, no GPU calls (free and instant) |

Tabs:

| Tab | What you do |
|---|---|
| **Product shoot** | Upload 1-3 product photos + describe the product; pick style, platform, image count and advanced options (model policy, own model photo, output dir). The pipeline's interactive steps appear as widgets - clarify questions, generate-vs-upload for model shots, persona review, shot-plan approval - with a live log; you finish with a gallery, per-image QA notes and a downloadable `manifest.json` |
| **Video studio** | Write a prompt or have the LLM draft it from a previous shoot's profile; choose resolution / duration / steps / seed; optionally set a first frame (uploaded still or a shot from your last run = image-to-video); renders in the background, then play + download the MP4 |
| **Results** | Browse past runs under `output/ecom/` (gallery, persona, manifest) and send any profile to the video studio |

Prefer the terminal? `run_product_shoot.py` runs the same pipeline as a batch
CLI (`--images`, `--description`, `--num-images`, `--style`, `--platform`,
`--auto-approve`, `--mock-llm`, `--dry-run`, ...):

```powershell
python run_product_shoot.py --images photo1.jpg --description "EcoBin medium garbage bags" `
    --num-images 2 --auto-approve
```

Outputs: `output/ecom/<slug>/` (images, persona, QA notes, `manifest.json`) and
`output/video/` for clips.

## Authentication: token ID + secret

The launchers authenticate with a **Modal API token** (ID + secret) instead of a
browser sign-in. Create a token in the Modal dashboard under
[Settings → API Tokens](https://modal.com/settings/tokens) — IDs start with
`ak-`, secrets with `as-`.

**Windows (PowerShell):**

```powershell
.\launch.ps1 -TokenId ak-XXXXXXXX -TokenSecret as-YYYYYYYY
```

**macOS / Linux:**

```bash
./launch.sh --token-id ak-XXXXXXXX --token-secret as-YYYYYYYY
```

Or set environment variables once and launch normally (ideal for CI):

```bash
export MODAL_TOKEN_ID=ak-XXXXXXXX
export MODAL_TOKEN_SECRET=as-YYYYYYYY
./launch.sh
```

Notes:

- The launcher persists the credentials with `modal token set` and verifies them
  with a test request, so `stop.ps1` / `stop.sh` and future launches keep working
  without re-entering the token.
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` take precedence over tokens stored in
  `~/.modal.toml` — including the `MODAL_PROFILE` selection — so unset them if
  you want profile switching to apply.
- If no token is provided and none is stored, the launcher falls back to the
  one-time browser sign-in (`modal token new`).
- Keep the token secret private: anyone who has it can use your Modal account
  (and its billing). Don't commit it to git.

## Stopping & billing

You are billed **per second** while a GPU container is running (approx: T4 $0.59/h,
L4 $0.80/h, A10G $1.10/h, L40S $1.95/h, A100-80GB $5.24/h — check modal.com/pricing).
Idle containers scale down to zero automatically, but to take the website fully
offline:

```bash
.\stop.ps1        # Windows      ./stop.sh    # macOS/Linux
```

Useful commands: `modal app list`, `modal app logs comfyui-hosting`,
`modal volume list`.

## Multiple Modal accounts (profiles)

Every Modal account is a separate **workspace** — the app, volumes and URL live
in whichever account you deploy to. To sign in to another account without losing
the current one:

```bash
modal token new          # a browser opens -- sign in with the OTHER account
                         # (use an incognito window if your browser stays
                         # signed in to the current one)
modal profile list       # both accounts now appear; * marks the active one
```

`modal token new` saves the new account as a "profile" (named after its
workspace) in `~/.modal.toml` (`C:\Users\<you>\.modal.toml` on Windows) and
makes it the active one. Switch between accounts any time:

```powershell
modal profile activate <name>     # change the default account
.\launch.ps1 -Profile <name>      # one-off launch in that account
.\stop.ps1 -Profile <name>        # stop that account's app
```

```bash
./launch.sh --profile <name>     # macOS/Linux equivalents
./stop.sh --profile <name>
```

(You can also set the `MODAL_PROFILE` environment variable, or pass
`--profile <name>` to any individual `modal` command.)

Note: token-based auth (`MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` env vars, or the
`-TokenId` / `--token-id` launcher options) takes precedence over profile
selection — unset those variables when you want the profile to apply.

Things to know when switching accounts:

- The new account starts **empty**: the first launch there re-downloads the
  ~66 GB model set into its own volumes, and the URL becomes
  `https://<new-workspace>--comfyui.modal.run`.
- The old account's app and volumes are untouched — stop its app (log back in
  or use the [Modal dashboard](https://modal.com)) so it doesn't keep billing.

## Configuration (edit `comfyui_app.py`)

- **GPU:** change `GPU_CONFIG` (e.g. `"L4"` to cut cost, `"L40S"`/`"H100"` for
  video/Flux-dev workloads).
- **Models:** edit the `MODEL_DOWNLOADS` list — any entry is
  `(folder, url)`, e.g. `("loras", "https://huggingface.co/.../my-lora.safetensors")`.
  The folder is any ComfyUI models subfolder (`checkpoints`, `loras`, `vae`, `clip`,
  `unet`/`diffusion_models`, `upscale_models`, ...). Then re-run `modal run comfyui_app.py`.
  You can also upload files directly:
  `modal volume put comfyui-models my_model.safetensors checkpoints/`.
  Repos must be **public (non-gated)** for unauthenticated downloads.
- **ComfyUI version:** change `COMFYUI_VERSION` (a release tag from
  https://github.com/Comfy-Org/ComfyUI/releases).
- **Custom nodes:** uncomment/add `.run_commands("git clone --depth 1 <url> <dir>")`
  lines in the image definition, then redeploy.

## Security note

The `*.modal.run` URL is **public**: anyone who has it can use your GPU.
ComfyUI has no built-in login. Mitigations:

1. The URL is long and unguessable — don't share it.
2. Stop the app when not in use (`.\stop.ps1`).
3. For real auth, put Modal's [proxy auth](https://modal.com/docs/guide/webhooks)
   (`requires_proxy_auth=True`) or a custom domain behind SSO (e.g. Cloudflare
   Access) in front of the endpoint.

The same URL also serves ComfyUI's HTTP API (`/prompt`, `/history`, `/view`, ...),
so scripts can talk to it too — e.g. POST an API-format workflow JSON to
`https://<workspace>--comfyui.modal.run/prompt`.

## Troubleshooting

- **`Token missing. Could not authenticate client`** → authenticate with
  `modal token set --token-id ak-... --token-secret as-...` (or `modal token new`);
  the launcher does this automatically when given `-TokenId`/`--token-id` and
  `-TokenSecret`/`--token-secret`.
- **Model download fails / 403** → the Hugging Face repo is gated or the URL is
  wrong; use a public repo or provide your own file URL.
- **Out of memory (OOM) during generation** → generate at ~1 MP instead of 4 MP
  (2K), pick a bigger GPU in `GPU_CONFIG` (e.g. `L40S`), or swap in smaller
  quantized files (see the commented options in `MODEL_DOWNLOADS`).
- **First page load is slow** → that's the cold start + model loading; it warms up
  after the first request.
- **Changed something but nothing happened** → redeploy (`modal deploy comfyui_app.py`);
  image/volume changes need it.

## Files

| File | What it is |
|---|---|
| `comfyui_app.py` | The Modal app: image, volumes, model downloads, web UI server |
| `workflows/` | Ready-made ComfyUI workflows: `qwen_image_2.1.json` (text-to-image) and `qwen_image_2.1_edit.json` (image editing / reference images), each with an `_api` API-format variant |
| `launch.ps1` / `launch.sh` | One-click launcher (setup → auth → models → deploy → open site) |
| `stop.ps1` / `stop.sh` | Take the app offline (stops GPU billing) |
| `test_download_helper.py` | Offline smoke test of the model-download logic (no Modal account needed) |
| `requirements.txt` | Local deps: `modal` CLI + the e-commerce studio (LangGraph, OpenAI-compatible client, Streamlit, requests) |
| `streamlit_app.py` | The e-commerce product studio web UI (see [above](#e-commerce-product-studio-streamlit-ui)) |
| `ecom_app/` | Studio internals: LangGraph graph + nodes, LLM & ComfyUI clients, MiniMax H3 video workflow builder, threaded runners |
| `run_product_shoot.py` | CLI for the same product-shot pipeline (batch / scripting) |
