from common import *
import os, yaml
from contract import ENTITIES, ROOTS, FUNCTIONS, BACKEND_CAPABILITIES, STATES, ALLOWED_AST

# CQA 템플릿: 응답 정의를 quantity_kind 단위로 분리 (C)
write_table("masters","cqa_templates.csv",
 ["cqa_template_id","name_ko","category","applies_to","default_criticality","quantity_kind","default_acceptance_operator",
  "default_lower","default_upper","unit","criterion_basis","criterion_note_ko","default_test_method_id","source_ids"],
 [
  ["CQA_ASSAY","함량","chemical","tablet","HIGH","percent_label_claim","BETWEEN","","","% label claim","MONOGRAPH","모노그래프 규격 사용 (연구자 입력)","TM_ASSAY_HPLC","SRC_ICH_Q6A"],
  ["CQA_CU_AV","함량균일성(AV)","chemical","tablet","HIGH","acceptance_value","LE","","15","AV","COMPENDIAL_SUMMARY","연구 요약 기준: L1 AV ≤ 15. 약전 판정 절차(단계, 개별값 조건)는 compendial_procedure_ref로 별도","TM_CU_USP905","SRC_USP_905"],
  ["CQA_DISSOLUTION","용출 (시점 %)","performance","tablet","HIGH","percent_dissolved_at_time","GE","","","% dissolved","MONOGRAPH_OR_PROJECT_TARGET","시점과 Q는 연구자 입력. 약전 단계 판정과 구분","TM_DISS_USP711_Q","SRC_USP_711"],
  ["CQA_DISSOLUTION_DE","용출효율 (DE)","performance","tablet","HIGH","dissolution_efficiency","GE","","","DE %","PROJECT_TARGET","약전 규격 없음. 적분 구간·방법 버전 고정","TM_DISS_USP711_DE","SRC_USP_711"],
  ["CQA_DISINTEGRATION","붕해시간","performance","tablet","MEDIUM","time","LE","","","min","COMPENDIAL","약전·모노그래프 기준","TM_DISINT_USP701","SRC_USP_701"],
  ["CQA_DISPERSIBILITY","분산시간","performance","dispersible_tablet","MEDIUM","time","LE","","180","s","COMPENDIAL","Ph. Eur. 분산정: 물(15–25 °C)에서 3분 이내","TM_DISPERS_PHEUR","SRC_PHEUR_TABLETS"],
  ["CQA_FINENESS_OF_DISPERSION","분산 미세도","performance","dispersible_tablet","LOW","pass_fail","PASS_FAIL","","","—","COMPENDIAL","Ph. Eur.: 710 µm 체 통과","TM_FINENESS_PHEUR","SRC_PHEUR_TABLETS"],
  ["CQA_FRIABILITY","마손도","physical_integrity","uncoated_tablet","MEDIUM","percent_weight_loss","LE","","1.0","%","COMPENDIAL","USP <1216>: 평균 중량감소 1.0% (대부분 제품)","TM_FRIAB_USP1216","SRC_USP_1216"],
  ["CQA_BREAKING_FORCE","파괴강도","physical_integrity","tablet","MEDIUM","force","BETWEEN","","","N","PROJECT_TARGET","약전 규격 없음","TM_BREAK_USP1217","SRC_USP_1217"],
  ["CQA_TENSILE_STRENGTH","인장강도","physical_integrity","tablet","MEDIUM","stress","GE","","","MPa","PROJECT_TARGET","파괴강도·치수에서 계산. 계산식 버전 고정","TM_BREAK_USP1217","SRC_USP_1217"],
  ["CQA_TABLET_WEIGHT_RSD","정제 중량편차 (IPC)","physical_integrity","tablet","MEDIUM","rsd","LE","","","% RSD","PROJECT_TARGET","공정 중 관리 지표. <905> 판정과 별개","TM_TABLET_WEIGHT_RSD","SRC_USP_905"],
  ["CQA_IMPURITIES","유연물질","chemical","tablet","HIGH","percent_area","LE","","","%","GUIDELINE","ICH Q3B 기준 (연구자 입력)","TM_IMPURITY_HPLC","SRC_ICH_Q3B"],
  ["CQA_WATER","수분","chemical","tablet","LOW","percent_w_w","LE","","","% w/w","PROJECT_TARGET","제품별","TM_WATER_KF","SRC_ICH_Q6A"],
 ], COMP)

