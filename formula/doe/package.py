"""v7.0 룰북 패키지 로더 — INSTALLATION §8의 강제 조건을 코드로 건다.

1. architecture_version == 7.0.0      2. manifest에 룰북 18 · 마스터 7      3. 실제 행 수 == manifest records
4. SHA256SUMS 대조 + 패키지 해시 기록   5. DRAFT 규칙은 읽되 집행 불가      6. enforcement_enabled=false면 상태 전진 금지
7. 중복 ID · 미등록 source/test/reason code 차단                         8. 금지 상태(CONTROL_STRATEGY 등) 차단
"""
from __future__ import annotations

import csv
import functools
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO = Path(__file__).resolve().parents[2]
EXPECTED_VERSION = "7.0.0"
APPROVED_STATUSES = {"APPROVED", "PRODUCTION_APPROVED"}


class PackageError(RuntimeError):
    """패키지가 계약을 어기면 로드 자체를 거부한다(조용히 일부만 쓰지 않는다)."""


@dataclass(frozen=True)
class DoeModuleConfig:
    module_version: str
    enabled: bool
    runtime_mode: str
    rulebook_root: Path
    package_manifest: Path
    development_policy: Path
    allow_draft_enforcement: bool
    legacy_07_doe_enabled: bool
    confirmation_test_master: Path
    statistical_constants: Path
    display_banner: str

    @classmethod
    def load(cls, path: Optional[Path] = None, base: Path = REPO) -> "DoeModuleConfig":
        raw = yaml.safe_load((path or base / "config/doe_module.yaml").read_text(encoding="utf-8"))
        p = lambda k: (base / raw[k]).resolve()  # noqa: E731
        return cls(module_version=str(raw["module_version"]), enabled=bool(raw["enabled"]), runtime_mode=raw["runtime_mode"],
                   rulebook_root=p("rulebook_root"), package_manifest=p("package_manifest"), development_policy=p("development_policy"),
                   allow_draft_enforcement=bool(raw["allow_draft_enforcement"]), legacy_07_doe_enabled=bool(raw["legacy_07_doe_enabled"]),
                   confirmation_test_master=p("confirmation_test_master"), statistical_constants=p("statistical_constants"),
                   display_banner=raw.get("display_banner", ""))


def _csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class DoePackage:
    config: DoeModuleConfig
    manifest: Dict[str, Any]
    policy: Dict[str, Any]
    rulebooks: Dict[str, Any]            # RB01..RB18 → rows(list) 또는 YAML(dict)
    masters: Dict[str, Any]              # M01..M07
    sources: Dict[str, Dict[str, str]]
    reason_codes: Dict[str, Dict[str, str]]
    confirmation_tests: Dict[str, Dict[str, str]]
    constants: Dict[str, float]
    package_hash: str
    file_hashes: Dict[str, str] = field(default_factory=dict)

    # ── 집행 가능성 — 설정과 규칙 양쪽이 허락해야 한다 ──
    def can_enforce(self, row: Dict[str, Any]) -> bool:
        if not self.config.enabled or self.config.runtime_mode != "ENFORCING":
            return False
        status = str(row.get("validation_status", ""))
        enabled = str(row.get("enforcement_enabled", "")).lower() == "true"
        if status.startswith("DRAFT") and not self.config.allow_draft_enforcement:
            return False
        return enabled and (status in APPROVED_STATUSES or self.config.allow_draft_enforcement)

    def rows(self, rb_id: str) -> List[Dict[str, str]]:
        v = self.rulebooks[rb_id]
        return v if isinstance(v, list) else []

    def rule(self, rb_id: str, rule_id: str) -> Dict[str, str]:
        key = "rule_id" if self.rows(rb_id) and "rule_id" in self.rows(rb_id)[0] else "pattern_id"
        for r in self.rows(rb_id):
            if r.get(key) == rule_id:
                return r
        raise KeyError(f"{rb_id}:{rule_id}")

    def reason(self, code: str) -> Dict[str, str]:
        if code not in self.reason_codes:
            raise PackageError(f"미등록 reason code: {code}")
        return self.reason_codes[code]

    @property
    def forbidden_states(self) -> List[str]:
        return list(self.policy.get("forbidden_states", []))

    def summary(self) -> Dict[str, Any]:
        return {"package": self.manifest.get("package"), "architecture_version": self.manifest.get("architecture_version"),
                "validation_status": self.manifest.get("validation_status"), "enabled": self.config.enabled,
                "runtime_mode": self.config.runtime_mode, "rulebooks": len(self.rulebooks), "masters": len(self.masters),
                "confirmation_tests": len(self.confirmation_tests), "reason_codes": len(self.reason_codes),
                "sources": len(self.sources), "package_hash": self.package_hash, "banner": self.config.display_banner,
                "enforceable_rules": sum(self.can_enforce(r) for v in self.rulebooks.values() if isinstance(v, list) for r in v)}


