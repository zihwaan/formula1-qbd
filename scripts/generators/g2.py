from common import *

write_table("planning","statistical_policy_constants.csv",
 ["constant_id","value","unit","kind","description_ko","change_requires","source_ids"],
 [
  ["alpha","0.05","probability","PROJECT_DEFAULT","유의수준 (단독 판정 기준 아님)","study_lead 승인","SRC_MONTGOMERY_DAE"],
  ["joint_pass_probability","0.90","probability","PROJECT_DEFAULT","design space 공동 통과확률 기준","AnalysisPlan 사전 고정","SRC_PETERSON_2004"],
  ["joint_probability_independence_assumed","true","bool","PROJECT_DEFAULT","반응 간 독립 가정 곱 (MVP 근사, DesignSpaceVersion에 기록)","study_lead 승인","SPEC:v6.1§6.D9"],
  ["domain_policy","CONVEX_HULL_OF_DESIGN_POINTS","enum","PROJECT_POLICY","supported domain = 설계점 convex hull (BBD 정육면체 꼭짓점 영역 제외)","study_lead 승인","SPEC:v6.1§6.D9"],
  ["feasible_fraction_denominator","DOMAIN_GRID_POINTS","enum","PROJECT_POLICY","영역 비율 분모 = domain 안의 격자점","—","SPEC:v6.1§6.D9"],
  ["region_grid_points_per_axis","21","points","PROJECT_DEFAULT","격자 해상도 (연속 영역 보장 아님)","—","SPEC:v6.1§6.D9"],
  ["region_mc_draws","10000","draws","PROJECT_DEFAULT","Monte Carlo 사용 시 draw 수 (seed·MC 오차 저장)","—","SPEC:v6.1§6.D9"],
  ["setpoint_min_edge_distance_coded","0.1","coded units","PROJECT_DEFAULT","권장 setpoint와 domain 경계 최소 거리","—","SPEC:v6.1§6.D9"],
  ["verification_family_alpha","0.05","probability","PROJECT_POLICY","확인계획 전체(필수 확인점 × DOE_RESPONSE) family 오류율","study_lead 승인","SPEC:v6.1§6.D10"],
  ["verification_multiplicity_method","BONFERRONI","enum","PROJECT_POLICY","동시 예측구간: 개별 수준 = 1 − family_alpha / 비교 수","study_lead 승인","SPEC:v6.1§6.D10"],
  ["verification_pi_scope","DOE_RESPONSE_ONLY","enum","PROJECT_POLICY","예측구간 판정 대상","—","SPEC:v6.1§6.D10"],
  ["verification_spec_scope","ALL_APPLICABLE_CQA","enum","PROJECT_POLICY","규격 판정 대상 (MONITOR_ONLY 포함)","—","SPEC:v6.1§6.D10"],
  ["verification_batches_per_point","1","batches","DEMO_POLICY","데모 최소 커버리지. 운영 값은 허용 예측오차·변동으로 결정","study_lead 승인","SPEC:v6.1§6.D10"],
  ["pred_r2_gap_flag","0.20","R2 units","RULE_OF_THUMB","adj R² − pred R² > 값이면 MODEL_FLAGGED","study_lead 승인","SRC_STATEASE_PRED_R2"],
  ["pred_r2_min_flag","0.50","R2 units","PROJECT_DEFAULT","pred R² < 값이면 넓은 예측구간 WARNING","study_lead 승인","SPEC:v6.1§6.D8"],
  ["pure_error_df_warning","2","df","PROJECT_DEFAULT","pure error 자유도 ≤ 값이면 WARNING","—","SPEC:v6.1§6.D8"],
  ["residual_df_min","1","df","STATISTICAL_LAW","잔차 자유도 < 값이면 분산·예측구간 계산 불가","—","SRC_MONTGOMERY_DAE"],
  ["residual_df_warning","3","df","PROJECT_DEFAULT","잔차 자유도 < 값이면 WARNING","—","SPEC:v6.1§8.C.15"],
  ["matrix_rank_rel_tolerance","1e-10","ratio","PROJECT_DEFAULT","행렬 rank 판정 상대 tolerance (특이값 기준)","—","SPEC:v6.1§8.C.15"],
  ["cooks_d_flag","1.0","—","RULE_OF_THUMB","Cook's D > 값이면 영향점 flag (삭제 아님)","—","SRC_COOK_1977"],
  ["leverage_flag_multiplier","2.0","× p/n","RULE_OF_THUMB","hat 값 > 배수×p/n이면 flag","—","SRC_MONTGOMERY_DAE"],
  ["high_pure_error_ratio","3.0","× method repeatability SD","PROJECT_DEFAULT","배치 반복 SD > 배수 × 시험법 반복 SD면 HIGH_PURE_ERROR (METHOD_REPEATABILITY 값이 있을 때만)","—","SPEC:v6.1§6.D7"],
  ["screening_center_points","3","runs","PROJECT_DEFAULT","screening 중심점 기본 개수","—","SRC_NIST_HANDBOOK"],
  ["screening_max_factors","4","factors","MVP_SCOPE","MVP screening 요인 최대 (초과 시 차단)","—","SPEC:v6.1§1.2"],
  ["rsm_max_factors","3","factors","MVP_SCOPE","MVP RSM 요인 최대","—","SPEC:v6.1§1.2"],
  ["range_width_multiplier","2.0","× repeatability SD","PROJECT_DEFAULT","|예상 범위 효과| ≥ 배수 × 시험 반복 SD","—","SPEC:v6.1§3.4"],
  ["non_binding_ratio","0.25","ratio","PROJECT_DEFAULT","최대 관측값 ≤ 비율×상한이면 NON_BINDING 표시","—","SPEC:v6.1§3.2"],
  ["composition_sum_tolerance_pct","0.5","% w/w","PROJECT_DEFAULT","조성 합계 허용 오차","—","SPEC:v6.1§6.D1"],
  ["fmea_high_severity","4","score","PROJECT_DEFAULT","고심각도 기준 S","—","SPEC:v6.1§6.D3"],
  ["range_finding_runs_max","4","runs","PROJECT_DEFAULT","범위 확인 run 최대","—","SPEC:v6.1§3.4"],
  ["challenge_min_fail_probability","0.5","probability","PROJECT_POLICY","CHALLENGE 점을 expected FAIL로 지정하려면 예측 실패확률 ≥ 값","—","SPEC:v6.1§6.D10"],
 ], STAT)

