"""확인시험 등급 계획 — 구조 경고와 예측 불확실성으로 등급을 **동적 승격**한다.

팀 리뷰 제안 ②를 구현한다. 지금까지 확인시험 등급은 "모든 고형 경구 API"에 대해 고정이었다.
그러면 에스터를 가진 API와 안 가진 API가 같은 시험 목록을 받는다 — 구조를 계산해 놓고
그 결과를 시험 선택에 쓰지 않는 셈이다.

승격 규칙은 데이터로 관리한다(`PROMOTIONS`). 규칙 하나는 이렇게 읽는다.

    "가수분해 가능 motif가 검출되면 → 스트레스 안정성 시험을 권장에서 필수로 올린다"

승격의 근거는 항상 함께 남긴다. 어떤 플래그가 어떤 시험을 왜 올렸는지 화면에서 되짚을 수
있어야 하고, 그래야 "구조 경고 → 시험 선택"이 설명 가능한 결정이 된다.

**투여경로 스코프** — 이 기본 목록은 팀 리뷰 제안 ④대로 고형 경구 제형 전용이다.
주사제·국소제에 그대로 쓰면 XRPD·DSC 같은 고체 특성화 비중이 과도해지므로,
`route`가 다르면 고체상 전용 시험을 목록에서 뺀다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 고형 경구 API 기본 시험 목록. tier는 구조·예측 신호에 따라 올라갈 수 있다.
BASELINE_TESTS: List[Dict[str, str]] = [
    {"test": "외관·성상 확인", "tier": "필수", "category": "일반"},
    {"test": "함량 (HPLC assay)", "tier": "필수", "category": "분석"},
    {"test": "관련물질 (impurity profile)", "tier": "필수", "category": "분석"},
    {"test": "XRPD 결정형 확인", "tier": "필수", "category": "고체상"},
    {"test": "DSC/TGA 열분석", "tier": "권장", "category": "고체상"},
    {"test": "입도분포 (PSD)", "tier": "권장", "category": "고체상"},
    {"test": "축약 수분 민감성 시험", "tier": "권장", "category": "안정성"},
    {"test": "소규모 stress stability", "tier": "권장", "category": "안정성"},
    {"test": "광안정성 (ICH Q1B)", "tier": "권장", "category": "안정성"},
    {"test": "부형제 배합적합성 시험", "tier": "권장", "category": "배합"},
    {"test": "DVS 흡습성 등온선", "tier": "선택", "category": "고체상"},
]

SOLID_ONLY = {"고체상"}   # 경구 고형 외 경로에서는 비중을 낮춘다

TIER_ORDER = {"선택": 0, "권장": 1, "필수": 2}


# 구조 플래그 → 승격할 시험. 근거(why)를 반드시 함께 적는다.
PROMOTIONS: List[Dict[str, Any]] = [
    {
        "when_flags": ["has_ester", "has_lactone", "has_lactam", "has_beta_lactam",
                       "has_carbamate", "has_anhydride", "has_carbonate", "has_thioester",
                       "has_imine", "has_hydrazone", "has_acetal", "has_ketal"],
        "test": "소규모 stress stability", "to": "필수",
        "why": "가수분해 가능 motif 검출 — 수분·pH·온도 조건에서 분해 경로를 먼저 확인해야 한다",
    },
    {
        "when_flags": ["has_anhydride", "has_peg_or_glycol_chain"],
        "test": "축약 수분 민감성 시험", "to": "필수",
        "why": "수분 반응성·수화 경향 motif 검출 — 수분 노출 영향을 직접 확인해야 한다",
    },
    {
        "when_flags": ["has_phenol", "has_catechol", "has_polyphenol", "has_thiol",
                       "has_thioether", "has_aldehyde", "has_hydroxylamine",
                       "has_hydrazine", "has_disulfide"],
        "test": "산화 stress 시험", "to": "필수",
        "why": "산화 가능 motif 검출 — peroxide·금속·산소 조건에서 분해 여부를 확인해야 한다",
        "add_if_missing": True, "category": "안정성",
    },
    {
        "when_flags": ["has_conjugated_diene", "has_polyene_chromophore",
                       "has_alpha_beta_unsaturated_carbonyl", "has_benzophenone_like",
                       "has_stilbene_like_motif", "has_nitroaromatic", "has_azo",
                       "has_n_oxide", "has_aryl_bromide", "has_aryl_iodide"],
        "test": "광안정성 (ICH Q1B)", "to": "필수",
        "why": "chromophore·광분해 우선순위 신호 검출 — 광 노출 영향을 확인해야 한다",
    },
    {
        "when_flags": ["has_primary_aliphatic_amine", "has_secondary_aliphatic_amine",
                       "has_aromatic_amine_aniline"],
        "test": "부형제 배합적합성 시험", "to": "필수",
        "why": "아민 검출 — 환원당 부형제와의 Maillard 반응 가능성을 확인해야 한다",
    },
    {
        "when_flags": ["has_n_nitrosamine", "has_nitrosatable_secondary_amine",
                       "has_cyclic_secondary_amine"],
        "test": "NDSRI 위험평가 (nitrite 노출·pH)", "to": "필수",
        "why": "nitrosatable amine 검출 — nitrite 노출·미세환경 pH와 결합 시 NDSRI 위험",
        "add_if_missing": True, "category": "규제",
    },
    {
        "when_flags": ["has_epoxide", "has_aziridine", "has_isocyanate",
                       "has_isothiocyanate", "has_sulfonate_ester", "has_quinone",
                       "has_peroxide"],
        "test": "ICH M7 변이원성 평가", "to": "필수",
        "why": "고반응성 electrophile 검출 — 상호보완적 두 (Q)SAR과 전문가 검토 필요",
        "add_if_missing": True, "category": "규제",
    },
    {
        "when_flags": ["has_catechol", "has_hydroxamate", "has_1_3_dicarbonyl",
                       "has_ortho_hydroxy_carboxylate", "has_fluoroquinolone_chelation_motif",
                       "has_phosphonic_acid"],
        "test": "다가금속 complexation·용출 시험", "to": "필수",
        "why": "킬레이션 motif 검출 — Ca/Mg/Al/Fe 존재 시 착물 형성·용출 저하 확인 필요",
        "add_if_missing": True, "category": "배합",
    },
    {
        "when_flags": ["has_quaternary_ammonium", "has_sulfonic_acid", "has_carboxylic_acid"],
        "test": "DVS 흡습성 등온선", "to": "권장",
        "why": "이온성·염 형성 site 검출 — 흡습 거동 확인이 유익하다",
    },
]


def plan_tests(
    flag_names: List[str],
    prediction_requests: Optional[List[Dict[str, str]]] = None,
    route: str = "oral_solid",
) -> Dict[str, Any]:
    """구조 플래그와 예측 불확실성으로 확인시험 등급을 계산한다.

    반환에는 최종 목록뿐 아니라 **무엇이 왜 승격됐는지**를 함께 담는다.
    """
    present = set(flag_names)
    tests: Dict[str, Dict[str, Any]] = {
        t["test"]: {**t, "promoted_from": None, "reasons": []} for t in BASELINE_TESTS
    }

    # 투여경로 스코프 — 고형 경구가 아니면 고체 특성화 비중을 낮춘다(팀 리뷰 제안 ④)
    scope_note = ""
    if route != "oral_solid":
        for name, item in tests.items():
            if item.get("category") in SOLID_ONLY and item["tier"] == "필수":
                item["tier"] = "권장"
                item["reasons"].append(f"{route} 경로 — 고체 특성화 비중 조정")
        scope_note = (f"투여경로가 '{route}'라 고형 경구 전용 시험(XRPD 등)의 등급을 낮췄습니다. "
                      "경로별 기본 목록은 별도로 정의해야 합니다.")

    promotions: List[Dict[str, Any]] = []
    for rule in PROMOTIONS:
        hit = sorted(present & set(rule["when_flags"]))
        if not hit:
            continue
        name = rule["test"]
        if name not in tests:
            if not rule.get("add_if_missing"):
                continue
            tests[name] = {"test": name, "tier": "선택",
                           "category": rule.get("category", "안정성"),
                           "promoted_from": None, "reasons": []}
        item = tests[name]
        before = item["tier"]
        if TIER_ORDER[rule["to"]] > TIER_ORDER[before]:
            item["tier"] = rule["to"]
            item["promoted_from"] = before
            promotions.append({
                "test": name, "from": before, "to": rule["to"],
                "trigger_flags": hit, "why": rule["why"], "trigger": "structural_alert",
            })
        item["reasons"].append(f"{rule['why']} (검출: {', '.join(hit)})")

    # 예측 불확실성이 요청한 시험을 합류시킨다 — ②의 출력이 ⑤로 이어지는 지점
    for request in prediction_requests or []:
        name = request["test"]
        item = tests.setdefault(name, {"test": name, "tier": "선택", "category": "물성",
                                       "promoted_from": None, "reasons": []})
        before = item["tier"]
        if TIER_ORDER.get(request.get("tier", "권장"), 1) > TIER_ORDER[before]:
            item["tier"] = request["tier"]
            item["promoted_from"] = before
            promotions.append({
                "test": name, "from": before, "to": request["tier"],
                "trigger_flags": [], "why": request["reason"],
                "trigger": request.get("trigger", "prediction_uncertainty"),
            })
        item["reasons"].append(request["reason"])

    ordered = sorted(tests.values(),
                     key=lambda t: (-TIER_ORDER[t["tier"]], t.get("category", ""), t["test"]))
    return {
        "route": route,
        "scope_note": scope_note,
        "tests": ordered,
        "promotions": promotions,
        "required_count": sum(1 for t in ordered if t["tier"] == "필수"),
        "baseline_required": sum(1 for t in BASELINE_TESTS if t["tier"] == "필수"),
    }