write_table("masters","process_unit_operation_master.csv",
 ["unit_op_code","process_route","order","name_ko","critical","typical_cma","typical_cpp","default_equipment_class","source_ids"],
 [
  ["UO_DC_01","direct_compression","1","칭량","false","","","balance","SRC_AULTON"],
  ["UO_DC_02","direct_compression","2","체질","false","api_psd","sieve_mesh","sieve","SRC_AULTON"],
  ["UO_DC_03","direct_compression","3","주혼합","true","filler_ratio;disintegrant_pct;api_psd","blend_time;blender_speed;fill_level","blender","SRC_AULTON"],
  ["UO_DC_04","direct_compression","4","활택 혼합","true","lubricant_pct","lubrication_time","blender","SRC_AULTON"],
  ["UO_DC_05","direct_compression","5","타정","true","","compression_force;press_speed;punch_geometry","tablet_press","SRC_AULTON"],
  ["UO_DC_06","direct_compression","6","공정 중 검사","false","","","ipc","SRC_AULTON"],
 ], SCI)

# 시험법: 분석 정밀도만. 배치 간 SD는 여기 두지 않음 (B1)
write_table("masters","test_method_registry.csv",
 ["test_method_id","version","name_ko","measures_cqa_template_ids","quantity_kind","compendial_ref","sampling_rule",
  "summary_function","summary_function_version","unit","variance_component_type","repeatability_sd","sd_df",
  "experimental_unit","n_technical_repeats","estimation_method","sd_evidence_status","validation_ref","notes_ko","source_ids"],
 [
  ["TM_DISS_USP711_Q","1","용출 (시점 %)","CQA_DISSOLUTION","percent_dissolved_at_time","USP <711>","{\"n_units\": 6}","mean","1","% dissolved","METHOD_REPEATABILITY","","","","","","UNKNOWN","","실험실 밸리데이션 값 입력 필요","SRC_USP_711"],
  ["TM_DISS_USP711_DE","1","용출효율 (DE)","CQA_DISSOLUTION_DE","dissolution_efficiency","USP <711> 프로파일 + 사다리꼴 적분","{\"n_units\": 6}","DE_trapezoid","1","DE %","METHOD_REPEATABILITY","","","","","","UNKNOWN","","적분 구간 고정","SRC_USP_711"],
  ["TM_FRIAB_USP1216","1","마손도","CQA_FRIABILITY","percent_weight_loss","USP <1216>","{\"rule\": \"≈6.5 g (단위 ≤650 mg) 또는 10정\"}","single","1","%","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_USP_1216"],
  ["TM_BREAK_USP1217","1","파괴강도","CQA_BREAKING_FORCE;CQA_TENSILE_STRENGTH","force","USP <1217>","{\"n_units\": 10}","mean","1","N","METHOD_REPEATABILITY","","","","","","UNKNOWN","","kp 입력 시 N 변환","SRC_USP_1217"],
  ["TM_CU_USP905","1","함량균일성","CQA_CU_AV","acceptance_value","USP <905>","{\"n_units\": 10, \"stages\": \"L1/L2\"}","AV","1","AV","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_USP_905"],
  ["TM_TABLET_WEIGHT_RSD","1","정제 중량편차 (IPC)","CQA_TABLET_WEIGHT_RSD","rsd","내부 IPC","{\"n_units\": 20}","rsd","1","% RSD","METHOD_REPEATABILITY","","","","","","UNKNOWN","","<905> 판정 절차 아님","SRC_USP_905"],
  ["TM_DISINT_USP701","1","붕해시험","CQA_DISINTEGRATION","time","USP <701>","{\"n_units\": 6}","max","1","min","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_USP_701"],
  ["TM_DISPERS_PHEUR","1","분산시간","CQA_DISPERSIBILITY","time","Ph. Eur. Tablets (dispersible)","{\"n_units\": 6}","mean","1","s","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_PHEUR_TABLETS"],
  ["TM_FINENESS_PHEUR","1","분산 미세도","CQA_FINENESS_OF_DISPERSION","pass_fail","Ph. Eur. Tablets (dispersible)","{\"n_units\": 2}","pass_fail","1","—","NOT_APPLICABLE","","","","","","NOT_APPLICABLE","","","SRC_PHEUR_TABLETS"],
  ["TM_ASSAY_HPLC","1","함량 (HPLC)","CQA_ASSAY","percent_label_claim","제품별 밸리데이션","{}","mean","1","%","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_ICH_Q2"],
  ["TM_IMPURITY_HPLC","1","유연물질 (HPLC)","CQA_IMPURITIES","percent_area","제품별 밸리데이션","{}","max_individual;total","1","%","METHOD_REPEATABILITY","","","","","","UNKNOWN","","함량법과 검증 목적 분리","SRC_ICH_Q2;SRC_ICH_Q3B"],
  ["TM_WATER_KF","1","수분 (Karl Fischer)","CQA_WATER","percent_w_w","USP <921>","{}","mean","1","% w/w","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_USP_921"],
  ["TM_FLOW_CARR","1","압축도 지수 (Carr)","","ratio_percent","USP <1174>","{}","single","1","%","METHOD_REPEATABILITY","","","","","","UNKNOWN","","안식각·Hausner는 별도 method로 분리","SRC_USP_1174"],
  ["TM_PSD_LASER","1","입도분포 (레이저 회절)","","length","USP <429>","{}","d10;d50;d90","1","µm","METHOD_REPEATABILITY","","","","","","UNKNOWN","","","SRC_USP_429"],
  ["TM_DSC","1","DSC","","thermal","USP <891>","{}","—","1","—","NOT_APPLICABLE","","","","","","NOT_APPLICABLE","","상호작용 스크리닝","SRC_USP_891"],
 ], COMP)

