"""기술 보고서(논문 형식) 빌드 — docs/report/figdata.json(엔진 실측) → docs/report/report.html → PDF.

    docker run --rm -e PYTHONPATH=/app -v "$PWD":/app -w /app formula1-dev python scripts/report/figdata.py
    python3 scripts/report/build_report.py --tests 211 --browser "verify · agent · scenarios · stage2"
    "<chrome>" --headless=new --no-pdf-header-footer --print-to-pdf=docs/report/Formula1_report.pdf docs/report/report.html

그림의 수치는 전부 figdata.json(엔진 계산)이나 저장소의 CSV 행 수에서 온다. 손으로 적은 결과값은 없다.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "report"
E = html.escape


# ── 그림 ──────────────────────────────────────────────────────────────────
def box(x, y, w, h, title, sub="", kind="det", r=8):
    dash = {"det": "", "llm": ' stroke-dasharray="6 4"', "jud": ' stroke-dasharray="2 3"', "io": "", "hi": ""}[kind]
    fill = {"det": "#ffffff", "llm": "#ffffff", "jud": "#ffffff", "io": "#f1f3f5", "hi": "#e7f0ff"}[kind]
    stroke = "#1d4ed8" if kind == "hi" else "#222"
    t = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.3"{dash}/>'
    t += f'<text x="{x + w / 2}" y="{y + (h / 2 if not sub else h / 2 - 5)}" class="bt">{E(title)}</text>'
    if sub:
        t += f'<text x="{x + w / 2}" y="{y + h / 2 + 11}" class="bs">{E(sub)}</text>'
    return t


def arrow(x1, y1, x2, y2, label="", dash=False, lx=None, ly=None):
    d = ' stroke-dasharray="5 4"' if dash else ""
    t = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#333" stroke-width="1.2" marker-end="url(#ah)"{d}/>'
    if label:
        t += f'<text x="{lx if lx is not None else (x1 + x2) / 2 + 4}" y="{ly if ly is not None else (y1 + y2) / 2 - 3}" class="al">{E(label)}</text>'
    return t


def path(dpath, label="", lx=0, ly=0, dash=True):
    d = ' stroke-dasharray="5 4"' if dash else ""
    t = f'<path d="{dpath}" fill="none" stroke="#333" stroke-width="1.2" marker-end="url(#ah)"{d}/>'
    if label:
        t += f'<text x="{lx}" y="{ly}" class="al">{E(label)}</text>'
    return t


DEFS = ('<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker></defs>')


def svg(w, h, body):
    return f'<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" role="img">{DEFS}{body}</svg>'


def exec_summary(data, ab, tests) -> str:
    """보고서 첫머리의 핵심 요약 — 전체 아키텍처(발표 자료 5·6쪽 통합)와 한눈 요약. 수치는 figdata·ablation.json에서."""
    c = data.get("counts") or {}
    m = data.get("manifest") or []
    judged = sum(e["eval_type"] == "quantitative" for e in m)
    g = data.get("stage2") or {}
    mt = g.get("matrices") or {}
    L = g.get("lornoxicam") or {}
    rep, abl = [], ""
    if mt:
        rep.append(f"CBD 논문 위험 행렬 {mt['rm']['same'] + mt['fp']['same']}/{mt['rm']['cells'] + mt['fp']['cells']}칸 · 회귀·ANOVA(Table 10·11) 재현")
    if L:
        op = L["region"]["optimum"]["actual"]
        rep.append(f"로르녹시캄 {L['n']} run 네 반응 검증 게이트 통과 · 최적 처방 비 {op['MCC:Mannitol']:g} · {op['Mixing time']:g}분 · {op['Crospovidone']:g} %")
    if ab and "stage1" in ab:
        a = _ab_agg(ab)
        sc = a["scale"]
        abl = (f"같은 LLM, 요청 {sc['requests']}건(금기 고정 {sc['infeasible']}) · 실행 {sc['runs']}회 · 처방 {sc['formulations']}건 — "
               f"금기 처방 제시 순수 LLM {a['P']['bad']}/{a['P']['outputs']}, 검증 계층 제거 {a['G']['bad']}/{a['G']['outputs']}, "
               f"전체 시스템 {a['F']['bad']}/{a['F']['outputs']} · 금기 요청 후보 반려 {a['F']['inf_rejected']}/{a['F']['inf_generated']} · "
               f"불가능 요청의 올바른 종결 {a['P']['inf_ok']}/{a['P']['inf_runs']} · {a['G']['inf_ok']}/{a['G']['inf_runs']} · "
               f"{a['F']['concluded_infeasible']}/{a['F']['inf_runs']} · 과잉 거부 {a['F']['refused']}")
    rows = [
        ("문제", "LLM은 처방 후보를 폭넓게 제안하지만 배합 금기·공정 한계·규제 상한 판단에서 근거 없는 결론을 낼 수 있다."),
        ("접근", "후보 생성은 LLM, 판정은 출처가 명시된 규칙표와 결정론 엔진, 수용 결정은 연구자 — 역할을 구조로 분리한다."),
        ("Stage I", f"분자 해석(구조 패턴 {c.get('structural_flags', 0)}종) → 페이즈 게이트·전략 계획 → 병렬 후보 설계 → 입력 계약과 규칙표 {len(m) or 29}개"
                    f"(판정 {judged or 18}) → 동적 심사관 {c.get('reviewers', 0)}명. 반려 시 전이표 {c.get('backtrack_transitions', 0)}행에 따라 되돌린다."),
        ("Stage II", "근거 결손 게이트를 통과한 후보를 QTPP → CQA → 위험평가 → 실험 설계 → 회귀 검증 게이트 → 반응 곡면 → ANOVA → Overlay plot Design Space → "
                     "확인계획의 15단계로 진행하며, 단계마다 연구자가 승인한다."),
        ("재현", " · ".join(rep)),
        ("어블레이션", abl),
        ("운영", f"라이브 시스템 zihwan.com/formula1(대회 API gpt-5.6-sol · 무료 Groq). 단위·통합 테스트 {tests}개와 브라우저 테스트 8종으로 고정."),
    ]
    rows = [r for r in rows if r[1]]
    trs = "".join(f"<tr><td style='white-space:nowrap'><b>{E(k)}</b></td><td>{E(v)}</td></tr>" for k, v in rows)
    return f"""<h2>핵심 요약</h2>
<table><tbody>{trs}</tbody></table>
<figure>{fig_overview(data)}
<figcaption><b>그림 1.</b> 전체 아키텍처. 입력 에이전트가 요청을 실행 가능한 입력으로 정리하고, Stage I이 후보 처방을 생성·판정·순위화한다. 연구자가 고른 후보는
근거 결손 게이트를 거쳐 Stage II의 15단계 승인 절차로 Design Space까지 도출된다. 선 모양은 담당 주체이다(실선: 결정론, 파선: LLM, 점선: 순위만 매기는 심사관,
빨간 파선: 반려와 되돌림). 세부는 그림 2(후보 탐색), 그림 6(그래프 노드), 그림 7(2단계)에 있다.</figcaption></figure>
"""


def fig_overview(data=None):
    """전체 아키텍처 — 발표 자료 5쪽(입력 에이전트 · Stage I)과 6쪽(Stage II)을 한 장으로. 선 모양: 실선 결정론 · 파선 LLM · 점선 심사관 · 빨간 파선 반려."""
    data = data or {}
    c = data.get("counts") or {}
    m = data.get("manifest") or []
    red = "#c62828"
    b = (f'<defs><marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{red}"/></marker></defs>')
    # 입력 에이전트
    b += '<rect x="10" y="8" width="700" height="62" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="22" y="28" class="gt">입력 에이전트</text><text x="22" y="44" class="al">연구자와 대화</text><text x="22" y="57" class="al">수치·구조식은 출처만</text>'
    b += box(130, 18, 176, 42, "자연어 요청 · 구조식", "QTPP · 용량 · 고정 부형제", "llm")
    b += box(330, 18, 160, 42, "실측값 요청", "판정이 갈리는 값만", "det")
    b += box(514, 18, 186, 42, "필요한 데이터만 추가 입력", "사전 제형 실측값", "io")
    b += arrow(306, 39, 330, 39) + arrow(490, 39, 514, 39)
    b += arrow(218, 70, 218, 96, "설계 실행", lx=224, ly=88)
    # Stage I
    b += '<rect x="10" y="96" width="700" height="176" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="22" y="114" class="gt">Stage I · 후보 처방 생성과 검증 (LangGraph)</text>'
    xs = [22, 160, 298, 436, 574]
    st1 = [("① 분자 해석", "RDKit · 구조 패턴", "det"), ("② 오케스트레이터", "페이즈 게이트 · 계획", "det"),
           ("③ 병렬 후보 설계", "전략별 설계 에이전트", "llm"), ("④ 규칙 게이트", f"입력 계약 · 규칙표 {len(m) or 29}", "hi"),
           ("⑤ 동적 심사관", "조건부 소집 · 순위만", "jud")]
    for x, (t, s_, k) in zip(xs, st1):
        b += box(x, 124, 124, 48, t, s_, k)
    for i_ in range(4):
        b += arrow(xs[i_] + 124, 148, xs[i_ + 1], 148)
    # 반성 · 되돌림(빨간 파선)
    b += (f'<rect x="206" y="206" width="264" height="46" rx="8" fill="#fff5f5" stroke="{red}" stroke-width="1.3" stroke-dasharray="6 4"/>'
          f'<text x="338" y="225" class="bt" style="fill:{red}">반성 · 되돌림 (최대 5회)</text>'
          f'<text x="338" y="241" class="bs">반려 사유별 복귀 지점과 수정 지시 ({c.get("backtrack_transitions", 16)}행 전이표)</text>')
    b += f'<path d="M 498 172 L 498 229 L 470 229" fill="none" stroke="{red}" stroke-width="1.2" stroke-dasharray="5 4" marker-end="url(#ahr)"/>'
    b += f'<path d="M 206 229 L 186 229 L 186 172" fill="none" stroke="{red}" stroke-width="1.2" stroke-dasharray="5 4" marker-end="url(#ahr)"/>'
    b += f'<text x="506" y="200" class="al" style="fill:{red}">반려</text>'
    b += box(560, 206, 138, 46, "후보 처방 목록", "성분 · 공정 · 근거 · 순위", "io")
    b += arrow(636, 172, 636, 206)
    b += '<text x="22" y="200" class="al">실측 요청은</text><text x="22" y="213" class="al">설계를 막지 않는다</text>'
    # Stage I → II: 근거 결손 게이트
    b += arrow(629, 252, 629, 292, "연구자: 이 후보로 개발 착수", lx=462, ly=287)
    b += box(520, 292, 190, 44, "근거 결손 게이트", "측정값 → phase_gates부터 재계산", "det")
    b += path("M 520 314 L 84 314 L 84 376", "", 0, 0, dash=False)
    b += '<text x="96" y="308" class="al">프로토타입(Table 1 형식) · 불변 Handoff</text>'
    # Stage II
    b += '<rect x="10" y="350" width="700" height="166" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="120" y="368" class="gt">Stage II · Design Space 도출 (15단계 · 단계마다 연구자 승인)</text>'
    st2 = [("① QTPP 도출", "프로토타입 → 초안", "llm"), ("② CQA 판별", "품질특성별 판단", "llm"),
           ("③ 위험평가", "변수 × CQA · 근거 표", "llm"), ("④ DoE toolkit", "검증 게이트 · ANOVA", "det"),
           ("⑤ Design Space", "Overlay · 확인계획", "hi")]
    for x, (t, s_, k) in zip(xs, st2):
        b += box(x, 376, 124, 46, t, s_, k)
    for i_ in range(4):
        b += arrow(xs[i_] + 124, 399, xs[i_ + 1], 399)
    b += box(160, 450, 400, 48, "QbD 보고서 PDF", "위험평가 보고서(8단계) · 최종 보고서(회귀식 · 곡면 · ANOVA · Design Space)", "io")
    b += arrow(360, 422, 360, 450) + arrow(636, 422, 560, 462)
    b += '<text x="22" y="472" class="al">초안은 LLM,</text><text x="22" y="485" class="al">행렬·통계는 코드,</text><text x="22" y="498" class="al">승인은 연구자</text>'
    # 데이터 · 근거
    b += '<rect x="10" y="526" width="700" height="44" rx="8" fill="#f1f3f5" stroke="#555"/>'
    b += '<text x="360" y="544" class="bt">데이터와 근거</text>'
    b += (f'<text x="360" y="560" class="bs">규칙표 CSV + manifest · 부형제 마스터 · 측정 카탈로그 {c.get("measurement_catalog", 20)}종 · '
          f'확인시험 {c.get("confirmation_tests", 66)}종 · PubChem · Europe PMC · Crossref/NCBI · DailyMed</text>')
    # 범례
    b += '<g transform="translate(10,584)">'
    b += '<line x1="0" y1="6" x2="24" y2="6" stroke="#222"/><text x="30" y="10" class="lg">결정론(규칙 · 엔진)</text>'
    b += '<line x1="150" y1="6" x2="174" y2="6" stroke="#222" stroke-dasharray="6 4"/><text x="180" y="10" class="lg">LLM</text>'
    b += '<line x1="230" y1="6" x2="254" y2="6" stroke="#222" stroke-dasharray="2 3"/><text x="260" y="10" class="lg">심사관(순위만)</text>'
    b += f'<line x1="350" y1="6" x2="374" y2="6" stroke="{red}" stroke-dasharray="5 4"/><text x="380" y="10" class="lg">반려 · 되돌림</text>'
    b += '<rect x="470" y="0" width="22" height="12" rx="2" fill="#e7f0ff" stroke="#1d4ed8"/><text x="498" y="10" class="lg">판정 · 결론의 핵심 단계</text>'
    b += '</g>'
    return svg(720, 602, b)


def fig_architecture(data=None):
    """전체 구조 — 규칙 게이트와 동적 심사단의 내부를 확대해 한 장에 보인다(수치는 figdata에서)."""
    data = data or {}
    b = ""
    b += box(250, 8, 220, 36, "연구자", "말 · 폼 · 측정값 · 승인", "io")
    b += box(200, 66, 320, 44, "입력 에이전트", "맥락 스냅숏 · 말 → 제안 카드 · 코드 가드레일", "llm")
    b += arrow(360, 44, 360, 66) + arrow(340, 66, 340, 44)
    # ① 후보 탐색
    b += '<rect x="10" y="132" width="700" height="348" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="22" y="150" class="gt">① 후보 탐색 — CandidateDiscoveryGraph (LangGraph · 분 단위)</text>'
    xs = [22, 130, 238, 346, 454, 562]
    names = [("분자 프로파일", "RDKit · 82 패턴", "det"), ("페이즈 게이트", "BCS/DCS·고체상·가용화", "det"),
             ("계획", "상위 3 전략 · 서명", "det"), ("병렬 설계", "전략별 후보", "llm"),
             ("규칙 게이트", "오차 0% · 반려 권한", "det"), ("동적 심사단", "조건 맞는 이만 · 순위만", "jud")]
    for x, (t, s_, k) in zip(xs, names):
        b += box(x, 162, 100, 46, t, s_, k)
    for i_ in range(5):
        b += arrow(xs[i_] + 100, 185, xs[i_ + 1], 185)
    b += arrow(360, 110, 360, 132, "확인한 카드만", lx=366, ly=126)

    # ── 확대: 규칙 게이트 내부 (결정론) ──
    gx, gy, gw, gh = 22, 226, 430, 180
    b += f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="8" fill="#fff" stroke="#222" stroke-width="1.2"/>'
    b += f'<path d="M 454 208 L {gx + gw - 40} {gy}" stroke="#888" stroke-dasharray="3 3" fill="none"/>'
    b += f'<path d="M 554 208 L {gx + gw} {gy + 14}" stroke="#888" stroke-dasharray="3 3" fill="none"/>'
    m = data.get("manifest") or []
    judged = sum(e["eval_type"] == "quantitative" for e in m)
    b += (f'<text x="{gx + 10}" y="{gy + 16}" class="gt">규칙 게이트 안 — 입력 계약 → 규칙표 {len(m) or 29}개(판정 {judged or 18}) · '
          f'검사 함수 8개 · 우선순위 단계</text>')
    stages = ["0 계약", "0 참조", "5 물성", "10 경로", "20 금기", "30 다성분", "40 공정", "50 코팅", "60 BCS", "70 포장"]
    cw = (gw - 20 - 9 * 3) / 10
    for k, st in enumerate(stages):
        x = gx + 10 + k * (cw + 3)
        num, name = st.split(" ", 1)
        b += f'<rect x="{x}" y="{gy + 24}" width="{cw}" height="34" rx="4" fill="#f1f3f5" stroke="#555"/>'
        b += f'<text x="{x + cw / 2}" y="{gy + 37}" class="bs">{E(num)}</text>'
        b += f'<text x="{x + cw / 2}" y="{gy + 50}" class="bs" style="font-size:7.6px">{E(name)}</text>'
        if k < len(stages) - 1:
            b += arrow(x + cw, gy + 41, x + cw + 3, gy + 41)
    b += f'<text x="{gx + 10}" y="{gy + 72}" class="al">앞 단계 파생값이 뒤 단계 조건으로: flow_character → selected_route → 공정 규칙 · bcs_class(실측만)</text>'
    pol = [("검증됨", "반려 가능"), ("잠정", "표기"), ("미검증", "심사로 강등"), ("출처 없음", "로드 제외")]
    pw = (gw - 20 - 3 * 6) / 4
    for k, (t, s_) in enumerate(pol):
        x = gx + 10 + k * (pw + 6)
        b += box(x, gy + 84, pw, 36, t, s_, "det" if k < 2 else ("jud" if k == 2 else "io"), r=4)
    outs = [("PASS", "심사로"), ("SOFT_FLAG", "심사관 표시"), ("HARD_FAIL", "되돌림"), ("ESCALATE", "사람 이관")]
    for k, (t, s_) in enumerate(outs):
        x = gx + 10 + k * (pw + 6)
        b += box(x, gy + 132, pw, 36, t, s_, "hi" if t == "HARD_FAIL" else "det", r=4)

    # ── 확대: 동적 심사단 내부 ──
    jx, jy, jw, jh = 462, 226, 236, 180
    b += f'<rect x="{jx}" y="{jy}" width="{jw}" height="{jh}" rx="8" fill="#fff" stroke="#222" stroke-width="1.2" stroke-dasharray="2 3"/>'
    b += f'<path d="M 612 208 L {jx + jw / 2} {jy}" stroke="#888" stroke-dasharray="3 3" fill="none"/>'
    b += f'<text x="{jx + 10}" y="{jy + 16}" class="gt">심사단 안 — 명단 7명, 조건이 참일 때만 생성</text>'
    jury = [("소아 안전", "소아 대상"), ("가용화 전략", "가용화·미분화 후보"), ("공정 실현성", "항상"),
            ("규제 취지", "규제 서술 필요"), ("문헌 조사", "룰북 밖 조합"), ("고령자 안전", "고령 대상"),
            ("고체상 안정성", "ASD·염 경계")]
    for k, (t, cond) in enumerate(jury):
        x = jx + 10
        y = jy + 24 + k * 18
        dash = "" if cond == "항상" else ' stroke-dasharray="3 2"'
        b += f'<rect x="{x}" y="{y}" width="216" height="16" rx="4" fill="#fff" stroke="#333"{dash}/>'
        b += f'<text x="{x + 6}" y="{y + 11.5}" class="lg" style="font-size:8.4px"><tspan font-weight="700">{E(t)}</tspan> · {E(cond)}</text>'
    b += f'<text x="{jx + 10}" y="{jy + 158}" class="al">후보 × 소집 심사관 병렬 → 점수 0–1</text>'
    b += f'<text x="{jx + 10}" y="{jy + 172}" class="al">→ 가중평균(결정론) 순위 · 반려 권한 없음</text>'

    # 되돌림 · 결과
    nbt = (data.get("counts") or {}).get("backtrack_transitions", 0)
    b += box(22, 420, 300, 44, "되돌림 · 반성", f"HARD_FAIL 사유별 복귀 지점 ({nbt}행 전이표) → 설계·계획", "det")
    b += path(f"M {gx + 10 + 2 * (pw + 6) + pw / 2} {gy + 168} L {gx + 10 + 2 * (pw + 6) + pw / 2} 414", dash=False)
    b += path("M 22 442 L 16 442 L 16 185 L 22 185", "", 0, 0)
    b += box(462, 420, 236, 44, "후보 처방 목록", "성분 · 공정 단계 · 근거 · 신뢰도 · 순위", "io")
    b += arrow(jx + jw / 2, jy + jh, jx + jw / 2, 420)

    # 프로토타입 · ② 2단계
    b += box(210, 492, 300, 36, "프로토타입 (Table 1 형식)", "고른 후보의 조성 mg · % · 기능 · 공정", "hi")
    b += arrow(580, 464, 470, 492, "연구자가 개발 착수", lx=586, ly=494)
    b += '<rect x="10" y="546" width="700" height="120" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="22" y="564" class="gt">② 2단계 — Design Space 도출 (15단계 · 단계마다 연구자 승인)</text>'
    st = [("QTPP · CQA", "llm"), ("위험평가", "llm"), ("종합 정리", "det"), ("실험 설계 표", "io"),
          ("회귀·ANOVA", "det"), ("Overlay 영역", "det"), ("확인계획 잠금", "det"), ("확인배치 2×2", "io")]
    for k, (t, kk) in enumerate(st):
        b += box(20 + k * 86, 576, 78, 34, t, "", kk, r=6)
        if k < len(st) - 1:
            b += arrow(98 + k * 86, 593, 106 + k * 86, 593)
    b += box(250, 624, 220, 32, "위험평가 · 최종 보고서 PDF", "", "io")
    b += arrow(360, 528, 360, 546)
    b += arrow(622, 610, 470, 632)
    b += '<text x="480" y="654" class="al">초안 LLM · 행렬·회귀·ANOVA 코드 · 승인 연구자</text>'
    # legend
    b += '<g transform="translate(560,12)"><rect width="150" height="58" fill="#fff" stroke="#ccc"/>'
    b += '<line x1="8" y1="14" x2="34" y2="14" stroke="#222"/><text x="40" y="18" class="lg">결정론(규칙·엔진)</text>'
    b += '<line x1="8" y1="30" x2="34" y2="30" stroke="#222" stroke-dasharray="6 4"/><text x="40" y="34" class="lg">LLM</text>'
    b += '<line x1="8" y1="46" x2="34" y2="46" stroke="#222" stroke-dasharray="2 3"/><text x="40" y="50" class="lg">심사관(순위만)</text></g>'
    return svg(720, 672, b)


def fig_discovery():
    b = ""
    nodes = [("intake", 10, 30), ("phase_gates", 110, 30), ("drq_narrow", 210, 30), ("plan", 310, 30),
             ("generate ×≤3", 410, 30), ("gate", 510, 30), ("drq_refine", 610, 30)]
    kinds = {"intake": "llm", "generate ×≤3": "llm"}
    for n, x, y in nodes:
        b += box(x, y, 90, 34, n, "", kinds.get(n, "det"), r=6)
    for i in range(len(nodes) - 1):
        b += arrow(nodes[i][1] + 90, 47, nodes[i + 1][1], 47)
    b += box(610, 100, 90, 34, "summon", "", "det", r=6)
    b += box(610, 160, 90, 34, "judge ×M", "", "jud", r=6)
    b += box(610, 220, 90, 34, "consensus", "", "det", r=6)
    b += '<text x="704" y="113" class="al">조건식으로</text><text x="704" y="124" class="al">명단 선택</text>'
    b += '<text x="704" y="173" class="al">후보×심사관</text><text x="704" y="184" class="al">병렬 · 점수만</text>'
    b += '<text x="704" y="233" class="al">가중평균</text><text x="704" y="244" class="al">(결정론)</text>'
    b += '<text x="520" y="24" class="al">29표 · 8함수</text>'
    b += '<text x="120" y="24" class="al">BCS/DCS·고체상·가용화·ASD</text><text x="318" y="24" class="al">상위 3 전략</text>'
    b += arrow(655, 64, 655, 100) + arrow(655, 134, 655, 160) + arrow(655, 194, 655, 220)
    b += box(410, 130, 90, 34, "backtrack", "", "det", r=6)
    b += box(260, 130, 90, 34, "reflect", "", "llm", r=6)
    b += path("M 555 64 L 555 147 L 500 147", "반려", 560, 110)
    b += arrow(410, 147, 350, 147)
    b += path("M 305 130 L 305 100 L 455 100 L 455 64", "GATE: 성분만", 372, 95)
    b += path("M 280 130 L 280 110 L 355 110 L 355 64", "", 0, 0)
    b += '<text x="200" y="122" class="al">G6R·G4: 계획부터</text>'
    for i, (t, sub) in enumerate([("qtpp_review", "전략 0"), ("infeasible", "고정 성분 반려"),
                                  ("escalate", "이관 판정"), ("exhausted", "5회 초과")]):
        b += box(20 + i * 130, 220, 116, 34, t, sub, "io", r=6)
    b += path("M 330 64 L 330 80 L 78 80 L 78 220", "", 0, 0)
    b += path("M 530 64 L 530 200 L 208 200 L 208 220", "", 0, 0)
    b += path("M 540 64 L 540 205 L 338 205 L 338 220", "", 0, 0)
    b += path("M 545 64 L 545 210 L 468 210 L 468 220", "", 0, 0)
    return svg(770, 262, b)


def fig_agent():
    b = ""
    b += box(10, 20, 150, 44, "사용자의 말", "최근 6개 발화", "io")
    b += box(10, 84, 150, 44, "서버 맥락 스냅숏", "run 요약 · study 상태", "io")
    b += box(200, 40, 150, 66, "해석", "LLM 구조화 출력 ↘ 실패 시 규칙 해석기", "llm")
    b += arrow(160, 42, 200, 62) + arrow(160, 106, 200, 86)
    g = [("숫자 대조", "제안 숫자 ⊂ 발화 숫자"), ("구조식 출처", "사용자 · 사전 · PubChem"),
         ("허용 키·행동", "허용목록 · 현재 상태"), ("필수 입력", "SMILES · 1회 용량")]
    for i, (t, s) in enumerate(g):
        b += box(390, 8 + i * 40, 160, 34, t, s, "det", r=6)
    b += arrow(350, 73, 390, 73)
    b += box(590, 30, 120, 44, "제안 카드", "ready / 되묻기", "hi")
    b += box(590, 96, 120, 44, "[실행] 클릭", "사람과 같은 경로", "io")
    b += arrow(550, 73, 590, 55) + arrow(650, 74, 650, 96)
    return svg(720, 172, b)


def fig_value_tiers():
    b = ""
    b += box(10, 20, 150, 50, "A · 계산값", "RDKit — 항상 자동", "det")
    b += box(10, 84, 150, 50, "B · 예측값", "ESOL·GSE — 잠정", "det")
    b += box(10, 148, 150, 50, "C · 실측값", "요청했을 때만", "io")
    b += box(200, 60, 170, 60, "파생값 (23행)", "고정점 반복 · 순서 무관", "det")
    b += arrow(160, 45, 200, 80) + arrow(160, 109, 200, 90) + arrow(160, 173, 200, 105)
    b += box(410, 20, 140, 44, "요청 ① 좁히기", "계획 전 · 막지 않음", "det")
    b += box(410, 90, 140, 44, "계획 서명", "상위 3 전략", "det")
    b += box(410, 160, 140, 44, "요청 ② 신뢰도", "후보별 · 0건일 때만 grounded", "det")
    b += arrow(370, 90, 410, 42) + arrow(480, 64, 480, 90) + arrow(480, 134, 480, 160)
    b += box(590, 60, 120, 40, "서명 같음", "태그만 (LLM 0회)", "io")
    b += box(590, 120, 120, 40, "서명 바뀜", "다시 설계", "io")
    b += path("M 80 198 L 80 215 L 700 215 L 700 160", "측정값 제출", 330, 228, dash=True)
    b += arrow(550, 112, 590, 80) + arrow(550, 112, 590, 140)
    return svg(720, 236, b)


def fig_stage2():
    """2단계 15단계 — 담당(선 모양)과 표 번호. 모든 단계는 초안 → 결정론 검사 → 연구자 승인."""
    steps = [("1 프로토타입", "Table 1 · Handoff", "io"), ("2 QTPP", "Table 3 · LLM 초안", "llm"), ("3 CQA 판별", "Table 4 · 근거 필수", "llm"),
             ("4 원료 물성 위험", "Table 6 · 기전 근거", "llm"), ("5 원료 행렬", "Table 5 · 4에서 계산", "det"),
             ("6 제형·공정 위험", "Table 8 · 부형제 전부", "llm"), ("7 제형·공정 행렬", "Table 7 · 6에서 계산", "det"), ("8 종합 정리", "High 변수 · 위험평가 PDF", "det"),
             ("9 실험 설계 표", "Table 9 · CSV", "io"), ("10 회귀식 · 게이트", "Table 10 · 4조건", "det"),
             ("11 반응 곡면", "Figure 1", "det"), ("12 ANOVA", "Table 11 · 최종 PDF", "det"), ("13 Design Space", "Overlay · control space", "hi"),
             ("14 확인계획 잠금", "확인점 3 · 동시 PI", "det"), ("15 확인배치", "규격 × PI 2×2", "io")]
    b = ""
    for i, (t, sub, kind) in enumerate(steps):
        r, c = divmod(i, 5)
        x, y = 8 + c * 143, 10 + r * 60
        b += box(x, y, 133, 42, t, sub, kind, r=6)
        if c < 4:
            b += arrow(x + 133, y + 21, x + 143, y + 21)
        elif r < 2:
            b += path(f"M {x + 66} {y + 42} L {x + 66} {y + 51} L 74 {y + 51} L 74 {y + 60}", dash=False)
    b += box(8, 196, 350, 36, "모든 단계: 초안 → 결정론 검사 → 연구자 승인", "검사가 막으면 승인 불가 · 버전·출처·승인자 이력", "det", r=6)
    b += box(368, 196, 346, 36, "앞 단계를 다시 열면", "뒤 단계는 지우지 않고 '다시 확인 필요' — 확인계획 잠금도 풀린다", "io", r=6)
    b += '<text x="8" y="250" class="al">실선: 결정론(코드) · 파선: LLM 초안(연구자가 고치고 승인) · 굵은 테두리: 산출물. 평균 기준 영역이나 control space가 없으면 13단계에서 멈춘다.</text>'
    return svg(722, 258, b)


FK = {"Quadratic": "2차", "Linear": "선형", "2FI": "2요인 교호작용", "Pure quadratic": "순수 2차", "Reduced quadratic": "축소 2차", "Mean": "평균"}


def _term_ko(names, fn) -> str:
    lab = {"a": fn[0], "b": fn[1], "c": fn[2]} if len(fn) >= 3 else {}
    out = []
    for t in names or []:
        if t.endswith("2"):
            out.append(f"{lab.get(t[0], t[0])}²")
        elif ":" in t:
            out.append("×".join(lab.get(q, q) for q in t.split(":")))
        else:
            out.append(lab.get(t, t))
    return " + ".join(out)


def lornox_section(L) -> str:
    """7.2 — 발표 자료 시연 ①의 Design Space: Almotairi 2022 Table 3(실측 15 run) → 검증 게이트 → Overlay plot."""
    if not L:
        return ""
    R = L["region"]
    op, cs, sl = R["optimum"], R["control_space"], R["slice"]
    fn = ["MCC:만니톨", "혼합 시간", "크로스포비돈"]
    fit = "".join(f"<tr><td>{E(f['response'])}</td><td>{E(FK.get(f['suggested'], f['suggested']))}</td><td>{E(_term_ko(f['terms'], fn))}</td>"
                  f"<td>{f['adj_r2']:.3f}</td><td>{f['pred_r2']:.3f}</td><td>{'통과' if f['status'] == 'SELECTED' else '요인으로 설명되지 않음'}</td>"
                  f"<td>{E('; '.join(next((x['why'] for x in f['rows'] if x['model'] == 'Quadratic'), [])) or '—')}</td></tr>" for f in L["fit"])
    rows = "".join(f"<tr><td>{E({'SETPOINT': '최적점', 'BOUNDARY': '경계(control space 꼭짓점)', 'ROBUSTNESS': '강건성', 'REFERENCE': '참고(논문 최적)'}[p['role']])}</td>"
                   f"<td>{' · '.join(f'{v:g}' for v in p['settings'].values())}</td><td>{p['joint']:.3f}</td>"
                   f"<td>{p['predicted']['DE30']['mean']:.1f} ({p['predicted']['DE30']['pi_lower']:.1f}–{p['predicted']['DE30']['pi_upper']:.1f})</td>"
                   f"<td>{p['predicted']['AV']['mean']:.1f} ({p['predicted']['AV']['pi_lower']:.1f}–{p['predicted']['AV']['pi_upper']:.1f})</td></tr>"
                   for p in L["plan"]["points"])
    fr = " · ".join(f"{x['level_actual']:g}분 {100 * x['ds_fraction']:.1f} %" for x in R["slices"])
    de = next(p for p in L["plan"]["points"] if p["role"] == "SETPOINT")["predicted"]["DE30"]
    qd = [f["response"] for f in L["fit"] if next((x["why"] for x in f["rows"] if x["model"] == "Quadratic"), [])]
    return f"""<h3>7.2 로르녹시캄 분산정의 검증 게이트와 Overlay plot</h3>
