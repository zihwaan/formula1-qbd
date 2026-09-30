"""근거 결손 게이트 값을 말로 받을 때의 결정론 계층(formula/agents/evidence_values.py).

용해도는 pH마다, 투과도는 표현(흡수율·분율·절대 생체이용률·요중 회수율·Papp)과 단위마다 다르다. 관측은 쓰인 그대로 받고
환산·pH 최저값·용량/용해도 부피·투과도 해석은 코드가 한다(ICH M9 5.1·5.2). 숫자·단위는 글에 있어야 옮긴다.
"""

from formula.agents.evidence_values import Observation, normalize, rule_observations


def _sol(value, unit, ph, **kw):
    return Observation(kind="solubility", value=value, unit=unit, ph=ph, **kw)


def test_ph_profile_takes_the_minimum_and_converts_units():
    text = "pH 1.2에서 2.1 mg/mL, 4.5에서 0.35 mg/mL, pH 6.8에서 40 µg/mL (37 °C)"
    r = normalize(rule_observations(text), text, dose_mg=100)
    assert r.measurements == {"solubility_mg_per_ml": 0.04, "dose_solubility_volume": 2500.0}
    assert any("최저값: pH 6.8" in line for line in r.lines)
    assert any("100 mg ÷ 0.04 mg/mL = 2500 mL" in line for line in r.lines)


def test_list_form_is_read_pairwise():
    text = "용해도는 pH 1.2, 4.5, 6.8에서 각각 5, 3, 2 mg/mL"
    obs = rule_observations(text)
    assert [(o.ph, o.value) for o in obs] == [(1.2, 5.0), (4.5, 3.0), (6.8, 2.0)]
    assert normalize(obs, text, dose_mg=200).measurements == {"solubility_mg_per_ml": 2.0, "dose_solubility_volume": 100.0}


def test_high_solubility_needs_every_ph_but_low_is_settled_by_one():
    text = "pH 1.2에서 5 mg/mL, pH 6.8에서 3 mg/mL"
    r = normalize(rule_observations(text), text, dose_mg=100)
    assert r.measurements == {} and any("4.5" in a for a in r.asks)          # 33 mL — 고용해도는 pH 4.5 없이 확정 못 함
    text = "pH 6.8에서 0.02 mg/mL"
    r = normalize(rule_observations(text), text, dose_mg=100)
    assert r.measurements == {"dose_solubility_volume": 5000.0}              # 한 pH에서 250 mL 초과 → 저용해도 확정(하한값)
    assert "solubility_mg_per_ml" not in r.measurements                      # 최저값이 아닐 수 있는 값은 최저 용해도 자리에 넣지 않는다


def test_out_of_range_ph_and_temperature_are_excluded():
    text = "pH 1.2 5 mg/mL, pH 4.5 4 mg/mL, pH 6.8 3 mg/mL, pH 7.4 0.01 mg/mL"
    obs = [_sol(5, "mg/mL", 1.2), _sol(4, "mg/mL", 4.5), _sol(3, "mg/mL", 6.8), _sol(0.01, "mg/mL", 7.4)]
    r = normalize(obs, text, dose_mg=100)
    assert r.measurements["solubility_mg_per_ml"] == 3.0 and any("7.4" in n for n in r.notes)
    text = "25 °C에서 pH 6.8 0.5 mg/mL"
    r = normalize([_sol(0.5, "mg/mL", 6.8, temp_c=25)], text, dose_mg=100)
    assert r.measurements == {} and any("37" in n for n in r.notes)


def test_molar_units_need_the_molecular_weight():
    text = "pH 1.2 10 mM, pH 4.5 5 mM, pH 6.8 1 mM"
    obs = [_sol(10, "mM", 1.2), _sol(5, "mM", 4.5), _sol(1, "mM", 6.8)]
    assert normalize(obs, text, dose_mg=100, mw=200.0).measurements["solubility_mg_per_ml"] == 0.2   # 1 mmol/L × 200 g/mol
    r = normalize(obs, text, dose_mg=100)
    assert r.measurements == {} and any("분자량" in n for n in r.notes)


def test_permeability_expressions():
    text = "절대 생체이용률 0.9, 요중 회수율 88%"
    r = normalize(rule_observations(text), text)
    assert r.measurements["fraction_absorbed"] == 90.0                       # 분율 → %, 여러 근거 중 최댓값(각각 흡수의 하한)
    text = "절대 생체이용률 70%"
    r = normalize(rule_observations(text), text, open_keys={"permeability_evidence_done"})
    assert "fraction_absorbed" not in r.measurements                          # 85% 미만 BA는 저흡수의 근거가 아니다(초회통과)
    assert r.measurements == {"permeability_evidence_done": True} and any("85" in n for n in r.notes)
    text = "Caco-2 Papp 2.1 × 10⁻⁶ cm/s"
    r = normalize(rule_observations(text), text)
    assert r.measurements == {} and any("2.1×10^-6 cm/s" in line and "환산하지 않습니다" in line for line in r.lines)
    text = "PAMPA 350 nm/s"
    assert any("3.5×10^-5 cm/s" in line for line in normalize(rule_observations(text), text).lines)


def test_llm_readings_are_checked_against_the_text():
    text = "pH 1.2: 2.1 mg/mL, pH 4.5: 0.35 mg/mL, pH 6.8: 40 µg/mL"
    r = normalize([_sol(40, "mg/mL", 6.8)], text, dose_mg=100)                # µg/mL를 mg/mL로 읽음(1000배)
    assert r.measurements == {} and "µg/ml" in r.notes[0]
    text = "Caco-2 Papp 2.1 x 10^-6 cm/s"
    assert normalize([Observation(kind="papp", value=2.1, unit="cm/s")], text).lines == []          # 지수 누락
    assert normalize([Observation(kind="papp", value=2.1e-6, unit="cm/s")], text).lines            # 과학 표기는 그대로 인정
    r = normalize([_sol(0.5, "mg/mL", 6.8)], "pH 6.8에서 0.3 mg/mL", dose_mg=100)                    # 글에 없는 숫자
    assert r.measurements == {} and "글에 없는 숫자" in r.notes[0]
    r = normalize([_sol(0.3, "mg/mL", 5.0)], "pH 6.8에서 0.3 mg/mL", dose_mg=100)                    # 글에 없는 pH
    assert r.measurements == {} and "pH" in r.notes[0]


def test_number_pool_keeps_list_items_and_thousands():
    from formula.agents.evidence_values import number_pool
    pool = number_pool("pH 1.2,4.5,6.8에서 2.1,0.35,0.04 mg/mL · 1,000 µg/mL · 2.1 × 10⁻⁶ cm/s")
    assert {0.35, 0.04, 1000.0}.issubset(pool) and any(abs(x - 2.1e-6) < 1e-15 for x in pool)