write_table("masters","excipient_use_range_master.csv",
 ["excipient_id","name_en","name_ko","grade","function","route","dosage_form","process_applicability","range_type","min_pct","max_pct","basis","evidence_claim","citation_locator","source_ids"],
 [
  ["EXU_MCC","Microcrystalline cellulose","미결정셀룰로오스","any","diluent/binder","oral","tablet","DC;WG","TYPICAL_USE","20","90","% w/w of tablet","HPE 모노그래프 사용 범위","HPE 6th ed., MCC monograph (페이지 확인 필요)","SRC_HPE"],
  ["EXU_MANNITOL","Mannitol","만니톨","any","diluent","oral","tablet","DC;WG","TYPICAL_USE","10","90","% w/w","HPE 모노그래프 사용 범위","HPE 6th ed., Mannitol (확인 필요)","SRC_HPE"],
  ["EXU_CROSPOVIDONE","Crospovidone","크로스포비돈","any","disintegrant","oral","tablet","DC;WG","TYPICAL_USE","2","5","% w/w","HPE 모노그래프 사용 범위","HPE 6th ed., Crospovidone (확인 필요)","SRC_HPE"],
  ["EXU_CROSCARMELLOSE","Croscarmellose sodium","크로스카멜로스나트륨","any","disintegrant","oral","tablet","DC;WG","TYPICAL_USE","0.5","5","% w/w","HPE 모노그래프 사용 범위","확인 필요","SRC_HPE"],
  ["EXU_SSG","Sodium starch glycolate","전분글리콜산나트륨","any","disintegrant","oral","tablet","DC;WG","TYPICAL_USE","2","8","% w/w","HPE 모노그래프 사용 범위","확인 필요","SRC_HPE"],
  ["EXU_MGST","Magnesium stearate","스테아르산마그네슘","any","lubricant","oral","tablet","DC;WG","TYPICAL_USE","0.25","5.0","% w/w","HPE 모노그래프 사용 범위","확인 필요","SRC_HPE"],
  ["EXU_SSF","Sodium stearyl fumarate","푸마르산스테아릴나트륨","any","lubricant","oral","tablet","DC;WG","TYPICAL_USE","0.5","2.0","% w/w","HPE 모노그래프 사용 범위","확인 필요","SRC_HPE"],
  ["EXU_SLS","Sodium lauryl sulfate","라우릴황산나트륨","any","lubricant/wetting","oral","tablet","DC","TYPICAL_USE","1.0","2.0","% w/w","HPE 모노그래프 사용 범위 (활택제 용도)","확인 필요","SRC_HPE"],
  ["EXU_TALC","Talc","탈크","any","glidant/lubricant","oral","tablet","DC;WG","TYPICAL_USE","1.0","10.0","% w/w","HPE 모노그래프 사용 범위","확인 필요","SRC_HPE"],
  ["EXU_CSD","Colloidal silicon dioxide","콜로이드성이산화규소","any","glidant","oral","tablet","DC;WG","TYPICAL_USE","0.1","1.0","% w/w","HPE 모노그래프 사용 범위","확인 필요","SRC_HPE"],
 ], SCI)

