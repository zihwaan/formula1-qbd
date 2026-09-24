"""v6.1 룰 문맥 계약. manifest(#1)에 그대로 기록되고 검증기가 사용한다."""

S, N, B, T = "str", "num", "bool", "time"
L = lambda t: f"list[{t}]"

ENTITIES = {
 "bound": {"value": N, "source_ref": S, "evidence_status": S, "amount_per_unit_mg": N},
 "range": {"low": N, "high": N},
 "ingredient": {"name": S, "pct_w_w": N, "unit": S, "grade": S, "is_critical": B},
 "fixed_parameter": {"name": S, "value": N, "unit": S, "status": S},
 "verdict": {"status": S, "resolved": B},
 "handoff": {"fingerprint": S, "candidate_version": N, "qtpp_snapshot_id": S, "ingredients": L("ingredient"),
             "process_steps": L(S), "equipment_id": S, "batch_scale": S, "fixed_parameters": L("fixed_parameter"),
             "rule_verdicts": L("verdict"), "api_amount_fixed": B, "total_weight_fixed": B},
 "upstream": {"candidate_version": N},
 "cqa": {"id": S, "template_id": S, "category": S, "analysis_role": S, "requirement": S,
         "acceptance_operator": S, "lower": N, "upper": N, "target": N, "target_tolerance": N,
         "lower_inclusive": B, "upper_inclusive": B, "unit": S, "test_method_id": S, "test_method_version": S,
         "criterion_source": S, "criterion_type": S, "summary_definition": S, "practical_effect_threshold": N,
         "replicate_policy": S, "rationale_refs": S, "has_registered_method": B, "max_observed": N},
 "change": {"op": S, "field": S, "from_value": S, "to_value": S, "from_role": S, "to_role": S,
            "target": S, "source_status": S, "evidence_ref": S, "data_ref": S, "preserves_hierarchy": B,
            "alternative_control": S},
 "fmea_row": {"severity": N, "occurrence": N, "occurrence_evidence": S, "evidence_status": S,
              "alternative_control": S, "approval_ref": S, "disposition": S, "controllable": B,
              "measurable": B, "range_definable": B, "prohibited": B, "function_locked": B,
              "kind": S, "unit": S, "fixed_value_status": S, "low": N, "high": N},
 "factor": {"id": S, "kind": S, "unit": S, "low": "bound", "center": "bound", "high": "bound",
            "expected_range_contrast": N, "manufacturability_evidence": S, "at_extreme_of_master_range": B,
            "levels": L(S), "redefinition_requested": B, "disposition": S},
 "excipient_range": {"typical_min_pct": N, "typical_max_pct": N},
 "iid_reference": {"max_potency_mg": N},
 "composition_group": {"balance_component": S},
 "method": {"repeatability_sd": N, "variance_component_type": S},
 "design_point": {"in_bounds": B, "in_forbidden_combination": B, "balance_component_value": N, "in_domain": B},
 "plan": {"design_type": S, "stage": S, "source": S, "n_runs": N, "n_center_points": N, "n_unique_runs": N,
          "n_terms": N, "resolution": N, "random_seed": N, "generator": S, "block_definition": S,
          "has_mixture": B, "mixture_sum_ok": B, "expected_days": N, "material_lots": N, "equipment_count": N,
          "randomization": S, "randomization_reason": S, "augments_previous_stage": B,
          "new_block_center_points": N, "locked_at": T, "locked_hash": S, "point_roles": L(S),
          "n_factors": N, "n_continuous": N, "n_categorical": N, "has_hard_to_change": B,
          "has_forbidden_combinations": B, "design_points": L("design_point"), "interactions_plausible": B,
          "prior_evidence_approved": B, "extreme_corner_risk": B, "axial_must_stay_in_range": B,
          "axial_points_safe": B, "screening_core_reusable": B},
 "selector": {"recommended_design_type": S},
 "validator": {"status": S},
 "run": {"batch_id": S, "batch_mass_g": N, "ingredient_mg_total": N, "target_unit_mg": N,
         "balance_component_mg": N, "settings_complete": B, "settings_on_resolution": B,
         "fixed_conditions_match": B, "influence_flag": B, "cooks_d": N, "leverage": N},
 "equipment": {"working_capacity_min_g": N, "working_capacity_max_g": N},
 "result": {"id": S, "batch_id": S, "parent_blend_id": S, "test_method_version": S, "response_id": S,
            "unit": S, "target_unit": S, "n_individual_values": N, "evidence_status": S,
            "replicate_independence": S, "deviation": S, "deviation_resolved": B,
            "human_verification_status": S, "settings_within_tolerance": B, "counted_as_independent_run": B,
            "submitted_at": T},
 "effect": {"actual": N, "ci_lower": N, "ci_upper": N, "aliased": B, "alias_resolved": B},
 "curvature_test": {"significant": B},
 "center_points": {"pure_error_sd": N},
 "decision": {"classification": S, "severity": N},
 "model": {"validation_status": S, "df_resid": N, "hierarchical": B, "all_terms_estimable": B,
           "lof_computable": B, "lof_p": N, "pure_error_df": N, "adj_r2": N, "pred_r2": N, "n": N, "p": N,
           "fit_method": S, "scope_hash": S, "inputs": L("result"), "input_batch_ids": L(S),
           "residual_pattern": B, "heteroscedastic": B, "runs": L("run"), "local_prediction_se_high": B,
           "invalid_cause": S},
 "region_scope": {"fixed_conditions_recorded": B, "critical_unmanaged_count": N, "limitations_recorded": B},
 "region": {"status": S, "method": S, "feasible_fraction": N, "scope": "region_scope",
            "joint_independence_assumed": B, "setpoint_edge_distance": N, "has_operating_range": B,
            "operating_range_is_subset": B, "criteria_changed_after_results": B,
            "all_points_in_domain": B, "domain_policy": S, "scope_hash": S},
 "point": {"role": S, "spec_pass_all_applicable": B, "within_family_pi_all_doe": B, "expected_outcome": S,
           "batch_id": S, "parent_blend_id": S, "results_confirmed": B, "coverage_complete": B,
           "evidence_status": S, "expected_fail_cqa": S, "expected_fail_probability": N},
 "verification": {"first_result_submitted_at": T, "scope_hash": S, "results_public_before_lock": B,
                  "pi_policy": S},
 "rule": {"gate_effect": S},
 "result_event": {"reason_code": S},
 "study": {"scope_hash": S},
}