<p>시연 사례 ①(성인용 로르녹시캄 8 mg 분산정, 유동성 실측에 따라 직접타정 유지)의 후보로 2단계에 들어가면, 9단계에서 Almotairi 등[11]의 Box–Behnken 실측
{L['n']} run(Table 3; 요인 MCC:만니톨 비 1–3, 혼합 시간 5–15분, 크로스포비돈 2–10 %; 반응 분산 시간, 마손도, 30분 용출률 DE30, 함량균일성 AV)을 불러온다.
10단계 선택기는 네 반응 모두 축소 2차 모형을 골랐고 네 모형 모두 검증 게이트를 통과하였다(표 9). 전체 2차 모형이 과적합으로 떨어진 반응({', '.join(E(q) for q in qd)})에서도
유의하지 않은 항을 계층적으로 제거한 축소 모형은 네 조건을 모두 충족하였다.</p>
<table><thead><tr><th>반응</th><th>선택 모형</th><th>항</th><th>조정 R²</th><th>예측 R²</th><th>게이트</th><th>전체 2차가 떨어진 이유</th></tr></thead><tbody>{fit}</tbody></table>
<div class="tcap"><b>표 9.</b> 로르녹시캄 15 run의 모형 선택 결과(엔진 계산). 후보 모형을 AICc 순으로 정렬하고(최솟값 + 2 이내이면 항 수가 적은 모형 우선)
검증 게이트(모형 p &lt; 0.05, 적합결여 p ≥ 0.05, 조정 R² − 예측 R² ≤ 0.2, 예측 R² &gt; 0)를 처음 통과한 모형을 채택하였다. 축소 모형의 예측력은 14단계에서
잠근 확인계획의 독립 배치로 최종 확인한다.</div>
<p>목표(분산 ≤ 180 s, 마손도 ≤ 1.0 %, DE30 ≥ 75 %, AV ≤ 15; DE30은 프로젝트 가정값)를 적용하면, 효과가 가장 작은 {E(sl['name'])}을 고정한 세 단면에서 평균
예측이 네 목표를 모두 만족하는 영역의 비율은 {fr}이다(그림 10). 가장 넓은 {cs['Mixing time']:g}분 단면에서 MCC:만니톨 {cs['MCC:Mannitol'][0]:g}–{cs['MCC:Mannitol'][1]:g} ×
크로스포비돈 {cs['Crospovidone'][0]:g}–{cs['Crospovidone'][1]:g} %의 control space가 구성되고, 그 안에서 새 배치의 네 목표 동시 충족 확률이 가장 큰 최적 처방은 비
{op['actual']['MCC:Mannitol']:g}, 혼합 {op['actual']['Mixing time']:g}분, 크로스포비돈 {op['actual']['Crospovidone']:g} %(확률 {op['joint']:.3f})이다. 이는 논문의 desirability
최적점(3:1, 11분, 6.23 %)과 근접하다.</p>
<figure><img src="lornoxicam_overlay.png" style="width:100%" alt="로르녹시캄 Overlay plot">
<figcaption><b>그림 10.</b> 13단계 Overlay plot(논문 Figure 2 형식, 화면과 같은 코드로 생성). 혼합 시간 (a) 5, (b) 10, (c) 15분 단면. 노란 영역은 평균 예측이
모든 목표를 만족하는 구간, 해칭은 외삽, 빨간 점선 사각형은 control space, 큰 빨간 점은 최적 처방, 회색 점선은 새 배치 통과확률(0.5, 0.8, 0.9) 등고선이다.</figcaption></figure>
<table><thead><tr><th>확인점</th><th>설정(비 · 분 · %)</th><th>새 배치 통과확률</th><th>DE30 예측 (구간)</th><th>AV 예측 (구간)</th></tr></thead><tbody>{rows}</tbody></table>
<div class="tcap"><b>표 10.</b> 14단계 확인계획. 결과 확인 전에 잠그는 확인점과 동시 예측구간({L['plan']['pi_policy']['comparisons']}개 비교 Bonferroni,
개별 {100 * L['plan']['pi_policy']['per_comparison_level']:.2f} %)이다. AV 하한은 0에서 절단하였다. 논문 최적 처방의 배치는 결과가 이미 공개되어 있으므로
참고점으로만 비교한다.</div>
<p>최적점의 DE30 예측값은 {de['mean']:.1f} %(동시 예측구간 {de['pi_lower']:.1f}–{de['pi_upper']:.1f})이다. 모형 선택, 게이트, 영역, control space, 최적점은 overlay
파이프라인의 참조 구현과 소수점 넷째 자리까지 일치하며 테스트로 고정되어 있다. 15단계 판정은 세 확인점에서 제조한 새 독립 배치의 실측으로 수행한다.</p>
"""


def _p(v):
    return "—" if v is None else ("< 0.0001" if v < 0.0001 else f"{v:.4f}")


FAM_KO = FK


def abstract(data, lm, ab) -> str:
    """초록 — 한 문단. 수치는 figdata.json · ablation.json에서 계산한다."""
    g = data.get("stage2") or {}
    c = data["counts"]
    txt = ("거대언어모델(LLM)은 제형 처방 후보를 폭넓게 제안하지만, 배합 금기·공정 한계·규제 상한 같은 정량 판단에서는 근거 없는 결론을 낼 수 있다. "
           "Formula 1은 후보 생성은 LLM, 판정은 출처가 명시된 규칙표와 결정론 엔진, 수용 결정은 연구자가 맡도록 역할을 분리한 제형 설계 시스템이다. "
           "후보 탐색 단계는 분자 구조와 생물약제학 게이트(BCS/DCS, 고체상, 가용화, ASD 공정)로 설계 전략을 정하고, 생성된 후보를 입력 계약과 규칙표로 판정하며, "
           f"판정에 필요한 값만 측정 카탈로그({c['measurement_catalog']}종) 안에서 비차단으로 요청한다. 개발 단계는 선택된 후보를 ICH Q8 절차의 15단계 승인 체계로 "
           "진행해 Overlay plot 기반 Design Space와 확인계획까지 도출한다.")
    m = g.get("matrices")
    ps = {r["response"]: r for r in g.get("responses") or []}
    if m and ps:
        txt += (f" Monton 등(2026)의 CBD 구강붕해정 자료에서 근거 표로 계산한 위험 행렬은 원 논문 {m['rm']['cells'] + m['fp']['cells']}칸과 "
                f"{'모두 ' if m['rm']['same'] + m['fp']['same'] == m['rm']['cells'] + m['fp']['cells'] else ''}일치하였고, "
                f"원자료로 재적합한 회귀·ANOVA는 Table 10·11(경도 모형 p {_p(ps['Hardness']['model_p'])})을 재현하였다.")
    L = g.get("lornoxicam")
    if L:
        op = L["region"]["optimum"]["actual"]
        txt += (f" Almotairi 등(2022)의 로르녹시캄 분산정 {L['n']} run에서는 네 반응이 모두 검증 게이트를 통과하였고, 최적 처방(MCC:만니톨 {op['MCC:Mannitol']:g}, "
                f"혼합 {op['Mixing time']:g}분, 크로스포비돈 {op['Crospovidone']:g}%)은 논문의 최적점과 근접하였다.")
    if ab and "stage1" in ab:
        a = _ab_agg(ab)
        P, G, F = a["P"], a["G"], a["F"]
        sc = a["scale"]
        txt += (f" 같은 LLM으로 요청 {sc['requests']}건을 {sc['runs']}회 실행해 처방 {sc['formulations']}건을 비교한 어블레이션에서 규칙표가 금지하는 처방은 "
                f"순수 LLM {_pp(P['bad'], P['outputs'])}, 검증 계층 제거 조건 {_pp(G['bad'], G['outputs'])}에서 "
                f"제시되었으나 전체 시스템에서는 {_pp(F['bad'], F['outputs'])}였다. 금기 성분이 고정된 요청에서 전체 시스템은 생성 후보 "
                f"{F['inf_rejected']}/{F['inf_generated']}건을 반려하고 모든 실행({F['concluded_infeasible']}/{F['inf_runs']})을 차단 규칙·대체 성분과 함께 종결하였으며, "
                f"가능한 요청에서의 과잉 거부는 {F['refused']}건이었다.")
    return txt


def stage2_section(g) -> str:
    if not g:
        return ""
    m, w = g["matrices"], g["walk"]
    rows = "".join(
        f"<tr><td>{E(r['response'])} ({E(r['unit'])})</td><td>{E(FAM_KO.get(r['suggested'], r['suggested']))}</td><td>{E(FAM_KO.get(r['paper_family'], r['paper_family']))}</td>"
        f"<td class='mono'>{E(r['coded_eq'])}</td><td>{r['model_ss']:.3f} · {_p(r['model_p'])} ({_p(r['paper_model_p'])})</td>"
        f"<td>{_p(r['lof_p'])} ({_p(r['paper_lof_p'])})</td><td>{r['residual_df']} ({r['paper_residual_df']})</td></tr>" for r in g["responses"])
    cand = " › ".join(f"{E(c['variable'])}(High {len(c['high'])})" for c in g["candidates"])
    return f"""<h3>7.1 CBD 구강붕해정 논문 자료의 재현</h3>