# 설비 능력만. study 설정(펀치 10 mm, 250 mg)은 Handoff/scope로 이동 (C)
write_table("masters","equipment_capability_master.csv",
 ["equipment_id","equipment_class","model","capability_parameter","min","max","unit","resolution","calibration_ref","evidence_status","notes_ko","source_ids"],
 [
  ["EQ_LX_MIXER","blender","Turbula S27 (Erweka)","batch_volume","","","L","","","UNKNOWN","Lornoxicam 논문 사용 장비. 능력 입력 필요","SRC_ALMOTAIRI_2022"],
  ["EQ_LX_MIXER","blender","Turbula S27 (Erweka)","blend_time","","","min","","","UNKNOWN","설계 범위 5–15분은 study 설정이며 설비 한계 아님","SRC_ALMOTAIRI_2022"],
  ["EQ_LX_PRESS","tablet_press","Erweka EKO 단발","compression_force","","","kN","","","UNKNOWN","논문 미보고","SRC_ALMOTAIRI_2022"],
  ["EQ_LX_PRESS","tablet_press","Erweka EKO 단발","punch_diameter_supported","","","mm","","","UNKNOWN","study는 10 mm 사용 (scope에 기록)","SRC_ALMOTAIRI_2022"],
 ], SCI)

write_table("masters","confirmation_test_master.csv",
 ["test_id","name_ko","purpose_ko","discriminates_between","experimental_unit","nested_structure","typical_design_ko","output_variable","related_reason_codes","source_ids"],
 [
  ["CT_BLEND_UNIF_TIME","혼합시간별 블렌드 균일성","혼합 부족과 과혼합 구별","under_mixing;over_mixing_demixing","blend_sample","시간 > 위치 > 채취","여러 혼합시간에서 blend 샘플링","blend RSD","HIGH_PURE_ERROR;VERIF_SPEC_FAIL","SRC_AULTON"],
  ["CT_LUB_SENSITIVITY","활택 민감도","과활택에 의한 용출·강도 저하 확인","over_lubrication;other","batch","동일 블렌드 분할 (독립 배치 아님)","활택시간 2수준","TS, dissolution","VERIF_SPEC_FAIL","SRC_AULTON"],
  ["CT_COMPACTION_PROFILE","압축 프로파일","압축력–강도–붕해 관계","compression_force_effect;formulation_effect","tablet","블렌드 1개 > 압축력 수준","3–5개 압축력","strength vs force","VERIF_SPEC_FAIL","SRC_USP_1217"],
  ["CT_METHOD_REPEAT","시험법 반복성","시험 편차와 공정 편차 구별","method_variance;process_variance","test_execution","동일 로트 반복 시험","동일 정제 로트 반복","repeatability SD","HIGH_PURE_ERROR","SRC_ICH_Q2"],
  ["CT_RETEST_RETAINED","보관 검체 재시험","측정 오류와 실제 배치 차이 구별","measurement_error;batch_difference","test_execution","원 배치의 재측정 (독립 배치 아님)","보관 검체 재측정","CQA value","VERIF_SPEC_FAIL;HIGH_PURE_ERROR","SRC_ICH_Q2"],
  ["CT_REMAKE_SAME_BLEND","동일 블렌드 재타정","블렌드 문제와 타정 문제 구별","blend_issue;compression_issue","compression_lot","parent_blend 공유 (독립 배치 아님)","보관 블렌드로 재타정","CQA value","VERIF_SPEC_FAIL","SRC_AULTON"],
  ["CT_API_PSD_LOT","API 로트 입도 확인","원료 로트 차이 확인","material_lot;process","material_lot","—","사용 로트 PSD","d10/d50/d90","VERIF_SPEC_FAIL","SRC_USP_429"],
  ["CT_DISINTEGRANT_FUNC","붕해제 기능 확인","붕해제 양·기능 문제 확인","disintegrant_level;other","batch","—","붕해제 수준별 붕해·흡수","disintegration time","VERIF_SPEC_FAIL","SRC_USP_701"],
  ["CT_MOISTURE","수분 확인","흡습에 의한 물성 변화 확인","moisture;other","tablet","—","KF 수분","% water","VERIF_SPEC_FAIL","SRC_USP_921"],
  ["CT_DISS_DISCRIM","용출 판별력 확인","용출법이 처방 차이를 구별하는지 확인","method_discrimination;formulation","batch","—","의도적 변형 처방 비교","profile difference","VERIF_OUTSIDE_PI","SRC_USP_711"],
 ], SCI)

