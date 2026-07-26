"""약대생 팀이 공급한 룰북 zip을 `database/`로 이관한다.

정본(canonical)  : 이도영 `formula1_rulebook.zip` → database/00_master ~ 06_config
참조(reference)  : 조하준 `제형AI agent.zip` 중 5개 파일 → database/reference/
레거시(legacy)   : 기존 7개 CSV → database/legacy/ (데모 회귀 비교용 보존)

이관 시 처리하는 것:
  - BOM(\\ufeff) 제거 — 조하준 CSV 헤더 첫 컬럼에 붙어 있어 컬럼명 매칭이 조용히 실패한다.
  - 인코딩 정규화 — utf-8 실패 시 cp949로 폴백해 utf-8로 다시 쓴다.
  - .DS_Store / __MACOSX 제외.

실행:  python scripts/import_rulebook.py [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
EXTRA = ROOT / "추가자료"
DATABASE = ROOT / "database"

CANONICAL_ZIP = EXTRA / "이도영" / "formula1_rulebook.zip"
REFERENCE_ZIP = EXTRA / "조하준" / "제형AI agent.zip"

# 조하준 자료에서 가져올 파일: zip 안 basename → database/reference/ 아래 저장할 이름.
# (zip 내부 한글 경로가 깨져 있으므로 경로가 아니라 basename으로 매칭한다)
REFERENCE_PICKS: Dict[str, str] = {
    "excipient_master.csv": "excipient_master_iid.csv",
    "excipient_regulatory_use_limits.csv": "excipient_regulatory_use_limits.csv",
    "api_physicochemical_thresholds_revised.csv": "api_physchem_thresholds.csv",
    "rule_input_dictionary.csv": "rule_input_dictionary.csv",
    "confirmation_test_master.csv": "confirmation_test_master.csv",
}

# 이관 전부터 database/에 있던 1세대 CSV — legacy/로 밀어두고 데모 회귀 비교에만 쓴다.
LEGACY_FILES = [
    "bcs_solubility_rules.csv",
    "incompatibility_multi.csv",
    "incompatibility_rules.csv",
    "packaging_stability_rules.csv",
    "pediatric_safety_rules.csv",
    "process_failure_rules.csv",
    "wetlab_feedback_rules.csv",
]

SKIP_PARTS = ("__MACOSX", ".DS_Store")


def _is_junk(name: str) -> bool:
    return any(part in name for part in SKIP_PARTS) or name.endswith("/")


def _decode(raw: bytes) -> str:
    """utf-8 우선, 실패 시 cp949 폴백. BOM은 항상 제거한다."""
    for encoding in ("utf-8", "utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # 어떤 인코딩으로도 못 읽으면 손실 허용 디코딩
        text = raw.decode("utf-8", errors="replace")
    return text.lstrip("﻿")


def _write_text(dest: Path, raw: bytes, dry_run: bool) -> int:
    """텍스트 파일을 BOM 없는 utf-8로 정규화해 저장. 반환값은 바이트 수."""
    text = _decode(raw)
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def import_canonical(dry_run: bool) -> List[Tuple[str, int]]:
    """이도영 룰북 30 CSV + 15 SOURCES.md를 database/ 바로 아래로 전개한다."""
    if not CANONICAL_ZIP.exists():
        sys.exit(f"[에러] 정본 zip을 찾을 수 없음: {CANONICAL_ZIP}")

    imported: List[Tuple[str, int]] = []
    with zipfile.ZipFile(CANONICAL_ZIP) as zf:
        for name in zf.namelist():
            if _is_junk(name):
                continue
            # zip 최상위 폴더 'formula1_rulebook/'는 벗겨내고 그 아래 구조만 유지
            parts = Path(name).parts
            if parts and parts[0] == "formula1_rulebook":
                parts = parts[1:]
            if not parts:
                continue
            dest = DATABASE.joinpath(*parts)
            size = _write_text(dest, zf.read(name), dry_run)
            imported.append((str(Path(*parts)), size))
    return sorted(imported)


def import_reference(dry_run: bool) -> List[Tuple[str, int]]:
    """조하준 자료에서 선별한 5개 참조 테이블만 database/reference/로 복사한다."""
    if not REFERENCE_ZIP.exists():
        sys.exit(f"[에러] 참조 zip을 찾을 수 없음: {REFERENCE_ZIP}")

    imported: List[Tuple[str, int]] = []
    seen: set = set()
    with zipfile.ZipFile(REFERENCE_ZIP) as zf:
        for name in zf.namelist():
            if _is_junk(name):
                continue
            basename = name.rsplit("/", 1)[-1]
            target: Optional[str] = REFERENCE_PICKS.get(basename)
            if target is None or target in seen:
                continue  # 미선별 파일이거나 이미 가져온 중복본
            seen.add(target)
            dest = DATABASE / "reference" / target
            size = _write_text(dest, zf.read(name), dry_run)
            imported.append((f"reference/{target}", size))

    missing = set(REFERENCE_PICKS.values()) - seen
    if missing:
        print(f"  ⚠ 참조 zip에서 못 찾은 파일: {sorted(missing)}")
    return sorted(imported)


def archive_legacy(dry_run: bool) -> List[str]:
    """1세대 CSV를 database/legacy/로 이동한다(삭제하지 않는다)."""
    moved: List[str] = []
    legacy_dir = DATABASE / "legacy"
    for filename in LEGACY_FILES:
        src = DATABASE / filename
        if not src.exists():
            continue
        if not dry_run:
            legacy_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(legacy_dir / filename))
        moved.append(filename)
    return moved


def main() -> None:
    parser = argparse.ArgumentParser(description="룰북 zip → database/ 이관")
    parser.add_argument("--dry-run", action="store_true", help="쓰기 없이 계획만 출력")
    args = parser.parse_args()

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}정본 룰북 이관: {CANONICAL_ZIP.name}")
    canonical = import_canonical(args.dry_run)
    for path, size in canonical:
        print(f"   {path:<62} {size:>8,} B")
    print(f"   → {len(canonical)}개 파일\n")

    print(f"{mode}참조 테이블 이관: {REFERENCE_ZIP.name}")
    reference = import_reference(args.dry_run)
    for path, size in reference:
        print(f"   {path:<62} {size:>8,} B")
    print(f"   → {len(reference)}개 파일\n")

    print(f"{mode}레거시 CSV 보관")
    for filename in archive_legacy(args.dry_run):
        print(f"   database/{filename} → database/legacy/{filename}")

    print(f"\n{mode}완료. 총 {len(canonical) + len(reference)}개 파일 이관.")


if __name__ == "__main__":
    main()
