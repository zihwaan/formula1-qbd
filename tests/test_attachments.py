"""측정 원본 첨부 — 과제 2 완료 기준(형식·크기 제한, 중복 저장 없음, 첨부 없이도 제출) + 과제 4 기기 원자료 해석."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("FORMULA1_LLM_PROVIDER", "none")


@pytest.fixture()
def app_with_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMULA1_EVIDENCE_DIR", str(tmp_path))
    import importlib
    import web.server as server
    server = importlib.reload(server)
    from formula.orchestrator.runner import Run
    run = Run(Path(server.ROOT), "테스트 요청")
    server.RUNS[run.run_id] = run
    return server, TestClient(server.app), run


def test_upload_dedupes_and_limits(app_with_run):
    server, client, run = app_with_run
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    a = client.post(f"/api/runs/{run.run_id}/attachments", data={"measurement_id": "M_XRPD"},
                    files={"file": ("pattern.png", png, "image/png")}).json()
    b = client.post(f"/api/runs/{run.run_id}/attachments", data={"measurement_id": "M_XRPD"},
                    files={"file": ("again.png", png, "image/png")}).json()
    assert a["attachment_id"] == b["attachment_id"]
    assert len(list((Path(os.environ["FORMULA1_EVIDENCE_DIR"]) / run.run_id).iterdir())) == 1
    assert client.get(f"/api/runs/{run.run_id}/attachments/{a['attachment_id']}").status_code == 200
    exe = client.post(f"/api/runs/{run.run_id}/attachments", data={"measurement_id": "M_XRPD"},
                      files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert exe.status_code == 415
    big = client.post(f"/api/runs/{run.run_id}/attachments", data={"measurement_id": "M_XRPD"},
                      files={"file": ("big.csv", b"0" * (21 * 1024 * 1024), "text/csv")})
    assert big.status_code == 413


def test_bool_field_rejects_integer(app_with_run):
    server, client, run = app_with_run
    r = client.post(f"/api/runs/{run.run_id}/measurements", json={"measurements": {"salt_screen_done": 1}})
    assert r.status_code == 422
    r = client.post(f"/api/runs/{run.run_id}/measurements",
                    json={"measurements": {"tm_c": 200}, "attachments": {"M_DSC": ["nope"]}})
    assert r.status_code == 422                                 # 없는 첨부 id


def test_dsc_and_tga_raw_files_are_interpreted_deterministically():
    from formula.analysis import instrument
    t = np.linspace(30, 300, 541)
    heat = -2.0 * np.exp(-((t - 160) / 2.0) ** 2)               # 160 °C 부근 흡열 1개(아래 방향)
    out = instrument.interpret("M_DSC", "\n".join(f"{a},{b}" for a, b in zip(t, heat)).encode())
    assert out["fields"]["multiple_endotherms"] is False and 150 < out["fields"]["tm_c"] < 160
    w = 100 - 3 * (t > 120) - 40 / (1 + np.exp(-(t - 250) / 5))
    out = instrument.interpret("M_TGA", "\n".join(f"{a} {b}" for a, b in zip(t, w)).encode())
    assert abs(out["fields"]["weight_loss_100_150c_percent"] - 3.0) < 0.2 and out["fields"]["decomposition_onset_c"] > 200
