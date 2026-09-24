"""E-commerce product-image generator.

LangGraph-orchestrated flow that turns raw seller photos into premium listing
images: a user-supplied OpenAI-compatible LLM (base_url + api_key) does all
analysis/planning/prompting, ComfyUI (Modal-hosted) renders the images.
"""

__version__ = "0.1.0"
