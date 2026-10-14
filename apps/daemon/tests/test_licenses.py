import importlib.util
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_licenses.py"
spec = importlib.util.spec_from_file_location("check_licenses", SCRIPT)
CL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CL)


def reg(**model):
    return {"capabilities": {"x": {"default": {"id": "m1", **model}}}}


def test_real_registry_passes():
    root = SCRIPT.parent.parent
    registry = yaml.safe_load((root / "models" / "registry.yaml").read_text(encoding="utf-8"))
    assert CL.check(registry, (root / "docs" / "MODEL_LICENSES.md").read_text(encoding="utf-8")) == []


def test_nc_license_must_be_flagged_and_never_default():
    errs = CL.check(reg(weights_license="CC-BY-NC-4.0"), "m1")
    assert any("non_commercial" in e for e in errs)
    errs = CL.check(reg(weights_license="CC-BY-NC-4.0", non_commercial=True), "m1")
    assert any("mặc định" in e for e in errs)                       # NC không được làm default
    assert CL.check({"capabilities": {"x": {"excluded": [{"id": "m1", "weights_license": "CC-BY-NC-4.0", "non_commercial": True}]}}}, "m1") == []


def test_nc_flag_conflicts_and_docs_and_downloads():
    assert any("mâu thuẫn" in e for e in CL.check({"capabilities": {"x": {"o": [{"id": "m1", "weights_license": "NC", "non_commercial": True, "commercial_ok": True}]}}}, "m1"))
    assert any("MODEL_LICENSES" in e for e in CL.check({"capabilities": {"x": {"o": [{"id": "m1", "weights_license": "NC", "non_commercial": True}]}}}, "không có"))
    big = reg(weights_license="MIT", download={"files": [{"url": "https://h/x", "path": "m.bin", "bytes": 9_000_000}]})
    assert any("sha256" in e for e in CL.check(big, ""))
    http = reg(weights_license="MIT", download={"files": [{"url": "http://h/x", "path": "m.bin", "bytes": 10, "sha256": "0" * 64}]})
    assert any("https" in e for e in CL.check(http, ""))
    assert CL.check(reg(), "")[0].startswith("m1") or "weights_license" in CL.check(reg(), "")[0]