write_table("masters","statistical_sources.csv",
 ["source_id","citation","type","url","used_for","check_status"],
 [
  ["SRC_ICH_Q8","ICH Q8(R2) Pharmaceutical Development (2009)","guideline","https://database.ich.org/sites/default/files/Q8_R2_Guideline.pdf","design space 개념","TO_VERIFY"],
  ["SRC_ICH_Q9","ICH Q9(R1) Quality Risk Management (2023)","guideline","https://database.ich.org/sites/default/files/ICH_Q9%28R1%29_Guideline_Step4_2025_0115_0.pdf","FMEA","TO_VERIFY"],
  ["SRC_ICH_Q6A","ICH Q6A Specifications (1999)","guideline","","CQA 규격","TO_VERIFY"],
  ["SRC_ICH_Q3B","ICH Q3B(R2) Impurities in New Drug Products","guideline","","유연물질","TO_VERIFY"],
  ["SRC_ICH_Q2","ICH Q2(R2) Validation of Analytical Procedures","guideline","https://www.ema.europa.eu/en/ich-q2r2-validation-analytical-procedures-scientific-guideline","시험법 정밀도","TO_VERIFY"],
  ["SRC_ICH_Q1A","ICH Q1A(R2) Stability Testing","guideline","","안정성","TO_VERIFY"],
  ["SRC_ICH_M9","ICH M9 BCS-based Biowaivers","guideline","","BCS","TO_VERIFY"],
  ["SRC_USP_711","USP <711> Dissolution","compendial","","용출","TO_VERIFY"],
  ["SRC_USP_701","USP <701> Disintegration","compendial","","붕해","TO_VERIFY"],
  ["SRC_USP_905","USP <905> Uniformity of Dosage Units","compendial","https://www.usp.org/sites/default/files/usp/document/harmonization/gen-method/q0304_stage_6_monograph_25_feb_2011.pdf","AV, 판정 절차","TO_VERIFY"],
  ["SRC_USP_1216","USP <1216> Tablet Friability","compendial","","마손도","TO_VERIFY"],
  ["SRC_USP_1217","USP <1217> Tablet Breaking Force","compendial","","파괴강도","TO_VERIFY"],
  ["SRC_USP_1174","USP <1174> Powder Flow","compendial","","흐름성","TO_VERIFY"],
  ["SRC_USP_429","USP <429> Light Diffraction Measurement of Particle Size","compendial","","입도","TO_VERIFY"],
  ["SRC_USP_891","USP <891> Thermal Analysis","compendial","","DSC","TO_VERIFY"],
  ["SRC_USP_921","USP <921> Water Determination","compendial","","수분","TO_VERIFY"],
  ["SRC_PHEUR_TABLETS","Ph. Eur. monograph Tablets (0478), dispersible tablets","compendial","","분산시간·미세도","TO_VERIFY"],
  ["SRC_HPE","Rowe RC, Sheskey PJ, Quinn ME. Handbook of Pharmaceutical Excipients, 6th ed. 2009","handbook","","부형제 통상 사용범위 (라이선스 확인)","TO_VERIFY"],
  ["SRC_AULTON","Aulton ME, Taylor KMG. Aulton's Pharmaceutics, 6th ed. 2021","textbook","","공정 실패모드","TO_VERIFY"],
  ["SRC_FDA_IID","FDA Inactive Ingredient Database (+FAQ: maximum potency vs maximum daily exposure)","database","https://www.fda.gov/drugs/drug-approvals-and-databases/inactive-ingredients-approved-drug-products-search-frequently-asked-questions","사용량 이력 참고","TO_VERIFY"],
  ["SRC_MONTGOMERY_DAE","Montgomery DC. Design and Analysis of Experiments. Wiley","textbook","","설계·분석","TO_VERIFY"],
  ["SRC_NIST_HANDBOOK","NIST/SEMATECH e-Handbook of Statistical Methods, Process Improvement","handbook","https://www.itl.nist.gov/div898/handbook/pri/pri.htm","screening, 중심점, 확인 run","TO_VERIFY"],
  ["SRC_NIST_STRD","NIST Statistical Reference Datasets","dataset","https://www.itl.nist.gov/div898/strd/","회귀 정확도 테스트","TO_VERIFY"],
  ["SRC_BOX_WILSON_1951","Box GEP, Wilson KB. J R Stat Soc B. 1951;13:1–45","paper","","CCD","TO_VERIFY"],
  ["SRC_BOX_BEHNKEN_1960","Box GEP, Behnken DW. Technometrics. 1960;2:455–475","paper","https://www.itl.nist.gov/div898/handbook/pri/section3/pri3362.htm","BBD geometry","TO_VERIFY"],
  ["SRC_PLACKETT_BURMAN_1946","Plackett RL, Burman JP. Biometrika. 1946;33:305–325","paper","","PB","TO_VERIFY"],
  ["SRC_JONES_NACHTSHEIM_2011","Jones B, Nachtsheim CJ. J Qual Technol. 2011;43:1–15","paper","","DSD (MVP 미지원)","TO_VERIFY"],
  ["SRC_COOK_1977","Cook RD. Technometrics. 1977;19:15–18","paper","","Cook's distance","TO_VERIFY"],
  ["SRC_PETERSON_2004","Peterson JJ. J Qual Technol. 2004;36:139–153","paper","","확률 기반 다중반응 영역","TO_VERIFY"],
  ["SRC_STATEASE_PRED_R2","Stat-Ease Design-Expert 문서: adj R²와 pred R² 차이 0.2 경험칙","vendor_doc","","과적합 flag","TO_VERIFY"],
  ["SRC_ALMOTAIRI_2022","Almotairi N et al. Pharmaceuticals. 2022;15:1463","paper","https://doi.org/10.3390/ph15121463","데모 데이터 (tests/fixtures)","TO_VERIFY"],
 ], STAT)

