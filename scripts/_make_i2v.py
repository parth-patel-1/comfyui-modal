"""One-off: derive minimax_h3_i2v_api.json from the t2v template."""

import json
from pathlib import Path

wf_dir = Path(__file__).parent.parent / "modal_app" / "workflows"
wf = json.loads((wf_dir / "minimax_h3_t2v_api.json").read_text())

wf["16"] = {"class_type": "LoadImage", "inputs": {"image": "first_frame.png"}}
wf["17"] = {"class_type": "LoadImage", "inputs": {"image": "last_frame.png"}}
wf["5"]["inputs"]["first_frame"] = ["16", 0]
wf["5"]["inputs"]["last_frame"] = ["17", 0]
wf["14"]["inputs"]["filename_prefix"] = "video/MiniMax_H3_i2v"

(wf_dir / "minimax_h3_i2v_api.json").write_text(json.dumps(wf, indent=2) + "\n")
print("written:", wf_dir / "minimax_h3_i2v_api.json")
