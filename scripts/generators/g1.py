from common import *

# ---------------- #2 evidence governance (A9) ----------------
write_table("governance", "evidence_governance_rules.csv",
 ["evidence_status","origin","description_ko","MODEL_FIT","PURE_ERROR","VERIFICATION","RANGE_BASIS","display_flag","upgrade_path","source_ids"],
 [
  ["MEASURED_CONFIRMED","OWN_LAB","자체 실험실 실측, 연구자 확인 완료","ALLOW","ALLOW","ALLOW","ALLOW","","—","SPEC:v6.1§8.A.2"],
  ["MEASURED_UNCONFIRMED","OWN_LAB","자체 실측, 확인 전","DENY","DENY","DENY","DENY","미확인","연구자 확인 → MEASURED_CONFIRMED (자체 실측에만 적용)","SPEC:v6.1§8.A.2"],
  ["LITERATURE_DIRECT","LITERATURE","문헌 표 수치. 사람이 확인해도 origin은 LITERATURE로 유지","ALLOW","ALLOW_IF_INDEPENDENT_REPLICATES","DENY","ALLOW","문헌","원자료 입수 시 새 evidence record 연결 (기존 기록 덮어쓰기 금지)","SPEC:v6.1§8.A.2"],
  ["LITERATURE_DIGITIZED","LITERATURE","문헌 그림 디지타이징 값","ALLOW_FLAGGED","DENY","DENY","ALLOW","디지타이징","원자료 입수 시 새 evidence record 연결","SPEC:v6.1§8.A.2"],
  ["MODEL_PREDICTED","DERIVED","모델 예측값","DENY","DENY","DENY","REFERENCE_ONLY","예측","실측으로만 대체","SPEC:v6.1§8.A.2"],
  ["EXPERT_ASSUMPTION","HUMAN","연구자 가정","DENY","DENY","DENY","ALLOW_FLAGGED","가정","근거 문헌 또는 실측 연결","SPEC:v6.1§8.A.2"],
  ["LLM_HYPOTHESIS","LLM","LLM 제안 가설","DENY","DENY","DENY","DENY","LLM 가설","데이터 일치 시 DATA_CONSISTENT 표시 (등급 유지)","SPEC:v6.1§3.3"],
  ["SYNTHETIC_DEMO","SYNTHETIC","시연용 합성값 (sandbox 전용)","DEMO_ONLY","DEMO_ONLY","DENY","DENY","과학적 결론 아님","—","SPEC:v6.1§8.A.2"],
  ["UNKNOWN","NONE","값 또는 근거 없음","DENY","DENY","DENY","DENY","미상","자료 제출","SPEC:v6.1§8.A.2"],
 ], POL)