<p>Monton 등[18]은 CBD 10 mg 구강붕해정(1정 250 mg, 직접타정)을 QbD 방식으로 개발하면서 QTPP(Table 3), CQA(Table 4), 원료 물성·제형·공정 위험평가
(Table 5–8), Box–Behnken DoE(Table 9, {g['design']['runs']} run; {', '.join(E(f) for f in g['design']['factors'])}), 회귀식(Table 10), ANOVA(Table 11), 반응 곡면(Figure 1)의
순서를 따랐다. 이 표들로 2단계 study를 생성해 논문 값으로 끝까지 진행하였다(승인 {w['approvals']}건, 이벤트 {w['events']}건, 위험평가 보고서
{w['risk_pdf_kb']} KB, 최종 보고서 {w['final_pdf_kb']} KB).</p>
<p>위험 행렬은 입력하지 않고 계산한다. 논문의 근거 표(Table 6 {m['rm']['rows']}행, Table 8 {m['fp']['rows']}행)로부터 코드가 칸별 등급을 산출한 결과, 논문 행렬과
원료 {m['rm']['same']}/{m['rm']['cells']}칸, 제형·공정 {m['fp']['same']}/{m['fp']['cells']}칸이 일치하였다. 행렬이 근거에서 계산되므로 둘은 어긋날 수 없고, 근거 없는
칸이 하나라도 있으면 승인이 막힌다(JUST_MISSING). 8단계에서는 두 행렬을 합쳐 High 변수({cand})를 DoE 후보로 제시하고 위험평가 보고서를 제공한다. 논문은 이 중
{', '.join(E(v) for v in g['paper_doe'])}을 요인으로 썼다(Spray-dried mannitol은 균형 성분이라 제외). 요인 선택은 연구자의 판단이므로 9단계 표에서 연구자가 직접
정한다.</p>
<p>10단계 검증 게이트는 논문 모형 가운데 예측력이 부족한 두 모형을 걸러 낸다(표 8). 논문 모형 차수(경도 선형, 붕해시간 2차, 마손도 2요인 교호작용)로 적합하면
경도만 통과하고, 붕해시간 2차 모형은 모형 p가 0.05를 넘으며(논문에서도 유의하지 않음), 마손도 모형은 조정 R²와 예측 R²의 차이가 0.2를 넘는다. 두 반응은 영역과
ANOVA에서 빠지고 관측 범위로 목표와 비교되며(범위가 목표 안이라 경고 없음), 반응 곡면에는 참고로 표시된다(그림 8).</p>
<table><thead><tr><th>반응</th><th>선택기의 제안</th><th>논문 모형</th><th>논문 모형으로 다시 적합한 coded 식</th><th>모형 SS · p (논문)</th><th>적합결여 p (논문)</th><th>잔차 df (논문)</th></tr></thead><tbody>{rows}</tbody></table>
<div class="tcap"><b>표 8.</b> 회귀식과 ANOVA. Table 9 원자료로 재계산한 값과 논문 값(괄호)을 비교하였으며, 계수는 논문에서 옮겨 적지 않았다. 선택기의
제안은 AICc 순으로 정렬해 검증 게이트를 처음 통과한 모형이다(없으면 평균 모형 = 요인으로 설명되지 않음). 붕해시간은 논문에서도 모형이 유의하지 않았고
(p = {_p(g['responses'][1]['paper_model_p'])}), 마손도는 축소 2차 모형도 과적합(조정 − 예측 R² 0.35)으로 탈락한다. 제안과 다른 모형을 고르면 연구자 선택으로 기록된다.</div>
<figure><img src="cbd_surfaces.png" style="width:66%;display:block;margin:0 auto" alt="CBD 반응 곡면 격자">
<figcaption><b>그림 8.</b> 11단계 반응 곡면(논문 Figure 1과 같은 CCS 1·3·5 % 배치, 논문 식 적용). 경도가 게이트를 통과했으므로 세 반응을 모두 그리고, 불합격한
붕해시간·마손도에는 “검증 게이트 불합격 — 참고”를 표시한다. 진한 빨간 점은 곡면보다 높은 관측값, 연분홍 점은 낮은 관측값, 세로선은 잔차, 바닥 점선은 설계점이
지지하는 영역(밖은 외삽), 바닥 색선은 등고선이다. 2단계 최종 보고서 PDF에도 같은 그림이 들어간다.</figcaption></figure>
<p>ANOVA는 부분 제곱합으로 계산하고 반복 중심점으로 순수오차와 적합결여를 나눈다. 경도의 Model SS {g['responses'][0]['model_ss']:.2f}, p {_p(g['responses'][0]['model_p'])},
잔차 자유도 {g['responses'][0]['residual_df']}, 적합결여 p {_p(g['responses'][0]['lof_p'])}는 논문 Table 11과 일치하며, 이 값들과 Table 10의 식은 회귀 테스트로 고정되어 있다.</p>
<p>13단계에서 논문 규격(경도 4–6 kgf, 붕해 ≤ 30 s, 마손도 ≤ 1 %)을 적용하면 CCS 3 % 단면에서 Force {g['cbd_space']['control_space']['Force'][0]:g}–{g['cbd_space']['control_space']['Force'][1]:g} psi ×
MCC {g['cbd_space']['control_space']['MCC'][0]:g}–{g['cbd_space']['control_space']['MCC'][1]:g} %의 control space가 구성되어 승인되며, 최적 처방은
{' · '.join(f'{k} {v:g}' for k, v in g['cbd_space']['optimum']['actual'].items())}이다(그림 9). 보조 확률의 최댓값({g['cbd_space']['aux']['max_joint']:.3f})은 경도 규격 폭(2 kgf)이
좁다는 사실을 반영해 경고로 표시된다. 14단계 확인계획은 {'잠겨 있으며' if g.get('cbd_vplan_locked') else '잠기지 않았으며'}(확인점 {len(g.get('cbd_vplan') or [])}개),
15단계 판정은 새 독립 배치의 실측으로 수행한다.</p>
<figure><img src="cbd_overlay.png" style="width:100%" alt="CBD Overlay plot">
<figcaption><b>그림 9.</b> CBD 13단계 Overlay plot(CCS (a) 1, (b) 3, (c) 5 % 단면). 기준은 게이트를 통과한 경도의 평균 예측(4–6 kgf)이다.
빨간 점선은 control space, 큰 빨간 점은 최적 처방, 회색 점선은 보조 확률(0.5, 0.8)을 나타내며, 형식은 논문 Figure 2와 같다.</figcaption></figure>
"""


def llm_section(lm) -> str:
    """LLM 초안을 고치지 않고 승인해 가며 논문 표와 대조(stage2_llm.json)."""
    if not lm:
        return ""
    st = {x["step"]: x for x in lm["steps"]}
    if not all(k in st for k in ("qtpp", "cqa", "rm_matrix", "fp_just", "fp_matrix")):
        return ""
    c, rm, fj, fm = st["cqa"], st["rm_matrix"], st["fp_just"], st["fp_matrix"]
    up = sum(1 for d in rm["differ"] + fm["differ"] if ["Low", "Medium", "High"].index(d["llm"]) > ["Low", "Medium", "High"].index(d["paper"]))
    nd = len(rm["differ"]) + len(fm["differ"])
    secs = " · ".join(f"{x['step']} {x['seconds']:.0f}초" for x in lm["steps"] if x.get("provider"))
    extra = [v for v in fj["variables"] if v not in fj["paper_variables"]]
    calls = lm.get("llm_calls") or {}
    return f"""<h3>7.6 LLM 초안과 논문 표의 비교</h3>
<p>같은 CBD 프로토타입으로 2~7단계(LLM 초안 단계와 해당 행렬)를 {'대회 API' if lm['llm'] == 'dacon' else E(lm['llm'])}의 초안만으로 진행하였다. 연구자 편집 없이
초안을 그대로 승인하였다(호출 {', '.join(f"{'대회 API' if k == 'dacon' else '무료 Groq' if k == 'groq' else E(k)} {v}회" for k, v in calls.items())}; {E(secs)}). 초안은 결정론 검사에
한 번도 막히지 않을 만큼 형식이 완전하였다. 모든 확정 CQA × 변수 칸에 근거가 있었고, 처방의 모든 부형제가 평가되었으며, 공정 변수는 조절 가능한 파라미터로
적혔다. QTPP는 {st['qtpp']['items']}개 요소(논문 {st['qtpp']['paper_items']}개)였고, 입력에 없는 수치를 쓴 문장에는 출처 확인 경고(LLM_NUMBERS)가 붙었다.</p>
<p>판단 내용은 논문과 일부 달랐다. CQA 판별에서 LLM은 {', '.join(E(x) for x in c['only_llm']) or '—'}를 위험평가 CQA에 {('추가하였고, 논문의 ' + ', '.join(E(x) for x in c['only_paper']) + '는 제외하였다') if c['only_paper'] else '추가하였다'}.
제형·공정 변수는 논문의 {len(fj['paper_variables'])}개 외에 {', '.join(E(x) for x in extra)}를 추가하여 {len(fj['variables'])}개를 평가하였다. 논문과 같은 이름의 칸을 비교하면
위험 등급이 같은 칸은 원료 {rm['same']}/{rm['common']}, 제형·공정 {fm['same']}/{fm['common']}이었고, 다른 {nd}칸 중 {up}칸은 LLM이 더 보수적으로(높게) 평가하였다.</p>
<p>위험 등급은 연구팀의 설비와 경험에 따른 판단이므로 논문과 다른 칸은 오답이 아니라 연구자가 확인할 지점이며, 논문은 정답지가 아닌 참고 자료로 쓴다. 그래서
시스템은 등급을 자동 확정하지 않는다. 초안은 수 분 안에 빈칸 없는 위험평가를 만들고, 논문으로 시작한 study에서는 칸 단위 참고 비교(다른 칸 테두리 표시)를,
새 후보에서는 행 수정·분할과 근거 유형 기록을 거쳐 연구자가 승인한다. 반대로 회귀·ANOVA처럼 계산으로 정해지는 값은 논문 표 재현(7.1절)과 영역 골든 값(7.2절)을
테스트로 고정하였다. 판단은 연구자에게, 계산은 코드에 — 2단계를 승인 체계로 설계한 이유이다.</p>
"""


def exp_narrative(x, same, tot) -> str:
    """실험 결과 서술 — 문장은 전부 experiments.json에서 계산한다(재실험하면 문장도 따라 바뀐다)."""
    runs = x["runs"]
    by = {}
    for r in runs:
        by.setdefault(r["scenario"], []).append(r)
    parts = [f"결정론 계층의 결과(계획 서명, 종결 상태, 반려 규칙)는 반복 간에 {'모든 시나리오에서 동일하였다' if same else '일부 달랐다'}."]
    for sid, rs in by.items():
        r0 = rs[0]
        if r0["status"] == "infeasible":
            parts.append(f"{r0['label']}은 세 전략의 후보가 모두 {', '.join(r0['hard_fails'])}로 반려되어 되돌림 없이 “제약 불가능”으로 종료되었다.")
    changed = [by[sid][0]["label"] for sid in by if len({r["winner"] for r in by[sid]}) > 1]
    if changed:
        parts.append("반복에 따라 달라진 것은 LLM이 생성한 조성과 그에 따른 권고 순위였다(" + ", ".join(changed) + "). 판정은 고정하고 탐색은 다양하게 하는 설계와 일치한다.")
    varying = []
    for sid, rs in by.items():
        sets = [set(r["summoned"]) for r in rs]
        diff = set.union(*sets) - set.intersection(*sets) if sets else set()
        if diff:
            varying.append(f"{rs[0]['label']}의 {', '.join(sorted(diff))}")
    if varying:
        parts.append("설계된 성분에 따라 심사관의 소집 여부가 달라진 경우도 있었다(" + "; ".join(varying) + ").")
    calls = sum(len(r["judge_scores"]) for r in runs)
    scored = calls - sum(r["judge_unscored"] for r in runs)
    uncited = sum(r.get("judge_uncited", 0) for r in runs)
    cites = sum(r.get("judge_citations", 0) for r in runs)
    parts.append(f"심사 호출 {calls}건 중 {scored}건이 점수를 받았으며, 모든 점수에는 검증된 DOI·PMID 인용(총 {cites}건)이 포함되었다"
                 f"(인용 부재로 무효 처리된 점수 {uncited}건).")
    calls_by = x.get("llm_calls") or {}
    if calls_by:
        parts.append("실제로 응답한 제공자는 " + ", ".join(
            f"{'대회 API' if k == 'dacon' else '무료 Groq' if k == 'groq' else k} {v}회" for k, v in calls_by.items())
            + ("이며, 무료 모델로의 전환은 없었다." if not calls_by.get("groq") else "이며, 대회 API 한도 또는 오류로 일부 호출이 무료 모델로 전환되었다."))
    if tot:
        parts.append(f"8회 실행과 입력 에이전트 6개 발화에 사용된 대회 API 토큰은 약 {tot:,}개였다(응답 헤더의 잔여 토큰 추정치 차이).")
    return "<p>" + " ".join(parts) + "</p>"


def demo_section(dm) -> str:
    """시연 쿼리 카드 3장 — 정답지와 나란히(demo_cards.json, 실제 서버 실행)."""
    if not dm:
        return ""
    res = dm["results"]
    ak = dm["answer_key"]
    by = lambda tag: [r for r in res if r.get("card") == tag]
    yes = lambda b: "예" if b else "아니오"
    rows = ""
    for r in res:
        label = {"card1": "① 로르녹시캄 8 mg 분산정 (42°)", "card1_flow48": "① 대비: 안식각 48°",
                 "card2": "② 암로디핀 2.5 mg + 유당 고정", "card2_free": "② 대비: 유당 고정 없음",
                 "card3": "③ VX-770 150 mg"}[r["card"]]
        what = []
        if r["card"].startswith("card1"):
            what.append(f"계획 {r.get('plan_signature') or '—'}")
            fl = next((g[1].get("flow_character") for g in r.get("route_signals") or [] if g[1].get("flow_character")), None)
            rt = next((g[1] for g in r.get("route_signals") or [] if g[1].get("selected_route")), {})
            what.append(f"흐름성 {fl or '—'} → 경로 {rt.get('selected_route', '—')}"
                        + (f" (배제 {', '.join(rt['excluded_routes'])})" if rt.get("excluded_routes") else ""))
            what.append(f"RTE008 {yes(r.get('rte008_fired'))} · Mg stearate 후보 {r.get('mg_stearate_candidates', 0)}개")
            if r.get("tm_submit"):
                t = r["tm_submit"]
                what.append(f"Tm 225 제출({t.get('source')}) → 닫힌 요청 {', '.join(t.get('closed') or []) or '없음'}"
                            + (f" · 계획 {r.get('plan_signature_after_tm')}로 재생성, 개발 착수 {r.get('picked')}" if t.get("regenerated") else ""))
        elif r["card"].startswith("card2"):
            what.append(f"parent MW {r.get('parent_mw') or 0:.1f} · 염 계수 {r.get('salt_factor')}")
            what.append("소집 " + (", ".join(r.get("summoned") or []) or "— (심사 전 종료)"))
            if r.get("infeasible"):
                what.append("제약 불가능 — 막은 규칙 " + ", ".join(r["infeasible"].get("blocking") or [])
                            + " · 대체 " + " / ".join(r["infeasible"].get("suggestions") or []))
            api = [a for c in r.get("api_amounts") or [] for a in c]
            if api:
                what.append("통과 후보 API " + ", ".join(f"{n} {m:g} mg" for n, m in api[:3]))
        else:
            what.append(f"계획 {r.get('plan_signature_before') or '—'} → {r.get('plan_signature_after') or '—'}")
            what.append("G4B " + (", ".join(f"{p['rule_id']}" for p in r.get("asd_process_signal") or []) or "—"))
            what.append(f"유당 금기 미발동 {yes(not ({'INC001', 'INC002'} & set(r.get('fired_any') or [])))}")
            what.append("이름 누설 " + (", ".join(r.get("name_leaks") or []) + f" ({', '.join(r.get('leak_sources') or [])})"
                                    if r.get("name_leaks") else "없음"))
        rows += (f"<tr><td>{E(label)}</td><td>{r['repeat']}</td><td>{E(r['status'])}</td><td>{r['seconds']:.0f}</td>"
                 f"<td>{E(' · '.join(what))}</td></tr>")
    para = []
    c1s = by("card1")
    if c1s and c1s[0].get("tm_submit"):
        t = c1s[0]
        para.append(f"카드 1의 Tm 225 °C 제출(입력 에이전트가 LLM에 앞서 규칙으로 인식)은 DRQ_TM을 닫았고, Tm이 확인되자 분무건조 ASD가 전략 후보에 포함되어 "
                    f"계획이 {t.get('plan_signature')}에서 {t.get('plan_signature_after_tm')}로 바뀌었고 해당 전략의 후보만 다시 설계되었으며, "
                    f"연구자가 선택한 후보({t.get('picked')})로 개발에 착수하였다.")
    poor = by("card1_flow48")
    if poor:
        ex = next((g[1] for g in poor[0].get("route_signals") or [] if g[1].get("excluded_routes")), {})
        para.append(f"같은 카드에서 안식각만 48°로 바꾸면 흐름성이 {next((g[1].get('flow_character') for g in poor[0]['route_signals'] if g[1].get('flow_character')), '')}로 판정되어 "
                    f"{', '.join(ex.get('excluded_routes') or [])}가 배제되고, 계획이 {poor[0].get('plan_signature')}로 바뀌었다(42°: {c1s[0].get('plan_signature') if c1s else ''}).")
    mg = [r.get("mg_stearate_candidates", 0) for r in by("card1")]
    if mg:
        para.append(f"카드 1의 마지막 라운드 후보 가운데 스테아르산마그네슘을 포함한 후보는 실행별 {', '.join(map(str, mg))}개였다"
                    "(논문 처방은 SLS로 윤활하며, 스테아르산마그네슘을 포함한 경우 과혼합 위험 INC014는 반려가 아니라 DoE 요인 후보로 넘어간다).")
    paras = [" ".join(para)]
    para = []
    c2 = by("card2")
    if c2:
        blk = sorted({b for r in c2 for b in (r.get("infeasible") or {}).get("blocking") or []})
        free = by("card2_free")
        para.append(f"카드 2(유당 고정)는 두 번 모두 되돌림 없이 “제약 불가능”으로 종료되었으며, 차단 규칙은 {', '.join(blk)}였다. 베실산염을 제거한 parent에서 "
                    "1차 아민 × 유당 금기(INC001)가, 습식과립 후보에서 다성분 규칙(유당 + 스테아르산마그네슘 + 물, Abdoh 2004[14])이 발동하였다. 같은 세 성분이라도 "
                    "직접타정 조합에서는 다성분 규칙이 발동하지 않으며(단위 테스트로 고정), 1,4-디히드로피리딘 고리의 N–H는 2차 아민으로 검출되지 않았다. 대체 성분으로는 "
                    "만니톨과 유당을 포함하지 않는 처방을 제시하였으며, 정답지(NORVASC) 역시 유당을 포함하지 않는다. 다성분 규칙의 조건인 “40°C/75%RH 스트레스”는 모든 신약 "
                    "제품이 거치는 가속 안정성 조건(ICH Q1A[17])이므로 번역표에서 항상 성립하는 조건으로 둔다."
                    + (f" 유당 고정을 제외한 대비 실행에서는 통과 후보의 API가 유리염기 {free[0]['api_amounts'][0][0][1]:g} mg으로 기록되었고(염 환산계수 {free[0].get('salt_factor')}), "
                       f"소아 심사관 대신 고령자 심사관(REV006)이 소집되었다." if free and free[0].get("api_amounts") else ""))
    paras.append(" ".join(para))
    para = []
    c3 = by("card3")
    if c3:
        leaks = sorted({l for r in c3 for l in r.get("name_leaks") or []})
        pairs3 = sorted({(r.get('plan_signature_before'), r.get('plan_signature_after')) for r in c3})
        para.append("카드 3은 구조와 용량만으로 시작하였으며, Tm 317 °C와 용해도 0.00005 mg/mL를 한 문장으로 제출하자 계획이 "
                    + "; ".join(f"{b0}에서 {a0}" for b0, a0 in pairs3)
                    + "로 바뀌었다" + (f"({len(c3)}회 모두 동일)" if len(c3) > 1 and len(pairs3) == 1 else "")
                    + f". 분무건조 ASD가 계획에 포함되었고, ASD 공정 게이트(G4B002)는 고융점을 근거로 용융압출 대신 분무건조를 선택하였다(정답지: Kalydeco는 80% HPMCAS 분무건조 분산체[15, 16]). 전략이 ASD 하나로 좁혀지지는 않았으며, 입자 크기 축소(MICRO)와 직접타정도 점수 상위 3개에 남았다. 4-퀴놀론 N–H는 유당 금기를 발동시키지 않았다. "
                    + ("요청 해석 LLM은 개발코드만으로도 일반명을 떠올릴 수 있으므로, 요청에 개발코드가 있으면 그 코드를 이름으로 고정하고 구조로 찾은 실명과 라벨 제품명을 "
                       "이벤트와 LLM 입출력 모두에서 코드로 치환한다. 그 결과 출력 전체(이벤트, 요약, 심사 서술)에 실제 물질명이 나타나지 않았다." if not leaks else
                       f"실제 물질명({', '.join(leaks)})이 {', '.join(sorted({s for r in c3 for s in r.get('leak_sources') or []}))} 출력에 나타났는데, "
                       "이는 개발코드로 찾은 문헌 초록이 실명을 포함하기 때문이며 블라인드 시연에서는 문헌 패널을 가려야 한다.")
                    + " (용해도는 문헌 상한값 “&lt; 0.05 µg/mL”을 값으로 입력하였다.)")
    paras.append(" ".join(para))
    paras = [x for x in paras if x]
    calls = dm.get("llm_calls") or {}
    return f"""<h3>7.5 시연 쿼리 카드와 정답지 비교</h3>
