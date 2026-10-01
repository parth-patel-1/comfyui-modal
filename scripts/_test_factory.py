"""Smoke test for modal_app.workflow_factory (no network needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "modal_app"))

import workflow_factory as f  # noqa: E402

t2i = f.build_image_t2i("a cat", "blurry", 1024, 1024, 42)
assert t2i["8"]["inputs"]["seed"] == 42
assert t2i["5"]["inputs"]["width"] == 1024
print("t2i OK:", len(t2i), "nodes")

edit = f.build_image_edit(
    "make <image1> red", "", ["r1.png", "r2.png", "r3.png"], 1024, 768, 7
)
assert "101" in edit and "103" in edit
assert edit["6"]["inputs"]["images.image_1"] == ["101", 0]
assert edit["6"]["inputs"]["images.image_3"] == ["103", 0]
assert edit["7"]["inputs"]["height"] == 768
print("edit OK:", len(edit), "nodes, refs wired:",
      [k for k in edit["6"]["inputs"] if k.startswith("images.")])

t2v = f.build_video_t2v("waves", 864, 480, 5, 1)
assert t2v["5"]["inputs"]["length"] == 124, t2v["5"]["inputs"]["length"]
assert "16" not in t2v  # no turbo lora by default
print("t2v OK:", len(t2v), "nodes, length", t2v["5"]["inputs"]["length"])

t2v_turbo = f.build_video_t2v("waves", 864, 480, 10, 1, turbo=True)
assert "16" in t2v_turbo and t2v_turbo["15"]["inputs"]["model"] == ["16", 0]
assert t2v_turbo["9"]["inputs"]["steps"] == 8
print("t2v turbo OK: length", t2v_turbo["5"]["inputs"]["length"])

i2v = f.build_video_i2v("pan left", "first.png", None, 1344, 768, 5, 3)
assert i2v["5"]["inputs"]["first_frame"] == ["16", 0]
assert "last_frame" not in i2v["5"]["inputs"] and "17" not in i2v
print("i2v (first only) OK:", len(i2v), "nodes")

i2v2 = f.build_video_i2v("pan left", "a.png", "b.png", 1344, 768, 5, 3)
assert i2v2["5"]["inputs"]["last_frame"] == ["17", 0]
print("i2v (first+last) OK")

assert f._snap_frames(15) == 365 or f._snap_frames(15) % 17 == 5
assert f._snap_frames(5) == 124
print("frame snapping OK")
print("ALL FACTORY TESTS PASSED")