entries = [
 ("governance","evidence_governance_rules.csv","table",20),("governance","approval_authority_rules.csv","rule",21),
 ("governance","provenance_versioning_rules.csv","rule",22),("readiness","development_readiness_rules.csv","rule",30),
 ("qbd_risk","qtpp_cqa_mapping_rules.csv","table",40),("qbd_risk","cqa_response_definition_rules.csv","rule",41),
 ("qbd_risk","fmea_failure_mode_rules.csv","table",42),("qbd_risk","fmea_scoring_scale.csv","table",43),
 ("qbd_risk","factor_eligibility_rules.csv","rule",44),("qbd_risk","factor_range_constraint_rules.csv","rule",45),
 ("planning","statistical_policy_constants.csv","table",10),("planning","doe_design_selection_rules.csv","rule",50),
 ("planning","doe_randomization_blocking_rules.csv","rule",51),("planning","doe_design_validation_rules.csv","rule",52),
 ("planning","doe_augmentation_rules.csv","rule",53),("execution","run_sheet_compilation_rules.csv","rule",60),
 ("execution","result_data_quality_rules.csv","rule",61),("analysis","screening_analysis_rules.csv","rule",70),
 ("analysis","model_validation_rules.csv","rule",71),("analysis","design_space_rules.csv","rule",72),
 ("verification","verification_rules.csv","rule",80),("verification","backtrack_routing_rules.csv","table",81),
 ("masters","cqa_templates.csv","master",0),("masters","process_unit_operation_master.csv","master",1),
 ("masters","test_method_registry.csv","master",2),("masters","excipient_use_range_master.csv","master",3),
 ("masters","equipment_capability_master.csv","master",4),("masters","confirmation_test_master.csv","master",5),
 ("masters","statistical_sources.csv","master",6),
]
demo = {"approval_authority_rules","evidence_governance_rules","development_readiness_rules","qtpp_cqa_mapping_rules",
 "cqa_response_definition_rules","fmea_failure_mode_rules","fmea_scoring_scale","factor_eligibility_rules",
 "factor_range_constraint_rules","statistical_policy_constants","doe_design_selection_rules","doe_design_validation_rules",
 "result_data_quality_rules","model_validation_rules","design_space_rules","verification_rules","backtrack_routing_rules",
 "cqa_templates","process_unit_operation_master","test_method_registry","excipient_use_range_master"}