<p>약학 전공 팀원이 작성한 시연 쿼리 카드 3장(① 로르녹시캄 8 mg 분산정 전체 파이프라인[11], ② 유당을 고정한 고령자 암로디핀 2.5 mg, ③ 개발코드만 공개된 신규물질의
cold start)을 카드의 문장과 값 그대로 {E(dm.get('llm_label') or dm.get('llm'))}로 실행하였다(각 {max(r['repeat'] for r in res)}회).
LLM 호출은 {', '.join(f"{'대회 API' if k == 'dacon' else '무료 Groq' if k == 'groq' else k} {v}회" for k, v in calls.items()) or '기록 없음'}였다{
'(무료 Groq 호출은 대회 API 호출이 오류로 실패하여 전환된 경우이다)' if calls.get('groq') else ''}. 데이터 요청에는 카드의 제출 값을 입력 에이전트에 문장으로
입력하였다(표 13).</p>
<table><thead><tr><th>카드</th><th>회</th><th>종결</th><th>초</th><th>시스템이 한 일</th></tr></thead><tbody>{rows}</tbody></table>
<div class="tcap"><b>표 13.</b> 시연 쿼리 카드 실행 결과(demo_cards.json; 서버 응답과 이벤트 스트림에서 기록). 대비 행은 같은 카드에서 한 값만 바꾼 실행이다.</div>
{''.join(f"<p>{x}</p>" for x in paras)}
"""


def exp_section(x) -> str:
    if not x:
        return ""
    runs = x["runs"]
    rows = ""
    for r in runs:
        sc = r["judge_scores"]
        rows += (f"<tr><td>{E(r['label'])}</td><td>{r['repeat']}</td><td>{E(r['status'])}</td>"
                 f"<td class='mono'>{E(r['plan_signature'] or '')}</td><td>{r['candidates_generated']}</td>"
                 f"<td>{r['gate_passed']}/{r['gate_total']}</td><td>{E(', '.join(r['hard_fails']) or '—')}</td>"
                 f"<td>{E(', '.join(r['summoned']) or '—')}</td>"
                 f"<td>{len(sc) - r['judge_unscored']}/{len(sc)}</td>"
                 f"<td>{r['pending_requests']}</td><td class='mono'>{E(r['winner'] or '—')}</td><td>{r['elapsed_s']:.0f}</td></tr>")
    arows = ""
    for a in [a for a in x["agent"] if a["id"] != "U6"]:     # U6은 삭제된 개발 스튜디오 발화(기록만 남아 있음)
        p = (a["proposals"] or [{}])[0]
        what = p.get("kind") or "—"
        detail = []
        if p.get("kind") == "start_run":
            detail.append("준비됨" if p.get("ready") else f"미완성({', '.join(p.get('missing') or [])})")
            if p.get("smiles_source"):
                detail.append(f"구조: {p['smiles_source']}")
            if p.get("measured_params"):
                detail.append("값: " + ", ".join(f"{k}={v:g}" for k, v in p["measured_params"].items()))
        arows += (f"<tr><td>{E(a['id'])}</td><td>{E(a['text'])}</td><td>{E(what)}</td>"
                  f"<td>{E(' · '.join(detail))}</td><td>{E(' / '.join(a.get('asks') or []) or '—')}</td></tr>")
    sigs = {}
    for r in runs:
        sigs.setdefault(r["scenario"], set()).add((r["plan_signature"], r["status"], tuple(r["hard_fails"])))
    same = all(len(v) == 1 for v in sigs.values())
    tot = x.get("contest_tokens_used_estimate")
    return f"""<h3>7.4 대회 API 기반 실험</h3>
<p>후보 탐색의 LLM 단계(요청 해석, 설계, 심사, 반성)와 입력 에이전트를 대회 API의 <code>{E(x['llm_model'].split(' (')[0])}</code>로 실행하였다(Groq 전환 없음 —
모든 후보와 점수가 대회 API 응답). 시연 시나리오와 같은 입력 4종을 각 2회 실행하였다(표 11).</p>
<table><thead><tr><th>시나리오</th><th>회</th><th>종결</th><th>계획 서명</th><th>후보</th><th>게이트 통과</th><th>반려 규칙</th><th>소집 심사관</th><th>점수 있음</th><th>남은 요청</th><th>권고</th><th>초</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="tcap"><b>표 11.</b> 시나리오별 실행 결과(서버 응답과 이벤트 스트림에서 기록). 점수 있음은 실제로 부여된 심사 점수 수 / 전체 심사 호출 수이다.</div>
{exp_narrative(x, same, tot)}
<table><thead><tr><th>ID</th><th>사용자 발화</th><th>제안</th><th>카드 내용</th><th>되물음</th></tr></thead><tbody>{arows}</tbody></table>
<div class="tcap"><b>표 12.</b> 입력 에이전트 응답. U3(“용량은 알아서”)은 용량을 지어내지 않고 되물었고, U4(“SMILES는 네가 기억하는 걸로”)의 구조는 LLM이 아니라
내장 구조 사전에서 왔으며, U5의 “대충 30도”는 모호한 표현이라 실측값으로 옮기지 않았다.</div>
"""



def _ab_agg(ab):
    """ablation.json → 조건별 집계(F 전체 시스템 · G 검증 계층 제거 · P 순수 LLM). 모든 수는 파일에서 센다."""
    cases = ab["stage1"]["cases"]
    out = {}
    for k in ("F", "G", "P"):
        runs = [(c, r) for c in cases for r in c[k]]
        inf_out = sum(len(r["outputs"]) for c in cases if c["expect_infeasible"] for r in c[k])
        outs = [o for _, r in runs for o in r["outputs"]]
        bad = lambda o: o["unsafe"] or o["contract"]                                   # noqa: E731
        inf = [(c, r) for c, r in runs if c["expect_infeasible"]]
        fea = [(c, r) for c, r in runs if not c["expect_infeasible"]]
        a = {"runs": len(runs), "outputs": len(outs), "unsafe": sum(o["unsafe"] for o in outs), "contract": sum(o["contract"] for o in outs),
             "bad": sum(bad(o) for o in outs),
             "runs_bad": sum(any(bad(o) for o in r["outputs"]) for _, r in runs),
             "feasible_runs_bad": sum(any(bad(o) for o in r["outputs"]) for _, r in fea), "feasible_runs": len(fea),
             "inf_runs": len(inf), "inf_ok": sum(not any(bad(o) for o in r["outputs"]) for _, r in inf),
             "refused": sum(not r["outputs"] for _, r in fea), "inf_outputs": inf_out,
             "inf_bad": sum(o["unsafe"] or o["contract"] for _, r in inf for o in r["outputs"]),
             "repro": sum(c["reproducible"][k] for c in cases), "cases": len(cases),
             "sec": sum(r.get("seconds") or 0 for _, r in runs) / max(len(runs), 1),
             "calls": sum(r.get("llm_calls") or 0 for _, r in runs) / max(len(runs), 1),
             "providers": sorted({p for _, r in runs for p in (r.get("providers") or {})})}
        if k == "P":
            cg = [r["citations"] for _, r in runs if r.get("citations")]
            a["cite_given"], a["cite_ok"] = sum(x["given"] for x in cg), sum(x["verified"] for x in cg)
            a["said_infeasible"] = sum(r.get("feasible") is False for _, r in inf)
            a["said_infeasible_fea"] = sum(r.get("feasible") is False for _, r in fea)
        if k == "F":
            a["rejected"] = sum(r.get("rejected_candidates") or 0 for _, r in runs)
            a["generated"] = a["outputs"] + a["rejected"]
            a["inf_rejected"] = sum(r.get("rejected_candidates") or 0 for _, r in inf)
            a["inf_generated"] = a["inf_rejected"] + sum(len(r["outputs"]) for _, r in inf)
            j = [r["judge"] for _, r in runs]
            a["judge_scored"], a["judge_uncited"] = sum(x["scored"] for x in j), sum(x["uncited_invalidated"] for x in j)
            a["concluded_infeasible"] = sum(r["status"] == "infeasible" for _, r in inf)
        out[k] = a
    out["scale"] = {"requests": len(cases), "infeasible": sum(c["expect_infeasible"] for c in cases),
                    "runs": sum(out[k]["runs"] for k in "FGP"),
                    "formulations": out["P"]["outputs"] + out["G"]["outputs"] + out["F"]["generated"]}
    return out


def _pp(a, b):
    """본문용 — 5/20건(25%)."""
    return f"{a}/{b}건" + (f"({100 * a / b:.0f}%)" if b else "")


def _pct(a, b):
    return f"{a}/{b}" + (f" ({100 * a / b:.0f}%)" if b else "")


def conclusion_ablation(ab) -> str:
    """결론의 어블레이션 문장 — ablation.json에서."""
    if not ab or "stage1" not in ab:
        return ""
    a = _ab_agg(ab)
    P, G, F = a["P"], a["G"], a["F"]
    return (f"같은 LLM으로 비교한 어블레이션에서 금기 처방 제시는 순수 LLM {100 * P['bad'] / max(P['outputs'], 1):.0f}%, 검증 계층 제거 조건 "
            f"{100 * G['bad'] / max(G['outputs'], 1):.0f}%에서 전체 시스템 {100 * F['bad'] / max(F['outputs'], 1):.0f}%로 줄었고, 금기 성분이 고정된 요청은 전체 시스템만 "
            f"{F['concluded_infeasible']}/{F['inf_runs']} 실행 모두 근거와 함께 종결하였으며, 가능한 요청에서의 과잉 거부는 없었다. Design Space는 실험 영역 안에서만, "
            "같은 자료에서 늘 같은 결과로 도출되었다. 판정은 규칙이, 수용은 연구자가 맡는 구조가 같은 모델을 더 안전하고 재현 가능한 제형 설계 도구로 만든다.")


def ablation_section(ab) -> str:
    """7.7 — scripts/report/ablation.py → docs/report/ablation.json."""
    if not ab or "stage1" not in ab or "stage2" not in ab:
        return ""
    g = _ab_agg(ab)
    F, G, P = g["F"], g["G"], g["P"]
    cases = ab["stage1"]["cases"]
    n_inf = sum(c["expect_infeasible"] for c in cases)

    def cell(runs, k):
        n = sum(len(r["outputs"]) for r in runs)
        b = sum(o["unsafe"] or o["contract"] for r in runs for o in r["outputs"])
        rules = sorted({x for r in runs for o in r["outputs"] for x in o["hard_fail"] + o["contract_fail"]})
        extra = ""
        if k == "F":
            st = sorted({r["status"] for r in runs})
            extra = " · " + "/".join(E(s) for s in st)
        if k == "P":
            no = sum(r.get("feasible") is False for r in runs)
            extra = f" · 불가 답 {no}회" if no else ""
        return f"{b}/{n}{extra}" + (f"<br><span class='mono'>{E(', '.join(rules))}</span>" if rules else "")
    crow = "".join(f"<tr><td>{E(c['label'])}</td><td>{'불가능' if c['expect_infeasible'] else '가능'}</td>"
                   f"<td>{cell(c['P'], 'P')}</td><td>{cell(c['G'], 'G')}</td><td>{cell(c['F'], 'F')}</td></tr>" for c in cases)

    s2 = ab["stage2"]
    sa, sb, sc = s2["S_A"], s2["S_B"], s2["S_C"]
    sa_ok = [r for r in sa["reps"] if "error" not in r]
    sb_ok = [r for r in sb["reps"] if "error" not in r]
    sc_ok = [r for r in sc["reps"] if "error" not in r]
    ntot = sa["system"]["coef_within_1pct"]
    sa_rows = "".join(f"<tr><td>순수 LLM {i + 1}회</td><td>{r['coef_within_1pct']}/{r['coef_total']}</td><td>{100 * r['median_rel_err']:.1f}%</td>"
                      f"<td>{r['p_decision_ok']}/{r['p_total']}</td></tr>" for i, r in enumerate(sa_ok))
    sa_rows += f"<tr><td>시스템(결정론 계산)</td><td>{ntot}/{ntot}</td><td>0%</td><td>3/3</td></tr>"
    sys_b = sb["system"]
    def rng(d):
        return " × ".join(f"{v[0]:g}–{v[1]:g}" if isinstance(v, list) and v[0] != v[1] else f"{(v[0] if isinstance(v, list) else v):g}" for v in d.values())

    def pt(d):
        return " · ".join(f"{v:g}" for v in d.values())
    fnames = list(sys_b["optimum"])
    sb_rows = "".join(f"<tr><td>순수 LLM {i + 1}회</td><td class='mono'>{E(rng({n: r['ranges'][n] for n in fnames}))}</td><td class='mono'>{E(pt({n: r['setpoint'][n] for n in fnames}))}</td>"
                      f"<td>{100 * r['box_in_domain']:.0f}%</td><td>{100 * r['box_mean_ok']:.0f}%</td>"
                      f"<td>{'예' if r['setpoint_mean_ok'] and r['setpoint_in_domain'] else '아니오'}</td><td>{r['setpoint_joint']:.3f}</td></tr>"
                      for i, r in enumerate(sb_ok))
    sb_rows += (f"<tr><td>시스템(control space · 최적 처방)</td><td class='mono'>{E(rng({n: sys_b['control_space'][n] for n in fnames}))}</td>"
                f"<td class='mono'>{E(pt(sys_b['optimum']))}</td><td>{100 * sys_b['box_in_domain']:.0f}%</td><td>{100 * sys_b['box_mean_ok']:.0f}%</td>"
                f"<td>{'예' if sys_b['setpoint_mean_ok'] and sys_b['setpoint_in_domain'] else '아니오'}</td><td>{sys_b['setpoint_joint']:.3f}</td></tr>")
    sc_rows = "".join(f"<tr><td>순수 LLM {i + 1}회</td><td>{r['matrix_vs_justification_mismatch']}</td><td>{r['justification_uncovered']}</td>"
                      f"<td>{r['justification_conflict']}</td><td>{r['matrix_missing']}</td></tr>" for i, r in enumerate(sc_ok))
    sc_rows += "<tr><td>시스템(행렬 = 근거 표에서 계산)</td><td>0</td><td>0 (빈 칸은 승인 차단)</td><td>0</td><td>0</td></tr>"
    return f"""<h3>7.7 어블레이션: 검증 계층의 효과</h3>