A = "approval_authority_rules"
rows = [
 R("AA001",10,"cqa","WAITING_CQA_APPROVAL","change.from_role == 'DOE_RESPONSE' and change.to_role == 'MONITOR_ONLY'","change","NA","WARNING","OVR_CQA_ROLE_DOWNGRADE","","DoE 반응을 모니터링으로 전환합니다. 요인 판정에 factor_effect_not_evaluated로 기록됩니다.","","REASON_ONLY","researcher","MONITOR_ONLY는 규격은 확인하지만 요인 효과는 평가하지 않음","SPEC:v6.1§6.D2",POL),
 R("AA002",10,"cqa","WAITING_CQA_APPROVAL","change.to_role == 'NOT_APPLICABLE' and cqa.requirement == 'MANDATORY'","change;cqa","REQUEST_DATA","REQUEST_DATA","OVR_CQA_MANDATORY_NA","","필수 CQA를 해당없음으로 바꾸려면 근거가 필요합니다.","","ALTERNATIVE_EVIDENCE","researcher","","SPEC:v6.1§6.D2",POL),
 R("AA003",1,"cqa","WAITING_CQA_APPROVAL","count(c for c in cqas if c.category == 'physical_integrity' and c.analysis_role != 'NOT_APPLICABLE') == 0","cqas","BLOCK_STAGE","BLOCK_STAGE","CQA_PHYSICAL_INTEGRITY_MISSING","","물리적 완전성 CQA를 모두 제외할 수 없습니다.","","NONE","","","SPEC:v6.1§6.D2",POL),
 R("AA004",1,"fmea","WAITING_FMEA_APPROVAL","change.op == 'DELETE' and row.severity >= const.fmea_high_severity and (change.alternative_control is None or row.approval_ref is None)","change;row","BLOCK_STAGE","BLOCK_STAGE","FMEA_HIGH_SEVERITY_DELETE","","고심각도 항목은 대체 관리수단과 승인 근거 없이 삭제할 수 없습니다.","","NONE","","고심각도 보존 invariant","SPEC:v6.1§6.D3;SRC_ICH_Q9",POL),
 R("AA005",1,"any","ANY","change.field == 'evidence_status' and change.data_ref is None","change","BLOCK_STAGE","BLOCK_STAGE","EVIDENCE_CHANGE_WITHOUT_DATA","","근거 등급은 데이터 연결 없이 바꿀 수 없습니다.","","NONE","","","SPEC:v6.1§0.12",POL),
 R("AA006",20,"fmea","WAITING_FMEA_APPROVAL","change.field == 'occurrence' and change.to_value is not None and change.evidence_ref is None","change","NA","WARNING","FMEA_O_WITHOUT_EVIDENCE","","근거 없는 Occurrence 값은 EXPERT_ASSUMPTION으로 표시됩니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D3",POL),
 R("AA007",20,"design","WAITING_SCREENING_APPROVAL|WAITING_RSM_APPROVAL","plan.design_type != selector.recommended_design_type","plan;selector","NA","WARNING","OVR_DESIGN_DIFFERS","","권고와 다른 설계입니다. 사유를 기록하세요.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D5",POL),
 R("AA008",1,"design","SCREENING_PLANNING|RSM_PLANNING","plan.source == 'RESEARCHER_PROVIDED' and validator.status != 'DESIGN_VALID'","plan;validator","BLOCK_STAGE","BLOCK_STAGE","IMPORT_DESIGN_INVALID","","가져온 설계가 검증을 통과하지 못했습니다.","","NONE","","","SPEC:v6.1§3.5",POL),
 R("AA010",1,"model","WAITING_MODEL_APPROVAL","change.op == 'REDUCE_MODEL' and not change.preserves_hierarchy","change","BLOCK_STAGE","BLOCK_STAGE","MODEL_HIERARCHY_VIOLATION","","계층성을 깨는 축소는 허용되지 않습니다.","","NONE","","","SPEC:v6.1§14.10;SRC_MONTGOMERY_DAE",POL),
 R("AA011",20,"model","WAITING_MODEL_APPROVAL","change.op == 'EXCLUDE_RUN' and run.influence_flag","change;run","NA","WARNING","OVR_EXCLUDE_INFLUENTIAL_RUN","","영향점 제외에는 사유와 승인이 필요하며 원자료는 보존됩니다.","","REASON_AND_APPROVER","study_lead","자동 삭제 금지","SPEC:v6.1§6.D8",POL),
 R("AA012",1,"any","ANY","change.op == 'OVERWRITE' and change.source_status in ('APPROVED','LOCKED')","change","BLOCK_STAGE","BLOCK_STAGE","APPROVED_ARTIFACT_OVERWRITE","","승인·잠금된 artifact는 수정할 수 없습니다. 새 버전을 만드세요.","원본 상태 기준","NONE","","","SPEC:v6.1§14.2",POL),
 R("AA014",1,"verification","WAITING_VERIFICATION_PLAN_APPROVAL|VERIFICATION_EXECUTION|VERIFICATION_GATE","change.target == 'verification_plan' and plan.locked_at is not None","plan;change","BLOCK_STAGE","BLOCK_STAGE","VERIFICATION_PLAN_LOCKED","","잠긴 확인계획은 수정할 수 없습니다.","","NONE","","","SPEC:v6.1§6.D10",POL),
 R("AA015",1,"region","WAITING_FINAL_APPROVAL","region.status == 'PROVISIONAL' and change.to_value == 'VERIFIED' and not nonempty_all(p.spec_pass_all_applicable and p.within_family_pi_all_doe for p in required_points)","region;change;required_points","BLOCK_STAGE","BLOCK_STAGE","PROMOTION_WITHOUT_VERIFICATION","","확인배치 판정 없이 VERIFIED로 승격할 수 없습니다.","","NONE","","","SPEC:v6.1§14.14",POL),
 R("AA016",20,"factor","WAITING_FACTOR_APPROVAL","factor.low.evidence_status == 'EXPERT_ASSUMPTION' or factor.high.evidence_status == 'EXPERT_ASSUMPTION'","factor","NA","WARNING","FACTOR_BOUND_ASSUMPTION","","경계값 일부가 연구자 가정입니다.","","REASON_ONLY","researcher","","SPEC:v6.1§3.4",POL),
 R("AA017",1,"any","ANY","rule.gate_effect in ('BLOCK_STAGE','INVALIDATE') and change.op == 'OVERRIDE'","rule;change","BLOCK_STAGE","BLOCK_STAGE","OVERRIDE_NOT_PERMITTED","","차단·무효화 규칙은 override할 수 없습니다.","","NONE","","","SPEC:v6.1§2.2",POL),
]
write_rules("governance","approval_authority_rules.csv",A,rows)