# 루트 이름 → 타입
ROOTS = {
 "handoff": "handoff", "upstream": "upstream", "study": "study", "cqa": "cqa", "cqas": L("cqa"),
 "cqa_candidates": L("cqa"), "change": "change", "row": "fmea_row", "item": "fmea_row",
 "factor": "factor", "factors": L("factor"), "master": "excipient_range", "iid": "iid_reference",
 "composition_group": "composition_group", "method": "method", "plan": "plan", "selector": "selector",
 "validator": "validator", "run": "run", "equipment": "equipment", "result": "result",
 "results": L("result"), "effect": "effect", "curvature_test": "curvature_test",
 "center_points": "center_points", "decision": "decision", "model": "model", "models": L("model"),
 "region": "region", "point": "point", "points": L("point"), "required_points": L("point"),
 "promotion_basis_points": L("point"), "verification": "verification", "rule": "rule",
 "event": "result_event", "fit_batch_ids": L(S), "fit_blend_ids": L(S), "range_finding_result_ids": L(S),
 "fit_result_ids": L(S),
}

# 함수 registry: 이름 → (인자 수, 반환 타입, 설명). -1 = 가변, "gen" = generator 1개
FUNCTIONS = {
 "len": (1, N, "컬렉션 길이"), "abs": (1, N, "절댓값"), "min": (-1, N, "최솟값"), "max": (-1, N, "최댓값"),
 "sum": ("gen", N, "합계 (generator)"),
 "any": ("gen", B, "하나라도 참 (generator). 빈 컬렉션 → False"),
 "all": ("gen", B, "모두 참 (generator). 빈 컬렉션 → True — 승격 판정에는 nonempty_all 사용"),
 "nonempty_all": ("gen", B, "비어 있지 않고 모두 참. 빈 컬렉션 → False"),
 "count": ("gen", N, "참인 원소 수 (generator)"),
 "distinct_count": ("gen", N, "서로 다른 값 수 (generator)"),
 "set_intersects": (2, B, "두 목록의 교집합 존재"),
 "matrix_rank": (1, N, "설계 모형행렬 rank (plan). 수치 tolerance는 엔진 설정"),
 "evidence_permits": (2, B, "evidence_governance_rules 표 조회: (evidence_status, use) 허용 여부"),
 "recompute_fingerprint": (1, S, "Handoff fingerprint 재계산"),
 "equipment_supports": (1, B, "설비가 요인을 실행 가능한가"),
 "redundant_with_any": (2, B, "요인이 다른 요인과 중복인가"),
 "protocol_available": (1, B, "범주 수준 실행 방법 존재"),
 "excipient_range_exists": (1, B, "부형제 통상 사용범위 master 행 존재"),
 "iid_reference_exists": (1, B, "외부 FDA IID snapshot 조회 가능 (의존성)"),
 "intersection_empty": (1, B, "요인 실행 가능 범위 교집합이 비었는가"),
 "block_confounded": (1, B, "블록이 의도 모형 항과 교락되는가"),
 "backend_supports": (1, B, "manifest backend_capabilities에 설계가 지원되는가"),
 "convertible": (2, B, "단위 변환 가능"),
}