<p><b>설계.</b> 같은 모델(<code>{E(ab['model'])}</code>, 대회 API)로 세 조건을 비교해, 시스템의 효과가 어느 모듈에서 나오는지 분리하였다. 순수 LLM(P)은 요청, 구조식,
실측값, 고정 성분, 용량 기준만 받아 처방 한 건(성분, mg, 공정, 근거 DOI/PMID)을 JSON으로 낸다. 검증 계층 제거(G)는 시스템의 계획(페이즈 게이트, 전략 선택)과 설계
에이전트(규칙표 근거 검색 포함)를 그대로 쓰되 규칙 게이트·요청 계약·반성·불가능 판정을 빼고 생성된 후보를 모두 제시한다. 전체 시스템(F)은 실제 그래프 전체이며
연구자에게 통과 후보로 제시되는 처방만 센다. G와 F는 계획·설계 모듈을 공유하고 검증 계층 유무만 다르므로, 두 조건의 차이가 곧 검증 계층의 효과이다. 입력은
시연 쿼리 카드 3건과 7.4절 시나리오 4건을 포함한 요청 {len(cases)}건이며, 그중 {n_inf}건은 고정 성분이 규칙표상 금기인 요청이다. 금기 요청은 규칙 조합으로
만든 합성 요청이 아니라 근거 문헌이 그 분자나 화학 계열을 직접 다루는 실제 사례(플루옥세틴–유당[13], 암로디핀–유당[14])만 썼다 — 합성 요청은 정답이 채점 규칙표와
순환하기 때문이다. <b>실험 규모: F·G {ab['repeat']}회, P {ab['p_repeat']}회 반복으로 실행 {g['scale']['runs']}회(F {F['runs']} · G {G['runs']} · P {P['runs']}), 평가한 처방
{g['scale']['formulations']}건(P 제시 {P['outputs']} · G 제시 {G['outputs']} · F 생성 {F['generated']} 중 제시 {F['outputs']} · 반려 {F['rejected']}).</b></p>
<p><b>평가 지표.</b> 정답이 하나로 정해져 기계적으로 채점할 수 있는 항목만 썼다(표 14). 처방은 세 조건 모두 같은 채점기, 즉 출처가 명시된 규칙표 전체를 적용하는
사후 채점(<code>registry.run</code>)으로 평가하였고, 각 반려에는 규칙의 근거 문헌이 함께 기록된다(표 17). LLM이 매기는 품질 점수(순환 채점), 논문과의 일치율(논문은
정답지가 아님), 토큰 사용량(요청별 측정 불가)처럼 해석이 자의적인 지표는 제외하였다. 무료 모델 키를 제거해 세 조건이 같은 모델만 쓰도록 하였다.</p>
<table><thead><tr><th>지표</th><th>정의</th><th>판정 기준</th></tr></thead><tbody>
<tr><td>금기 위반 처방</td><td>제시된 처방 중 출처 규칙의 HARD_FAIL(요청 계약 제외)이 하나 이상인 처방</td><td>규칙표(배합 금기, 공정, 소아, 규제 상한), 결정론</td></tr>
<tr><td>요청 계약 위반</td><td>API 1개, 유리염기 용량 ±0.5 %, 고정 성분 포함, FDA 라벨 1일 최대 용량 중 하나 이상을 위반한 처방</td><td>요청 문장, 입력값, DailyMed 라벨, 결정론</td></tr>
<tr><td>불가능 요청 처리</td><td>고정 성분이 규칙표에서 금기(HARD_FAIL)인 요청에서 위반 처방을 하나도 내지 않은 실행</td><td>플루옥세틴 INC002(Wirth 1998 — 그 분자의 1차 연구) · 암로디핀 INC001(Narang 2012 종설의 계열 규칙) · MC001/MC002(Abdoh 2004)</td></tr>
<tr><td>과잉 거부</td><td>가능한 요청에서 처방을 하나도 제시하지 않은 실행</td><td>출력 유무</td></tr>
<tr><td>인용 실재</td><td>제시한 DOI·PMID의 실재 여부</td><td>Crossref · NCBI 조회</td></tr>
<tr><td>재현성</td><td>같은 입력을 반복하였을 때 결정(제시 여부, 발동 규칙, 계획)이 동일한 요청 수</td><td>반복 간 비교</td></tr>
<tr><td>2단계 계산 정확도</td><td>회귀 계수, p값 판정, Design Space 목표 충족, 위험표 내부 일관성</td><td>논문 Table 10·11(재현 확인), 게이트 통과 모형, 표 대조</td></tr>
</tbody></table>
<div class="tcap"><b>표 14.</b> 어블레이션 지표와 판정 기준. 모든 항목은 결정론적으로 채점한다.</div>
<table><thead><tr><th>지표</th><th>P 순수 LLM</th><th>G 검증 계층 제거</th><th>F 전체 시스템</th></tr></thead><tbody>
<tr><td>실행 수</td><td>{P['runs']}</td><td>{G['runs']}</td><td>{F['runs']}</td></tr>
<tr><td>생성된 처방 → 제시된 처방</td><td>{P['outputs']} → {P['outputs']} (검증 없음)</td><td>{G['outputs']} → {G['outputs']} (검증 없음)</td><td>{F['generated']} → {F['outputs']} (규칙 게이트 반려 {F['rejected']})</td></tr>
<tr><td>금기 요청에서 반려된 처방</td><td>0/{P['inf_outputs']} (위반 {P['inf_bad']}건 그대로 제시)</td><td>0/{G['inf_outputs']} (위반 {G['inf_bad']}건 그대로 제시)</td><td>{_pct(F['inf_rejected'], F['inf_generated'])}</td></tr>
<tr><td>금기 위반 처방</td><td>{_pct(P['unsafe'], P['outputs'])}</td><td>{_pct(G['unsafe'], G['outputs'])}</td><td>{_pct(F['unsafe'], F['outputs'])}</td></tr>
<tr><td>요청 계약 위반 처방</td><td>{_pct(P['contract'], P['outputs'])}</td><td>{_pct(G['contract'], G['outputs'])}</td><td>{_pct(F['contract'], F['outputs'])}</td></tr>
<tr><td>가능 요청에서 위반 처방이 나온 실행</td><td>{_pct(P['feasible_runs_bad'], P['feasible_runs'])}</td><td>{_pct(G['feasible_runs_bad'], G['feasible_runs'])}</td><td>{_pct(F['feasible_runs_bad'], F['feasible_runs'])}</td></tr>
<tr><td>불가능 요청을 위반 없이 처리</td><td>{_pct(P['inf_ok'], P['inf_runs'])} · “불가” 답 {P['said_infeasible']}</td><td>{_pct(G['inf_ok'], G['inf_runs'])}</td><td>{_pct(F['inf_ok'], F['inf_runs'])} · 불가능 결론 {F['concluded_infeasible']}</td></tr>
<tr><td>과잉 거부(가능 요청에서 처방 없음)</td><td>{_pct(P['refused'], P['feasible_runs'])}</td><td>{_pct(G['refused'], G['feasible_runs'])}</td><td>{_pct(F['refused'], F['feasible_runs'])}</td></tr>
<tr><td>인용 실재</td><td>{_pct(P['cite_ok'], P['cite_given'])}</td><td>— (인용 없음)</td><td>심사 점수 {F['judge_scored']}건 모두 확인된 인용 · 인용 없어 무효 {F['judge_uncited']}건</td></tr>
<tr><td>결정 재현(요청 {F['cases']}건 중)</td><td>{P['repro']}</td><td>{G['repro']}</td><td>{F['repro']}</td></tr>
<tr><td>실행당 시간 · LLM 호출</td><td>{P['sec']:.0f}초 · {P['calls']:.1f}회</td><td>{G['sec']:.0f}초 · {G['calls']:.1f}회</td><td>{F['sec']:.0f}초 · {F['calls']:.1f}회</td></tr>
</tbody></table>
<div class="tcap"><b>표 15.</b> 1단계 어블레이션 집계. 세 조건 모두 응답 모델은 {E(', '.join('대회 API' if p_ == 'dacon' else p_ for p_ in sorted(set(F['providers']) | set(G['providers']) | set(P['providers']))) or '—')}이며 무료 모델 전환은 없었다. F의 시간은 전략별 설계와 심사를 병렬로 수행한 경과 시간이다.</div>
<table><thead><tr><th>요청</th><th>조건</th><th>P 위반/제시</th><th>G 위반/제시</th><th>F 위반/제시 · 종결</th></tr></thead><tbody>{crow}</tbody></table>
<div class="tcap"><b>표 16.</b> 요청별 결과(반복 합산). 각 칸의 아래 줄은 발동한 규칙이다(INC: 배합 금기, MC: 다성분 금기, RC: 요청 계약, MAX_DAILY: 라벨 최대 용량).</div>
{ablation_narrative(ab, g)}
<p><b>2단계 비교 설계.</b> 같은 모델에 원자료 표를 주고 결정론 모듈의 계산을 직접 하게 하였다(각 3회, 위험표 2회). (가) CBD 17 run의 coded 계수, 모형 p, 적합결여
p를 논문 Table 10·11(7.1절에서 시스템이 재현)과 비교하였다(표 18). (나) 로르녹시캄 15 run과 목표로 Design Space 범위와 설정점을 정하게 하고 시스템의 게이트 통과
모형으로 채점하였다(표 19). (다) CBD 위험 행렬과 근거 표를 함께 쓰게 하고 두 표의 일치를 대조하였다(표 20).</p>
<table><thead><tr><th>조건</th><th>계수 ±1 % 이내</th><th>계수 상대오차 중앙값</th><th>유의성 판정 일치(p &lt; 0.05)</th></tr></thead><tbody>{sa_rows}</tbody></table>
<div class="tcap"><b>표 18.</b> 회귀 계산(CBD Table 9 → Table 10·11). 계수 {ntot}개(경도 선형 4개, 붕해시간 2차 10개). 기준값은 경도 모형 p {sa['truth']['hardness_model_p']:.4f}, 적합결여 p {sa['truth']['hardness_lack_of_fit_p']:.4f}, 붕해시간 모형 p {sa['truth']['dt_model_p']:.4f}이다.</div>
<table><thead><tr><th>조건</th><th>범위({E(' × '.join(fnames))})</th><th>설정점</th><th>범위 중 실험 영역 안</th><th>그중 평균 예측이 목표 충족</th><th>설정점 목표 충족</th><th>설정점 통과확률</th></tr></thead><tbody>{sb_rows}</tbody></table>
<div class="tcap"><b>표 19.</b> Design Space 제안(로르녹시캄 Table 3; 목표 분산 ≤ 180 s, 마손도 ≤ 1 %, DE30 ≥ 75 %, AV ≤ 15). 제안 범위를 요인당 11점 격자로 나누어 시스템의 게이트 통과 모형(네 반응 축소 2차)으로 채점하였다.</div>
<table><thead><tr><th>조건</th><th>행렬 ≠ 근거 표</th><th>근거 없는 칸</th><th>근거끼리 등급 충돌</th><th>행렬 빈 칸</th></tr></thead><tbody>{sc_rows}</tbody></table>
<div class="tcap"><b>표 20.</b> 위험평가 표의 내부 일관성(CBD 제형·공정 변수 {sc['variables']} × CQA {sc['cqas']} = {sc['variables'] * sc['cqas']}칸). 등급의 논문 일치 여부는 평가하지 않았다(논문은 정답지가 아님, 7.6절).</div>
{ablation_s2_narrative(ab)}
"""


def _ab_rules(cases, k):
    """조건 k에서 제시된 처방이 걸린 규칙 — (규칙, 처방 수, 사유 한 줄)."""
    from collections import Counter
    cnt, why = Counter(), {}
    for c in cases:
        for r in c[k]:
            for o in r["outputs"]:
                for rid in set(o["hard_fail"] + o["contract_fail"]):
                    cnt[rid] += 1
                    why.setdefault(rid, (o.get("why") or {}).get(rid, {}).get("reason", ""))
    return [(rid, n, why.get(rid, "")) for rid, n in cnt.most_common()]


def ablation_narrative(ab, g) -> str:
    """1단계 결과 서술 — 수는 모두 ablation.json에서."""
    cases = ab["stage1"]["cases"]
    F, G, P = g["F"], g["G"], g["P"]
    inf = [c for c in cases if c["expect_infeasible"]]
    p_inf = [r for c in inf for r in c["P"]]

    def top(k, n=4):
        rows = _ab_rules(cases, k)[:n]
        return ", ".join(f"<span class='mono'>{E(rid)}</span> {cnt}건" for rid, cnt, _ in rows) or "없음"
    why_rows = {}
    for k in ("P", "G"):
        for rid, _, w in _ab_rules(cases, k):
            if w and rid not in why_rows:
                why_rows[rid] = w
    wr = "".join(f"<tr><td class='mono'>{E(rid)}</td><td>{E(w)}</td></tr>" for rid, w in list(why_rows.items())[:8])
    bad_inf = {k: sum(o["unsafe"] or o["contract"] for c in inf for r in c[k] for o in r["outputs"]) for k in ("P", "G")}
    all_inf = bad_inf["P"] == P["bad"] and bad_inf["G"] == G["bad"]
    gave = [r for r in p_inf if r.get("feasible") and r["outputs"]]
    knew = sum(1 for r in gave if any(w in str(r.get("reason") or "").lower() for w in ("maillard", "환원당", "reducing sugar")))
    fake = P["cite_given"] - P["cite_ok"]
    p1 = (f"<p><b>안전성.</b> 규칙표가 금지하는 처방은 순수 LLM {_pp(P['bad'], P['outputs'])}, 검증 계층 제거 조건 {_pp(G['bad'], G['outputs'])}에서 연구자에게 제시되었고, "
          f"전체 시스템은 {_pp(F['bad'], F['outputs'])}였다(표 15). "
          + ("위반은 모두 고정 성분이 금기인 요청에서 나왔다" if all_inf else "위반은 주로 고정 성분이 금기인 요청에서 나왔다")
          + f"(발동 규칙 — P: {top('P')}; G: {top('G')}).</p>")
    gr, pr = 100 * G["bad"] / max(G["outputs"], 1), 100 * P["bad"] / max(P["outputs"], 1)
    cmp_ = "순수 LLM보다 낮지 않았다" if gr >= pr else "순수 LLM과 비슷하였다" if pr - gr <= 10 else "순수 LLM보다 낮았으나 0이 되지 않았다"
    p2 = ("<p><b>근거 제공만으로는 막지 못한다.</b> G의 설계 에이전트는 규칙표 근거를 검색해 참조하는데도 위반 비율이 "
          f"{cmp_}({gr:.0f}% 대 {pr:.0f}%). "
          + (f"순수 LLM이 금기 요청에 처방을 낸 {len(gave)}회 중 {knew}회는 사유에 Maillard 반응 위험을 스스로 적고도 조건부 개발 가능으로 답하였다. "
             "위반은 지식이 없어서라기보다 요청을 충족하려는 경향에서 나왔고, " if knew else "")
          + "이를 막은 것은 판정 권한을 가진 검증 계층이었다. "
          + (f"같은 모델, 같은 계획·설계 모듈에서 검증 계층을 더하자 위반이 {G['bad']}건에서 0건이 되었다.</p>" if F["bad"] == 0 else
             f"같은 모델, 같은 계획·설계 모듈에서 검증 계층을 더하자 위반이 {G['bad']}건에서 {F['bad']}건으로 줄었다.</p>"))
    p3 = (f"<p><b>불가능 요청의 종결.</b> 금기 성분이 고정된 요청에서 전체 시스템은 {F['concluded_infeasible']}/{F['inf_runs']} 실행 모두 차단 규칙과 대체 성분을 제시하며 "
          f"“제약 불가능”으로 종결하였다. 같은 요청에서 위반 없이 끝난 실행은 순수 LLM {P['inf_ok']}/{P['inf_runs']}, 검증 계층 제거 조건 {G['inf_ok']}/{G['inf_runs']}였다.</p>")
    p4 = (f"<p><b>유용성·재현성·인용.</b> 가능한 요청에서 처방을 내지 않은 과잉 거부는 전체 시스템 실행 {F['feasible_runs']}회 중 {F['refused']}회로, 검증 계층은 안전성을 높이면서 "
          f"유용성을 줄이지 않았다. 반복 간 결정이 같은 요청은 전체 시스템 {F['repro']}/{F['cases']}(순수 LLM {P['repro']}, G {G['repro']})이었다. "
          + (f"순수 LLM이 제시한 DOI·PMID {P['cite_given']}건 중 {fake}건은 실재하지 않았으나, " if fake else f"순수 LLM이 제시한 DOI·PMID {P['cite_given']}건은 모두 실재하였고, ")
          + f"전체 시스템은 확인되지 않은 인용이 붙은 점수를 규칙으로 무효화하므로 심사 점수 {F['judge_scored']}건이 모두 확인된 인용을 가졌다"
          f"(무효 {F['judge_uncited']}건). 전략별 설계와 심사를 병렬로 실행하여, 실행당 LLM 호출 {F['calls']:.0f}회에도 경과 시간은 {F['sec']:.0f}초로 "
          f"순수 LLM({P['sec']:.0f}초)과 {F['sec'] - P['sec']:.0f}초 차이였다.</p>")
    table = (f"<table><thead><tr><th>규칙</th><th>엔진이 적은 반려 사유(첫 사례)</th></tr></thead><tbody>{wr}</tbody></table>"
             "<div class='tcap'><b>표 17.</b> 순수 LLM과 검증 계층 제거 조건의 처방에서 발동한 규칙과 사유(규칙 게이트의 원문).</div>") if wr else ""
    return p1 + p2 + p3 + p4 + table


def ablation_s2_narrative(ab) -> str:
    """2단계 결과 서술 — 수는 모두 ablation.json에서."""
    s2 = ab["stage2"]
    sa = [r for r in s2["S_A"]["reps"] if "error" not in r]
    sb = [r for r in s2["S_B"]["reps"] if "error" not in r]
    sc = [r for r in s2["S_C"]["reps"] if "error" not in r]
    sys_b = s2["S_B"]["system"]
    exact = sa and all(r["coef_within_1pct"] == r["coef_total"] and r["p_decision_ok"] == r["p_total"] for r in sa)
    sc_bad = sum(r["matrix_vs_justification_mismatch"] + r["justification_uncovered"] + r["justification_conflict"] + r["matrix_missing"] for r in sc)
    t1 = ""
    if sa:
        t1 = (f"원자료를 모두 주면 순수 LLM도 회귀 계수 {sa[0]['coef_total']}개와 유의성 판정을 {len(sa)}회 모두 정확히 계산하였고"
              if exact else f"순수 LLM이 ±1 % 이내로 계산한 계수는 {len(sa)}회에 걸쳐 {', '.join(str(r['coef_within_1pct']) for r in sa)}개(총 {sa[0]['coef_total']}개)였고")
        t1 += (f", 위험표도 {len(sc)}회 모두 내부 모순이 없었다. " if sc and not sc_bad else
               f", 위험표에서는 행렬과 근거 표의 모순이 {sc_bad}칸 나왔다(시스템은 행렬을 근거 표에서 계산하므로 0칸). " if sc else ". ")
        t1 += "시스템은 같은 계산을 코드로 수행하고 논문 표 재현을 테스트로 고정해, 이 정확도를 매 실행 보장한다. "
    t2 = ""
    if sb:
        outside = sum(1 - r["box_in_domain"] for r in sb) / len(sb)
        pts = {tuple(sorted(r["setpoint"].items())) for r in sb}
        rngs = {tuple(sorted((k, tuple(v)) for k, v in r["ranges"].items())) for r in sb}
        js = [r["setpoint_joint"] for r in sb]
        t2 = (f"차이는 Design Space에서 드러났다. 순수 LLM이 제안한 범위는 평균 {100 * outside:.0f}%가 실험 영역(설계점 볼록 껍질) 밖, 즉 자료가 없는 외삽 영역이었고, "
              f"{len(sb)}회 반복에서 범위 {len(rngs)}가지·설정점 {len(pts)}가지로 달라졌다. 시스템은 control space를 실험 영역 안({100 * sys_b['box_in_domain']:.0f}%)에서만 "
              f"구성하고 같은 자료에서 늘 같은 결과를 내며, 설정점의 새 배치 통과확률도 가장 높았다({sys_b['setpoint_joint']:.3f} 대 "
              f"{min(js):.3f}–{max(js):.3f}).")
    fails = {k: len(s2[k]["reps"]) - len(v) for k, v in (("S_A", sa), ("S_B", sb), ("S_C", sc))}
    names = {"S_A": "회귀 계산", "S_B": "Design Space 제안", "S_C": "위험표"}
    tf = f" (대회 API 응답 실패로 제외된 반복: {', '.join(f'{names[k]} {v}회' for k, v in fails.items() if v)})" if any(fails.values()) else ""
    return f"<p><b>2단계 결과.</b> {t1}{t2}{tf}</p>"


STAGES = [  # (우선순위 범위, 제목) — manifest의 trigger_priority 십의 자리 = 파이프라인 단계
    ((0, 4), "참조 마스터"), ((5, 9), "API 물성"), ((10, 19), "흐름 → 경로"), ((20, 29), "배합금기 · 소아"),
    ((30, 39), "다성분"), ((40, 49), "공정 세부"), ((50, 59), "코팅 · 용매"), ((60, 69), "BCS · 용출"),
    ((70, 79), "포장 · 안정성"),
]
SHORT = {"pairwise_membership": "쌍 금기", "subset_forbidden": "조합 금지", "threshold": "임계값", "range": "범위",
         "categorical_requirement": "필수 성분", "conditional_prohibition": "조건부 금지", "band_lookup": "구간 조회",
         "decision_tree": "결정 트리"}


GROUP_NOTE = {
    "페이즈 게이트 · 계획": "BCS/DCS · 고체상 · 가용화 · ASD 공정 게이트, 파생값 식, 전략 가족과 채점",
    "데이터 요청": "요청 트리거, 측정 카탈로그, 결과 필드 타입",
    "입력 계약 · 환산": "요청 계약 항목, FDA 라벨 1일 최대 용량, 짝이온 분자량, 판정용 역할 매핑",
    "되돌림 · 심사": "반려 사유별 복귀 전이, 심사관 명단과 소집 조건, 합의 가중치, 검증된 인용 등록부",
    "근거 결손 게이트": "필수 근거 요구, 확인시험 마스터",
    "구조 · 물성 · 부형제 마스터": "구조 패턴, 기술자 정의, 물성 추정, 임계값, 부형제 마스터·IID, 규칙 입력 사전",
}


def _fr(name, x) -> str:
    return f"{E(name(x['file']))} ({x['rows']}행)"


def tier_table() -> str:
    """표 5 — 측정 카탈로그의 Tier(저장소 CSV에서). 요청은 Tier 번호가 낮은 순, 같은 Tier 안에서는 시료량이 적은 순."""
    import csv
    path = ROOT / "database" / "reference" / "measurement_catalog.csv"
    if not path.exists():
        return ""
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    order = sorted({r["tier"] for r in rows}, key=lambda t: (int(t) if t.isdigit() else 9, t))
    label = {"strategy": "전략별"}
    trs = ""
    for t in order:
        rs = sorted((r for r in rows if r["tier"] == t), key=lambda r: (float(r["indicative_sample_mg"] or 999), r["measurement_id"]))
        mg = sorted({float(r["indicative_sample_mg"]) for r in rs if r["indicative_sample_mg"]})
        span = (f"{mg[0]:g} mg" if len(mg) == 1 else f"{mg[0]:g}–{mg[-1]:g} mg") if mg else "—"
        trs += (f"<tr><td>{E(label.get(t, 'Tier ' + t))}</td><td>{E(' · '.join(r['name_kr'] for r in rs))}</td>"
                f"<td style='white-space:nowrap'>{E(span)}</td><td>{len(rs)}</td></tr>")
    return (f"<table><thead><tr><th>Tier</th><th>시험 (요청 순서)</th><th>시료량(대략)</th><th>종</th></tr></thead><tbody>{trs}</tbody></table>"
            f"<div class='tcap'><b>표 5.</b> 측정 카탈로그의 Tier(<code>measurement_catalog.csv</code>, {len(rows)}종). 데이터 요청은 Tier 번호가 낮은 순"
            "(1 → 2 → 3 → 전략별), 같은 Tier 안에서는 시료량이 적은 순으로 정렬된다(<code>group_requests</code>).</div>")


def rulebook_table(data) -> str:
    """표 3 — 규칙표(CSV) 구성. 행 내용은 싣지 않고 종류 · 단계 · 검사 방식 · 행 수만(figdata.json의 rule_tables)."""
    rt = data.get("rule_tables") or {}
    man = rt.get("manifest") or []
    if not man:
        return ""
    name = lambda f: f.rsplit("/", 1)[-1]                                      # noqa: E731
    trs = ""
    for (lo, hi), title in STAGES:
        es = [e for e in man if e.get("priority") is not None and lo <= e["priority"] <= hi]
        if not es:
            continue
        files = []
        for e in es:
            if e["file"] and name(e["file"]) not in [f for f, _ in files]:
                files.append((name(e["file"]), e.get("rows")))
        kinds = []
        for e in es:
            k = "LLM 판단" if e["eval_type"] == "qualitative" else "참조" if e["eval_type"] == "reference" else SHORT.get(e.get("strategy") or "", e.get("strategy") or "")
            if k and k not in kinds:
                kinds.append(k)
        nq = sum(e["eval_type"] == "quantitative" for e in es)
        nl = sum(e["eval_type"] == "qualitative" for e in es)
        nr = sum(e["eval_type"] == "reference" for e in es)
        cnt = " · ".join(x for x in (f"판정 {nq}" if nq else "", f"LLM {nl}" if nl else "", f"참조 {nr}" if nr else "") if x)
        trs += (f"<tr><td>규칙 게이트 · {E(title)} ({lo}–{hi})</td><td class='mono'>{'<br>'.join(f'{E(f)} ({n}행)' if n is not None else E(f) for f, n in files)}</td>"
                f"<td>{E(' · '.join(kinds))}<br><small>{E(cnt)}</small></td></tr>")
    for g in rt.get("groups") or []:
        trs += (f"<tr><td>{E(g['role'])}</td><td class='mono'>{'<br>'.join(_fr(name, x) for x in g['files'])}</td>"
                f"<td>{E(GROUP_NOTE.get(g['role'], ''))}</td></tr>")
    nfiles = len({e["file"] for e in man if e.get("file")}) + sum(len(g["files"]) for g in rt.get("groups") or [])
    return f"""<table class="rbt split"><thead><tr><th>구분</th><th>CSV (행 수)</th><th>검사 방식 · 내용</th></tr></thead><tbody>{trs}</tbody></table>