P="provenance_versioning_rules"
rows=[
 R("PV001",1,"handoff","ANY","handoff.fingerprint != recompute_fingerprint(handoff)","handoff","BLOCK_STAGE","BLOCK_STAGE","LINEAGE_MISMATCH","WAITING_AUDIT_REVIEW","Handoff fingerprint가 일치하지 않습니다.","","NONE","","","SPEC:v6.1§5.3",POL),
 R("PV002",20,"handoff","ANY","upstream.candidate_version > handoff.candidate_version","upstream;handoff","NA","WARNING","CANDIDATE_VERSION_AVAILABLE","","상류 후보의 새 버전이 있습니다. 현재 study는 계속 유효합니다.","알림 이벤트만 발행","REASON_ONLY","researcher","","SPEC:v6.1§5.4",POL),
 R("PV003",1,"results","SCREENING_ANALYSIS|MODEL_VALIDATION","distinct_count(r.test_method_version for r in results) > 1","results","BLOCK_STAGE","BLOCK_STAGE","METHOD_VERSION_MIXED","","같은 반응에 서로 다른 시험법 버전이 섞여 있습니다.","반응별로 평가","NONE","","","SPEC:v6.1§8.A.4",POL),
 R("PV004",1,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.equipment_count > 1 and plan.block_definition is None","plan","BLOCK_STAGE","BLOCK_STAGE","EQUIPMENT_SCOPE_MIXED","","블록 정의 없이 설비가 섞여 있습니다.","","NONE","","","SPEC:v6.1§8.C.14",POL),
 R("PV005",1,"model","VERIFICATION_GATE","set_intersects(model.input_batch_ids, [p.batch_id for p in points])","model;points","BLOCK_STAGE","BLOCK_STAGE","VERIFICATION_REUSED_IN_FIT","","확인배치를 적합에 사용했습니다. 새 확인계획이 필요합니다.","","NONE","","","SPEC:v6.1§14.16",POL),
 R("PV007",20,"any","ANY","change.field in ('composition','process_route','fixed_parameter','factor_range','model_terms','design_matrix','method_version','cqa_criterion','model_dataset','uncertainty_policy','domain_policy')","change","NA","WARNING","NEW_VERSION_REQUIRED","","변경 사항은 새 버전으로 저장됩니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.A.4",POL),
 R("PV008",1,"results","MODEL_VALIDATION","set_intersects(fit_result_ids, range_finding_result_ids)","fit_result_ids;range_finding_result_ids","BLOCK_STAGE","BLOCK_STAGE","RANGE_FINDING_IN_FIT","","범위 확인 run은 적합에 사용할 수 없습니다.","","NONE","","","SPEC:v6.1§3.4",POL),
]
write_rules("governance","provenance_versioning_rules.csv",P,rows)

RD="development_readiness_rules"
rows=[
 R("RD001",1,"handoff","ENTRY_READINESS","abs(sum(i.pct_w_w for i in handoff.ingredients) - 100) > const.composition_sum_tolerance_pct","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","조성 합계가 100%가 아닙니다.","","NONE","","","SPEC:v6.1§6.D1",POL),
 R("RD002",1,"handoff","ENTRY_READINESS","any(i.unit is None for i in handoff.ingredients)","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","단위가 없는 성분이 있습니다.","","NONE","","","SPEC:v6.1§6.D1",POL),
 R("RD003",2,"handoff","ENTRY_READINESS","any(i.grade is None and i.is_critical for i in handoff.ingredients)","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","중요 원료의 등급이 정해지지 않았습니다.","","ALTERNATIVE_EVIDENCE","researcher","","SPEC:v6.1§6.D1",POL),
 R("RD004",1,"handoff","ENTRY_READINESS","len(handoff.process_steps) == 0","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","구조화된 공정 단계가 없습니다.","","NONE","","","SPEC:v6.1§6.D1",POL),
 R("RD005",1,"handoff","ENTRY_READINESS","handoff.equipment_id is None","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","설비가 지정되지 않았습니다.","","NONE","","","SPEC:v6.1§6.D1",POL),
 R("RD006",1,"handoff","ENTRY_READINESS","handoff.batch_scale is None","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","배치 규모가 없습니다.","","ALTERNATIVE_EVIDENCE","researcher","","SPEC:v6.1§6.D1",POL),
 R("RD007",5,"handoff","ENTRY_READINESS","any(p.value is None and p.status != 'UNKNOWN' for p in handoff.fixed_parameters)","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","고정 공정변수 값을 입력하거나 UNKNOWN으로 기록하세요.","UNKNOWN 선택 시 scope 제한 기록","ALTERNATIVE_EVIDENCE","researcher","","SPEC:v6.1§6.D1",POL),
 R("RD008",2,"handoff","ENTRY_READINESS","any(c.requirement == 'MANDATORY' and not c.has_registered_method for c in cqa_candidates)","cqa_candidates","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","필수 CQA의 시험법이 등록되어 있지 않습니다.","","NONE","","","SPEC:v6.1§6.D1",POL),
 R("RD009",1,"handoff","ENTRY_READINESS","any(v.status == 'hard_fail' and not v.resolved for v in handoff.rule_verdicts)","handoff","BLOCK_STAGE","BLOCK_STAGE","UNRESOLVED_HARD_FAIL","INELIGIBLE","상류 Hard Fail이 해소되지 않았습니다.","","NONE","","","SPEC:v6.1§6.D1",POL),
 R("RD010",1,"handoff","ENTRY_READINESS","handoff.qtpp_snapshot_id is None","handoff","REQUEST_DATA","REQUEST_DATA","MISSING_INPUT","WAITING_REQUIRED_DATA","QTPP 스냅샷이 없습니다.","","NONE","","","SPEC:v6.1§6.D0",POL),
]
write_rules("readiness","development_readiness_rules.csv",RD,rows)

write_table("qbd_risk","qtpp_cqa_mapping_rules.csv",
 ["mapping_id","dosage_form","inherits_from","release_type","condition_expression","cqa_template_id",
  "requirement","default_role","merge_priority","rationale","source_ids"],
 [
  ["QM001","tablet","","immediate_release","True","CQA_ASSAY","MANDATORY","MONITOR_ONLY","10","함량","SRC_ICH_Q6A"],
  ["QM002","tablet","","immediate_release","True","CQA_CU_AV","MANDATORY","MONITOR_ONLY","10","함량균일성 기본","SRC_USP_905"],
  ["QM003","tablet","","immediate_release","api.dose_mg < 25 or api.pct_w_w < 25","CQA_CU_AV","MANDATORY","DOE_RESPONSE","20","저용량: 같은 CQA에서 merge_priority가 높은 행이 QM002를 대체","SRC_USP_905"],
  ["QM004","tablet","","immediate_release","True","CQA_DISSOLUTION","MANDATORY","DOE_RESPONSE","10","방출 성능","SRC_USP_711;SRC_ICH_Q6A"],
  ["QM005","tablet","","immediate_release","True","CQA_DISINTEGRATION","CONDITIONAL","MONITOR_ONLY","10","붕해","SRC_USP_701"],
  ["QM006","tablet","","*","coating == 'none'","CQA_FRIABILITY","MANDATORY","DOE_RESPONSE","10","비코팅정 물리적 강도","SRC_USP_1216"],
  ["QM007","tablet","","*","True","CQA_BREAKING_FORCE","MANDATORY","MONITOR_ONLY","10","파괴강도","SRC_USP_1217"],
  ["QM008","tablet","","*","True","CQA_IMPURITIES","MANDATORY","MONITOR_ONLY","10","유연물질","SRC_ICH_Q3B"],
  ["QM009","tablet","","*","'hygroscopic' in api.flags","CQA_WATER","CONDITIONAL","MONITOR_ONLY","10","흡습성","SRC_ICH_Q6A"],
  ["QM010","tablet","","*","True","CQA_TABLET_WEIGHT_RSD","MANDATORY","MONITOR_ONLY","10","정제 중량편차(IPC). <905> 판정 절차와 별개","SRC_USP_905"],
  ["QM011","dispersible_tablet","tablet","immediate_release","True","CQA_DISPERSIBILITY","MANDATORY","DOE_RESPONSE","10","분산정은 tablet mandatory CQA를 상속하고 분산 CQA 추가","SRC_PHEUR_TABLETS"],
  ["QM012","dispersible_tablet","tablet","immediate_release","True","CQA_FINENESS_OF_DISPERSION","MANDATORY","MONITOR_ONLY","10","분산 미세도","SRC_PHEUR_TABLETS"],
  ["QM013","*","","immediate_release","api.bcs_class in ('II','IV')","CQA_DISSOLUTION","MANDATORY","DOE_RESPONSE","20","용해도 제한 약물","SRC_ICH_M9"],
 ], COMP)

C="cqa_response_definition_rules"
rows=[
 R("CR001",1,"cqa","WAITING_CQA_APPROVAL","cqa.analysis_role in ('DOE_RESPONSE','MONITOR_ONLY') and cqa.acceptance_operator is None","cqa","BLOCK_STAGE","BLOCK_STAGE","CQA_NO_ACCEPTANCE_OPERATOR","","판정 방식(acceptance_operator: LE, GE, BETWEEN, TARGET_TOL)이 필요합니다.","MONITOR_ONLY도 배치별 판정 기준 필요","NONE","","A8: target만으로는 판정 불가","SPEC:v6.1§6.D2",POL),
 R("CR002",1,"cqa","WAITING_CQA_APPROVAL","(cqa.acceptance_operator == 'LE' and cqa.upper is None) or (cqa.acceptance_operator == 'GE' and cqa.lower is None) or (cqa.acceptance_operator == 'BETWEEN' and (cqa.lower is None or cqa.upper is None)) or (cqa.acceptance_operator == 'TARGET_TOL' and (cqa.target is None or cqa.target_tolerance is None))","cqa","BLOCK_STAGE","BLOCK_STAGE","CQA_BOUNDS_INCOMPLETE","","판정 방식에 필요한 한계값이 없습니다.","","NONE","","","SPEC:v6.1§6.D2",POL),
 R("CR003",1,"cqa","WAITING_CQA_APPROVAL","cqa.lower is not None and cqa.upper is not None and cqa.lower > cqa.upper","cqa","BLOCK_STAGE","BLOCK_STAGE","CQA_BOUNDS_INVERTED","","하한이 상한보다 큽니다.","NaN/Inf는 입력 단계에서 거부","NONE","","","SPEC:v6.1§6.D2",POL),
 R("CR004",1,"cqa","WAITING_CQA_APPROVAL","cqa.analysis_role == 'DOE_RESPONSE' and cqa.criterion_type == 'RELATIVE_ONLY'","cqa","BLOCK_STAGE","BLOCK_STAGE","CQA_RELATIVE_CRITERION_ONLY","","상대 기준(예: 최선 대비 f2)은 보조 지표로만 쓸 수 있습니다.","","NONE","","TCB 케이스","SPEC:v6.1§6.D2",POL),
 R("CR005",1,"cqa","WAITING_CQA_APPROVAL","cqa.analysis_role == 'DOE_RESPONSE' and (cqa.test_method_id is None or cqa.unit is None)","cqa","BLOCK_STAGE","BLOCK_STAGE","CQA_NO_METHOD","","시험법과 단위가 없는 CQA는 DoE 반응이 될 수 없습니다.","","NONE","","","SPEC:v6.1§6.D2",POL),
 R("CR006",1,"cqa","WAITING_CQA_APPROVAL","cqa.template_id == 'CQA_DISSOLUTION' and cqa.analysis_role == 'DOE_RESPONSE' and cqa.summary_definition in (None,'PER_TIMEPOINT')","cqa","BLOCK_STAGE","BLOCK_STAGE","DISSOLUTION_SUMMARY_UNDEFINED","","용출은 단일 요약값(특정 시점 %, DE, profile model 중 하나)을 정해야 합니다.","","NONE","","","SPEC:v6.1§6.D2",POL),
 R("CR007",20,"cqa","WAITING_CQA_APPROVAL","cqa.analysis_role == 'DOE_RESPONSE' and cqa.practical_effect_threshold is None","cqa","NA","WARNING","CQA_NO_PRACTICAL_THRESHOLD","","실질 효과 기준(delta)이 없으면 screening 판정이 INCONCLUSIVE가 됩니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D7",POL),
 R("CR008",20,"cqa","WAITING_CQA_APPROVAL","cqa.analysis_role == 'DOE_RESPONSE' and cqa.replicate_policy is None","cqa","REQUEST_DATA","REQUEST_DATA","CQA_NO_REPLICATE_POLICY","","검체수와 요약 방법을 정하세요.","","ALTERNATIVE_EVIDENCE","researcher","","SPEC:v6.1§8.B.7",POL),
 R("CR009",50,"cqa","MODEL_VALIDATION","cqa.analysis_role == 'DOE_RESPONSE' and cqa.acceptance_operator == 'LE' and cqa.max_observed <= const.non_binding_ratio * cqa.upper","cqa","NA","WARNING","CQA_NON_BINDING","","모든 결과가 규격에서 멀리 떨어져 영역 경계에 관여하지 않습니다.","binding_status=NON_BINDING (역할 유지)","REASON_ONLY","researcher","","SPEC:v6.1§3.2",POL),
 R("CR010",20,"cqa","WAITING_CQA_APPROVAL","cqa.criterion_source == 'PROJECT_TARGET' and cqa.rationale_refs is None","cqa","NA","WARNING","CQA_TARGET_UNJUSTIFIED","","프로젝트 목표값의 근거를 기록하세요.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D2",POL),
]
write_rules("qbd_risk","cqa_response_definition_rules.csv",C,rows)

write_table("qbd_risk","fmea_failure_mode_rules.csv",
 ["seed_id","process_route","risk_category","unit_op_code","cause","failure_mode","local_effect","cqa_effect",
  "candidate_factor","factor_kind","default_disposition","detection_method_ids","evidence_type","source_ids"],
 [
  ["FM001","direct_compression","PROCESS","UO_DC_01","칭량 오차","조성 편차","블렌드 조성 이탈","CQA_ASSAY;CQA_CU_AV","—","—","CONTROL_SOP","TM_ASSAY_HPLC","general_gmp","SRC_ICH_Q9"],
  ["FM002","direct_compression","PROCESS","UO_DC_02","응집 API 미분쇄","응집체 잔존","국소 과량","CQA_CU_AV;CQA_DISSOLUTION","sieve_mesh","CPP","CONTROL_SOP","TM_CU_USP905","textbook","SRC_AULTON"],
  ["FM003","direct_compression","PROCESS","UO_DC_03","혼합시간 부족","API 분포 불균일","블렌드 균일성 저하","CQA_CU_AV","blend_time","CPP","DOE_CANDIDATE","TM_CU_USP905","textbook","SRC_AULTON"],
  ["FM004","direct_compression","PROCESS","UO_DC_03","원료 간 입도·밀도 차이","분리(segregation)","이송 중 조성 변동","CQA_CU_AV","transfer_control","CPP","REQUEST_DATA","TM_CU_USP905","textbook","SRC_AULTON"],
  ["FM005","direct_compression","FORMULATION","","충진제 비율(가소성/취성)","결합력 변화","정제 강도 변화","CQA_FRIABILITY;CQA_BREAKING_FORCE;CQA_DISINTEGRATION","filler_ratio","CMA","DOE_CANDIDATE","TM_FRIAB_USP1216;TM_BREAK_USP1217","textbook","SRC_HPE"],
  ["FM006","direct_compression","FORMULATION","","붕해제 부족","붕해 지연","용출 지연","CQA_DISINTEGRATION;CQA_DISPERSIBILITY;CQA_DISSOLUTION","disintegrant_pct","CMA","DOE_CANDIDATE","TM_DISS_USP711_Q;TM_DISINT_USP701","textbook","SRC_HPE"],
  ["FM007","direct_compression","FORMULATION","","붕해제 과량","정제 약화","마손도 증가, 붕해 역효과 가능","CQA_FRIABILITY;CQA_DISINTEGRATION","disintegrant_pct","CMA","DOE_CANDIDATE","TM_FRIAB_USP1216","textbook","SRC_HPE"],
  ["FM008","direct_compression","PROCESS","UO_DC_04","활택제 과량 또는 과혼합","소수성 피막","젖음성·결합력 저하","CQA_DISSOLUTION;CQA_BREAKING_FORCE","lubricant_pct;lubrication_time","CMA;CPP","DOE_CANDIDATE","TM_DISS_USP711_Q;TM_BREAK_USP1217","textbook","SRC_HPE;SRC_AULTON"],
  ["FM009","direct_compression","PROCESS","UO_DC_04","활택 부족","스티킹·피킹","외관·중량 편차","CQA_TABLET_WEIGHT_RSD","lubricant_pct","CMA","CONTROL_SOP","TM_TABLET_WEIGHT_RSD","textbook","SRC_AULTON"],
  ["FM010","direct_compression","PROCESS","UO_DC_05","압축력 과소","결합 부족","강도 저하","CQA_FRIABILITY;CQA_BREAKING_FORCE","compression_force","CPP","DOE_CANDIDATE","TM_FRIAB_USP1216;TM_BREAK_USP1217","textbook","SRC_AULTON"],
  ["FM011","direct_compression","PROCESS","UO_DC_05","압축력 과다","기공 감소","붕해·용출 지연","CQA_DISINTEGRATION;CQA_DISSOLUTION","compression_force","CPP","DOE_CANDIDATE","TM_DISS_USP711_Q","textbook","SRC_AULTON"],
  ["FM012","direct_compression","PROCESS","UO_DC_05","분체 흐름성 불량","다이 충전 불균일","중량편차","CQA_TABLET_WEIGHT_RSD;CQA_CU_AV","glidant_pct","CMA","CONTROL_SOP","TM_TABLET_WEIGHT_RSD;TM_FLOW_CARR","compendial","SRC_USP_1174"],
  ["FM013","direct_compression","RAW_MATERIAL","","API 입자크기 변동","표면적 변화","용출·균일성 변화","CQA_DISSOLUTION;CQA_CU_AV","api_psd","CMA","MATERIAL_SPEC","TM_PSD_LASER","textbook","SRC_AULTON"],
  ["FM014","direct_compression","RAW_MATERIAL","","API–부형제 상호작용","분해","함량 저하·유연물질 증가","CQA_ASSAY;CQA_IMPURITIES","—","—","REQUEST_DATA","TM_ASSAY_HPLC;TM_IMPURITY_HPLC","guideline","SRC_ICH_Q8"],
  ["FM015","direct_compression","STORAGE","","흡습","경도·붕해 변화","물리적 특성 변동","CQA_BREAKING_FORCE;CQA_DISINTEGRATION;CQA_WATER","—","—","MONITOR","TM_WATER_KF","guideline","SRC_ICH_Q1A"],
  ["FM016","direct_compression","PROCESS","UO_DC_03","과혼합","미세 API 재분리(demixing)","블렌드 균일성 저하","CQA_CU_AV","blend_time","CPP","DOE_CANDIDATE","TM_CU_USP905","textbook","SRC_AULTON"],
 ], SCI)

write_table("qbd_risk","fmea_scoring_scale.csv",
 ["dimension","score","label_ko","definition_ko","evidence_required","source_ids"],
 [
  ["SEVERITY","5","매우 높음","critical CQA 실패로 환자 안전·유효성 영향 (함량, 함량균일성, BCS II 용출)","CQA criticality 연결","SRC_ICH_Q9"],
  ["SEVERITY","4","높음","critical CQA 규격 이탈 가능","CQA criticality 연결","SRC_ICH_Q9"],
  ["SEVERITY","3","중간","비critical CQA 이탈 또는 공정 실패","CQA 연결","SRC_ICH_Q9"],
  ["SEVERITY","2","낮음","외관·취급성 영향","—","SRC_ICH_Q9"],
  ["SEVERITY","1","무시","품질 영향 없음","—","SRC_ICH_Q9"],
  ["OCCURRENCE","UNKNOWN","미상","발생률 자료 없음 (기본값)","—","SPEC:v6.1§3.3"],
  ["OCCURRENCE","5","빈번","동일 조건 실측에서 반복 관찰","실측 발생 기록","SRC_ICH_Q9"],
  ["OCCURRENCE","3","가끔","문헌·유사 제품에서 발생 보고","문헌","SRC_ICH_Q9"],
  ["OCCURRENCE","1","드묾","발생률 자료로 낮음 확인. 시험 범위 내 미검출(예: DSC/FTIR 음성)은 부분 근거로만 기록","발생률 근거","SRC_ICH_Q9"],
  ["DETECTABILITY","1","확실히 검출","원인 판별에 필요한 감도·표본추출·검출 시점을 갖춘 배치별 시험","test_method_id + 판별력 근거","SRC_ICH_Q9"],
  ["DETECTABILITY","3","부분 검출","간접·표본 시험 또는 사후 검출","test_method_id","SRC_ICH_Q9"],
  ["DETECTABILITY","5","검출 불가","시험·모니터링 없음 (예: 압축력 미기록)","—","SRC_ICH_Q9"],
  ["RULE","RPN_WHEN_O_UNKNOWN","RPN 미계산","O가 UNKNOWN이면 RPN을 계산하지 않고 S·조절가능성·근거로 처리 방향 결정","—","SPEC:v6.1§3.3"],
  ["RULE","HIGH_SEVERITY_RETENTION","고심각도 보존","S≥4 항목은 O와 무관하게 대체관리 + 승인 없이 제외 금지 (FE012)","—","SPEC:v6.1§6.D3"],
 ], POL)

FE="factor_eligibility_rules"
rows=[
 R("FE001",1,"factor","FACTOR_READINESS","not item.controllable and not item.measurable","item","BLOCK_STAGE","BLOCK_STAGE","FACTOR_NOT_CONTROLLABLE","","조절도 측정도 불가능한 항목은 요인이 될 수 없습니다.","","NONE","","","SPEC:v6.1§8.B.10",POL),
 R("FE002",2,"factor","FACTOR_READINESS","item.disposition == 'DOE_CANDIDATE' and (item.low is None or item.high is None)","item","REQUEST_DATA","REQUEST_DATA","RANGE_MISSING","WAITING_FACTOR_DATA","범위가 정해지지 않았습니다. RangeProposer를 실행하세요.","","NONE","","","SPEC:v6.1§6.D4",POL),
 R("FE003",1,"factor","FACTOR_READINESS","item.prohibited","item","BLOCK_STAGE","BLOCK_STAGE","FACTOR_PROHIBITED","","안전·규제상 금지된 항목입니다.","","NONE","","","SPEC:v6.1§6.D3",POL),
 R("FE004",20,"factor","FACTOR_READINESS","redundant_with_any(factor, factors)","factor;factors","NA","WARNING","FACTOR_REDUNDANT","","다른 요인과 중복됩니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.B.10",POL),
 R("FE005",1,"factor","FACTOR_READINESS","not equipment_supports(factor)","factor","BLOCK_STAGE","BLOCK_STAGE","FACTOR_NOT_EXECUTABLE","","보유 설비로 실행할 수 없는 요인입니다.","","NONE","","","SPEC:v6.1§8.B.10",POL),
 R("FE006",30,"factor","FACTOR_READINESS","item.severity >= const.fmea_high_severity and item.controllable and item.range_definable","item","NA","PASS","FACTOR_RECOMMEND_DOE","","DoE 요인 후보로 권고합니다.","recommendation 필드 기록 (판정 강도와 별개 축)","REASON_ONLY","researcher","","SPEC:v6.1§6.D3",POL),
 R("FE007",30,"factor","FACTOR_READINESS","item.function_locked","item","NA","PASS","FACTOR_RECOMMEND_FIXED","","기능상 고정 관리가 적절합니다.","recommendation 필드 기록","REASON_ONLY","researcher","","SPEC:v6.1§6.D3",POL),
 R("FE008",30,"factor","FACTOR_READINESS","item.occurrence == 1 and item.occurrence_evidence is not None and item.severity < const.fmea_high_severity","item","NA","PASS","FACTOR_RECOMMEND_EXCLUDE","","근거로 위험이 낮아 제외를 권고합니다.","고심각도는 대상 아님 (A5)","REASON_ONLY","researcher","","SPEC:v6.1§6.D3",POL),
 R("FE009",10,"factor","FACTOR_READINESS","item.kind == 'CPP' and item.fixed_value_status == 'UNKNOWN'","item","NA","WARNING","FACTOR_UNMANAGED","","값이 기록되지 않은 공정변수입니다. scope 제한으로 기록됩니다.","critical이면 critical_unmanaged_count 증가","REASON_ONLY","researcher","","SPEC:v6.1§6.D1",POL),
 R("FE010",10,"factor","FACTOR_READINESS","item.kind == 'CMA' and item.unit == 'mg_per_unit' and handoff.api_amount_fixed and not handoff.total_weight_fixed","item;handoff","NA","WARNING","FACTOR_TOTAL_WEIGHT_VARIES","","절대량(mg) 변경으로 정제 총중량이 변합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§3.4",POL),
 R("FE011",1,"factor","WAITING_FACTOR_APPROVAL","count(f for f in factors if f.disposition == 'DOE_CANDIDATE') > const.screening_max_factors","factors","BLOCK_STAGE","BLOCK_STAGE","FACTOR_COUNT_UNSUPPORTED","","MVP 백엔드가 지원하는 screening 요인 수를 초과했습니다.","A10","NONE","","","SPEC:v6.1§1.2",POL),
 R("FE012",1,"factor","WAITING_FMEA_APPROVAL|WAITING_FACTOR_APPROVAL","item.disposition == 'EXCLUDED' and item.severity >= const.fmea_high_severity and (item.alternative_control is None or item.approval_ref is None)","item","BLOCK_STAGE","BLOCK_STAGE","HIGH_SEVERITY_EXCLUSION_BLOCKED","","고심각도 항목은 발생도와 무관하게 대체관리·승인 없이 제외할 수 없습니다.","독립 invariant (A5)","NONE","","","SPEC:v6.1§6.D3",POL),
]
write_rules("qbd_risk","factor_eligibility_rules.csv",FE,rows)

FR="factor_range_constraint_rules"
rows=[
 R("FR001",30,"factor","FACTOR_READINESS","factor.center.value is None","factor","NA","PASS","RANGE_CENTER_DEFAULT","","center는 Handoff의 현재값으로 설정합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§3.4",POL),
 R("FR002",2,"factor","FACTOR_READINESS","factor.low.source_ref is None or factor.high.source_ref is None","factor","REQUEST_DATA","REQUEST_DATA","RANGE_MISSING","WAITING_FACTOR_DATA","경계값의 출처가 없습니다.","","ALTERNATIVE_EVIDENCE","researcher","","SPEC:v6.1§3.4",POL),
 R("FR003",10,"factor","FACTOR_READINESS","excipient_range_exists(factor) and (factor.high.value > master.typical_max_pct or factor.low.value < master.typical_min_pct)","factor;master","NA","WARNING","RANGE_OUTSIDE_TYPICAL","","통상 사용범위(TYPICAL_USE)를 벗어납니다. 한계가 아닌 참고 범위이므로 연구 목적을 기록하세요.","TYPICAL_USE는 교집합에 쓰지 않음","REASON_ONLY","researcher","예: crospovidone 10%","SRC_HPE;SPEC:v6.1§3.4",SCI),
 R("FR004",10,"factor","FACTOR_READINESS","iid_reference_exists(factor) and factor.high.amount_per_unit_mg > iid.max_potency_mg","factor;iid","NA","WARNING","RANGE_ABOVE_HISTORICAL_EXPOSURE","","FDA IID의 동일 경로·제형 승인제품 최대 사용량 이력을 초과합니다 (안전 한계 아님).","외부 의존성 (manifest external_dependencies)","REASON_ONLY","researcher","maximum potency ≠ maximum daily exposure","SRC_FDA_IID",COMP),
 R("FR005",1,"factor","FACTOR_READINESS","factor.unit == 'pct_w_w' and (factor.low.value < 0 or factor.high.value > 100)","factor","BLOCK_STAGE","BLOCK_STAGE","RANGE_PHYSICALLY_IMPOSSIBLE","","물리적으로 불가능한 범위입니다.","","NONE","","","SPEC:v6.1§3.4",POL),
 R("FR006",1,"design","SCREENING_PLANNING|RSM_PLANNING","any(dp.balance_component_value < 0 for dp in plan.design_points)","plan","BLOCK_STAGE","BLOCK_STAGE","UNSAFE_OR_INFEASIBLE_POINT","DESIGN_REPLAN","어느 설계점에서 balance 성분이 음수가 됩니다.","축점 포함 전체","NONE","","","SPEC:v6.1§3.4",POL),
 R("FR007",20,"factor","FACTOR_READINESS","composition_group.balance_component is not None","composition_group","NA","WARNING","RANGE_DILUTION_CONFOUNDED","","balance 구조가 있어 요인 효과와 희석 효과가 섞입니다.","","REASON_ONLY","researcher","","SPEC:v6.1§3.4",POL),
 R("FR008",20,"factor","FACTOR_READINESS","abs(factor.expected_range_contrast) < const.range_width_multiplier * method.repeatability_sd","factor;method","RECORD_NOT_CHECKED","WARNING","RANGE_TOO_NARROW","","범위 내 예상 효과가 시험 반복오차에 비해 작습니다.","expected_range_contrast = 범위 양끝 예측 반응 차(선형: |기울기|×폭, 곡면: 범위 내 최대 차). 값 또는 METHOD_REPEATABILITY SD가 없으면 NOT_CHECKED","REASON_ONLY","researcher","A7","SPEC:v6.1§3.4",STAT),
 R("FR009",10,"factor","FACTOR_READINESS","factor.manufacturability_evidence is None and factor.at_extreme_of_master_range","factor","NA","ROUTE","BOUNDS_UNCERTAIN","RANGE_FINDING_RUNS","끝점 제조 가능성 근거가 없습니다. 범위 확인 run을 제안합니다.","극단 조합 2-4개, fitting 제외","REASON_ONLY","researcher","","SPEC:v6.1§3.4",POL),
 R("FR010",1,"factor","FACTOR_READINESS","intersection_empty(factor)","factor","BLOCK_STAGE","BLOCK_STAGE","EMPTY_FACTOR_INTERSECTION","STRATEGY_REVIEW","실행 가능 범위(PHYSICAL ∩ EQUIPMENT ∩ STUDY_PURPOSE)의 교집합이 비어 있습니다.","TYPICAL_USE는 교집합에 넣지 않음","NONE","","","SPEC:v6.1§6.D4",POL),
 R("FR011",20,"factor","FACTOR_READINESS","factor.kind == 'CATEGORICAL' and any(not protocol_available(lv) for lv in factor.levels)","factor","REQUEST_DATA","REQUEST_DATA","CATEGORY_PROTOCOL_MISSING","WAITING_FACTOR_DATA","범주 수준별 실행 방법이 없습니다.","","NONE","","","SPEC:v6.1§8.B.11",POL),
]
write_rules("qbd_risk","factor_range_constraint_rules.csv",FR,rows)
print("g1 v6.1 done")