ALLOWED_AST = {"Expression","BoolOp","And","Or","UnaryOp","Not","USub","Compare","Eq","NotEq","Lt","LtE",
 "Gt","GtE","In","NotIn","Is","IsNot","Name","Load","Attribute","Constant","Tuple","Call","BinOp",
 "Add","Sub","Mult","Div","GeneratorExp","comprehension","Store"}

BACKEND_CAPABILITIES = {
 "FRACTIONAL_FACTORIAL": {"supported": True, "factor_types": "continuous or 2-level categorical", "min_factors": 3, "max_factors": 4},
 "PLACKETT_BURMAN": {"supported": True, "factor_types": "continuous or 2-level categorical", "min_factors": 3, "max_factors": 4, "note": "Res III 경고"},
 "BOX_BEHNKEN": {"supported": True, "factor_types": "continuous only", "min_factors": 3, "max_factors": 3},
 "CCD": {"supported": True, "factor_types": "continuous only", "min_factors": 2, "max_factors": 3},
 "FACE_CENTERED_CCD": {"supported": True, "factor_types": "continuous only", "min_factors": 2, "max_factors": 3},
 "DSD": {"supported": False, "note": "MVP 백엔드 미지원"},
 "D_OPTIMAL": {"supported": False, "note": "MVP 백엔드 미지원"},
 "MIXTURE": {"supported": False, "note": "MVP 백엔드 미지원"},
 "MIXTURE_PROCESS": {"supported": False, "note": "MVP 백엔드 미지원"},
 "SPLIT_PLOT": {"supported": False, "note": "MVP 백엔드 미지원"},
}

STATES = """HANDOFF_CREATED ENTRY_READINESS WAITING_REQUIRED_DATA INELIGIBLE CQA_DRAFTING
WAITING_CQA_APPROVAL FMEA_DRAFTING WAITING_FMEA_APPROVAL FACTOR_READINESS WAITING_FACTOR_DATA
RANGE_FINDING_RUNS STRATEGY_REVIEW WAITING_FACTOR_APPROVAL DESIGN_SELECTION SCREENING_PLANNING
RSM_PLANNING DESIGN_REPLAN WAITING_SCREENING_APPROVAL SCREENING_EXECUTION SCREENING_ANALYSIS
SCREENING_AUGMENTATION DIAGNOSING WAITING_RSM_APPROVAL RSM_EXECUTION MODEL_VALIDATION
WAITING_MODEL_APPROVAL RSM_AUGMENTATION REGION_COMPUTATION WAITING_REGION_APPROVAL
VERIFICATION_PLANNING WAITING_VERIFICATION_PLAN_APPROVAL VERIFICATION_EXECUTION VERIFICATION_GATE
WAITING_FINAL_APPROVAL COMPLETED WAITING_DISCRIMINATING_TESTS WAITING_HUMAN_TRIAGE REFLECTING
WAITING_DIRECTIVE_APPROVAL CLOSED_SUPERSEDED WAITING_AUDIT_REVIEW
RUN_SHEET_COMPILE WAITING_RUN_DATA WAITING_BATCH_RESULTS WAITING_RESULT_CONFIRMATION
RESULT_QUALITY_GATE""".split()