def load_package(config: Optional[DoeModuleConfig] = None) -> DoePackage:
    cfg = config or DoeModuleConfig.load()
    root = cfg.rulebook_root
    manifest = yaml.safe_load(cfg.package_manifest.read_text(encoding="utf-8"))
    errors: List[str] = []
    if str(manifest.get("architecture_version")) != EXPECTED_VERSION:
        errors.append(f"architecture_version {manifest.get('architecture_version')} ≠ {EXPECTED_VERSION}")
    if cfg.module_version != EXPECTED_VERSION:
        errors.append(f"doe_module.yaml module_version {cfg.module_version} ≠ {EXPECTED_VERSION}")
    rb_entries, m_entries = manifest.get("rulebooks", []), manifest.get("reference_masters", [])
    if len(rb_entries) != 18:
        errors.append(f"룰북 {len(rb_entries)}개(18 필요)")
    if len(m_entries) != 7:
        errors.append(f"참조 마스터 {len(m_entries)}개(7 필요)")

    # 4) 해시 — SHA256SUMS와 대조하고, 대조한 파일 해시로 패키지 해시를 만든다
    sums: Dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            sums[name.strip().lstrip("*").lstrip("./")] = h
    file_hashes = {}
    for name, h in sums.items():
        f = root / name
        if not f.exists():
            errors.append(f"SHA256SUMS 파일 없음: {name}")
            continue
        got = _sha256(f)
        file_hashes[name] = got
        if got != h:
            errors.append(f"해시 불일치: {name}")
    package_hash = hashlib.sha256("".join(f"{k}:{file_hashes[k]}\n" for k in sorted(file_hashes)).encode()).hexdigest()

    def load_entry(e: Dict[str, Any]) -> Any:
        f = root / e["file"]
        if not f.exists():
            errors.append(f"manifest 파일 없음: {e['file']}")
            return []
        if f.suffix == ".csv":
            rows = _csv(f)
            if "records" in e and int(e["records"]) != len(rows):
                errors.append(f"{e['id']} 행 수 {len(rows)} ≠ manifest {e['records']}")
            return rows
        return yaml.safe_load(f.read_text(encoding="utf-8"))

    rulebooks = {e["id"]: load_entry(e) for e in rb_entries}
    masters = {e["id"]: load_entry(e) for e in m_entries}
    policy = yaml.safe_load(cfg.development_policy.read_text(encoding="utf-8"))

    # 7) 참조 무결성
    sources = {r["source_id"]: r for r in _csv(root / "sources/source_registry.csv")}
    reason_rows = masters.get("M07", [])
    reason_codes = {r["reason_code"]: r for r in reason_rows}
    if len(reason_codes) != len(reason_rows):
        errors.append("M07 reason code 중복")
    tests_rows = masters.get("M06", [])
    tests = {r["test_id"]: r for r in tests_rows}
    if len(tests) != len(tests_rows):
        errors.append("M06 test_id 중복")
    for rb_id, rows in rulebooks.items():
        if not isinstance(rows, list) or not rows:
            continue
        key = next((k for k in ("rule_id", "pattern_id", "mapping_id", "failure_mode_id") if k in rows[0]), None)
        if key:
            ids = [r[key] for r in rows]
            if len(ids) != len(set(ids)):
                errors.append(f"{rb_id} 중복 ID")
        for r in rows:
            for sid in [s.strip() for s in str(r.get("source_ids", "")).replace(",", ";").split(";") if s.strip()]:
                if sid.startswith("SRC_") and sid not in sources:
                    errors.append(f"{rb_id} 미등록 source {sid}")
            code = r.get("result_code") or r.get("reason_code")
            if code and code not in reason_codes:
                errors.append(f"{rb_id} 미등록 reason code {code}")
            nxt = r.get("next_state") or r.get("backtrack_state")
            if nxt and nxt in policy.get("forbidden_states", []):
                errors.append(f"{rb_id} 금지 상태로 전이: {nxt}")   # 8)
    for r in rulebooks.get("RB18", []):
        for tid in [t.strip() for t in r.get("confirmation_test_ids", "").replace(",", ";").split(";") if t.strip()]:
            if tid not in tests:
                errors.append(f"RB18 {r['pattern_id']} 미등록 확인시험 {tid}")
    for code, r in reason_codes.items():
        if r.get("default_next_state") in policy.get("forbidden_states", []):
            errors.append(f"M07 {code} → 금지 상태")

    constants = {}
    if cfg.statistical_constants.exists():
        for r in _csv(cfg.statistical_constants):
            try:
                constants[r["constant_id"]] = float(r["value"])
            except ValueError:
                pass
    if errors:
        raise PackageError("; ".join(errors[:12]) + (f" … 외 {len(errors) - 12}건" if len(errors) > 12 else ""))
    return DoePackage(config=cfg, manifest=manifest, policy=policy, rulebooks=rulebooks, masters=masters, sources=sources,
                      reason_codes=reason_codes, confirmation_tests=tests, constants=constants,
                      package_hash=package_hash, file_hashes=file_hashes)


@functools.lru_cache(maxsize=1)
def package() -> DoePackage:
    return load_package()