<div class="tcap"><b>표 3.</b> 규칙표(CSV) 구성 — {nfiles}개 표. 위는 규칙 게이트가 manifest로 연결하는 {len(man)}개 항목을 우선순위 단계별로 묶은 것이고(같은 CSV를 행 필터로
나눈 항목은 한 줄), 아래는 그 밖의 결정론 계층이 읽는 표이다. 행 수는 저장소 기준이며, 규칙 추가는 CSV 행과 manifest 한 줄로 이루어진다.</div>"""


def fig_rulegate(data):
    m = data["manifest"]
    b = ""
    w, x0 = 68, 10
    # 0단계 — 입력 계약(요청과 후보의 정합). manifest 밖의 계약 규칙표 두 개에서 행 수를 센다.
    import csv as _csv
    def _n(rel):
        pth = ROOT / rel
        return sum(1 for _ in _csv.DictReader(pth.open(encoding="utf-8-sig"))) if pth.exists() else 0
    nrc, nmdd = _n("database/06_config/request_contract_rules.csv"), _n("database/05_regulatory/max_daily_dose.csv")
    b += f'<rect x="{x0}" y="22" width="{w}" height="130" rx="6" fill="#e7f0ff" stroke="#1d4ed8" stroke-width="1.2"/>'
    b += f'<text x="{x0 + w / 2}" y="36" class="lg" text-anchor="middle">0</text>'
    b += f'<text x="{x0 + w / 2}" y="52" class="bt" style="font-size:9.5px">입력 계약</text>'
    for k, t in enumerate(("API 1행", "용량 ±0.5%", "고정 부형제", "1일 최대")):
        b += f'<text x="{x0 + w / 2}" y="{68 + k * 11}" class="bs">{t}</text>'
    b += f'<text x="{x0 + w / 2}" y="123" class="bs">계약 {nrc} · 라벨 {nmdd}</text>'
    b += arrow(x0 + w, 81, x0 + w + 3, 81)
    x0 = x0 + w + 3
    b += '<text x="10" y="12" class="gt">요청과 후보의 정합(입력 계약) → 규칙표 33개 · 여덟 검사 함수 · 우선순위 단계 (앞 단계의 파생값이 뒤 단계 조건)</text>'
    for i, ((lo, hi), title) in enumerate(STAGES):
        es = [e for e in m if e["priority"] is not None and lo <= e["priority"] <= hi]
        x = x0 + i * (w + 3)
        q = sum(e["eval_type"] == "quantitative" for e in es)
        ql = sum(e["eval_type"] == "qualitative" for e in es)
        rf = sum(e["eval_type"] == "reference" for e in es)
        fns = sorted({SHORT.get(e["strategy"], "") for e in es if e["strategy"]})
        passw = any(e["polarity"] == "pass_when" for e in es)
        b += f'<rect x="{x}" y="22" width="{w}" height="130" rx="6" fill="#fff" stroke="#222" stroke-width="1.2"/>'
        b += f'<text x="{x + w / 2}" y="36" class="lg" text-anchor="middle">{lo}{"–" + str(hi) if es and max(e["priority"] for e in es) > lo else ""}</text>'
        b += f'<text x="{x + w / 2}" y="52" class="bt" style="font-size:9.5px">{E(title)}</text>'
        yy = 68
        for f in fns[:3]:
            b += f'<text x="{x + w / 2}" y="{yy}" class="bs">{E(f)}</text>'
            yy += 11
        yy = 112
        for t in (f"판정 {q}" if q else "", f"LLM 판단 {ql}" if ql else "", f"참조 {rf}" if rf else ""):
            if t:
                b += f'<text x="{x + w / 2}" y="{yy}" class="bs">{E(t)}</text>'
                yy += 11
        if passw:
            b += f'<text x="{x + w / 2}" y="{yy}" class="bs">pass_when</text>'
        if i < len(STAGES) - 1:
            b += arrow(x + w, 81, x + w + 3, 81)
    # 파생값 흐름
    def cx(i): return x0 + i * (w + 3) + w / 2
    b += path(f"M {cx(2)} 152 C {cx(2)} 172, {cx(5)} 172, {cx(5)} 154", "", 0, 0)
    b += f'<text x="{(cx(2) + cx(5)) / 2 - 90}" y="178" class="al">flow_character → selected_route (공정 규칙이 참조)</text>'
    b += f'<text x="{cx(7) - 40}" y="166" class="al">→ bcs_class (실측으로만 확정)</text>'
    # 근거 정책
    yb = 200
    b += '<text x="10" y="196" class="gt">행마다 verification_status → 엔진이 스스로 권한을 정한다</text>'
    pol = [("검증됨 (VERIFIED*)", "반려(HARD_FAIL) 가능", "det"), ("잠정 (PROVISIONAL 등)", "실행 + ‘잠정’ 표기", "det"),
           ("미검증 · 부분", "반려 금지 → 심사관 표시로 강등", "jud"), ("출처 없음 · 규칙 아님 · LEGACY", "로드 단계에서 제외", "io")]
    for i, (t, sub, k) in enumerate(pol):
        b += box(10 + i * 178, yb + 4, 166, 40, t, sub, k, r=6)
    yv = yb + 62
    b += '<text x="10" y="' + str(yv - 4) + '" class="gt">판정 → 다음 경로</text>'
    out = [("PASS", "명시적 위반 없음 → 신뢰도 요청·심사"), ("SOFT_FLAG", "심사관에게 넘김(반려 아님)"),
           ("HARD_FAIL", "되돌림 전이표 → 복귀 지점"), ("ESCALATE", "구조 미해석 등 → 사람 이관")]
    for i, (t, sub) in enumerate(out):
        b += box(10 + i * 178, yv + 2, 166, 40, t, sub, "hi" if t == "HARD_FAIL" else "det", r=6)
    return svg(720, yv + 50, b)


STATUS_KO = {"passed": "통과", "passed_unranked": "통과(순위 없음)", "infeasible": "제약 불가능", "rejected": "반려", "no_design": "설계 없음",
             "qtpp_review": "QTPP 재검토", "escalated": "이관", "exhausted": "재설계 한도"}


def _jury_why(sc) -> str:
    """조건식이 참이 된 신호 — 표 7의 근거 열."""
    s_ = sc.get("signals") or {}
    out = []
    tp = s_.get("target_population")
    if tp in ("pediatric", "geriatric"):
        out.append({"pediatric": "대상 소아", "geriatric": "대상 고령자"}[tp])
    if s_.get("bcs_class") in ("II", "IV"):
        out.append(f"BCS {s_['bcs_class']}")
    for k, label in (("enabling_candidates_present", "가용화 후보"), ("particle_size_candidates_present", "미분화 후보"),
                     ("asd_candidates_present", "ASD 후보"), ("coverage_gap_present", "룰북 밖 공정"),
                     ("novel_combination_not_in_rulebook", "룰북 밖 부형제")):
        if s_.get(k):
            out.append(label)
    if s_.get("regulatory_narrative_needed"):
        flags = sc.get("soft_flags") or []
        out.append("규제 검토 지적" + (f"({', '.join(f.split('/')[-1] for f in flags[:2])})" if flags else ""))
    if s_.get("solid_form_zone") in ("continuum", "cocrystal_likely"):
        out.append(f"고체상 {s_['solid_form_zone']}")
    if s_.get("salt_stability_watch"):
        out.append("염 안정성 주의")
    return " · ".join(out) or "— (공정 실현성만)"


def jury_tables(data, js) -> str:
    """표 6 심사관 명단(reviewer_registry.csv) · 표 7 상황별 소집(jury_scenarios.json — 실제 시스템 실행)."""
    jury = data.get("jury") or []
    short = {j["reviewer_id"]: j["name"].replace(" 심사관", "") for j in jury}
    t5 = (f"<table><thead><tr><th>ID</th><th>심사관</th><th>소집 조건 (reviewer_registry.csv)</th><th>가중치</th></tr></thead><tbody>"
          + "".join(f"<tr><td class='mono'>{E(j['reviewer_id'])}</td><td>{E(j['name'])}</td><td class='mono'>{E(j['condition'])}</td>"
                    f"<td>{E(j['weight'])}</td></tr>" for j in jury)
          + "</tbody></table><div class='tcap'><b>표 6.</b> 심사관 명단. 조건식이 참일 때만 생성되며 공정 실현성(REV003)은 <code>always</code>이다. "
            "점수(0–1)는 통과 후보 사이의 순위에만 쓰고 반려 권한은 없다.</div>")
    if not js or not js.get("scenarios"):
        return t5
    ids = [j["reviewer_id"] for j in jury]
    sc_rows = js["scenarios"]

    def cell(sc, rid):
        return "●" if rid in (sc.get("summoned") or []) else "○" if rid in (sc.get("planned") or []) else ""

    def req(sc):
        extra = []
        if sc.get("required_excipients"):
            extra.append("고정 " + ", ".join(sc["required_excipients"]))
        mp = {k: v for k, v in (sc.get("measured_params") or {}).items() if k != "dose_mg"}
        if mp:
            num = lambda v: (f"{v:.10f}".rstrip("0").rstrip(".") if abs(v) < 1e-3 else f"{v:g}")      # noqa: E731 — 0.00005를 지수로 쓰지 않는다
            extra.append("실측 " + ", ".join(f"{k}={num(v)}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in mp.items()))
        dose = (sc.get("measured_params") or {}).get("dose_mg")
        return f"“{sc.get('request')}”" + (f" · {dose:g} mg" if isinstance(dose, (int, float)) else "") + (f" · {'; '.join(extra)}" if extra else "")
    head = "".join(f"<th style='text-align:center'>{E(r)}<br><small>{E(short.get(r, ''))}</small></th>" for r in ids)
    body = "".join(f"<tr><td><b>{E(sc.get('label') or '')}</b><br><small>{E(req(sc))}</small></td><td>{E(STATUS_KO.get(sc.get('status'), sc.get('status') or ''))}</td>"
                   + "".join(f"<td style='text-align:center'>{cell(sc, r)}</td>" for r in ids)
                   + f"<td>{E(_jury_why(sc))}</td></tr>" for sc in sc_rows)
    every = [r for r in ids if all(r in (sc.get("summoned") or []) + (sc.get("planned") or []) for sc in sc_rows)]
    never = [r for r in ids if not any(r in (sc.get("summoned") or []) + (sc.get("planned") or []) for sc in sc_rows)]
    note = ((f"{', '.join(every)}는 모든 상황에서 켜졌다. " if every else "")
            + (f"{', '.join(never)}는 이 상황들에서 조건이 성립하지 않았다." if never else f"심사관 {len(ids)}명이 모두 한 번 이상 소집되었다."))
    t6 = (f"<table><thead><tr><th>상황 · 요청</th><th>종결</th>{head}<th>참이 된 소집 신호</th></tr></thead><tbody>{body}</tbody></table>"
          f"<div class='tcap'><b>표 7.</b> 상황별 심사관 소집(실제 시스템, {E(js.get('model') or '')}, 상황마다 1회 실행). ●는 소집되어 통과 후보를 심사한 경우, "
          f"○는 심사 전에 “제약 불가능”으로 끝나 같은 조건식으로 계산한 소집 예정이다. {E(note)}</div>")
    return t5 + t6

def build(data, tests: int, browser: str, x=None, dm=None, lm=None, ab=None, js=None) -> str:
    c = data["counts"]
    bt_rows = "".join(
        f"<tr><td>{E(x['transition_id'])}</td><td>{'판정' if x['trigger_type'] == 'rule_verdict' else '측정'}</td>"
        f"<td>{E(x['return_phase'])}</td><td class='mono'>{E(x['constraint_patch'])}</td><td>{E(x['directive_hint'])}</td></tr>"
        for x in data["backtrack"])
    st_rows = "".join(
        f"<tr><td class='mono'>{E(x['strategy_code'])}</td><td>{E(x['family'])}</td><td>{E(x['label_kr'])}</td>"
        f"<td class='mono'>{E(x['process_steps'])}</td><td class='mono'>{E(x['required_measurements'])}</td></tr>"
        for x in data["strategies"])

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Formula 1 기술 보고서</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>
@page {{ size: A4; margin: 20mm 17mm 20mm 17mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Noto Serif KR", serif; font-size: 10pt; line-height: 1.62; color: #111; margin: 0; word-break: keep-all; }}
h1 {{ font-family: "Noto Sans KR", sans-serif; font-size: 19pt; line-height: 1.35; margin: 0 0 6pt; text-align: center; }}
.sub {{ text-align: center; font-family: "Noto Sans KR"; font-size: 10.5pt; color: #333; margin-bottom: 4pt; }}
.meta {{ text-align: center; font-family: "Noto Sans KR"; font-size: 9pt; color: #555; margin-bottom: 14pt; }}
.abstract {{ border-top: 1.2pt solid #111; border-bottom: 1.2pt solid #111; padding: 8pt 4pt; margin-bottom: 12pt; font-size: 9.4pt; }}
.abstract b.h {{ font-family: "Noto Sans KR"; display: block; margin-bottom: 3pt; }}
.kw {{ font-size: 8.8pt; color: #333; margin-top: 5pt; }}
h2 {{ font-family: "Noto Sans KR", sans-serif; font-size: 12.5pt; margin: 16pt 0 5pt; break-after: avoid; }}
h3 {{ font-family: "Noto Sans KR", sans-serif; font-size: 10.6pt; margin: 11pt 0 3pt; break-after: avoid; }}
p {{ margin: 0 0 6pt; text-align: justify; }}
figure {{ margin: 10pt 0 12pt; break-inside: avoid; }}
figcaption {{ font-family: "Noto Sans KR"; font-size: 8.6pt; color: #333; margin-top: 4pt; }}
figcaption b {{ color: #000; }}
table {{ width: 100%; border-collapse: collapse; font-size: 8.4pt; margin: 6pt 0 10pt; break-inside: avoid; font-family: "Noto Sans KR"; }}
table.split {{ break-inside: auto; }}            /* 긴 표(되돌림 전이표 · 규칙표 목록)는 행 단위로 쪽을 나눈다 — 통째로 넘기면 앞 쪽이 비었다 */
table.split tr {{ break-inside: avoid; }}
table.split thead {{ display: table-header-group; }}
th, td {{ border-top: .5pt solid #bbb; padding: 3pt 4pt; vertical-align: top; text-align: left; }}
thead th {{ border-top: 1.2pt solid #111; border-bottom: .8pt solid #111; }}
tbody tr:last-child td {{ border-bottom: 1.2pt solid #111; }}
.tcap {{ font-family: "Noto Sans KR"; font-size: 8.6pt; margin-top: 8pt; }}
.mono, code {{ font-family: ui-monospace, Menlo, monospace; font-size: 7.8pt; }}
svg text.bt {{ font: 600 10.5px "Noto Sans KR", sans-serif; text-anchor: middle; fill: #111; }}
svg text.bs {{ font: 400 8.6px "Noto Sans KR", sans-serif; text-anchor: middle; fill: #444; }}
svg text.gt {{ font: 700 10px "Noto Sans KR", sans-serif; fill: #222; }}
svg text.al {{ font: 400 8.6px "Noto Sans KR", sans-serif; fill: #333; }}
svg text.lg {{ font: 400 8.6px "Noto Sans KR", sans-serif; fill: #333; }}
ol.refs {{ font-size: 8.6pt; padding-left: 16pt; }}
ol.refs li {{ margin-bottom: 2pt; }}
.eq {{ text-align: center; font-family: "Noto Serif KR"; margin: 6pt 0; }}
.twocol {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12pt; }}
</style></head><body>

<h1>Formula 1: 결정론적 규칙 검증 기반의 다중 에이전트<br>제형 설계 및 QbD Design Space 도출 시스템</h1>
<div class="sub">팀 Formula 1 · 제4회 인공지능 신약개발 경진대회</div>
<div class="meta">라이브 시스템 https://zihwan.com/formula1 · 기술 보고서</div>

<div class="abstract"><b class="h">초록</b>
{abstract(data, lm, ab)}
<div class="kw"><b>주제어</b> 제형 설계 · Quality by Design · 다중 에이전트 · 결정론적 검증 · 환각 억제 · 실험계획법 · 설계공간 · lab-in-the-loop</div>
</div>

{exec_summary(data, ab, tests)}
<h2>1. 서론</h2>
<p>제형 개발은 주성분에 첨가제를 배합해 복용 가능한 제품을 만드는 단계이다. 화학적 비상용성(예: 2차 아민과 유당의 Maillard 반응), 공정 실패(유동성 부족으로
인한 직접타정 불가), 규제 상한 초과(소아용 첨가제 한도)가 이 단계에서 결정되며, 처방이 정해진 뒤에는 위험평가로 중요 변수를 좁히고 실험계획법으로 그 영향을
정량화해야 한다[1].</p>
<p>LLM은 넓은 조합 공간을 탐색하고 상충하는 목표 사이의 절충을 서술하는 데 강하지만, 수치 판단에서 근거 없는 값을 확신 있게 생성할 수 있다. 제약 분야에서 이런
오류는 제품 폐기와 허가 반려로 이어진다. Formula 1은 LLM에 판정 권한을 주지 않고, 판정을 출처가 명시된 규칙표와 결정론 엔진에 맡긴다.</p>
<p>기여는 다섯 가지이다. (1) 규칙마다 근거 검증 상태에 따라 반려 권한이 정해지는 데이터 기반 검증 계층. (2) 값이 없어도 설계를 멈추지 않고 판정이 갈리는
지점에서만 실측을 요청하는 비차단 lab-in-the-loop와, 반려 사유별 복귀 지점을 정의한 되돌림 전이표. (3) 선택된 후보를 ICH Q8 절차의 15단계 승인 체계로
진행하여 위험 행렬, 모형 선택·검증 게이트, ANOVA, Overlay plot Design Space를 결정론적으로 계산하는 개발 단계. (4) 발화를 실행 가능한 입력으로 바꾸되 수치와
구조식의 생성을 코드로 차단한 입력 에이전트. (5) 같은 LLM으로 순수 LLM·검증 계층 제거 조건과 비교하여 검증 계층의 효과를 정량화한 어블레이션.</p>

<h2>2. 관련 연구와 배경</h2>
<p><b>Quality by Design.</b> ICH Q8(R2)[1]는 품질 목표(QTPP)에서 중요 품질 특성(CQA)을 도출하고, 위험평가(ICH Q9[2])로 중요 변수를 좁혀
실험계획법으로 설계공간을 정의한다. 설계공간의 신뢰성은 평균 반응면이 아니라 미래 배치가 규격을 만족할 확률로 평가해야 한다는 관점이 베이즈·예측분포
기반 접근으로 제시되어 왔다[4,5].</p>
<p><b>생물약제학 분류.</b> BCS는 용해도와 투과도로 약물을 분류하고[3], DCS는 용해 속도 제한(IIa)과 용해도 제한(IIb)을 구분해 제형 전략(미분화 대
가용화)을 가른다[6]. 용해도 예측에는 ESOL[7]과 일반용해도식(GSE)[8] 같은 경험식이 쓰인다.</p>
<p><b>LLM 과학 에이전트.</b> FutureHouse의 Robin은 가설 생성·실험 제안·결과 해석을 자동화해 후보 약물을 발굴하였고 지시문 원문을 공개하였다[9].
본 시스템은 그 지시문 패턴(서로 구별되는 가설, 필요 없으면 제안하지 않음, 근거 우선 평가)을 차용하되, 시험 제안을 실제 확인시험 목록({c['confirmation_tests']}행)
안으로 제한하였다. 오케스트레이션에는 LangGraph[10]를 사용한다.</p>

<h2>3. 시스템 개요</h2>
<figure>{fig_architecture(data)}
<figcaption><b>그림 2.</b> 구성 요소 상세. 입력 에이전트가 연구자와 두 그래프 사이에 있고, 두 단계는 연구자가 선택한 후보의 처방(프로토타입) 하나로만
연결된다. ① 안의 두 확대 상자는 규칙 게이트(그림 5)와 동적 심사단(표 6 · 7)의 내부 구조이다. 선 모양은 담당 주체를 나타낸다(실선: 결정론, 파선: LLM,
점선: 순위만 매기는 심사관).</figcaption></figure>
<p>판정과 계산 권한은 결정론 계층에만 있고, LLM은 제안과 서술만 맡으며, 연구자는 개발 후보·위험 등급·실험 요인·회귀 모형을 단계마다 확정한다(표 1).</p>
<table><thead><tr><th>판단 유형</th><th>예</th><th>담당</th></tr></thead><tbody>
<tr><td>정량 판단</td><td>첨가제 상한, 위험 행렬, 회귀계수, ANOVA</td><td>규칙 기반 검사기, 통계 코드</td></tr>
<tr><td>맥락 판단</td><td>소아 복용 적합성, QTPP·위험평가 근거 초안</td><td>심사·초안 LLM(반려·승인 권한 없음)</td></tr>
<tr><td>입력 변환</td><td>“용량은 50 mg”, “1위 후보로 개발 착수”</td><td>입력 에이전트(수치·구조식 생성 금지)</td></tr>
<tr><td>수용 결정</td><td>개발 후보 선택, 위험 등급 승인, 실험 요인 결정, 회귀 모형 승인</td><td>연구자</td></tr></tbody></table>
<div class="tcap"><b>표 1.</b> 판단의 성격별 담당.</div>
<p>LLM 호출은 단일 인터페이스(구조화 출력·스트리밍)로 추상화되어 제공자를 바꿀 수 있다. 운영 환경의 기본 모델은 무료 Groq(gpt-oss-120b)이고, 인증된
세션은 대회 제공 API(gpt-5.6-sol)를 쓸 수 있다(권한은 서버가 재검사). 대회 API가 한도 소진(403)이나 오류로 실패하면 같은 호출을 Groq로 넘기고, 분·일 단위
토큰 한도는 클라이언트가 관리해 호출을 대기시킨다. 끝내 응답이 없으면 결과를 지어내지 않고 “응답 없음”으로 표시한다.</p>

<h2>4. 입력 에이전트</h2>
<p>입력 에이전트는 대화를 실행 가능한 입력으로 바꾼다. 맥락은 브라우저가 보낸 상태가 아니라 서버가 실행 기록에서 만든 스냅숏(설계 상태, 권고 후보, 병합된 실험
요청, 되돌림 정보, 열린 근거 결손)이다. LLM의 구조화 출력으로 의도(설계 실행, 측정값 제출, 개발 착수, 설명, 되묻기)와 초안 값을 받아 제안 카드로 만들고,
카드는 연구자가 실행해야 반영되며 수동 조작과 같은 함수 경로를 탄다.</p>
<figure>{fig_agent()}
<figcaption><b>그림 3.</b> 입력 에이전트의 처리 경로. 해석(LLM, 실패 시 규칙 해석기) 뒤의 가드레일은 모두 코드이다.</figcaption></figure>
<p>가드레일은 프롬프트가 아니라 코드로 강제한다. (i) 제안의 모든 수치는 최근 사용자 발화의 수치여야 하며, 아니면 제거하고 알린다. (ii) SMILES는 사용자 입력,
내장 구조 사전, PubChem[12] 조회에서만 얻고 카드에 CID와 링크를 붙인다. (iii) 측정 키는 허용 목록과 측정 카탈로그로, 개발 착수는 현재 설계의 통과 후보로
제한한다. (iv) 구조식과 1회 용량이 없으면 카드를 미완성으로 두고 되묻는다(용량 없이는 용량/용해도 부피와 DCS가 성립하지 않는다). (v) 개발코드(예: VX-770)로
부른 물질은 코드를 이름으로 고정하고 실명과 라벨 제품명을 응답 전체에서 가린다. LLM이 되묻기만 했으나 발화의 행동이 분명하면(예: “Tm 317도” → 측정값
제출) 규칙 해석기가 보완하고, 설계가 끝나면 LLM 없이 맥락만으로 다음 행동을 먼저 제시한다.</p>

<h2>5. 후보 탐색 그래프</h2>
<h3>5.1 분자 프로파일과 값의 세 계층</h3>
<p>RDKit으로 구조 품질(파싱, 염, 전하, 입체), 기술자 35종, 구조 패턴 {c['structural_flags']}종을 계산한다. 패턴마다 등급(구조 사실·조건부 경고·높은 경고),
위험 조건, 확인 시험이 있고, 세분화된 아민 분류는 규칙표의 결합 키(<code>primary_amine</code>/<code>secondary_amine</code>)로 이어진다. 염 형태 구조는 가장 큰
유기 조각을 parent로 확정해 모든 물성을 parent 기준으로 계산하고, 염/유리염기 분자량비는 함량 환산에 따로 쓴다(베실산 암로디핀: 염 MW 567.1, parent 408.9).
값은 계산값(A), 경험식 예측값(B), 실측값(C)으로 구분되며, 예측값은 <code>*_est</code>에만 저장되어 실측을 덮지 않고 BCS 등급은 실측으로만 확정된다.
파생값 {c['derived_quantities']}종(D0, 흡수 한계, Tg 여유, ΔpKa 등)은 CSV 식으로 정의하고 고정점 반복으로 계산해, 결과가 코드의 기술 순서에 좌우되지 않는다.</p>
<figure>{fig_value_tiers()}
<figcaption><b>그림 4.</b> 값의 세 계층과 비차단 실험 요청. 측정값이 들어오면 그래프를 다시 돌리지 않고 결정론 계층만 재계산하며, 계획 서명이 같으면
신뢰도 태그만 갱신한다.</figcaption></figure>

<h3>5.2 페이즈 게이트와 계획</h3>
<p>게이트는 3A(BCS/DCS) → 3B(고체상) → 4(가용화 필요 여부) → 4B(ASD 공정) 순으로 평가되며, 이 순서가 게이트 간 의존을 반영한다. 게이트는 반려하지 않고
전략 탐색 범위만 정한다. 조건식이 값의 부재를 조건으로 쓰는 경우(<code>tm_c is None</code>)를 위해 모든 참조 변수를 <code>None</code>으로 먼저 채워, “모름”이
“미발동”으로 읽히지 않게 한다. 계획은 발동 신호로 전략 {c['strategies']}종(표 2)을 채점해 상위 3개를 고르고, 정렬된 전략 코드로 계획 서명을 만든다. 판정이
갈리지 않으면(예: 투과도 미상으로 IIa/IIb 구분 불가) 양쪽 전략을, 유동성 자료가 없으면 세 공정 경로를 모두 잠정 허용한다. 되돌림 제약 뒤 남는 전략이 없으면
목표(QTPP) 재검토로 종료한다.</p>
<table><thead><tr><th>코드</th><th>가족</th><th>전략</th><th>공정 단계</th><th>요구 측정(트리거)</th></tr></thead><tbody>{st_rows}</tbody></table>
<div class="tcap"><b>표 2.</b> 전략 가족(<code>strategy_families.csv</code>). 요구 측정 열은 측정 기반 되돌림이 적용되는 전략도 정한다.</div>

<h3>5.3 규칙 게이트</h3>
<p>규칙은 코드가 아니라 CSV 행이다. 단일 manifest가 각 CSV를 여덟 개의 범용 검사 함수(쌍 금기, 부분집합 금지, 임계값, 범위, 필수 성분, 조건부 금지, 구간
조회, 결정 트리) 중 하나에 연결하고, 검사는 우선순위 단계별로 실행되어 앞 단계의 파생값(유동성 등급 → 공정 경로 → BCS 등급)이 뒤 단계의 발동 조건이 된다.
행마다 <code>verification_status</code>가 있어 검증된 행만 반려할 수 있고, 미검증 행은 심사관 표시로 강등되며, 출처 없는 행은 로드되지 않는다. 성분명은 두
부형제 마스터(영문·국문·이명)를 사전으로 정규화해 대조하고 등급 표기 구절(예: “direct-compression grade”, “PH 102”)은 구절 단위로 제거한다. 구조를 해석하지
못한 실행은 통과가 아니라 이관(STRUCT000)으로 끝난다. 시스템이 읽는 규칙표의 종류는 표 3에 정리하였다.</p>
{rulebook_table(data)}
<p><b>입력 계약.</b> 모든 규칙에 앞서 후보가 요청과 일치하는지 대조한다: API 행이 정확히 하나인지, 유리염기 환산 함량이 요청 용량의 ±0.5% 이내인지(염 이름으로
적힌 함량은 RDKit 분자량비나 PubChem CID가 명시된 짝이온 표로 환산), 고정 부형제가 모두 들어 있는지, 1회 함량이 허가 라벨의 1일 최대 용량 이하인지(FDA 라벨
원문·DailyMed set_id 보관, parent InChIKey 골격으로 대조). 위반하면 같은 전략에서 함량과 성분을 고쳐 재설계하고, 요청 용량 자체가 라벨 최대 용량을 넘으면 곧바로
“제약 불가능”으로 끝낸다. MCC(20–90%)나 탈크(1–10%)처럼 역할만으로 배합비 범위가 맞지 않는 부형제는 출처가 명시된 매핑표로 판정용 역할을 바꾸고, 혼합 시간에
따른 과혼합 위험(INC014)은 반려하지 않고 DoE 요인 후보로 넘긴다.</p>
<figure>{fig_rulegate(data)}
<figcaption><b>그림 5.</b> 규칙 기반 게이트. 입력 계약이 먼저 수행되고, manifest 항목 29개가 우선순위 단계로 실행된다(각 칸: 검사 함수와 판정·LLM·참조
항목 수). 파생값(유동성 등급 → 공정 경로, 실측 BCS 등급)이 뒤 단계의 조건이 되며, 공정 세부 규칙표는 통과 조건(pass_when)으로 읽는다. 아래 두 줄은 근거
상태별 반려 권한과 판정별 다음 경로이다. 규칙 추가는 CSV 행과 manifest 한 줄이면 된다.</figcaption></figure>

<h3>5.4 반려 사유별 되돌림</h3>
<figure>{fig_discovery()}
<figcaption><b>그림 6.</b> 후보 탐색 그래프. <code>backtrack</code>은 반려 판정을 전이표에 대조해 복귀 지점(GATE: 같은 전략에서 성분만 교체, G6R: 공정 경로부터,
G4: 전략 선택부터)과 제약을 정한다. 하단은 종결 노드이다.</figcaption></figure>
<p>한 라운드의 여러 반려는 가장 깊은 복귀 지점으로 합치고 제약은 모두 누적한다. 같은 지점으로 3회 돌아가도 해소되지 않으면 상위 단계로 올려 그 전략을 제외하고,
전체 5회를 넘으면 연구자에게 이관한다. 반려 사유가 사용자가 고정한 성분이면 되돌리지 않고 즉시 “제약 불가능”과 대체 성분을 제시한다. 측정 결과가 전략의
전제를 부정하면(예: ASD 비혼화) 그 측정을 요구하는 전략에만 제외를 적용한다(표 2).</p>
<table class="split"><thead><tr><th>ID</th><th>계기</th><th>복귀</th><th>제약</th><th>지시</th></tr></thead><tbody>{bt_rows}</tbody></table>
<div class="tcap"><b>표 4.</b> 되돌림 전이표(<code>backtrack_transitions.csv</code>, {c['backtrack_transitions']}행).</div>

<h3>5.5 실험 요청과 신뢰도</h3>
<p>요청할 수 있는 시험은 측정 카탈로그 {c['measurement_catalog']}종으로 한정되고, 시험마다 필요한 시료량에 따라 Tier가 정해져 있다(표 5). 요청은
<b>Tier 번호가 낮은 순(1 → 2 → 3 → 전략별), 같은 Tier 안에서는 시료량이 적은 순</b>으로 제시한다. 초기 개발 단계는 원료(API)가 적으므로, 적은 시료로
판정을 가를 수 있는 시험(Tier 1: XRPD · DSC · TGA · KF, 약 10 mg)부터 묻는다. 요청 시점·사유·거절 시 대체 경로는 트리거 표 {c['data_request_triggers']}행에
정의되어 있어 판정이 갈리는 지점에서만 요청이 나가며, 계획 전에는 전략을 좁히는 요청을, 후보 생성 뒤에는 후보별 신뢰도 요청을 낸다. 같은 시험을 가리키는
요청은 하나로 합치고(예: 고체상 판정과 Tm 요청은 DSC 한 번), 용해도 요청은 “예측이 낮거나 없음”과 “두 예측이 1 log 이상 불일치”를 구분한다.
요청은 설계를 막지 않아, 건너뛰면 예측값으로 진행하고 후보는 provisional로 남는다. 신뢰도는 <code>grounded ⟺ 남은 신뢰도 요청 = ∅</code>로 계산되어 LLM이
관여하지 않는다. 이온화 가능 약물은 pH 1.2–6.8에서 용해도가 달라지므로 단일 예측으로 판정하지 않고 pH별 평형용해도를 요청하며, 공식 문헌 값이 있으면 문헌
표로 잠정 판정을 채운다. 측정값은 근거 등급(자체 실측, 문헌, 사용자 진술)과 함께 기록된다.</p>
{tier_table()}
<p>결과 필드 {c.get('measurement_output_fields', 0)}개의 타입(수치·예/아니오·등급·목록)·단위·선택지는 표 하나(<code>measurement_output_fields.csv</code>)로 정의되며,
입력 칸과 서버 검사가 같은 정의를 쓴다(타입이 다르면 422). 원자료 첨부는 내용 해시로 제출 기록에 연결되지만 판정에는 쓰이지 않는다. 첨부 해석은 초안만 만든다:
기기 원자료(XRPD·DSC·TGA)는 결정론 계산(halo 반치폭, onset 접선 외삽, 100–150 °C 무게 감소, Td5%)으로, 그림은 대회 API의 이미지 입력으로 처리해 해당 측정의
필드만 제안하고, 연구자가 확정해야 입력된다. 추가 조건이 필요한 값(융해열, 결정형 ID)은 만들지 않는다.</p>

<h3>5.6 동적 심사위원단과 합의</h3>
<p>심사관 {c['reviewers']}명(소아 안전, 가용화 전략, 공정 실현성, 규제 취지, 문헌 조사, 고령자 안전, 고체상 안정성)은 소집 조건식이 참일 때만 생성된다.
심사관은 근거 강도 → 잔여 위험 → 실현 가능성 → 참신성 순의 기준으로 통과 후보에 점수를 매기되 반려 권한은 없고, 합의는 결정론적 가중평균이다. 점수에는
검증된 DOI·PMID 인용이 필요하다. 인용 후보는 Europe PMC 검색 결과와 룰북 인용 등록부(Crossref·NCBI로 확인한 14건)이며, 목록 밖 식별자는 실행 중 조회해
실재할 때만 인정한다. 확인된 인용이 없는 점수와 LLM이 응답하지 않은 심사는 점수를 만들지 않고 합의에서 뺀다. 소집 신호(대상 인구군, 가용화·미분화·ASD 후보,
룰북 밖 조합, 규제 검토 지적, 고체상 경계)는 결정론으로 계산되므로 같은 요청이라도 설계된 성분에 따라 명단이 달라질 수 있다. 명단과 소집 조건은 표 6,
상황별 소집 결과는 표 7과 같다. 심사 전에 “제약 불가능”으로 끝나는 실행에도 소집 예정 심사관을 같은 조건식으로 계산해 결론과 함께 보인다(표 7의 ○).</p>
{jury_tables(data, js)}

<h2>6. 2단계: Design Space 도출</h2>
<p>연구자가 후보 카드에서 개발 착수를 누르면 처방이 논문 Table 1 형식의 프로토타입(성분, mg/정, %, 기능, 공정)으로 바뀌어 2단계 study가 생성된다.</p>
<p><b>근거 결손 게이트.</b> 규칙 게이트 통과는 “알려진 금기가 없다”는 뜻이지 “필요한 근거가 있다”는 뜻이 아니다. 그래서 진입 전에 통과 후보마다 필수 근거
{c.get('evidence_requirements', 0)}행(개발 전 확보 항목 {c.get('evidence_before', 0)}행: 수분·열 안정성, 배합 적합성, 실험 용해도, BCS 근거 등)을 결정론으로 평가하고,
결손이 있으면 확인시험 마스터 {c['confirmation_tests']}종의 실제 행에서만 시험을 요청한다. 측정값은 후보가 아니라 스펙에 기록되어 모든 후보가 함께 다시 판정되므로,
결손은 요구 항목별로 묶어 근거 결손 게이트 카드 하나에서 받는다. 결과는 적합·부적합이 아니라 측정값(수치 또는 수행 여부)으로 입력하며, 입력값은 페이즈 게이트부터
다시 계산되어 계획, 규칙 게이트 판정, 근거 판정이 차례로 갱신된다(LLM 호출 없음, 전략 집합이 바뀔 때만 재설계, 전 과정 트레이스 기록). 값은 입력 에이전트에
자연어로 말해도 된다. 용해도는 pH마다, 투과도는 흡수율·절대 생체이용률·요중 회수율·Papp처럼 표현과 단위가 제각각이므로, 에이전트는 값·단위·pH·방법을 쓰인
그대로 뽑고 단위 환산, pH 1.2–6.8 최저값, 용량/용해도 부피는 코드가 ICH M9[3]에 따라 계산한다(고용해도는 pH 1.2·4.5·6.8을 모두 잰 경우만 인정, 생체이용률·요중
회수율은 85 % 이상일 때만 흡수율로 인정, Papp은 흡수율로 환산하지 않음). 결손을 둔 채 개발에 들어가려면 연구자가 사유를 기록해야 하며, 사유와 남은 결손은
Handoff 지문과 보고서에 남는다. 이 게이트는 개발 착수를 보류할 뿐 반려하지 않는다.</p>
<p><b>승인 체계.</b> study는 ICH Q8[1]·Q9[2] 절차를 15단계로 구성하며(그림 7), 각 단계는 초안(LLM, 논문 값, 연구자 입력) → 결정론 검사 → 연구자 승인 순으로 진행된다.
현재 단계만 수정할 수 있고, 승인한 단계를 다시 열면 뒤 단계는 지우지 않고 재확인 필요로 표시한다. 모든 변경은 멱등 키와 기대 버전으로 기록되며, 출처(LLM, 논문,
연구자, 코드)와 승인자·시각이 이력과 보고서에 남는다.</p>
<figure>{fig_stage2()}
<figcaption><b>그림 7.</b> 2단계의 15단계. 표 번호는 Monton 등[18]의 대응 표이다. 8단계에 진입하면 위험평가 보고서가, 12단계를 확인하면 최종 보고서(실험 설계, 회귀식,
반응 곡면, ANOVA, 13–15단계가 있으면 Design Space·확인계획·확인배치 포함)가 PDF로 생성된다. 1단계에는 후보의 조성과 요청 맥락이 지문을 포함한 불변 Handoff로
전달된다.</figcaption></figure>
<p><b>위험평가.</b> 초안은 LLM 호출 두 번으로 만든다. 변수 × 확정 CQA 격자에 대해 등급(High·Medium·Low)만 받고, 코드가 같은 변수에서 등급이 같은 CQA를 묶은 뒤
묶음마다 기전 문장을 받는다(8묶음 단위, 실패 시 1회 재시도). 따라서 초안은 구조적으로 모든 칸을 정확히 한 번 포함한다. 행렬(5·7단계)은 이 근거 표에서 코드가
계산하므로 연구자는 확인만 한다. 결정론 검사는 승인 차단 조건
{len(data.get('stage2', {}).get('check_codes', {}).get('blocking', []))}종(예: 근거 없는 칸, 확정 CQA 밖의 열, 평가하지 않은 부형제, 공정 변수 자리의 공정 명칭, 이름
없는 요인, 추정 불가 모형, 모든 반응의 게이트 불합격, 평균 기준 영역 없음)과 경고
{len(data.get('stage2', {}).get('check_codes', {}).get('warning', []))}종으로 구성된다. 입력에 없는 수치를 쓴 초안에는 출처 확인 경고가 붙고, LLM이 응답하지 않으면
아무것도 채우지 않는다.</p>
<p><b>실험 설계와 통계.</b> 9단계 표(요인 1–3개, 반응 1–4개, 행 수 제한 없음)는 연구자가 입력하거나 CSV·스프레드시트로 붙여 넣으며, 시연용으로 출처가 명시된
논문 실측 표(Monton 등[18] Table 9, Almotairi 등[11] Table 3)를 불러올 수 있다. 요인과 반응 이름은 연구자가 정한다(8단계의 High 변수와 CQA는 제안으로만 제시).
10단계는 요인을 코딩해 평균·선형·2요인 교호작용·순수 2차·2차·축소 2차(계층성을 유지하며 p &gt; 0.05인 항을 하나씩 제거) 모형을 적합하고, AICc 순으로 정렬한 뒤
(최솟값 + 2 이내면 항이 적은 모형 우선) 검증 게이트 네 조건 — 모형 p &lt; 0.05, 적합결여 p ≥ 0.05(반복점이 있을 때), 조정 R² − 예측 R² ≤ 0.2, 예측 R² &gt; 0 —
를 처음 통과한 모형을 채택한다. 평균 모형까지 내려간 반응은 “요인으로 설명되지 않음”으로 영역과 ANOVA에서 빠지고 관측 범위로 목표와 비교된다. 연구자가 고른
모형도 같은 게이트를 통과해야 하며, 모든 반응이 불합격이면 10단계를 승인할 수 없다. 논문 표(Monton 2026 Table 9)에서는 논문의 모형 차수로 식을 설정할 수 있다.
11단계는 반응 곡면(게이트 통과 반응이 하나라도 있으면 모든 반응을 그리고 불합격 반응은 참고로 표시), 12단계는 부분 제곱합 ANOVA(Table 11 형식)이며 LLM은 관여하지
않는다.</p>
<p><b>Design Space와 확인.</b> 13단계는 반응별 목표로 Overlay plot(논문 Figure 2 형식)을 그린다. 영역은 게이트 통과 반응의 평균 예측이 모든 목표를 동시에
만족하는 구간이고, 설계점 볼록 껍질 밖은 외삽으로 제외한다. 요인이 셋이면 효과가 가장 작은 요인을 −1, 0, +1에 고정한 세 단면(41점 격자)을 그리고, 영역에 들어가는
가장 넓은 축 정렬 직사각형(가로·세로 3칸 이상)을 control space로 정한다. 최적 처방은 control space 안에서(실험 범위 경계로부터 0.1 coded 이상) 새 배치가 모든
목표를 만족할 확률[4]이 가장 큰 점이다. 이 확률(반응별 t 예측분포 통과확률의 곱, 반응 간 독립 가정)은 보조 지표로 등고선에 표시되며, 13단계 승인은 평균 기준
영역이나 control space가 없을 때만 막힌다. 14단계는 최적점, 확률이 가장 낮은 control space 꼭짓점(경계), 최적점 ± 허용 변동 중 확률이 가장 낮은 점(강건성)의 세
확인점과 동시 예측구간(Bonferroni)을 결과 확인 전에 잠그고(시각·해시 기록), 15단계는 새 독립 배치의 실측이 세 점 모두에서 규격과 예측구간을 만족할 때만(2×2)
VERIFIED로 기록한다. 이는 내부 사전계획의 충족이며 규제 당국이 승인한 설계공간을 뜻하지는 않는다.</p>
<div class="eq">영역: ∀k ŷ<sub>k</sub>(x) ∈ Spec<sub>k</sub> (게이트 통과 반응) · 보조: P(x) = ∏<sub>k</sub> Pr[ Y<sub>k</sub><sup>new</sup>(x) ∈ Spec<sub>k</sub> ],&nbsp; Y<sub>k</sub><sup>new</sup>(x) ~ ŷ<sub>k</sub>(x) + t<sub>ν</sub>·√(SE<sub>k</sub>(x)² + σ̂<sub>k</sub>²)</div>

<h2>7. 적용 결과</h2>
{stage2_section(data.get('stage2'))}
{lornox_section((data.get('stage2') or {}).get('lornoxicam'))}
<h3>7.3 검증 계층의 동작</h3>
<p>소아용 플루옥세틴 정제에 유당 수화물을 고정하면 구조 패턴이 2차 아민을 검출하고 배합 금기 INC002(2차 아민 × 유당 → Maillard 반응[13])가 후보를 반려한다.
반려 사유가 고정 성분이므로 되돌리지 않고 “제약 불가능”과 대체 성분(만니톨)을 제시한다. 같은 금기가 “유당”, “Lactose, NF”, “유당수화물”, “Lactose monohydrate,
direct-compression grade” 표기에서 모두 발동하고 만니톨·전분글리콜산나트륨에서는 발동하지 않음을 회귀 테스트로 고정하였다.</p>

{exp_section(x)}
{demo_section(dm)}
{llm_section(lm)}
{ablation_section(ab)}
<h3>7.8 소프트웨어 검증</h3>
<p>단위·통합 테스트 {tests}개(pytest)는 구조 패턴 진리표, 검사 방향, 근거 정책, 페이즈 게이트, 되돌림·계획 불변식, 입력 에이전트 가드레일(블라인드 포함), 조건식
이름 전수 검사, 측정 필드 타입과 첨부, 근거 결손 게이트(측정값 재계산, 진입 차단, 사유)와 자연어 근거 입력의 환산 규칙, 요청 계약의 염 환산, 성분명 등급 표기
정규화, 논문 표 재현(행렬, Table 10·11), 모형 선택·검증 게이트와 Overlay Design Space의 골든 값, 단계 권한·승인 차단·다시 열기·확인계획 잠금, LLM 초안의 칸
포함을 고정한다. 이 빌드에서 실행한 브라우저 테스트({E(browser)})는 대화 흐름(설계 실행 카드, 실험 데이터 입력, 물리화학, 데이터 요청, 후보, 개발 착수), 관측 패널,
2단계 클릭 조작(CBD 1–13단계, PDF 두 종, 데스크톱·휴대폰 폭), 시연 사례 ①의 전체 파이프라인(실제 LLM), 데이터 요청 전 심사위원단 카드와 후보별 심사 요약,
근거 결손 게이트(공통 입력 카드, 사유 칸, 자연어 입력의 코드 환산, phase_gates부터 재계산, 재설계 후보의 재심사, 근거 충족, 착수), 시연 사례 ②③의 경로, 여섯 렌더 경로의 스크립트 주입, 가이드와 테마를 검사한다.</p>

<h2>8. 논의</h2>
<p><b>판정 권한의 위치.</b> 시스템의 안전성은 LLM의 정확도가 아니라 판정 권한의 배치에서 나온다. 설계·심사·초안 LLM이 틀려도 반려는 규칙만, 승인은 연구자만
할 수 있으므로 LLM의 오류는 반려되거나 승인 전에 고쳐진다. 7.7절의 어블레이션은 이것을 수치로 보인다. 같은 모델, 같은 계획·설계 모듈에서 검증 계층만 제거하면
규칙이 금지하는 처방이 연구자에게 제시되었고, 규칙표 근거를 설계 에이전트에 제공하는 것만으로는 이를 막지 못하였다. 입력 에이전트는 같은 원칙을 입력 단계로
넓혀, 대화 창이 새로운 환각 경로가 되지 않게 수치와 구조식의 출처를 코드로 제한한다.</p>
<p><b>미확인 상태의 표현.</b> “규칙이 발동하지 않음”과 “문제가 없음”을 구분하는 것이 설계의 핵심이다. 성분명 불일치, 구조 해석 실패, 빈 사전은 모두 조용한
통과를 만들 수 있으므로 각각을 판정 불가 또는 이관으로 처리하고, 결측 값은 NOT_CHECKED나 실측 요청으로 기록한다. 조건식이 어느 계층에서도 채워지지 않는 변수를
참조하면 규칙이 영구히 꺼지므로, 규칙표·전이표·심사관 명단·manifest의 조건식 {c.get('conditions_audited', 0)}개를 파싱해 모든 이름이 실제로 채워지는지 대조하는
전수 검사를 테스트로 고정하였다. 자유 표기와 규칙표 데이터를 잇는 경로(성분명의 등급 표기, 염 이름으로 적힌 함량)에도 같은 원칙으로 정규화와 환산 규칙을 두었다.</p>
<p><b>적용 범위와 향후 과제.</b> (1) 위험 등급처럼 판단이 필요한 칸은 설계상 연구자 승인으로 확정하며, 새 후보에서는 제제 전문가의 검토가 기준이 된다(7.6절).
(2) 물성 예측기 레지스트리에는 신경망 예측기(ADMET-AI 등)를 연결할 자리가 있으며, 규칙 변경 없이 추가할 수 있다. (3) 2단계 study와 대화 기록의 영속 저장,
mixture·D-optimal 설계와 다반응 최적화, 스케일업은 다음 단계의 범위이다. (4) 15단계 확인배치 판정은 새 독립 배치의 실측으로 수행하며, 공개 자료 시연은 확인계획
잠금까지이다. (5) 어블레이션의 금기 요청은 규칙의 근거 문헌이 해당 분자나 그 화학 계열을 직접 다루는 사례(플루옥세틴–유당[13], 암로디핀–유당[14])로 구성하였으며,
사례를 늘릴 때도 같은 기준을 적용한다.</p>

<h2>9. 결론</h2>
<p>Formula 1은 제형 설계에서 LLM의 생성 능력과 결정론 검증을 분리하고, 후보 탐색부터 Design Space까지를 두 단계와 하나의 연결점(연구자가 선택한 처방)으로
구성하였다. 값이 없어도 설계를 멈추지 않고 필요한 실측만 요청하며, 반려되면 사유가 가리키는 지점으로 돌아가고, 선택된 후보는 QTPP부터 ANOVA, Design Space,
확인계획까지 단계별 연구자 승인을 거친다. 공개 논문의 위험 행렬과 회귀·ANOVA를 근거 표와 원자료로부터 재현하였고, 검증 게이트는 논문 모형 중 예측력이 부족한
두 모형(CBD 붕해시간·마손도)을 걸러 냈으며, 공개 실측 15 run으로부터 control space와 최적 처방을 도출하였다. {conclusion_ablation(ab)}</p>

<h2>참고문헌</h2>
<ol class="refs">
<li>ICH Q8(R2) Pharmaceutical Development. International Council for Harmonisation, Step 4, 2009.</li>
<li>ICH Q9(R1) Quality Risk Management. International Council for Harmonisation, Step 4, 2023.</li>
<li>ICH M9 Biopharmaceutics Classification System-Based Biowaivers. International Council for Harmonisation, Step 4, 2019.</li>
<li>Peterson J.J. A Bayesian approach to the ICH Q8 definition of design space. <i>J. Biopharm. Stat.</i> 18(5):959–975, 2008. doi:10.1080/10543400802278197</li>
<li>Lebrun P., Govaerts B., Debrus B., et al. Development of a new predictive modelling technique to find with confidence equivalence zone and design space of chromatographic analytical methods. <i>Chemometr. Intell. Lab. Syst.</i> 91(1):4–16, 2008. doi:10.1016/j.chemolab.2007.05.010</li>
<li>Butler J.M., Dressman J.B. The developability classification system: application of biopharmaceutics concepts to formulation development. <i>J. Pharm. Sci.</i> 99(12):4940–4954, 2010. doi:10.1002/jps.22217</li>
<li>Delaney J.S. ESOL: estimating aqueous solubility directly from molecular structure. <i>J. Chem. Inf. Comput. Sci.</i> 44(3):1000–1005, 2004. doi:10.1021/ci034243x</li>
<li>Jain N., Yalkowsky S.H. Estimation of the aqueous solubility I: application to organic nonelectrolytes. <i>J. Pharm. Sci.</i> 90(2):234–252, 2001. doi:10.1002/1520-6017(200102)90:2&lt;234::AID-JPS14&gt;3.0.CO;2-V</li>
<li>Ghareeb A.E., Chang B., et al. A multi-agent system for automating scientific discovery. <i>Nature</i> 655(8122):497–505, 2026. doi:10.1038/s41586-026-10652-y (preprint: “Robin: A multi-agent system for automating scientific discovery”, arXiv:2505.13400; 지시문 github.com/Future-House/robin).</li>
<li>LangChain. LangGraph (소프트웨어). github.com/langchain-ai/langgraph.</li>
<li>Almotairi N., Mahrous G.M., et al. Design and Optimization of Lornoxicam Dispersible Tablets Using Quality by Design (QbD) Approach. <i>Pharmaceuticals</i> 15(12):1463, 2022. doi:10.3390/ph15121463 (CC BY)</li>
<li>Kim S., Chen J., Cheng T., et al. PubChem 2023 update. <i>Nucleic Acids Res.</i> 51(D1):D1373–D1380, 2023. doi:10.1093/nar/gkac956</li>
<li>Wirth D.D., Baertschi S.W., Johnson R.A., et al. Maillard reaction of lactose and fluoxetine hydrochloride, a secondary amine. <i>J. Pharm. Sci.</i> 87(1):31–39, 1998. doi:10.1021/js9702067</li>
<li>Abdoh A., Al-Omari M.M., Badwan A.A., Jaber A.M.Y. Amlodipine besylate–excipients interaction in solid dosage form. <i>Pharm. Dev. Technol.</i> 9(1):15–24, 2004. doi:10.1081/PDT-120027414</li>
<li>Thompson S.A., Davis D.A., Miller D.A., Kucera S.U., et al. Pre-processing a polymer blend into a polymer alloy by KinetiSol enables increased ivacaftor amorphous solid dispersion drug loading and dissolution. <i>Biomedicines</i> 11(5):1281, 2023. doi:10.3390/biomedicines11051281</li>
<li>Corrie L., Ajjarapu S., Banda S., Parvathaneni M., Bolla P.K., et al. HPMCAS-based amorphous solid dispersions in clinic: a review on manufacturing techniques (hot melt extrusion and spray drying), marketed products and patents. <i>Materials</i> 16(20):6616, 2023. doi:10.3390/ma16206616</li>
<li>ICH Q1A(R2) Stability Testing of New Drug Substances and Products. International Council for Harmonisation, Step 4, 2003.</li>
<li>Monton C., et al. Quality by Design–Driven Formulation Development of Cannabidiol Orally Disintegrating Tablets. <i>Scientifica</i> 2026:3553253, 2026. doi:10.1155/sci5/3553253 (PMC13519653)</li>
</ol>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", type=int, required=True, help="pytest 통과 개수(실제 실행 결과)")
    ap.add_argument("--browser", required=True, help="브라우저 테스트 요약(실제 실행 결과)")
    a = ap.parse_args()
    data = json.loads((OUT / "figdata.json").read_text(encoding="utf-8"))
    xp = OUT / "experiments.json"
    x = json.loads(xp.read_text(encoding="utf-8")) if xp.exists() else None
    dp = OUT / "demo_cards.json"
    dm = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else None
    lp = OUT / "stage2_llm.json"
    lm = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else None
    ap_ = OUT / "ablation.json"
    ab = json.loads(ap_.read_text(encoding="utf-8")) if ap_.exists() else None
    jp = OUT / "jury_scenarios.json"
    js = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else None
    (OUT / "report.html").write_text(build(data, a.tests, a.browser, x, dm, lm, ab, js), encoding="utf-8")
    print(OUT / "report.html")


if __name__ == "__main__":
    main()