manifest = {
 "id": "07_doe", "version": "6.1", "effective_from": "2026-09-23",
 "evaluator": {"name": "ast_whitelist_v1", "python_eval": False,
               "allowed_ast_nodes": sorted(ALLOWED_AST | {"ListComp"}),
               "generator_rule": "any/all/nonempty_all/sum/count/distinct_count은 generator expression 1개를 받는다. 변수 바인딩은 for 절에만. 빈 컬렉션: any→False, all→True, nonempty_all→False",
               "null_policy": "None과의 비교 외 연산에 None이 들어가면 missing_value_action 적용 (규칙 미발화 아님)",
               "const_namespace": "const.X = statistical_policy_constants.constant_id"},
 "modes": {
   "production": {"enforce_min_validation_status": "APPROVED", "evidence_DEMO_ONLY": "DENY", "namespace": "prod"},
   "demo": {"enforce_min_validation_status": "DRAFT_PENDING_REVIEW", "evidence_DEMO_ONLY": "ALLOW", "namespace": "sandbox",
            "note": "demo 결과는 sandbox에 격리, production artifact로 승격 불가"}},
 "validation_status_order": ["DRAFT_PENDING_REVIEW","UNDER_REVIEW","APPROVED","RETIRED"],
 "backend_capabilities": BACKEND_CAPABILITIES,
 "external_dependencies": [
   {"id": "fda_iid_snapshot", "used_by": ["FR004"], "status": "NOT_BUNDLED",
    "lookup_keys": ["UNII","route","dosage_form","unit"], "note": "없으면 iid_reference_exists → False (규칙 미발화 + NOT_CHECKED 기록)"}],
 "context_schema": {"roots": ROOTS, "entities": ENTITIES},
 "functions": {k: {"arity": v[0], "returns": v[1], "description_ko": v[2]} for k, v in FUNCTIONS.items()},
 "stages": STATES + ["ANY"],
 "entries": [{"id": fn.replace(".csv",""), "file": f"database/07_doe/{folder}/{fn}", "kind": kind,
              "load_order": order, "demo_required": fn.replace(".csv","") in demo,
              "load_enabled": True, "enforcement_enabled": True} for folder, fn, kind, order in entries],
}
header = ("# Formula 1 · 07_doe 룰북 매니페스트 (#1), v6.1\n"
          "# load_enabled: 파일 로드 여부 / enforcement_enabled: 판정 권한. 실제 집행은 modes의 최소 validation_status를 함께 만족해야 함.\n"
          "# 현재 모든 행이 DRAFT_PENDING_REVIEW이므로 production 모드에서는 어떤 규칙도 집행되지 않는다.\n")
os.makedirs(os.path.join(ROOT,"governance"), exist_ok=True)
with open(os.path.join(ROOT,"governance","rulebook_manifest.yaml"),"w",encoding="utf-8") as f:
    f.write(header); yaml.safe_dump(manifest, f, allow_unicode=True, sort_keys=False, width=120)
print("g3 v6.1 done")