D="doe_design_selection_rules"
rows=[
 R("DS001",10,"design","DESIGN_SELECTION","plan.has_mixture","plan","NA","WARNING","DESIGN_MIXTURE_UNSUPPORTED","","조성 합계 제약이 있습니다. mixture 설계가 필요하지만 MVP 백엔드는 지원하지 않습니다 (DV013에서 실행 차단).","","REASON_ONLY","researcher","A10","SRC_MONTGOMERY_DAE",STAT),
 R("DS002",15,"design","DESIGN_SELECTION","plan.has_forbidden_combinations","plan","NA","WARNING","DESIGN_D_OPTIMAL_UNSUPPORTED","","불규칙 영역입니다. D-optimal이 필요하지만 MVP 백엔드는 지원하지 않습니다.","","REASON_ONLY","researcher","A10","SRC_MONTGOMERY_DAE",STAT),
 R("DS003",15,"design","DESIGN_SELECTION","plan.has_hard_to_change","plan","NA","WARNING","DESIGN_SPLIT_PLOT_UNSUPPORTED","","바꾸기 어려운 요인이 있습니다. split-plot이 필요하지만 MVP 백엔드는 지원하지 않습니다.","","REASON_ONLY","researcher","A10","SRC_MONTGOMERY_DAE",STAT),
 R("DS004",20,"design","DESIGN_SELECTION","plan.stage == 'SCREENING' and plan.n_continuous >= 3 and plan.n_categorical == 0","plan","NA","PASS","DESIGN_RES_IV_FF","","Resolution IV 이상 부분요인설계 + 중심점을 권고합니다.","","REASON_ONLY","researcher","","SRC_NIST_HANDBOOK",STAT),
 R("DS005",20,"design","DESIGN_SELECTION","plan.stage == 'SCREENING' and plan.n_categorical >= 1","plan","NA","PASS","DESIGN_FF_WITH_2LEVEL_CATEGORICAL","","범주형이 2수준이면 Res IV 부분요인설계에 포함합니다 (DSD는 MVP 미지원). 범주별 중심점을 둡니다.","3수준 이상 범주형은 DV013 차단","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("DS006",25,"design","DESIGN_SELECTION","plan.design_type == 'PLACKETT_BURMAN' and plan.interactions_plausible","plan","NA","WARNING","DESIGN_RES_III_WARNING","","Plackett-Burman은 주효과와 2인자 상호작용이 부분적으로 섞입니다.","","REASON_ONLY","researcher","","SRC_PLACKETT_BURMAN_1946",STAT),
 R("DS007",20,"design","DESIGN_SELECTION","plan.n_factors <= const.rsm_max_factors and plan.n_categorical == 0 and plan.prior_evidence_approved","plan","NA","ROUTE","DESIGN_RSM_DIRECT","RSM_PLANNING","3요인 이하 연속요인이고 승인된 사전근거가 있어 RSM으로 직행합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§5.1",POL),
 R("DS008",30,"design","DESIGN_SELECTION|RSM_PLANNING","plan.extreme_corner_risk and plan.n_continuous == 3 and plan.n_categorical == 0","plan","NA","PASS","DESIGN_BBD","","꼭짓점 위험이 있어 Box-Behnken을 권고합니다 (3개 연속요인).","","REASON_ONLY","researcher","","SRC_BOX_BEHNKEN_1960",STAT),
 R("DS009",30,"design","DESIGN_SELECTION|RSM_PLANNING","plan.axial_must_stay_in_range and plan.n_continuous in (2,3) and plan.n_categorical == 0","plan","NA","PASS","DESIGN_FCCD","","축점을 범위 안에 두는 face-centered CCD를 권고합니다.","","REASON_ONLY","researcher","","SRC_BOX_WILSON_1951",STAT),
 R("DS010",35,"design","DESIGN_SELECTION|RSM_PLANNING","plan.axial_points_safe and plan.n_continuous in (2,3) and plan.n_categorical == 0","plan","NA","PASS","DESIGN_CCD","","축점이 안전하여 CCD를 권고합니다.","","REASON_ONLY","researcher","","SRC_BOX_WILSON_1951",STAT),
 R("DS011",5,"design","RSM_PLANNING","plan.screening_core_reusable","plan","NA","PASS","DESIGN_AUGMENT_TO_CCD","","screening core를 재사용해 축점과 블록 중심점을 추가합니다.","v6.1 §11 조건","REASON_AND_APPROVER","study_lead","","SPEC:v6.1§11",POL),
]
write_rules("planning","doe_design_selection_rules.csv",D,rows)

B="doe_randomization_blocking_rules"
rows=[
 R("RB001",10,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.expected_days > 1 and plan.block_definition is None","plan","NA","WARNING","BLOCK_BY_DAY","","여러 날에 걸친 제조입니다. day를 블록으로 두세요.","","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("RB002",10,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.material_lots > 1 and plan.block_definition is None","plan","NA","WARNING","BLOCK_BY_LOT","","원료 lot이 바뀝니다. 블록 또는 noise factor로 처리하세요.","","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("RB003",1,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.equipment_count > 1 and plan.block_definition is None","plan","BLOCK_STAGE","BLOCK_STAGE","EQUIPMENT_SCOPE_MIXED","","설비 변경은 scope 분리 또는 블록이 필요합니다.","","NONE","","","SPEC:v6.1§8.C.14",POL),
 R("RB004",1,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.has_hard_to_change","plan","BLOCK_STAGE","BLOCK_STAGE","HTC_UNSUPPORTED","","바꾸기 어려운 요인은 split-plot 오차구조가 필요하며 MVP에서 실행할 수 없습니다.","A10","NONE","","","SPEC:v6.1§14.6",STAT),
 R("RB005",20,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.randomization == 'RESTRICTED' and plan.randomization_reason is None","plan","REQUEST_DATA","REQUEST_DATA","RANDOMIZATION_REASON_MISSING","","제한 무작위화의 이유를 기록하세요.","","NONE","","","SPEC:v6.1§8.C.14",POL),
 R("RB006",10,"plan","RSM_PLANNING","plan.augments_previous_stage and plan.new_block_center_points < 1","plan","NA","WARNING","AUGMENT_BLOCK_NO_CENTER","","증강 블록에 중심점이 없어 블록 효과를 추정할 수 없습니다.","권장 1-2개","REASON_ONLY","researcher","","SPEC:v6.1§11",STAT),
]
write_rules("planning","doe_randomization_blocking_rules.csv",B,rows)

V="doe_design_validation_rules"
rows=[
 R("DV001",1,"plan","SCREENING_PLANNING|RSM_PLANNING","matrix_rank(plan) < plan.n_terms","plan","BLOCK_STAGE","BLOCK_STAGE","DESIGN_RANK_DEFICIENT","DESIGN_REPLAN","의도한 모형 항을 추정할 수 없습니다.","n_terms에 block 항 포함, tolerance = const.matrix_rank_rel_tolerance","NONE","","","SRC_MONTGOMERY_DAE",STAT),
 R("DV002",1,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.n_runs - plan.n_terms < const.residual_df_min","plan","BLOCK_STAGE","BLOCK_STAGE","DESIGN_NO_RESIDUAL_DF","DESIGN_REPLAN","잔차 자유도가 없어 분산·예측구간을 계산할 수 없습니다.","","NONE","","","SRC_MONTGOMERY_DAE",STAT),
 R("DV003",20,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.n_runs - plan.n_terms < const.residual_df_warning","plan","NA","WARNING","DESIGN_LOW_RESIDUAL_DF","","잔차 자유도가 적습니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.C.15",STAT),
 R("DV004",10,"plan","SCREENING_PLANNING","plan.stage == 'SCREENING' and plan.resolution < 4","plan","NA","WARNING","DESIGN_RES_III_WARNING","","Resolution III 설계입니다.","","REASON_ONLY","researcher","","SRC_NIST_HANDBOOK",STAT),
 R("DV005",15,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.n_center_points < 2","plan","NA","WARNING","DESIGN_FEW_CENTERS","","중심점이 부족해 곡률과 pure error 추정이 어렵습니다.","","REASON_ONLY","researcher","","SRC_NIST_HANDBOOK",STAT),
 R("DV006",1,"plan","SCREENING_PLANNING|RSM_PLANNING","any(not dp.in_bounds for dp in plan.design_points)","plan","BLOCK_STAGE","BLOCK_STAGE","UNSAFE_OR_INFEASIBLE_POINT","DESIGN_REPLAN","승인 범위 밖의 점이 있습니다.","","NONE","","","SPEC:v6.1§14.4",POL),
 R("DV007",1,"plan","SCREENING_PLANNING|RSM_PLANNING","any(dp.in_forbidden_combination for dp in plan.design_points)","plan","BLOCK_STAGE","BLOCK_STAGE","UNSAFE_OR_INFEASIBLE_POINT","DESIGN_REPLAN","금지 조합이 포함되어 있습니다.","","NONE","","","SPEC:v6.1§14.4",POL),
 R("DV008",10,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.block_definition is not None and block_confounded(plan)","plan","NA","WARNING","DESIGN_BLOCK_CONFOUNDED","","블록이 모형 항과 교락됩니다.","","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("DV009",1,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.random_seed is None or plan.generator is None","plan","BLOCK_STAGE","BLOCK_STAGE","DESIGN_NOT_REPRODUCIBLE","","seed와 생성기 버전이 필요합니다.","","NONE","","","SPEC:v6.1§6.D5",POL),
 R("DV010",20,"plan","RSM_PLANNING","plan.design_type == 'BOX_BEHNKEN'","plan","NA","WARNING","DESIGN_BBD_DOMAIN_POLICY","","Box-Behnken의 supported domain은 설계점 convex hull입니다. 정육면체 꼭짓점 영역은 영역 계산에서 제외됩니다.","","REASON_ONLY","researcher","B2","SRC_BOX_BEHNKEN_1960",STAT),
 R("DV011",1,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.has_mixture and not plan.mixture_sum_ok","plan","BLOCK_STAGE","BLOCK_STAGE","DESIGN_MIXTURE_SUM_VIOLATED","DESIGN_REPLAN","조성 합계 제약을 위반합니다.","","NONE","","","SPEC:v6.1§8.C.15",POL),
 R("DV012",30,"plan","SCREENING_PLANNING|RSM_PLANNING","plan.n_unique_runs < plan.n_runs - plan.n_center_points","plan","NA","WARNING","DESIGN_DUPLICATE_RUNS","","의도하지 않은 중복 run이 있습니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.C.15",POL),
 R("DV013",1,"plan","SCREENING_PLANNING|RSM_PLANNING","not backend_supports(plan)","plan","BLOCK_STAGE","BLOCK_STAGE","DESIGN_BACKEND_UNSUPPORTED","","MVP 백엔드가 지원하지 않는 설계·요인 조합입니다 (manifest backend_capabilities).","mixture, D-optimal, split-plot, DSD, 3수준 이상 범주형","NONE","","A10","SPEC:v6.1§6.D5",POL),
 R("DV014",1,"plan","RSM_PLANNING","plan.design_type == 'BOX_BEHNKEN' and (plan.n_continuous < 3 or plan.n_categorical > 0)","plan","BLOCK_STAGE","BLOCK_STAGE","DESIGN_BBD_FACTOR_COUNT","","Box-Behnken은 연속요인 3개 이상에서만 정의됩니다.","","NONE","","A10","SRC_BOX_BEHNKEN_1960",STAT),
]
write_rules("planning","doe_design_validation_rules.csv",V,rows)

G="doe_augmentation_rules"
rows=[
 R("AU001",10,"analysis","SCREENING_AUGMENTATION","event.reason_code == 'UNRESOLVED_ALIAS'","event","NA","AUGMENT","AUG_FOLDOVER","","alias 해소를 위해 foldover 또는 표적 run을 추가합니다.","증강 방법 선택만, 전이는 전이표","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("AU002",10,"analysis","RSM_PLANNING","event.reason_code == 'CURVATURE_DETECTED'","event","NA","AUGMENT","AUG_AXIAL","","축점을 추가해 RSM으로 전환합니다.","","REASON_ONLY","researcher","","SRC_NIST_HANDBOOK",STAT),
 R("AU003",10,"analysis","RSM_AUGMENTATION","event.reason_code == 'MODEL_INVALID' and model.invalid_cause == 'RANK'","event;model","NA","AUGMENT","AUG_RANK_REPAIR","","추정 불가 항을 위한 점을 추가합니다 (MVP: 연구자 지정 점, D-optimal 미지원).","","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("AU004",10,"analysis","RSM_AUGMENTATION","event.reason_code == 'VERIF_OUTSIDE_PI'","event","NA","AUGMENT","AUG_TARGETED_LOCAL","","예측이 어긋난 지점 주변에 표적 run을 추가합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D10",STAT),
 R("AU006",20,"analysis","RSM_AUGMENTATION","model.local_prediction_se_high","model","NA","AUGMENT","AUG_TARGETED_UNCERTAINTY","","예측불확실성이 큰 구역에 점을 추가합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.C.16",STAT),
]
write_rules("planning","doe_augmentation_rules.csv",G,rows)

S="run_sheet_compilation_rules"
rows=[
 R("RS001",1,"run","RUN_SHEET_COMPILE","abs(run.ingredient_mg_total - run.target_unit_mg) > run.target_unit_mg * const.composition_sum_tolerance_pct / 100","run","BLOCK_STAGE","BLOCK_STAGE","RUNSHEET_MASS_MISMATCH","","단위 질량 합계가 목표와 다릅니다.","","NONE","","","SPEC:v6.1§8.D.17",POL),
 R("RS002",1,"run","RUN_SHEET_COMPILE","run.balance_component_mg < 0","run","BLOCK_STAGE","BLOCK_STAGE","UNSAFE_OR_INFEASIBLE_POINT","DESIGN_REPLAN","balance 성분이 음수입니다.","","NONE","","","SPEC:v6.1§3.4",POL),
 R("RS003",1,"run","RUN_SHEET_COMPILE","run.batch_mass_g > equipment.working_capacity_max_g or run.batch_mass_g < equipment.working_capacity_min_g","run;equipment","BLOCK_STAGE","BLOCK_STAGE","RUNSHEET_CAPACITY","","설비 작업 용량을 벗어납니다.","","NONE","","","SPEC:v6.1§8.D.17",POL),
 R("RS004",10,"run","RUN_SHEET_COMPILE","not run.settings_on_resolution","run","NA","WARNING","RUNSHEET_RESOLUTION","","설비 설정 분해능에 맞지 않는 값입니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.D.17",POL),
 R("RS005",1,"run","RUN_SHEET_COMPILE","not run.settings_complete","run","REQUEST_DATA","REQUEST_DATA","RUN_DATA_MISSING","WAITING_RUN_DATA","근거 없는 설정값은 만들지 않습니다. 값을 제출하세요.","","NONE","","","SPEC:v6.1§3.7",POL),
 R("RS006",1,"run","RUN_SHEET_COMPILE","not run.fixed_conditions_match","run","BLOCK_STAGE","BLOCK_STAGE","RUNSHEET_FIXED_MISMATCH","","고정 조건이 Handoff와 다릅니다.","","NONE","","","SPEC:v6.1§8.D.17",POL),
]
write_rules("execution","run_sheet_compilation_rules.csv",S,rows)

Q="result_data_quality_rules"
rows=[
 R("RQ001",1,"result","RESULT_QUALITY_GATE","result.batch_id is None","result","BLOCK_STAGE","BLOCK_STAGE","RESULT_NO_BATCH","WAITING_BATCH_RESULTS","batch_id가 없습니다.","","NONE","","","SPEC:v6.1§8.D.18",POL),
 R("RQ002",5,"result","RESULT_QUALITY_GATE","not result.settings_within_tolerance","result","REQUEST_DATA","REQUEST_DATA","RESULT_SETTING_DEVIATION","WAITING_BATCH_RESULTS","실제 설정이 허용오차를 벗어났습니다. 실제값을 보존하고 deviation으로 기록하세요.","허용오차 이내면 actual settings로 분석. 원자료를 계획값에 맞게 고치지 말 것","NONE","","B9","SPEC:v6.1§8.D.18",POL),
 R("RQ003",1,"result","RESULT_QUALITY_GATE","result.test_method_version is None","result","BLOCK_STAGE","BLOCK_STAGE","RESULT_NO_METHOD_VERSION","WAITING_BATCH_RESULTS","시험법 버전이 없습니다.","","NONE","","","SPEC:v6.1§8.D.18",POL),
 R("RQ004",1,"result","RESULT_QUALITY_GATE","result.unit != result.target_unit and not convertible(result.unit, result.target_unit)","result","BLOCK_STAGE","BLOCK_STAGE","RESULT_UNIT_UNCLEAR","WAITING_BATCH_RESULTS","단위를 변환할 수 없습니다.","","NONE","","","SPEC:v6.1§8.D.18",POL),
 R("RQ005",10,"result","RESULT_QUALITY_GATE","result.n_individual_values == 0 and result.evidence_status == 'MEASURED_CONFIRMED'","result","NA","WARNING","RESULT_NO_INDIVIDUAL_VALUES","","개별값이 없습니다. 요약값만 사용합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.D.18",POL),
 R("RQ006",1,"result","RESULT_QUALITY_GATE","result.human_verification_status != 'CONFIRMED'","result","BLOCK_STAGE","BLOCK_STAGE","RESULT_UNCONFIRMED","WAITING_RESULT_CONFIRMATION","확인되지 않은 결과는 분석하지 않습니다.","","NONE","","","SPEC:v6.1§14.7",POL),
 R("RQ007",1,"result","RESULT_QUALITY_GATE","result.deviation is not None and not result.deviation_resolved","result","BLOCK_STAGE","BLOCK_STAGE","UNRESOLVED_DEVIATION","DIAGNOSING","처리되지 않은 deviation이 있습니다.","","NONE","","","SPEC:v6.1§5.3",POL),
 R("RQ008",1,"result","RESULT_QUALITY_GATE","result.replicate_independence == 'UNKNOWN'","result","REQUEST_DATA","REQUEST_DATA","RESULT_REPLICATE_UNKNOWN","WAITING_BATCH_RESULTS","반복이 독립 배치인지 같은 배치 내 반복인지 확인하세요.","","NONE","","","SPEC:v6.1§6.D6",POL),
 R("RQ009",1,"result","RESULT_QUALITY_GATE","result.replicate_independence == 'WITHIN_BATCH' and result.counted_as_independent_run","result","BLOCK_STAGE","BLOCK_STAGE","RESULT_PSEUDO_REPLICATION","","같은 배치(재시험, 재타정, 재주입 포함)의 반복을 독립 run으로 셀 수 없습니다.","","NONE","","","SPEC:v6.1§14.8",POL),
 R("RQ010",1,"result","RESULT_QUALITY_GATE","not evidence_permits(result.evidence_status, 'MODEL_FIT')","result","BLOCK_STAGE","BLOCK_STAGE","RESULT_EVIDENCE_NOT_PERMITTED","","이 근거 등급의 값은 분석 입력으로 쓸 수 없습니다.","evidence_governance_rules 조회","NONE","","A9","SPEC:v6.1§8.A.2",POL),
 R("RQ011",20,"result","RESULT_QUALITY_GATE","result.evidence_status == 'LITERATURE_DIGITIZED'","result","NA","WARNING","RESULT_DIGITIZED","","디지타이징 값입니다. pure error와 확인 판정에는 쓰지 않습니다.","","REASON_ONLY","researcher","","SPEC:v6.1§8.A.2",POL),
]
write_rules("execution","result_data_quality_rules.csv",Q,rows)

SC="screening_analysis_rules"
DEL="cqa.practical_effect_threshold"
rows=[
 R("SA001",10,"factor","SCREENING_ANALYSIS",f"not effect.aliased and (effect.ci_lower >= {DEL} or effect.ci_upper <= -{DEL})","effect;cqa","INCONCLUSIVE","PASS","FACTOR_ACTIVE","","효과구간 전체가 실질 효과 기준 밖에 있습니다 (ACTIVE).","효과구간과 근거 보존. p값 단독 판정 금지","REASON_ONLY","researcher","A6","SPEC:v6.1§6.D7",STAT),
 R("SA002",10,"factor","SCREENING_ANALYSIS","effect.aliased and not effect.alias_resolved","effect","NA","ROUTE","UNRESOLVED_ALIAS","SCREENING_AUGMENTATION","alias가 해소되지 않아 원인을 단정할 수 없습니다.","heredity 해석은 연구자 승인 시에만","REASON_AND_APPROVER","study_lead","","SPEC:v6.1§14.9",STAT),
 R("SA003",10,"study","SCREENING_ANALYSIS","curvature_test.significant","curvature_test","NA","ROUTE","CURVATURE_DETECTED","RSM_PLANNING","중심점에서 곡률이 감지되었습니다.","","REASON_ONLY","researcher","","SRC_NIST_HANDBOOK",STAT),
 R("SA004",10,"factor","SCREENING_ANALYSIS",f"not effect.aliased and effect.ci_lower > -{DEL} and effect.ci_upper < {DEL}","effect;cqa","INCONCLUSIVE","PASS","FACTOR_FIXED","","효과구간 전체가 [−delta, +delta] 안에 있어 고정합니다.","range_tested, responses_evaluated, factor_effect_not_evaluated 기록","REASON_ONLY","researcher","A6: 음의 효과 포함","SPEC:v6.1§6.D7",STAT),
 R("SA005",5,"factor","SCREENING_ANALYSIS","decision.severity >= const.fmea_high_severity and decision.classification == 'FACTOR_FIXED'","decision","NA","WARNING","FACTOR_RETAIN_FOR_SAFETY","","고심각도 요인입니다. 고정 결정 전에 검토하세요.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D7",POL),
 R("SA006",10,"factor","SCREENING_ANALYSIS",f"not effect.aliased and effect.ci_lower < {DEL} and effect.ci_upper > -{DEL} and (effect.ci_lower <= -{DEL} or effect.ci_upper >= {DEL})","effect;cqa","INCONCLUSIVE","ROUTE","INCONCLUSIVE","SCREENING_AUGMENTATION","효과구간이 실질 효과 기준에 걸쳐 판정할 수 없습니다.","SA001·SA004·SA006은 상호배타","REASON_ONLY","researcher","A6","SPEC:v6.1§8.E.19",STAT),
 R("SA007",10,"study","SCREENING_ANALYSIS","count(f for f in factors if f.disposition == 'ACTIVE') == 0 and not curvature_test.significant","factors;curvature_test","NA","ROUTE","NO_ACTIVE_FACTOR","STRATEGY_REVIEW","활성 요인이 없습니다.","","REASON_ONLY","researcher","","SPEC:v6.1§5.3",POL),
 R("SA008",5,"study","SCREENING_ANALYSIS|MODEL_VALIDATION","method.variance_component_type == 'METHOD_REPEATABILITY' and center_points.pure_error_sd > const.high_pure_error_ratio * method.repeatability_sd","center_points;method","RECORD_NOT_CHECKED","ROUTE","HIGH_PURE_ERROR","DIAGNOSING","배치 반복 오차가 시험법 반복정밀도보다 크게 높습니다.","배치 간 SD를 method SD로 쓰지 말 것 (B1)","REASON_AND_APPROVER","study_lead","","SPEC:v6.1§5.3",STAT),
 R("SA009",5,"factor","SCREENING_ANALYSIS","factor.redefinition_requested","factor","NA","ROUTE","FACTOR_REDEFINED","FACTOR_READINESS","요인 종류·척도가 바뀌어 새 FactorDefinition 버전이 필요합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D4",POL),
]
write_rules("analysis","screening_analysis_rules.csv",SC,rows)

M="model_validation_rules"
rows=[
 R("MV001",1,"model","MODEL_VALIDATION","not model.all_terms_estimable","model","BLOCK_STAGE","BLOCK_STAGE","MODEL_INVALID","RSM_AUGMENTATION","추정할 수 없는 항이 있습니다.","invalid_cause=RANK","NONE","","","SRC_MONTGOMERY_DAE",STAT),
 R("MV002",1,"model","MODEL_VALIDATION","model.df_resid < const.residual_df_min","model","BLOCK_STAGE","BLOCK_STAGE","MODEL_INVALID","RSM_AUGMENTATION","잔차 자유도가 없어 분산·예측구간을 계산할 수 없습니다.","invalid_cause=DF","NONE","","","SRC_MONTGOMERY_DAE",STAT),
 R("MV003",1,"model","MODEL_VALIDATION","not model.hierarchical","model","BLOCK_STAGE","BLOCK_STAGE","MODEL_HIERARCHY_VIOLATION","","계층성을 위반합니다.","","NONE","","","SRC_MONTGOMERY_DAE",STAT),
 R("MV004",5,"model","MODEL_VALIDATION","model.lof_computable and model.lof_p < const.alpha","model","NA","ROUTE","MODEL_INVALID","RSM_AUGMENTATION","적합결여가 유의합니다.","invalid_cause=LOF; 변환 검토 제안","REASON_AND_APPROVER","study_lead","","SRC_MONTGOMERY_DAE",STAT),
 R("MV014",20,"model","MODEL_VALIDATION","not model.lof_computable","model","NA","WARNING","MODEL_LOF_NOT_COMPUTABLE","","적합결여를 계산할 수 없습니다 (비유의와 다름).","","REASON_ONLY","researcher","B8","SPEC:v6.1§6.D8",STAT),
 R("MV005",20,"model","MODEL_VALIDATION","model.pure_error_df <= const.pure_error_df_warning","model","NA","WARNING","MODEL_LOW_PURE_ERROR_DF","","pure error 자유도가 적어 적합결여 검정력이 약합니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D8",STAT),
 R("MV006",10,"model","MODEL_VALIDATION","model.adj_r2 - model.pred_r2 > const.pred_r2_gap_flag","model","NA","ROUTE","MODEL_FLAGGED","WAITING_MODEL_APPROVAL","예측 R²가 크게 낮아 과적합이 의심됩니다.","연구자: 계층성 유지 축소(새 버전 VALID) 또는 그대로 수용(ACCEPTED_WITH_FLAGS)","REASON_ONLY","researcher","축소 후 같은 자료 PRESS는 독립 성능 추정 아님 (selection_history 보존)","SRC_STATEASE_PRED_R2",STAT),
 R("MV007",20,"model","MODEL_VALIDATION","model.pred_r2 < const.pred_r2_min_flag","model","NA","WARNING","MODEL_LOW_PREDICTIVE_POWER","","예측력이 낮아 예측구간이 넓어집니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D8",STAT),
 R("MV008",20,"model","MODEL_VALIDATION","any(r.cooks_d > const.cooks_d_flag for r in model.runs)","model","NA","WARNING","MODEL_INFLUENCE_FLAG","","영향점이 있습니다. 조사 신호이며 자동 삭제하지 않습니다.","","REASON_ONLY","researcher","","SRC_COOK_1977",STAT),
 R("MV009",20,"model","MODEL_VALIDATION","any(r.leverage > const.leverage_flag_multiplier * model.p / model.n for r in model.runs)","model","NA","WARNING","MODEL_LEVERAGE_FLAG","","고leverage 점이 있습니다.","","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("MV010",20,"model","MODEL_VALIDATION","model.residual_pattern or model.heteroscedastic","model","NA","WARNING","MODEL_RESIDUAL_PATTERN","","잔차에 구조가 있습니다. 변환을 검토하세요.","","REASON_ONLY","researcher","","SRC_MONTGOMERY_DAE",STAT),
 R("MV011",1,"model","MODEL_VALIDATION","any(r.human_verification_status != 'CONFIRMED' or not evidence_permits(r.evidence_status, 'MODEL_FIT') for r in model.inputs)","model","BLOCK_STAGE","BLOCK_STAGE","MODEL_INPUT_NOT_PERMITTED","","확인되지 않았거나 적합에 쓸 수 없는 근거 등급의 결과가 포함되어 있습니다.","A9","NONE","","","SPEC:v6.1§14.7",POL),
 R("MV012",1,"model","MODEL_VALIDATION","model.scope_hash != study.scope_hash","model;study","BLOCK_STAGE","BLOCK_STAGE","LINEAGE_MISMATCH","WAITING_AUDIT_REVIEW","모델 scope가 study와 다릅니다.","","NONE","","","SPEC:v6.1§5.3",POL),
 R("MV013",1,"model","MODEL_VALIDATION","model.fit_method == 'AUTO_STEPWISE'","model","BLOCK_STAGE","BLOCK_STAGE","MODEL_AUTO_STEPWISE","","자동 stepwise 항 삭제는 허용되지 않습니다.","","NONE","","","SPEC:v6.1§14.10",POL),
]
write_rules("analysis","model_validation_rules.csv",M,rows)

DSR="design_space_rules"
rows=[
 R("DR001",1,"region","REGION_COMPUTATION","any(m.validation_status not in ('VALID','ACCEPTED_WITH_FLAGS') for m in models)","models","BLOCK_STAGE","BLOCK_STAGE","REGION_INVALID_MODEL_INPUT","","검증되지 않은 모델은 영역 입력이 될 수 없습니다.","enum: VALID, FLAGGED, ACCEPTED_WITH_FLAGS, HOLD, REJECTED","NONE","","","SPEC:v6.1§14.12",POL),
 R("DR002",1,"region","REGION_COMPUTATION","any(c.acceptance_operator is None for c in cqas if c.analysis_role == 'DOE_RESPONSE')","cqas","BLOCK_STAGE","BLOCK_STAGE","CQA_NO_ACCEPTANCE_OPERATOR","","모든 DoE 반응에 판정 방식과 한계값이 필요합니다.","","NONE","","","SPEC:v6.1§14.21",POL),
 R("DR003",1,"region","REGION_COMPUTATION","not region.all_points_in_domain","region","BLOCK_STAGE","BLOCK_STAGE","REGION_EXTRAPOLATION","","supported domain 밖은 영역에 포함할 수 없습니다.","membership = const.domain_policy","NONE","","B2","SPEC:v6.1§14.13",POL),
 R("DR012",1,"region","REGION_COMPUTATION","region.domain_policy is None","region","BLOCK_STAGE","BLOCK_STAGE","REGION_DOMAIN_UNDEFINED","","domain 정책(형태, membership 알고리즘, 분모)이 필요합니다.","","NONE","","B2","SPEC:v6.1§6.D9",POL),
 R("DR005",1,"region","REGION_COMPUTATION","region.method == 'MEAN_ONLY'","region","BLOCK_STAGE","BLOCK_STAGE","REGION_NO_UNCERTAINTY","","평균 예측만으로 영역을 만들 수 없습니다.","","NONE","","","SPEC:v6.1§6.D9",POL),
 R("DR006",1,"region","REGION_COMPUTATION","region.feasible_fraction == 0","region","NA","ROUTE","EMPTY_COMMON_REGION","STRATEGY_REVIEW","공동 영역이 비어 있습니다. 규격을 자동 완화하지 않습니다.","","NONE","","","SPEC:v6.1§6.D9",POL),
 R("DR007",10,"region","REGION_COMPUTATION","region.joint_independence_assumed","region","NA","WARNING","REGION_INDEPENDENCE_ASSUMED","","반응 간 독립을 가정한 공동확률입니다 (MVP 근사).","marginal 확률과 잔차 상관 추정을 함께 저장","REASON_ONLY","researcher","B7","SPEC:v6.1§6.D9",STAT),
 R("DR008",5,"region","REGION_COMPUTATION","region.setpoint_edge_distance < const.setpoint_min_edge_distance_coded","region","NA","WARNING","SETPOINT_ON_EDGE","","권장 setpoint가 domain 경계에 너무 가깝습니다. 내부점을 선택하세요.","","REASON_AND_APPROVER","study_lead","","SPEC:v6.1§6.D9",POL),
 R("DR009",1,"region","WAITING_FINAL_APPROVAL","region.has_operating_range and not region.operating_range_is_subset","region","BLOCK_STAGE","BLOCK_STAGE","OPERATING_RANGE_NOT_SUBSET","","권장 운전범위는 영역의 부분집합이어야 합니다.","","NONE","","","SPEC:v6.1§14.17",POL),
 R("DR010",1,"region","REGION_COMPUTATION","not region.scope.fixed_conditions_recorded","region","BLOCK_STAGE","BLOCK_STAGE","REGION_SCOPE_MISSING","","성립 조건(scope)이 필요합니다.","","NONE","","","SPEC:v6.1§14.18",POL),
 R("DR011",1,"region","REGION_COMPUTATION","region.criteria_changed_after_results","region","BLOCK_STAGE","BLOCK_STAGE","CRITERIA_RELAXED_POST_HOC","","결과를 본 뒤 규격을 완화할 수 없습니다.","","NONE","","","SPEC:v6.1§6.D9",POL),
 R("DR013",1,"region","WAITING_FINAL_APPROVAL","region.scope.critical_unmanaged_count > 0 and not region.scope.limitations_recorded","region","BLOCK_STAGE","BLOCK_STAGE","UNMANAGED_LIMITATION_MISSING","","관리되지 않은 중요 공정변수가 있으면 검증 주장의 한계를 기록해야 합니다.","","NONE","","D7","SPEC:v6.1§6.D11",POL),
]
write_rules("analysis","design_space_rules.csv",DSR,rows)

REQ="('SETPOINT','BOUNDARY','ROBUSTNESS')"
VR="verification_rules"
rows=[
 R("VR001",1,"verification","WAITING_VERIFICATION_PLAN_APPROVAL","'SETPOINT' not in plan.point_roles or 'BOUNDARY' not in plan.point_roles or 'ROBUSTNESS' not in plan.point_roles","plan","BLOCK_STAGE","BLOCK_STAGE","VERIF_ROLES_MISSING","","필수 확인점(setpoint, boundary, robustness)이 모두 필요합니다.","","NONE","","","SPEC:v6.1§6.D10",POL),
 R("VR018",1,"verification","WAITING_VERIFICATION_PLAN_APPROVAL","verification.pi_policy is None","verification","BLOCK_STAGE","BLOCK_STAGE","VERIF_PI_POLICY_MISSING","","family 예측구간 정책(비교 수, family alpha, 다중성 보정)이 필요합니다.","","NONE","","B5","SPEC:v6.1§6.D10",POL),
 R("VR002",1,"verification","VERIFICATION_GATE","plan.locked_at is None or (verification.first_result_submitted_at is not None and plan.locked_at >= verification.first_result_submitted_at)","plan;verification","BLOCK_STAGE","BLOCK_STAGE","VERIF_NOT_PRELOCKED","","확인계획은 첫 결과 제출 전에 잠겨야 합니다.","locked_hash와 모델·규격·PI 버전 고정","NONE","","A4","SPEC:v6.1§6.D10",POL),
 R("VR012",1,"verification","WAITING_VERIFICATION_PLAN_APPROVAL|VERIFICATION_GATE","verification.results_public_before_lock","verification","BLOCK_STAGE","BLOCK_STAGE","VERIF_RESULTS_PUBLIC_BEFORE_LOCK","","결과가 이미 공개된 배치(문헌 등)는 사전 확인배치가 될 수 없습니다.","REFERENCE_EXISTING으로만 등록","NONE","","A4","SPEC:v6.1§6.D10",POL),
 R("VR003",1,"verification","VERIFICATION_GATE","set_intersects([p.batch_id for p in required_points], model.input_batch_ids) or set_intersects([p.parent_blend_id for p in required_points], fit_blend_ids)","required_points;model;fit_blend_ids","BLOCK_STAGE","BLOCK_STAGE","VERIFICATION_REUSED_IN_FIT","","확인점이 적합 데이터와 독립이 아닙니다 (배치 또는 블렌드 공유).","result_id가 아닌 독립 제조단위 ID로 판정","NONE","","A4","SPEC:v6.1§14.16",POL),
 R("VR013",1,"verification","VERIFICATION_GATE","distinct_count(p.batch_id for p in required_points) < len(required_points)","required_points","BLOCK_STAGE","BLOCK_STAGE","VERIF_BATCH_REUSED_ACROSS_ROLES","","같은 배치를 여러 확인점에 쓸 수 없습니다.","","NONE","","A4","SPEC:v6.1§6.D10",POL),
 R("VR014",1,"verification","VERIFICATION_GATE","len(required_points) == 0 or any(not p.coverage_complete or not p.results_confirmed for p in required_points)","required_points","BLOCK_STAGE","BLOCK_STAGE","VERIF_COVERAGE_INCOMPLETE","","필수 확인점 × 적용 CQA 결과가 모두 확정되어야 합니다.","빈 집합 차단","NONE","","A4","SPEC:v6.1§6.D10",POL),
 R("VR015",1,"verification","VERIFICATION_GATE","any(not evidence_permits(p.evidence_status, 'VERIFICATION') for p in required_points)","required_points","BLOCK_STAGE","BLOCK_STAGE","VERIF_EVIDENCE_NOT_PERMITTED","","문헌·합성·미확인 결과는 확인 판정에 쓸 수 없습니다.","","NONE","","A9","SPEC:v6.1§8.A.2",POL),
 R("VR004",10,"verification","VERIFICATION_GATE",f"point.role in {REQ} and point.spec_pass_all_applicable and point.within_family_pi_all_doe","point","NA","PASS","VERIF_POINT_PASS","","규격 통과, family 예측구간 안입니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D10",POL),
 R("VR005",1,"verification","VERIFICATION_GATE",f"point.role in {REQ} and point.spec_pass_all_applicable and not point.within_family_pi_all_doe","point","NA","INVALIDATE","VERIF_OUTSIDE_PI","RSM_AUGMENTATION","규격은 통과했지만 family 예측구간을 벗어났습니다. 영역을 무효화하고 모델을 보강합니다.","PI는 DOE_RESPONSE만, Bonferroni 동시구간","NONE","","A3, B5","SPEC:v6.1§6.D10",POL),
 R("VR006",1,"verification","VERIFICATION_GATE",f"point.role in {REQ} and not point.spec_pass_all_applicable","point","NA","INVALIDATE","VERIF_SPEC_FAIL","DIAGNOSING","규격 실패입니다. 영역을 무효화하고 진단합니다.","규격은 MONITOR_ONLY 포함 모든 적용 CQA","NONE","","A3","SPEC:v6.1§6.D10",POL),
 R("VR016",20,"verification","VERIFICATION_GATE","point.role == 'REFERENCE_EXISTING' and not (point.spec_pass_all_applicable and point.within_family_pi_all_doe)","point","NA","WARNING","REFERENCE_REVIEW_REQUESTED","","참고 배치가 예측과 다릅니다. 영역에는 영향이 없으며 검토 요청만 생성합니다.","승격·무효화 근거 아님","REASON_ONLY","researcher","A3","SPEC:v6.1§14.25",POL),
 R("VR017",1,"verification","WAITING_VERIFICATION_PLAN_APPROVAL","point.role == 'CHALLENGE' and point.expected_outcome == 'FAIL' and (point.expected_fail_probability is None or point.expected_fail_probability < const.challenge_min_fail_probability)","point","BLOCK_STAGE","BLOCK_STAGE","VERIF_CHALLENGE_EXPECTATION_UNJUSTIFIED","","CHALLENGE 점의 FAIL 예상에는 실패 CQA와 예측 실패확률 근거가 필요합니다.","공동 통과확률 < 0.90 ≠ 실패확률 > 0.5","NONE","","B6","SPEC:v6.1§6.D10",POL),
 R("VR007",10,"verification","VERIFICATION_GATE","point.role == 'CHALLENGE' and point.expected_outcome == 'FAIL' and not point.spec_pass_all_applicable","point","NA","PASS","VERIF_CHALLENGE_CONFIRMED","","음성대조가 예측대로 불합격했습니다 (제한적 추가 근거).","","REASON_ONLY","researcher","","SPEC:v6.1§6.D10",POL),
 R("VR008",20,"verification","VERIFICATION_GATE","point.role == 'CHALLENGE' and point.spec_pass_all_applicable","point","NA","WARNING","VERIF_CHALLENGE_UNEXPECTED_PASS","","음성대조가 통과했습니다. 영역이 보수적일 수 있습니다.","","REASON_ONLY","researcher","","SPEC:v6.1§6.D10",POL),
 R("VR009",1,"verification","WAITING_FINAL_APPROVAL",f"any(p.role not in {REQ} for p in promotion_basis_points)","promotion_basis_points","BLOCK_STAGE","BLOCK_STAGE","VERIF_NON_REQUIRED_IN_BASIS","","승격 근거에는 필수 확인점만 쓸 수 있습니다 (참고·challenge·범위확인 제외).","","NONE","","A3","SPEC:v6.1§14.25",POL),
 R("VR010",1,"verification","WAITING_FINAL_APPROVAL","verification.scope_hash != region.scope_hash","verification;region","BLOCK_STAGE","BLOCK_STAGE","LINEAGE_MISMATCH","WAITING_AUDIT_REVIEW","확인배치 scope가 영역과 다릅니다.","","NONE","","","SPEC:v6.1§6.D10",POL),
 R("VR011",10,"verification","VERIFICATION_GATE","nonempty_all(p.spec_pass_all_applicable and p.within_family_pi_all_doe for p in required_points)","required_points","NA","ROUTE","VERIF_ALL_PASS","WAITING_FINAL_APPROVAL","필수 확인점이 모두 통과했습니다. 최종 승인을 요청합니다.","빈 집합이면 False","REASON_ONLY","researcher","A4","SPEC:v6.1§5.1",POL),
]
write_rules("verification","verification_rules.csv",VR,rows)

# ---------------- #23 routing registry: (reason_code, from_state) → next_state (D1) ----------------
BT = [
 ["MISSING_INPUT","DATA","필수 입력 누락","ENTRY_READINESS","WAITING_REQUIRED_DATA",""],
 ["UNRESOLVED_HARD_FAIL","DATA","상류 Hard Fail 미해소","ENTRY_READINESS","INELIGIBLE",""],
 ["RANGE_MISSING","DATA","요인 범위·근거 누락","FACTOR_READINESS","WAITING_FACTOR_DATA",""],
 ["CATEGORY_PROTOCOL_MISSING","DATA","범주 수준 실행 방법 없음","FACTOR_READINESS","WAITING_FACTOR_DATA",""],
 ["BOUNDS_UNCERTAIN","DESIGN","끝점 제조 가능성 불확실","FACTOR_READINESS","RANGE_FINDING_RUNS","range-finding run은 fitting 제외"],
 ["EMPTY_FACTOR_INTERSECTION","STRATEGY","실행 가능 범위 교집합 없음","FACTOR_READINESS","STRATEGY_REVIEW",""],
 ["DESIGN_RSM_DIRECT","DESIGN","RSM 직행","DESIGN_SELECTION","RSM_PLANNING",""],
 ["UNSAFE_OR_INFEASIBLE_POINT","DESIGN","안전·설비·조성 불가능 점","SCREENING_PLANNING;RSM_PLANNING;RUN_SHEET_COMPILE","DESIGN_REPLAN","plan → REJECTED"],
 ["DESIGN_RANK_DEFICIENT","DESIGN","모형 항 추정 불가","SCREENING_PLANNING;RSM_PLANNING","DESIGN_REPLAN","plan → REJECTED"],
 ["DESIGN_NO_RESIDUAL_DF","DESIGN","잔차 자유도 없음","SCREENING_PLANNING;RSM_PLANNING","DESIGN_REPLAN","plan → REJECTED"],
 ["DESIGN_MIXTURE_SUM_VIOLATED","DESIGN","조성 합계 위반","SCREENING_PLANNING;RSM_PLANNING","DESIGN_REPLAN","plan → REJECTED"],
 ["UNRESOLVED_ALIAS","ANALYSIS","alias 미해소","SCREENING_ANALYSIS","SCREENING_AUGMENTATION",""],
 ["INCONCLUSIVE","ANALYSIS","효과구간이 기준에 걸침","SCREENING_ANALYSIS","SCREENING_AUGMENTATION",""],
 ["FACTOR_REDEFINED","DESIGN","요인 종류·척도 재정의","SCREENING_ANALYSIS","FACTOR_READINESS","FactorDefinition 새 버전"],
 ["CURVATURE_DETECTED","ANALYSIS","곡률 감지","SCREENING_ANALYSIS","RSM_PLANNING",""],
 ["NO_ACTIVE_FACTOR","STRATEGY","활성 요인 없음","SCREENING_ANALYSIS","STRATEGY_REVIEW",""],
 ["HIGH_PURE_ERROR","PROCESS_METHOD","반복 오차 과다","SCREENING_ANALYSIS;MODEL_VALIDATION","DIAGNOSING","model → HOLD"],
 ["MODEL_FLAGGED","ANALYSIS","과적합 의심, 연구자 판단","MODEL_VALIDATION","WAITING_MODEL_APPROVAL",""],
 ["MODEL_INVALID","ANALYSIS","모델 무효(rank, df, LOF)","MODEL_VALIDATION","RSM_AUGMENTATION","model → REJECTED"],
 ["EMPTY_COMMON_REGION","STRATEGY","공동 영역 없음","REGION_COMPUTATION","STRATEGY_REVIEW",""],
 ["VERIF_OUTSIDE_PI","VERIFICATION","규격 통과, family PI 밖","VERIFICATION_GATE","RSM_AUGMENTATION","region → INVALIDATED"],
 ["VERIF_SPEC_FAIL","VERIFICATION","필수 확인점 규격 실패","VERIFICATION_GATE","DIAGNOSING","region → INVALIDATED"],
 ["VERIF_ALL_PASS","VERIFICATION","필수 확인점 모두 통과","VERIFICATION_GATE","WAITING_FINAL_APPROVAL",""],
 ["RUN_DATA_MISSING","DATA","run 설정값 누락","RUN_SHEET_COMPILE","WAITING_RUN_DATA",""],
 ["RESULT_NO_BATCH","DATA","batch_id 없음","RESULT_QUALITY_GATE","WAITING_BATCH_RESULTS",""],
 ["RESULT_SETTING_DEVIATION","DATA","설정 허용오차 이탈","RESULT_QUALITY_GATE","WAITING_BATCH_RESULTS","deviation 기록"],
 ["RESULT_NO_METHOD_VERSION","DATA","시험법 버전 없음","RESULT_QUALITY_GATE","WAITING_BATCH_RESULTS",""],
 ["RESULT_UNIT_UNCLEAR","DATA","단위 변환 불가","RESULT_QUALITY_GATE","WAITING_BATCH_RESULTS",""],
 ["RESULT_REPLICATE_UNKNOWN","DATA","반복 독립성 미상","RESULT_QUALITY_GATE","WAITING_BATCH_RESULTS",""],
 ["RESULT_UNCONFIRMED","DATA","결과 미확인","RESULT_QUALITY_GATE","WAITING_RESULT_CONFIRMATION",""],
 ["UNRESOLVED_DEVIATION","DATA","deviation 미처리","RESULT_QUALITY_GATE","DIAGNOSING","result → EXCLUDED"],
 ["CANDIDATE_PREMISE_FAILURE","STRATEGY","후보 전제 붕괴","WAITING_DIRECTIVE_APPROVAL;STRATEGY_REVIEW","CLOSED_SUPERSEDED","child candidate 이벤트"],
 ["LINEAGE_MISMATCH","GOVERNANCE","lineage·scope 불일치","*","WAITING_AUDIT_REVIEW","복귀 지점 저장"],
 ["UNKNOWN","GOVERNANCE","등록되지 않은 실패","*","WAITING_HUMAN_TRIAGE","복귀 지점 저장"],
]
write_table("verification","backtrack_routing_rules.csv",
 ["reason_code","category","description_ko","from_states","next_state","artifact_side_effect","source_ids"],
 [r + ["SPEC:v6.1§5.3"] for r in BT], POL)
print("g2 v6.1 done")
