"""DoE v7.0 패키지 로더 — INSTALLATION §11.3 최소 확인 항목 + §8 강제 조건(변조·버전·금지 상태)."""
import dataclasses
import shutil

import pytest

from formula.doe.package import REPO, DoeModuleConfig, PackageError, load_package, package


def test_counts_and_references():
    p = package()
    assert len(p.rulebooks) == 18 and set(p.rulebooks) == {f"RB{i:02d}" for i in range(1, 19)}
    assert len(p.masters) == 7 and set(p.masters) == {f"M{i:02d}" for i in range(1, 8)}
    assert len(p.confirmation_tests) == 90
    assert len(p.reason_codes) == 167
    for r in p.rulebooks["RB18"]:                       # RB18의 확인시험은 모두 M06에 있다
        for t in [x.strip() for x in r["confirmation_test_ids"].replace(",", ";").split(";") if x.strip()]:
            assert t in p.confirmation_tests
    assert p.package_hash and len(p.file_hashes) == 38


def test_feature_flag_off_and_draft_never_enforced():
    p = package()
    assert p.config.enabled is False and p.config.runtime_mode == "VALIDATION_ONLY"
    assert p.summary()["enforceable_rules"] == 0
    # 설정을 ENFORCING으로 바꿔도 DRAFT 규칙은 allow_draft_enforcement 없이 집행되지 않는다
    cfg = dataclasses.replace(p.config, enabled=True, runtime_mode="ENFORCING")
    p2 = dataclasses.replace(p, config=cfg)
    assert not any(p2.can_enforce(r) for v in p2.rulebooks.values() if isinstance(v, list) for r in v)


def test_forbidden_states_declared():
    assert set(package().forbidden_states) == {"CONTROL_STRATEGY", "PPQ_READY", "COMMERCIAL_RELEASE"}


def _copy(tmp_path):
    base = DoeModuleConfig.load()
    root = tmp_path / "v7_0"
    shutil.copytree(base.rulebook_root, root)
    return dataclasses.replace(base, rulebook_root=root, package_manifest=root / "manifest.yaml",
                               development_policy=root / "config/development_policy.yaml")


def test_tampered_file_is_rejected(tmp_path):
    cfg = _copy(tmp_path)
    f = cfg.rulebook_root / "rulebooks/09_doe_design_selection_rules.csv"
    f.write_text(f.read_text(encoding="utf-8-sig").replace("17-run", "18-run"), encoding="utf-8")
    with pytest.raises(PackageError, match="해시 불일치"):
        load_package(cfg)


def test_wrong_version_is_rejected(tmp_path):
    cfg = dataclasses.replace(_copy(tmp_path), module_version="6.1.0")
    with pytest.raises(PackageError, match="module_version"):
        load_package(cfg)


def test_legacy_assets_untouched():
    """v7 설치가 v6.1 확인시험 마스터(66)와 기존 manifest를 덮지 않았다."""
    import csv
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    with (root / "database/reference/confirmation_test_master.csv").open(encoding="utf-8-sig") as h:
        assert len(list(csv.DictReader(h))) == 66
    assert "v7_0" not in (root / "config/rulebook_manifest.yaml").read_text(encoding="utf-8")


def test_migration_matrix_covers_every_legacy_file():
    """INSTALLATION §6.2 — v6.1 파일마다 이관 상태가 하나씩 있어야 archive를 검토할 수 있다."""
    import csv
    root = REPO / "database" / "07_doe"
    legacy = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
              and not str(p.relative_to(root)).startswith(("v7_0", "archive")) and p.name != "V6_TO_V7_MIGRATION_MATRIX.csv"}
    with (root / "V6_TO_V7_MIGRATION_MATRIX.csv").open(encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert {r["legacy_file"] for r in rows} == legacy
    allowed = {"MIGRATED", "PARTIALLY_MIGRATED", "NOT_MIGRATED", "REPLACED", "DEPRECATED_AFTER_VALIDATION"}
    assert all(r["migration_status"] in allowed for r in rows)
    for r in rows:
        if r["v7_target"]:
            assert (root / r["v7_target"]).exists(), r["v7_target"]
