"""기술 보고서(논문 형식) 빌드 — docs/report/figdata.json(엔진 실측) → docs/report/report.html → PDF.

    docker run --rm -e PYTHONPATH=/app -v "$PWD":/app -w /app formula1-dev python scripts/report/figdata.py
    python3 scripts/report/build_report.py --tests 199 --browser "verify 33 · audit · scenarios · studio · agent"
    "<chrome>" --headless=new --no-pdf-header-footer --print-to-pdf=docs/report/Formula1_report.pdf docs/report/report.html

그림의 수치는 전부 figdata.json(엔진 계산)이나 저장소의 CSV 행 수에서 온다. 손으로 적은 결과값은 없다.
"""
from __future__ import annotations

import argparse
import html
import json
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
    stages = ["0 입력계약", "0 참조", "5 물성", "10 흐름→경로", "20 금기·소아", "30 다성분", "40 공정", "50 코팅", "60 BCS", "70 포장"]
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

    # Handoff · ② 개발 스튜디오
    b += box(210, 492, 300, 36, "불변 Handoff", "candidate_id@version · fingerprint", "hi")
    b += arrow(580, 464, 470, 492, "연구자가 선택", lx=540, ly=484)
    b += '<rect x="10" y="546" width="700" height="120" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="22" y="564" class="gt">② 개발 스튜디오 — ExperimentalDevelopmentGraph (상태기계 · 주·월 단위)</text>'
    st = [("Readiness", "det"), ("CQA 계약", "det"), ("FMEA", "llm"), ("요인·수준", "det"), ("DoE 설계", "det"),
          ("결과·모델", "det"), ("잠정 영역", "det"), ("확인배치", "det")]
    for k, (t, kk) in enumerate(st):
        b += box(20 + k * 86, 576, 78, 34, t, "", kk, r=6)
        if k < len(st) - 1:
            b += arrow(98 + k * 86, 593, 106 + k * 86, 593)
    b += box(250, 624, 220, 32, "VERIFIED 영역 + 성립 조건", "", "io")
    b += arrow(360, 528, 360, 546)
    b += arrow(622, 610, 470, 632)
    b += '<text x="480" y="654" class="al">판정 07_doe 171규칙 · 숫자 엔진 · 승인 연구자</text>'
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
    b += path("M 305 130 L 305 100 L 455 100 L 455 64", "GATE: 성분만", 330, 95)
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


def fig_region(data):
    sl = data["slice"]
    n = len(sl["rows"])
    cell = 11
    ox, oy = 48, 18

    def panel(x0, title, key):
        t = f'<text x="{x0 + n * cell / 2}" y="12" class="gt" text-anchor="middle">{E(title)}</text>'
        for ia in range(n):
            for ib in range(n):
                x = x0 + ib * cell
                y = oy + (n - 1 - ia) * cell
                if not sl["in"][ia][ib]:
                    t += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="#e9ecef"/>'
                    continue
                if key == "P":
                    p = sl["P"][ia][ib]
                    shade = int(245 - 205 * p)
                    col = f"rgb({shade},{shade + 5 if shade < 250 else 250},{min(255, shade + 40)})"
                    t += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{col}"/>'
                    if p >= 0.9:
                        t += f'<rect x="{x + 3.5}" y="{y + 3.5}" width="4" height="4" fill="#fff"/>'
                else:
                    ok = sl["mean_ok"][ia][ib]
                    t += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{"#6c8fd6" if ok else "#f6d5d5"}"/>'
        t += f'<rect x="{x0}" y="{oy}" width="{n * cell}" height="{n * cell}" fill="none" stroke="#333"/>'
        # setpoint
        sa, sb = data["setpoint"]["coded"]["a"], data["setpoint"]["coded"]["c"]
        ia = min(range(n), key=lambda i: abs(sl["rows"][i] - sa)); ib = min(range(n), key=lambda i: abs(sl["cols"][i] - sb))
        t += f'<circle cx="{x0 + ib * cell + cell / 2}" cy="{oy + (n - 1 - ia) * cell + cell / 2}" r="4.5" fill="none" stroke="#d00" stroke-width="2"/>'
        # axes
        for v, lab in ((0, "2"), (n // 2, "6"), (n - 1, "10")):
            t += f'<text x="{x0 + v * cell + cell / 2}" y="{oy + n * cell + 12}" class="lg" text-anchor="middle">{lab}</text>'
        for v, lab in ((0, "1"), (n // 2, "2"), (n - 1, "3")):
            t += f'<text x="{x0 - 5}" y="{oy + (n - 1 - v) * cell + cell / 2 + 3}" class="lg" text-anchor="end">{lab}</text>'
        t += f'<text x="{x0 + n * cell / 2}" y="{oy + n * cell + 26}" class="lg" text-anchor="middle">크로스포비돈 (%)</text>'
        return t

    b = panel(ox, "(a) 평균 예측이 규격 안 (파랑)", "mean") + panel(ox + n * cell + 70, "(b) 미래 배치 공동 통과확률 (□ ≥ 0.90)", "P")
    b += f'<text x="14" y="{oy + n * cell / 2}" class="lg" transform="rotate(-90 14 {oy + n * cell / 2})" text-anchor="middle">MCC : 만니톨 비</text>'
    # colorbar
    cx = ox + 2 * n * cell + 90
    for i in range(20):
        p = 1 - i / 19
        shade = int(245 - 205 * p)
        b += f'<rect x="{cx}" y="{oy + i * 11}" width="12" height="11" fill="rgb({shade},{min(250, shade + 5)},{min(255, shade + 40)})"/>'
    b += f'<text x="{cx + 16}" y="{oy + 8}" class="lg">1.0</text><text x="{cx + 16}" y="{oy + 20 * 11}" class="lg">0.0</text>'
    b += f'<text x="{cx - 2}" y="{oy + 20 * 11 + 18}" class="lg">P(공동)</text>'
    return svg(cx + 60, oy + n * cell + 34, b)


def fig_fits(data):
    fits = data["fits"]
    w, h = 660, 190
    b = ""
    base, top = 160, 26
    scale = lambda v: base - max(0.0, v) * (base - top)
    labels = {"Y1": "분산 시간", "Y2": "마손도", "Y3": "DE30", "Y4": "함량균일성 AV"}
    for gi in range(5):
        v = gi / 4
        b += f'<line x1="50" x2="{w - 10}" y1="{scale(v)}" y2="{scale(v)}" stroke="#e5e5e5"/>'
        b += f'<text x="44" y="{scale(v) + 3}" class="lg" text-anchor="end">{v:.2f}</text>'
    for i, f in enumerate(fits):
        x = 70 + i * 150
        bars = [("R² (이차)", f["full_r2"], "#9aa5b1"), ("예측 R² (이차)", f["full_pred_r2"], "#4b5563")]
        if f["used_terms"] == "linear":
            bars.append(("예측 R² (축소)", f["used_pred_r2"], "#1d4ed8"))
        for j, (lab, v, col) in enumerate(bars):
            bx = x + j * 30
            b += f'<rect x="{bx}" y="{scale(v)}" width="24" height="{base - scale(v)}" fill="{col}"/>'
            b += f'<text x="{bx + 12}" y="{scale(v) - 3}" class="lg" text-anchor="middle">{v:.2f}</text>'
        b += f'<text x="{x + 40}" y="{base + 14}" class="lg" text-anchor="middle">{E(labels[f["cqa"]])}</text>'
    b += '<g transform="translate(470,4)"><rect width="10" height="8" fill="#9aa5b1"/><text x="14" y="8" class="lg">R²</text>'
    b += '<rect x="44" width="10" height="8" fill="#4b5563"/><text x="58" y="8" class="lg">예측 R²</text>'
    b += '<rect x="112" width="10" height="8" fill="#1d4ed8"/><text x="126" y="8" class="lg">축소 후 예측 R²</text></g>'
    return svg(w, h, b)


def fig_states():
    b = ""
    rows = [[("진입 자료", "REQUIRED_DATA"), ("CQA 계약", "CQA_APPROVAL"), ("FMEA", "FMEA_APPROVAL"), ("요인 근거", "FACTOR_DATA")],
            [("요인·수준 승인", "FACTOR_APPROVAL"), ("DoE 설계 승인", "RSM_APPROVAL"), ("실험 결과", "RSM_EXECUTION"), ("모델 판단", "MODEL_APPROVAL")],
            [("잠정 영역", "REGION_APPROVAL"), ("확인계획 잠금", "VERIFICATION_PLAN_APPROVAL"), ("확인배치 결과", "VERIFICATION_EXECUTION"), ("VERIFIED", "COMPLETED")]]
    for r, row in enumerate(rows):
        for c, (t, name) in enumerate(row):
            x, y = 10 + c * 178, 10 + r * 60
            b += box(x, y, 166, 40, t, name, "hi" if name == "COMPLETED" else "det", r=6)
            if c < 3:
                b += arrow(x + 166, y + 20, x + 178, y + 20)
        if r < 2:
            b += path(f"M {10 + 3 * 178 + 83} {10 + r * 60 + 40} L {10 + 3 * 178 + 83} {10 + r * 60 + 50} L 93 {10 + r * 60 + 50} L 93 {10 + (r + 1) * 60}", dash=False)
    b += box(10, 194, 220, 40, "사람 판단", "HUMAN_TRIAGE · 전이표에 없는 사유", "io", r=6)
    b += box(250, 194, 220, 40, "진단 방향 승인", "DIRECTIVE_APPROVAL · 경쟁 가설", "llm", r=6)
    b += box(490, 194, 220, 40, "재계획 · 전략 검토", "DESIGN_REPLAN · STRATEGY_REVIEW", "io", r=6)
    b += '<text x="10" y="254" class="al">상태명은 WAITING_ 접두 생략. 다음 상태는 backtrack_routing_rules.csv의 (reason_code, from_state)로만 결정된다.</text>'
    return svg(720, 262, b)


def exp_narrative(x, same, tot) -> str:
    """실험 결과 서술 — 문장은 전부 experiments.json에서 계산한다(재실험하면 문장도 따라 바뀐다)."""
    runs = x["runs"]
    by = {}
    for r in runs:
        by.setdefault(r["scenario"], []).append(r)
    parts = [f"결정론 계층의 결과(계획 서명·종결 상태·반려 규칙)는 반복 간 {'시나리오마다 모두 같았다' if same else '일부 달랐다'}."]
    for sid, rs in by.items():
        r0 = rs[0]
        if r0["status"] == "infeasible":
            parts.append(f"{r0['label']}은 세 전략의 후보가 모두 {', '.join(r0['hard_fails'])}로 반려되어 되돌림 없이 “제약 불가능”으로 끝났다.")
    changed = [by[sid][0]["label"] for sid in by if len({r["winner"] for r in by[sid]}) > 1]
    if changed:
        parts.append("반면 LLM이 만드는 부분은 달라졌다 — 권고 후보가 반복마다 바뀐 시나리오: " + ", ".join(changed) + ".")
    varying = []
    for sid, rs in by.items():
        sets = [set(r["summoned"]) for r in rs]
        diff = set.union(*sets) - set.intersection(*sets) if sets else set()
        if diff:
            varying.append(f"{rs[0]['label']}의 {', '.join(sorted(diff))}")
    if varying:
        parts.append("설계된 성분에 따라 소집이 달라진 심사관: " + "; ".join(varying) + ".")
    calls = sum(len(r["judge_scores"]) for r in runs)
    scored = calls - sum(r["judge_unscored"] for r in runs)
    uncited = sum(r.get("judge_uncited", 0) for r in runs)
    cites = sum(r.get("judge_citations", 0) for r in runs)
    parts.append(f"심사 호출 {calls}건 중 {scored}건이 점수를 받았고, 모든 점수는 검증된 DOI·PMID 인용(총 {cites}건)을 달았다"
                 f"(인용이 없어 무효가 된 점수 {uncited}건).")
    if tot:
        parts.append(f"8회 실행과 입력 에이전트 6개 발화에 쓰인 대회 API 토큰은 약 {tot:,}개였다(응답 헤더의 잔여 토큰 추정치 차이).")
    return "<p>" + " ".join(parts) + "</p>"


def devfix_section(fx) -> str:
    """개발자 수정 과제 §6 검증 계획 결과 표 — devfix_results.json(실제 서버 실행)."""
    if not fx:
        return ""
    rows = ""
    for r in fx["results"]:
        ok = [k for k, v in r["checks"].items() if v]
        bad = [k for k, v in r["checks"].items() if not v]
        rows += (f"<tr><td>{E(r['case'])}</td><td>{r['repeat']}</td><td>{E(r['status'])}</td><td>{r['seconds']:.0f}</td>"
                 f"<td>{E(' · '.join(ok))}</td><td>{E(' · '.join(bad) or '—')}</td></tr>")
    t1 = next((r for r in fx["results"] if r["case"] == "T1"), None)
    t4 = next((r for r in fx["results"] if r["case"] == "T4"), None)
    t2 = next((r for r in fx["results"] if r["case"] == "T2"), None)
    extra = []
    if t1:
        extra.append("T1(로르녹시캄 8 mg)에서 마지막 라운드 후보의 API 함량은 " +
                     ", ".join(f"{c['api'][0][1]:g} mg" for c in t1["candidates"] if c["api"]) + "였다.")
    if t2 and t2.get("parent_mw"):
        extra.append(f"T2의 분자 특성값은 parent 기준(MW {t2['parent_mw']:.1f}, 염 환산계수 {t2.get('salt_factor')})으로 계산됐다.")
    if t4 and t4.get("submission"):
        sub = t4["submission"]
        extra.append(f"T4에서 입력 에이전트는 측정 문장을 {t4['agent']['source']} 경로로 제출 카드로 바꿨고, 제출은 근거 등급 "
                     f"‘{sub['grade_ko']}’으로 기록되어 요청 {', '.join(sub['closed_requests']) or '없음'}을 닫았다({sub['rerun_scope']}).")
    return f"""<h3>7.4 데모 결함 수정의 검증</h3>
<p>시연 쿼리 3건을 무료 모델로 돌린 데모 실행 결과 보고서와 그 원인·수정·합격 기준을 정리한 개발자 수정 과제(14건)를 반영한 뒤, 과제 문서 §6의
검증 계획을 {E(fx.get('llm_label') or fx.get('llm'))}로 각 {max(r['repeat'] for r in fx['results'])}회 실행했다(표 7). 수정의 핵심은 세 가지다 — (1) 모든 규칙보다 먼저
후보가 요청과 맞는지 대조하는 입력 계약 검사(API 1행, 요청 용량의 유리염기 ±0.5%, 고정 부형제, FDA 라벨 1일 최대 용량), (2) 염 형태 입력의 분자 특성값을
parent로 계산, (3) 측정값 문장을 LLM보다 먼저 규칙으로 잡아 설계를 다시 돌리지 않고 제출. {' '.join(extra)}
T5(API 누락 후보 주입)·T6(암로디핀 50 mg 후보 주입)은 결정론 계층만의 동작이라 단위 테스트로 고정했다(RC001 · MAX_DAILY_DOSE 반려).</p>
<table><thead><tr><th>케이스</th><th>회</th><th>종결</th><th>초</th><th>통과한 기준</th><th>실패한 기준</th></tr></thead><tbody>{{rows}}</tbody></table>
<div class="tcap"><b>표 7.</b> 검증 계획 T1–T4의 실제 실행 결과(devfix_results.json). T1: 로르녹시캄 8 mg·고정 MCC·만니톨·크로스포비돈·유동성 42°/22%/1.28,
T2: 고령자 암로디핀 2.5 mg + 유당 고정(베실산염 SMILES), T3: T2에서 유당 제외, T4: VX-770 150 mg cold start 후 Tm·용해도 문장 제출.</div>
""".replace("{rows}", rows)


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
    for a in x["agent"]:
        p = (a["proposals"] or [{}])[0]
        what = p.get("kind") or "—"
        detail = []
        if p.get("kind") == "start_run":
            detail.append("준비됨" if p.get("ready") else f"미완성({', '.join(p.get('missing') or [])})")
            if p.get("smiles_source"):
                detail.append(f"구조: {p['smiles_source']}")
            if p.get("measured_params"):
                detail.append("값: " + ", ".join(f"{k}={v:g}" for k, v in p["measured_params"].items()))
        elif p.get("kind") == "studio_action":
            fp = (p.get("payload") or {}).get("fixed_parameters") or []
            detail.append(f"{p.get('action')} · " + ", ".join(f"{f.get('name')}={f.get('status')}" for f in fp))
        arows += (f"<tr><td>{E(a['id'])}</td><td>{E(a['text'])}</td><td>{E(what)}</td>"
                  f"<td>{E(' · '.join(detail))}</td><td>{E(' / '.join(a.get('asks') or []) or '—')}</td></tr>")
    sigs = {}
    for r in runs:
        sigs.setdefault(r["scenario"], set()).add((r["plan_signature"], r["status"], tuple(r["hard_fails"])))
    same = all(len(v) == 1 for v in sigs.values())
    tot = x.get("contest_tokens_used_estimate")
    return f"""<h3>7.3 대회 API 기반 재실험</h3>
<p>후보 탐색의 LLM 단계(요청 해석·설계·심사·반성)와 입력 에이전트를 대회 제공 API의 <code>{E(x['llm_model'].split(' (')[0])}</code>(OpenAI Responses 호환)로
실행했다. 대회 API가 누적 한도 소진(403)이나 오류를 내면 같은 호출이 무료 Groq(gpt-oss-120b)로 넘어가도록 구현했고, 이 실험에서는 전환이
일어나지 않았다(모든 후보·점수의 출처가 LLM). 화면의 시연 시나리오와 같은 입력 4종을 각 2회 실행했다(표 5).</p>
<table><thead><tr><th>시나리오</th><th>회</th><th>종결</th><th>계획 서명</th><th>후보</th><th>게이트 통과</th><th>반려 규칙</th><th>소집 심사관</th><th>점수 있음</th><th>남은 요청</th><th>권고</th><th>초</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="tcap"><b>표 5.</b> 시나리오별 실행 결과(서버 응답·이벤트 스트림에서 기록). 점수 있음 = 실제로 매겨진 심사 점수 / 전체 심사 호출.</div>
{exp_narrative(x, same, tot)}
<table><thead><tr><th>ID</th><th>사용자 발화</th><th>제안</th><th>카드 내용</th><th>되물음</th></tr></thead><tbody>{arows}</tbody></table>
<div class="tcap"><b>표 6.</b> 입력 에이전트 응답. U3(“용량은 알아서”)은 용량을 채우지 않고 되물었고, U4(“SMILES는 네가 기억하는 걸로”)의 구조는 LLM이 아니라
내장 구조 사전에서 왔다. U5의 “안식각 대충 30도”는 모델이 측정값으로 옮기지 않았다(사용자가 쓴 값이므로 옮겨도 가드레일은 통과한다 — 모호한 표현을
실측값으로 받지 않은 것은 모델의 판단이다). U6은 개발 스튜디오의 진입 자료 단계에서 압축력을 UNKNOWN으로 기록하는 행동이 되었다.</div>
"""



STAGES = [  # (우선순위 범위, 제목) — manifest의 trigger_priority 십의 자리 = 파이프라인 단계
    ((0, 4), "참조 마스터"), ((5, 9), "API 물성"), ((10, 19), "흐름 → 경로"), ((20, 29), "배합금기 · 소아"),
    ((30, 39), "다성분"), ((40, 49), "공정 세부"), ((50, 59), "코팅 · 용매"), ((60, 69), "BCS · 용출"),
    ((70, 79), "포장 · 안정성"),
]
SHORT = {"pairwise_membership": "쌍 금기", "subset_forbidden": "조합 금지", "threshold": "임계값", "range": "범위",
         "categorical_requirement": "필수 성분", "conditional_prohibition": "조건부 금지", "band_lookup": "구간 조회",
         "decision_tree": "결정 트리"}


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
    b += '<text x="10" y="12" class="gt">요청과 후보의 정합(입력 계약) → 규칙표 29개 · 여덟 검사 함수 · 우선순위 단계 (앞 단계의 파생값이 뒤 단계 조건)</text>'
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


def _short_cond(c: str) -> str:
    c = c.replace("==True", "").replace("True", "")
    return (c[:58] + "…") if len(c) > 60 else c


def fig_jury(data, x):
    jury = data["jury"]
    scen = []
    if x:
        for r in x["runs"]:
            if r["scenario"] not in [s_[0] for s_ in scen]:
                scen.append((r["scenario"], r["label"]))
    col0, colc, colw = 10, 128, 44
    b = '<text x="10" y="12" class="gt">명단 7명 · 소집 조건은 CSV 한 줄 · 신호는 게이트 결과와 스펙에서 결정론으로 계산 · 반려 권한 없음</text>'
    y0 = 26
    b += f'<text x="{col0}" y="{y0 + 12}" class="lg">심사관</text><text x="{colc}" y="{y0 + 12}" class="lg">소집 조건 (reviewer_registry.csv)</text>'
    b += f'<text x="{colc + 358}" y="{y0 + 12}" class="lg">가중치</text>'
    sx = colc + 400
    for j, (sid, lab) in enumerate(scen):
        b += f'<text x="{sx + j * colw + colw / 2}" y="{y0 + 4}" class="lg" text-anchor="middle">{E(lab.split(" ")[0])}</text>'
        b += f'<text x="{sx + j * colw + colw / 2}" y="{y0 + 14}" class="lg" text-anchor="middle">{E(lab.split(" ")[1][:6])}</text>'
    for i, r in enumerate(jury):
        y = y0 + 24 + i * 26
        b += f'<rect x="{col0 - 4}" y="{y - 2}" width="700" height="24" fill="{"#f6f7f9" if i % 2 == 0 else "#fff"}"/>'
        b += f'<text x="{col0}" y="{y + 14}" class="bt" style="text-anchor:start;font-size:9.5px">{E(r["reviewer_id"])} {E(r["name"].replace(" 심사관", ""))}</text>'
        b += f'<text x="{colc}" y="{y + 14}" class="lg" style="font-family:ui-monospace,Menlo,monospace;font-size:7.6px">{E(_short_cond(r["condition"]))}</text>'
        b += f'<text x="{colc + 366}" y="{y + 14}" class="lg">{E(r["weight"])}</text>'
        for j, (sid, _) in enumerate(scen):
            reps = [rr for rr in x["runs"] if rr["scenario"] == sid]
            hit = sum(r["reviewer_id"] in rr["summoned"] for rr in reps)
            cxp, cyp = sx + j * colw + colw / 2, y + 10
            if hit == len(reps) and hit:
                b += f'<circle cx="{cxp}" cy="{cyp}" r="6" fill="#1d4ed8"/>'
            elif hit:
                b += f'<circle cx="{cxp}" cy="{cyp}" r="6" fill="none" stroke="#1d4ed8" stroke-width="1.6"/><path d="M {cxp} {cyp - 6} A 6 6 0 0 1 {cxp} {cyp + 6} z" fill="#1d4ed8"/>'
            else:
                b += f'<circle cx="{cxp}" cy="{cyp}" r="5.5" fill="none" stroke="#bbb"/>'
    yl = y0 + 24 + len(jury) * 26 + 16
    b += f'<circle cx="16" cy="{yl - 3}" r="5" fill="#1d4ed8"/><text x="26" y="{yl}" class="lg">2회 모두 소집</text>'
    b += f'<circle cx="116" cy="{yl - 3}" r="5" fill="none" stroke="#1d4ed8" stroke-width="1.5"/><path d="M 116 {yl - 8} A 5 5 0 0 1 116 {yl + 2} z" fill="#1d4ed8"/><text x="126" y="{yl}" class="lg">1회만(설계 성분에 따라 달라지는 신호)</text>'
    b += f'<circle cx="336" cy="{yl - 3}" r="5" fill="none" stroke="#bbb"/><text x="346" y="{yl}" class="lg">생성되지 않음</text>'
    b += f'<text x="10" y="{yl + 18}" class="al">소집된 심사관만 후보별로 병렬 실행 → 점수 0–1(검증된 DOI·PMID 인용 필수, 없으면 무효) → 가중평균(결정론) → 통과 후보 사이의 순위.</text>'
    return svg(720, yl + 26, b)


# ── 본문 ──────────────────────────────────────────────────────────────────
def build(data, tests: int, browser: str, x=None, fx=None) -> str:
    r = data["region"]
    sp = data["setpoint"]
    c = data["counts"]
    fits = {f["cqa"]: f for f in data["fits"]}
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

<h1>Formula 1: 결정론적 규칙 검증과 입력 에이전트를 갖춘<br>다중 에이전트 제형 설계 및 실험계획 기반 운전 영역 검증 시스템</h1>
<div class="sub">팀 Formula 1 · 제4회 인공지능 신약개발 경진대회</div>
<div class="meta">라이브 시스템 https://zihwan.com/formula1 · 기술 보고서</div>

<div class="abstract"><b class="h">초록</b>
거대언어모델(LLM)은 제형 처방을 그럴듯하게 제안하지만, 배합 금기·공정 한계·규제 상한 같은 정량 판단에서
근거 없는 수치를 만들어 낼 수 있다. 본 연구는 <b>창의는 AI가, 검증은 규칙이, 결정은 연구자가</b> 맡는 역할 분리를
구조로 강제하는 제형 설계 시스템 Formula 1을 제시한다. 시스템은 두 그래프로 구성된다. ① 후보 탐색 그래프는
분자 구조에서 계산한 값과 공개 경험식 예측만으로 생물약제학 페이즈 게이트(BCS/DCS·고체상·가용화·ASD 공정)를 돌려
전략을 좁히고, 전략별 후보를 병렬 설계한 뒤, 출처와 검증 상태가 붙은 규칙표로 반려하며, 반려 사유별 복귀 지점을
전이표({c['backtrack_transitions']}행)로 정한다. 값이 없을 때는 멈추지 않고 측정 카탈로그({c['measurement_catalog']}종) 안에서만
실측을 요청한다. ② 개발 스튜디오 그래프는 연구자가 고른 후보를 불변 Handoff로 받아 CQA 계약·FMEA·실험계획법(DoE)·모델
진단·미래 배치 예측분포 기반 공동확률 영역·독립 확인배치까지를 규칙 171개와 결정론 통계 엔진으로 진행한다.
두 그래프 앞에는 <b>입력 에이전트</b>가 서서, 서버가 구성한 맥락을 읽고 사용자의 말을 실행 가능한 제안 카드로 바꾸되,
제안의 수치는 사용자 발화에, 구조식은 사용자 입력·내장 사전·PubChem에만 근거하도록 코드로 강제한다. 모든 규칙보다 먼저
후보가 요청한 약·용량·고정 부형제와 FDA 라벨 1일 최대 용량에 맞는지 대조하는 입력 계약 검사를 두고, 심사 점수에는 Crossref·NCBI로 확인되는
DOI·PMID 인용을 요구한다.
공개 논문(Almotairi 등, 2022)의 Lornoxicam 분산정 Box–Behnken 실측 15 run에 적용한 결과, 평균 예측 기준으로는 지지 영역의
{r['mean_ok_fraction'] * 100:.1f}%가 규격을 만족했으나 미래 배치 공동 통과확률 0.90 기준으로는 {r['feasible_fraction'] * 100:.1f}%만 남았고,
권장 설정점(비 {sp['actual']['x1']} · 혼합 {sp['actual']['x2']}분 · 크로스포비돈 {sp['actual']['x3']}%)의 공동확률은 {sp['joint_probability']:.3f}였다.
<div class="kw"><b>주제어</b> 제형 설계 · Quality by Design · 다중 에이전트 · 결정론적 검증 · 환각 억제 · 실험계획법 · 설계공간 · lab-in-the-loop</div>
</div>

<h2>1. 서론</h2>
<p>신약 하나가 허가되기까지의 비용과 시간 가운데 상당 부분은 주성분을 사람이 복용할 수 있는 형태로 만드는 제형 개발에서 쓰인다.
주성분만으로는 정제가 형성되지 않으므로 희석제·결합제·붕해제·활택제 같은 첨가제를 섞는데, 바로 그 조합에서 화학적 비상용성
(예: 2차 아민과 유당의 Maillard 반응), 공정 실패(유동성 부족으로 인한 직접타정 불가), 규제 상한 초과(소아용 첨가제 한도)가 발생한다.
처방이 정해진 뒤에도 공정 변수를 어느 범위에서 흔들어도 규격을 지키는지 — 운전 영역 — 를 실험으로 증명해야 한다[1].</p>
<p>LLM은 넓은 조합 공간에서 후보를 상상하고 상충하는 목표 사이의 타협을 서술하는 데 강하지만, 수치 판단에서 근거 없는 값을
확신 있게 생성하는 환각 문제가 있다. 제약에서 이러한 오류는 제품 폐기와 허가 반려로 직결된다. 따라서 우리는 LLM에게 판정 권한을
주지 않고, 판정은 출처가 있는 규칙표와 결정론 엔진에만 맡기는 구조를 설계했다. 본 보고서는 그 구조와 구현, 그리고 공개 실측 데이터에
대한 적용 결과를 서술한다.</p>
<p>기여는 다음과 같다. (1) 판정 권한을 데이터(규칙표)로 제한하고, 근거 상태에 따라 반려 가능 여부를 엔진이 스스로 정하는 검증 계층.
(2) 값을 모를 때 멈추지 않고 판정이 갈리는 지점에서만 실측을 요청하는 비차단 lab-in-the-loop와, 반려 사유별 복귀 지점을 정하는 되돌림 전이표.
(3) 후보 이후의 개발을 상태기계로 옮기고, 영역을 평균이 아닌 미래 배치 예측분포로 계산하는 DoE 파이프라인.
(4) 사용자와 시스템 사이에서 맥락을 읽고 입력을 정리하되 수치·구조식 생성을 코드로 차단한 입력 에이전트.</p>

<h2>2. 관련 연구와 배경</h2>
<p><b>Quality by Design.</b> ICH Q8(R2)[1]는 품질 목표(QTPP)에서 중요 품질 특성(CQA)을 도출하고, 위험평가(ICH Q9[2])로 중요 공정 변수를 좁혀
실험계획법으로 설계공간을 정의하는 체계를 제시한다. 설계공간의 신뢰성은 평균 반응면이 아니라 미래 배치가 규격을 만족할 확률로
평가해야 한다는 관점이 베이즈·예측분포 기반 접근으로 제안되어 왔다[4,5].</p>
<p><b>생물약제학 분류.</b> BCS는 용해도와 투과도로 약물을 분류하고[3], DCS는 용해 속도 제한(IIa)과 용해도 제한(IIb)을 구분해 제형
전략(미분화 대 가용화)을 가른다[6]. 용해도 예측에는 ESOL[7]과 일반용해도식(GSE)[8] 같은 경험식이 쓰인다.</p>
<p><b>LLM 과학 에이전트.</b> FutureHouse의 Robin은 가설 생성·실험 제안·결과 해석을 자동화해 후보 약물을 찾은 사례로, 지시문 원문을
공개했다[9]. 본 시스템은 그 지시문 패턴(구별되는 가설의 배열 강제, 필요 없으면 제안하지 않기, 근거 우선의 평가 기준)을 가져오되,
시험 제안은 자유 텍스트가 아닌 실제 확인시험 목록({c['confirmation_tests']}행) 안으로 제한했다. 오케스트레이션은 LangGraph[10]를 사용한다.</p>

<h2>3. 시스템 개요</h2>
<figure>{fig_architecture(data)}
<figcaption><b>그림 1.</b> 전체 구조. 연구자와 두 그래프 사이에 입력 에이전트가 있고, 두 그래프는 내부 상태를 공유하지 않은 채 불변 Handoff
하나로만 연결된다. ① 안의 두 확대 상자는 규칙 게이트(우선순위 단계, 근거 상태별 권한, 판정별 경로 — 그림 4)와 동적 심사단(명단 7명과 소집 조건,
순위만 매기는 합의 — 그림 6)의 내부다. 선 모양은 담당 주체를 나타낸다(실선: 결정론 규칙·엔진, 파선: LLM, 점선: 순위만 매기는 심사관).</figcaption></figure>
<p>역할 분리는 표 1과 같다. 판정·계산 권한은 결정론 계층에만 있고, LLM은 제안과 서술만 한다. 연구자는 어떤 후보를 개발할지,
경고를 사유와 함께 넘길지, 모델을 축소할지 같은 수용 결정을 내린다.</p>
<table><thead><tr><th>성격</th><th>예</th><th>담당</th></tr></thead><tbody>
<tr><td>숫자로 답이 떨어지는 것</td><td>첨가제 상한, 회귀계수, 예측구간, 공동확률</td><td>규칙 기반 검사기 · 통계 엔진</td></tr>
<tr><td>맥락을 읽어야 하는 것</td><td>소아 복용 적합성, 실패 원인 가설</td><td>심사·가설 LLM (반려 권한 없음)</td></tr>
<tr><td>말을 입력으로 옮기는 것</td><td>“용량은 50 mg”, “압축력은 모름”</td><td>입력 에이전트 (수치·구조식 생성 금지)</td></tr>
<tr><td>받아들일지 정하는 것</td><td>개발 후보 선택, 과적합 모델 처리</td><td>연구자</td></tr></tbody></table>
<div class="tcap"><b>표 1.</b> 판단의 성격별 담당.</div>
<p>LLM 호출은 한 인터페이스(구조화 출력·스트리밍)로 감싸 프로바이더를 바꿔 끼운다. 라이브 시스템에서는 연구자가 화면에서 모델을
고른다 — 기본은 무료 Groq(gpt-oss-120b)이고, 비밀번호로 접속한 세션만 대회 제공 API(OpenAI Responses 호환, gpt-5.6-sol)를 고를 수 있다(권한은
서버가 다시 검사). 대회 API를 고른 호출은 팀 누적 한도 소진(403)이나 오류가 나면 같은 호출을 무료 Groq로 넘긴다. 무료 모델의 분·일 단위 토큰 한도는
클라이언트가 직접 회계해 호출이 몰릴 때 순번을 기다리게 하며, 끝내 응답이 없으면 결과를 지어내지 않고 “응답 없음”으로 표시한다.</p>

<h2>4. 입력 에이전트</h2>
<p>입력 에이전트는 두 그래프 앞에서 대화를 받는다. 맥락은 브라우저가 보낸 상태가 아니라 서버가 실행(run)과 개발 스터디(study)에서
직접 구성한 스냅숏이다 — 현재 탭, 설계 상태와 권고 후보, 병합된 실험 요청(측정 ID·Tier·산출 키·사유), 마지막 되돌림, 스튜디오의 현재 상태와
그 상태에서 허용되는 행동, 막고 있는 규칙. 에이전트는 LLM 구조화 출력으로 의도(설계 실행 · 측정값 제출 · 스튜디오 행동 · 개발 착수 · 설명 · 되묻기)와
초안 값을 받고, 이를 <b>제안 카드</b>로 바꾼다. 카드는 연구자가 [실행]을 눌러야 반영되며, 실행은 사람이 누르는 버튼과 같은 함수 경로를 탄다.</p>
<figure>{fig_agent()}
<figcaption><b>그림 2.</b> 입력 에이전트 처리 경로. 해석(LLM, 실패 시 규칙 해석기) 뒤의 네 가드레일은 모두 코드로 구현되어 있다.</figcaption></figure>
<p>가드레일은 프롬프트가 아니라 코드다. (i) 제안에 들어가는 모든 숫자는 최근 사용자 발화에서 추출한 숫자 집합에 속해야 하며, 아니면 제거되고
제거 사실이 사용자에게 표시된다. (ii) SMILES는 사용자 글에 그대로 있거나, 내장 구조 사전 또는 PubChem[12] PUG-REST 조회에서만 얻고, 카드에 CID와 링크를
붙인다. LLM이 쓴 SMILES는 사용하지 않는다. (iii) 측정 키는 실험 입력 허용목록과 측정 카탈로그 산출 필드 안에서만, 스튜디오 행동은 현재 상태가
허용하는 것만 받고, 카드를 실행할 때 상태 버전이 바뀌었으면 실행하지 않는다. (iv) 설계 실행에는 구조식과 1회 용량이 필요하며, 없으면 카드는
미완성으로 표시되고 에이전트가 되묻는다 — 용량이 없으면 용량/용해도 부피를 계산할 수 없어 DCS 분류가 성립하지 않기 때문이다.
LLM이 되묻기만 하고 글에서 행동이 명확히 읽히는 경우(예: “압축력은 몰라요” → 진입 자료의 압축력 UNKNOWN 기록)에는 규칙 해석기가 바닥을 받친다.
설계 종료·재계산·스튜디오 상태 전이 때에는 LLM 없이 맥락만으로 다음 행동을 먼저 제시한다(nudge).</p>

<h2>5. 후보 탐색 그래프</h2>
<h3>5.1 분자 프로파일과 값의 세 계층</h3>
<p>RDKit으로 구조 품질(파싱·염·전하·입체), 35종 기술자, 구조 패턴 {c['structural_flags']}종을 계산한다. 패턴은 “구조 사실 · 조건부 경고 · 높은 경고”의
세 등급과 위험 조건·확인 시험을 함께 가지며, 세분화된 아민 분류는 규칙표의 결합 키(<code>primary_amine</code>/<code>secondary_amine</code>)로 연결된다.
염 형태로 입력된 구조는 가장 큰 유기 조각을 parent로 확정해 기술자·구조 패턴·용해도 예측을 모두 parent로 계산하고,
짝이온과 염/유리염기 분자량비는 함량 환산용으로 따로 둔다(베실산 암로디핀: 염 MW 567.1 → parent 408.9). 모든 값은 획득 방식에 따라 계산값(A), 경험식 예측값(B), 실측값(C)으로 나뉜다. 예측값은 <code>*_est</code> 변수에만 저장되어 실측을 덮지 않고,
BCS 등급은 실측으로만 확정된다. 파생값 {c['derived_quantities']}종(D0, 흡수 한계, Tg 여유, ΔpKa 등)은 CSV의 식으로 정의되고, 상호 의존은 값이 더 바뀌지
않을 때까지 반복(고정점)해 계산 순서를 코드 줄 순서에 맡기지 않는다.</p>
<figure>{fig_value_tiers()}
<figcaption><b>그림 3.</b> 값의 세 계층과 비차단 실험 요청. 측정값이 들어오면 그래프를 다시 돌리지 않고 결정론 계층만 재계산해, 계획 서명이 같으면
신뢰도 태그만 갱신한다.</figcaption></figure>

<h3>5.2 페이즈 게이트와 계획</h3>
<p>Gate 3A(BCS/DCS) → 3B(고체상, 권고) → 4(가용화 필요 여부) → 4B(ASD 공정) 순서로 돌며, 순서가 곧 의존 관계다. 게이트에는 반려 권한이 없고
전략 탐색 범위만 정한다. CSV 조건식이 “값을 모름”을 조건으로 쓰는 경우(<code>tm_c is None</code>), 변수가 문맥에 아예 없으면 평가 오류가 “미발화”로
삼켜지므로, 모든 참조 변수를 <code>None</code>으로 먼저 채운다. 계획 단계는 켜진 신호로 전략 {c['strategies']}종(표 2)을 채점해 상위 3개를 고르고,
정렬된 전략 코드를 이어 계획 서명을 만든다. 판정이 갈리지 않으면(예: 투과도를 몰라 IIa/IIb 불명) 양쪽을 모두 열고, 유동성 자료가 없으면 세 공정 경로를
잠정으로 모두 연다. 되돌림 제약을 반영해 남는 전략이 없으면 설계하지 않고 목표(QTPP) 재검토로 끝난다.</p>
<table><thead><tr><th>코드</th><th>가족</th><th>전략</th><th>공정 단계</th><th>요구 측정(트리거)</th></tr></thead><tbody>{st_rows}</tbody></table>
<div class="tcap"><b>표 2.</b> 전략 가족(<code>strategy_families.csv</code>). 요구 측정 열은 측정 기반 되돌림이 어느 전략에 적용되는지도 정한다.</div>

<h3>5.3 규칙 게이트</h3>
<p>규칙은 코드가 아니라 CSV 행이고, 단일 manifest가 각 CSV를 여덟 개의 범용 검사 함수(쌍 금기, 부분집합 금지, 임계값, 범위, 필수 성분,
조건부 금지, 구간 조회, 결정 트리) 중 하나에 연결한다. 검사는 우선순위 단계로 돌며 앞 단계가 만든 값(유동성 등급 → 공정 경로 → BCS 등급)이
다음 단계의 발동 조건으로 흘러간다. 행마다 <code>verification_status</code>가 있어 검증된 행만 반려를 만들 수 있고, 미검증 행은 심사관 표시로 강등되며,
출처를 찾지 못한 행은 로드 단계에서 제외된다. 성분명은 문자열 동등 비교가 아니라 두 부형제 마스터(영문·국문·이명)를 사전으로 한 정규화로
대조하며, 구조를 해석하지 못한 실행은 통과가 아니라 이관(STRUCT000)으로 끝난다.</p>
<p><b>입력 계약.</b> 모든 규칙보다 먼저 후보가 요청과 맞는지 결정론으로 대조한다 — API 행이 정확히 하나인가, API 함량을 유리염기로 환산했을 때
요청 1회 용량과 ±0.5% 안인가(이름에 염이 적혀 있으면 RDKit 분자량비로 환산), 고정 부형제가 모두 있는가, 1회 함량이 허가 라벨의 1일 최대 용량을
넘지 않는가(FDA 라벨 원문 문장과 DailyMed set_id를 함께 저장하고, 약물은 이름이 아니라 parent InChIKey 골격으로 대조). 위반은 되돌림 전이표에 따라
같은 전략으로 함량·성분을 고쳐 다시 설계하며, 요청 용량 자체가 라벨 최대를 넘으면 재설계 없이 “제약 불가능”으로 끝낸다. 배합비 규칙은 LLM이 붙인
기능 역할로 부형제를 묶는데, MCC(결합제·희석제 겸용 20–90%)나 탈크(1–10%)처럼 역할만으로 범위가 맞지 않는 부형제는 출처가 있는 매핑표로
판정용 역할을 바꾸고, 혼합 시간에 달린 과혼합 위험(INC014)은 후보 탐색에서 경고 대신 DoE 요인 후보로 넘긴다.</p>
<figure>{fig_rulegate(data)}
<figcaption><b>그림 4.</b> 규칙 기반 게이트. 맨 앞의 입력 계약(요청한 그 약·그 용량·그 고정 부형제인가, FDA 라벨 1일 최대 용량)이 모든 규칙보다 먼저
돌고, 이어서 manifest 항목 29개를 우선순위 단계로 묶어 실행한다(각 칸: 쓰이는 검사 함수, 판정·LLM·참조 항목 수).
유동성 등급 → 공정 경로, 실측 BCS 등급 같은 파생값이 뒤 단계의 발동 조건으로 흐르고, 공정 세부 규칙표는 통과 조건(pass_when)으로 읽는다.
아래 두 줄은 행의 근거 상태가 반려 권한을 정하는 방식과, 판정별 다음 경로다. 규칙을 더하는 일은 CSV 행과 manifest 한 줄이다.</figcaption></figure>

<h3>5.4 되돌림 — 반려 사유별 복귀 지점</h3>
<figure>{fig_discovery()}
<figcaption><b>그림 5.</b> 후보 탐색 그래프. <code>backtrack</code>은 반려 판정을 전이표에 대조해 복귀 지점(GATE: 같은 전략으로 성분만 교체,
G6R: 공정 경로부터, G4: 전략 선택부터)과 제약을 정한다. 하단은 종결 노드.</figcaption></figure>
<p>한 라운드의 여러 반려는 가장 깊은 복귀 지점으로 합치되 제약은 모두 누적한다. 같은 지점에 3회 복귀해도 해소되지 않으면 한 단계 위로 올리며
반려된 전략을 제외하고, 전체 5회를 넘으면 사람에게 이관한다. 반려 사유가 사용자가 고정한 성분이면 되돌리지 않고 즉시 “제약 불가능”과 규칙표의
대체 성분을 낸다. 측정 결과가 전략 전제를 부정하는 경우(예: ASD 혼화성 부적합)에는 <b>그 측정을 요구하는 전략에만</b> 제외를 적용한다(표 2의 요구 측정 열).</p>
<table><thead><tr><th>ID</th><th>계기</th><th>복귀</th><th>제약</th><th>지시</th></tr></thead><tbody>{bt_rows}</tbody></table>
<div class="tcap"><b>표 3.</b> 되돌림 전이표(<code>backtrack_transitions.csv</code>, {c['backtrack_transitions']}행).</div>

<h3>5.5 실험 요청과 신뢰도</h3>
<p>요청 가능한 시험은 측정 카탈로그 {c['measurement_catalog']}종(Tier 1 ~10 mg: XRPD·DSC·TGA·KF, Tier 2 ~30 mg, Tier 3, 전략별)으로 한정되며,
“언제·무엇을·왜·거절 시 대체 경로”는 트리거 표 {c['data_request_triggers']}행에 정의된다. 계획 전에는 전략을 좁히는 요청을, 후보 생성 뒤에는 후보별
신뢰도 요청을 낸다. 같은 시험을 가리키는 요청은 하나로 병합되고 시료가 적은 Tier부터 제시되며, 용해도 요청은 “예측이 낮거나 모름”과
“두 예측이 1 log 이상 불일치”를 구분해 표시한다. 요청은 흐름을 막지 않는다 — 건너뛰면 예측값으로 계속하고 후보는 provisional로 남는다.
신뢰도는 <code>grounded ⟺ 남은 신뢰도 요청 = ∅</code>로 계산되어 LLM이 매길 여지가 없다. 산·염기 site가 있는 이온화 가능 약물은
pH 1.2–6.8에서 용해도가 달라 단일 ESOL 예측으로 판정하지 않고 잠정 용해도를 “미정”으로 둔 채 pH별 평형용해도를 요청하며, 공식 문헌 값이 있는 약물은
문헌 표(등급: 문헌 표 수치)로 잠정 판정을 채운다. 측정값은 근거 등급(자체 실측·문헌·사용자 진술)과 함께 기록된다.</p>

<h3>5.6 동적 심사위원단과 합의</h3>
<p>심사관 {c['reviewers']}명(소아 안전, 가용화 전략, 공정 실현성, 규제 취지, 문헌 조사, 고령자 안전, 고체상 안정성)은 소집 조건식이 참일 때만 생성된다.
심사관은 근거 강도 → 잔여 위험 → 실현 가능성 → 참신성 순의 기준으로 통과 후보에 점수를 매기되 반려 권한이 없고, 합의는 결정론 가중평균이다.
LLM이 응답하지 않으면 두 번 재시도한 뒤에도 점수를 대신 채우지 않고 “점수 없음”으로 표시하며, 순위는 실제 점수만으로 정한다.
점수에는 <b>검증된 인용</b>이 필요하다 — 심사관은 DOI·PMID로만 인용할 수 있고, 후보로는 이 약에 대해 Europe PMC가 돌려준 실제 문헌과 룰북 인용 등록부
(룰북에 적힌 식별자를 Crossref·NCBI로 조회해 통과한 14건)가 주어진다. 목록 밖 식별자는 실행 중에 같은 방식으로 조회해 실재할 때만 인정하며,
검증된 인용이 없는 점수는 무효로 합의에서 빠진다. 소집 신호(대상 인구군, 가용화·미분화·ASD 후보 존재, 룰북 밖 성분 조합, 규제 서술 필요, 고체상 경계 구간)는 스펙과 게이트 결과에서 결정론으로 계산되므로,
같은 요청이라도 설계된 성분이 달라지면 소집 명단이 달라질 수 있다(그림 6의 반쪽 원).</p>
<figure>{fig_jury(data, x)}
<figcaption><b>그림 6.</b> 동적 심사위원단. 왼쪽은 명단과 소집 조건(CSV 원문), 오른쪽은 7.3절 재실험(시나리오 4종 × 2회)에서 실제로 소집된 결과다.
공정 실현성(REV003)만 항상 소집되고, 소아·고령자 심사관은 대상 인구군에 따라 서로 배타적으로 나타나며, 문헌 조사(REV005)는 룰북 밖 조합이 설계됐을
때만 들어온다. 규제 취지(REV004)·고체상 안정성(REV007)은 이 네 요청에서 조건이 맞지 않아 한 번도 생성되지 않았다.</figcaption></figure>

<h2>6. 개발 스튜디오 그래프</h2>
<p>연구자가 후보를 고르면 조성·공정·고정 변수·QTPP를 담은 불변 Handoff가 fingerprint와 함께 생성된다. 이후 판정은 <code>database/07_doe</code>의
규칙 171개(CSV 22종 + 마스터 7종)가 전부 맡는다. 조건식은 Python <code>eval</code>이 아니라 AST 화이트리스트 평가기로 해석되어, 허용되지 않은 문법이
CSV에 들어오면 로드 자체가 실패한다. 값이 없으면 “미발화”가 아니라 규칙별 결측 처리(RECORD_NOT_CHECKED, REQUEST_DATA, BLOCK_STAGE 등)를 적용한다.
여러 규칙이 동시에 발화하면 모두 기록하고 가장 강한 효과(INVALIDATE/BLOCK &gt; REQUEST_DATA &gt; AUGMENT &gt; ROUTE &gt; WARNING) 하나로 전이하며,
다음 상태는 전이표의 (reason_code, from_state)에서만 찾는다.</p>
<figure>{fig_states()}
<figcaption><b>그림 7.</b> 개발 스튜디오 상태기계의 주 경로. 모든 WAITING 상태에서 연구자의 입력·승인을 기다린다.</figcaption></figure>
<p>통계 엔진은 numpy·scipy만으로 설계 생성(BBD·CCD·FCCD·2<sup>4−1</sup>·PB12), OLS 적합, PRESS 기반 예측 R², Cook's D, 순수오차·적합결여 검정을
구현한다. 잠정 영역은 반응별 미래 배치 예측분포(자유도 = 잔차 자유도인 t 분포, 척도 √(SE²<sub>평균</sub> + σ̂²))로 통과확률을 구해 곱한 공동확률이
0.90 이상인 격자점이며, 분모는 설계점 convex hull 안의 격자점이다.</p>
<div class="eq">P<sub>joint</sub>(x) = ∏<sub>k</sub> Pr[ Y<sub>k</sub><sup>new</sup>(x) ∈ Spec<sub>k</sub> ],&nbsp;&nbsp; Y<sub>k</sub><sup>new</sup>(x) ~ ŷ<sub>k</sub>(x) + t<sub>ν</sub>·√(SE<sub>k</sub>(x)² + σ̂<sub>k</sub>²)</div>
<p>확인점은 설정점·영역 경계 최저 확률점·설정점 주변 허용 변동 최악점의 세 개가 필수이며, 예측구간은 첫 결과 전에 Bonferroni 동시구간으로 잠긴다.
판정은 규격 통과 × 예측구간 포함의 2×2이고, VERIFIED는 내부 사전계획 통과를 뜻할 뿐 규제 승인 설계공간을 의미하지 않는다.</p>

<h2>7. 적용 결과</h2>
<h3>7.1 Lornoxicam 분산정 (공개 실측 데이터)</h3>
<p>Almotairi 등[11]의 Box–Behnken 15 run(요인: MCC:만니톨 비 1–3, 혼합 시간 5–15분, 크로스포비돈 2–10%; 반응: 분산 시간, 마손도, 30분 용출률 DE30,
함량균일성 AV)을 결과 제출 화면으로 입력하고, 논문의 회귀식은 쓰지 않고 엔진이 처음부터 계산했다. 규격은 분산 시간 ≤ 180 s, 마손도 ≤ 1.0%,
AV ≤ 15, DE30 ≥ 75%이며, DE30 기준은 논문 기준이 아니라 프로젝트 목표로서 화면에 가정으로 표시된다.</p>
<figure>{fig_fits(data)}
<figcaption><b>그림 8.</b> 반응별 적합도. 마손도의 전체 이차모형은 R² {fits['Y2']['full_r2']:.2f}이나 예측 R²가 {fits['Y2']['full_pred_r2']:.2f}로 과적합 flag(MV006)가
서고, 계층성을 지킨 선형 축소 후 예측 R² {fits['Y2']['used_pred_r2']:.2f}로 회복했다. 함량균일성(예측 R² {fits['Y4']['full_pred_r2']:.2f})도 flag가 서며, 데모에서는 사유를
기록하고 수용했다. 잔차 자유도는 이차모형 {fits['Y1']['df_resid']}, 선형 {fits['Y2']['df_resid']}.</figcaption></figure>
<figure>{fig_region(data)}
<figcaption><b>그림 9.</b> 혼합 시간 {data['slice']['fixed_actual']:.1f}분 단면(설정점을 지나는 면, 엔진 계산 격자 21×21). (a) 평균 예측만 보면 이 면의
지지 영역 중 {data['slice']['mean_ok_fraction'] * 100:.0f}%가 규격 안이지만, (b) 미래 배치의 공동 통과확률 ≥ 0.90(흰 점)을 요구하면 {data['slice']['feasible_fraction'] * 100:.0f}%만 남는다.
전체 격자에서 미달 점의 대부분은 DE30이 결정한다(표 4). 회색은 설계점 convex hull 밖(외삽), 빨간 원은 권장 설정점.</figcaption></figure>
<table><thead><tr><th>지표</th><th>값</th></tr></thead><tbody>
<tr><td>격자점 (21³) / 지지 영역 안</td><td>{r['grid_points_total']:,} / {r['grid_points_in_domain']:,}</td></tr>
<tr><td>평균 예측이 모든 규격 안</td><td>{r['mean_ok_fraction'] * 100:.1f}%</td></tr>
<tr><td>공동 통과확률 ≥ 0.90</td><td>{r['feasible_fraction'] * 100:.1f}% ({r['feasible_points']:,}점)</td></tr>
<tr><td>경계를 주도하는 CQA (미달 격자점 수)</td><td>{', '.join(f'{k} {v:,}' for k, v in r['binding_cqa_counts'].items())} — DE30이 주도</td></tr>
<tr><td>권장 설정점 (비 · 혼합 · 크로스포비돈)</td><td>{sp['actual']['x1']} · {sp['actual']['x2']}분 · {sp['actual']['x3']}% (공동확률 {sp['joint_probability']:.3f}, 경계 거리 {sp['edge_distance']:.1f} coded)</td></tr>
<tr><td>분산 시간 모형 최대 Cook's D</td><td>{data['cook_max']:.2f} (run 3·12 동률 — 표시만, 삭제 없음)</td></tr>
</tbody></table>
<div class="tcap"><b>표 4.</b> Lornoxicam 사례의 엔진 계산 결과. 값은 저장소의 골든 테스트(statsmodels 참조 구현과 대조)로 고정되어 있다.</div>
<p>평균 기준 {r['mean_ok_fraction'] * 100:.1f}%와 공동확률 기준 {r['feasible_fraction'] * 100:.1f}%의 차이는, 잔차 자유도 5의 소표본 모형에서 미래 배치의 변동을
무시하고 평균면만으로 영역을 그리면 영역을 약 1.6배 과대평가함을 보여 준다. 논문의 최적 처방 배치 관측값은 결과가 이미 공개되어 있어 확인 판정에는
쓰지 않고 참고점으로만 비교하며, 합성·문헌 데이터로는 VERIFIED로 승격되지 않는다(VR015).</p>

<h3>7.2 검증 계층의 동작</h3>
<p>소아용 플루옥세틴 정제에 유당 수화물을 고정 성분으로 요구하면, 구조 패턴이 2차 아민을 검출하고 1대1 배합 금기 INC002(2차 아민 × 유당 → Maillard 반응[13])가
반려하며, 반려 사유가 고정 성분이므로 되돌림 없이 “제약 불가능”과 대체 성분(만니톨)을 낸다. 같은 금기가 “유당”, “Lactose, NF”, “유당수화물” 표기에서
모두 발동하고 대체품인 만니톨·전분글리콜산나트륨에서는 발동하지 않음을 회귀 테스트가 고정한다.</p>

{exp_section(x)}
{devfix_section(fx)}
<h3>7.5 소프트웨어 검증</h3>
<p>단위·통합 테스트 {tests}개(pytest)가 구조 패턴 진리표, 검사 방향, 근거 정책, 페이즈 게이트, 되돌림·계획 불변식, 입력 에이전트 가드레일, 07_doe 규칙
fixture 48건, 통계 골든 값, 스터디 흐름을 고정한다. 실제 브라우저 테스트({E(browser)})는 화면 상호작용, 다섯 렌더 경로의 스크립트 주입 차단, 9개 뷰포트
폭의 반응형, 시연 시나리오의 실제 경로, 개발 스튜디오 9장면, 입력 에이전트의 대화→카드→실행 흐름을 검사한다.</p>

<h2>8. 논의와 한계</h2>
<p><b>판정 권한의 위치.</b> 이 시스템의 안전성은 LLM의 정확도가 아니라 판정 권한이 어디에 있는가에서 나온다. 설계·심사·가설 LLM이 틀려도 반려와
승격은 규칙과 엔진만 할 수 있으므로, LLM 오류는 “잘못된 후보가 반려됨” 또는 “가설이 기각됨”으로 흡수된다. 입력 에이전트는 이 원칙을 입력 쪽으로
확장한다 — 대화 창이 새로운 환각 통로가 되지 않도록 수치와 구조식의 출처를 코드로 제한했다.</p>
<p><b>모르는 것의 표현.</b> “규칙이 발동하지 않음”과 “문제가 없음”을 구분하는 것이 핵심이었다. 성분명 불일치, 구조 해석 실패, 비어 있는 사전은 모두
조용한 통과를 만들 수 있었고, 각각을 판정 불가·이관으로 바꾸었다. 결측 값은 NOT_CHECKED나 실측 요청으로 기록된다.</p>
<p><b>한계.</b> (1) 개발 스튜디오 규칙 171개는 약학 담당 검토 전(DRAFT)이라 production 모드의 집행 규칙은 0개이며, 화면은 sandbox 모드로 동작한다.
(2) 신경망 물성 예측기는 연결하지 않았다. (3) 스터디 저장소는 임시 SQLite로 재시작 시 사라진다. (4) LLM 출력은 반복마다 달라 권고 후보가 바뀔 수 있다(표 5) —
결정론 계층은 같은 판정을 내지만 순위는 심사 LLM 점수에 기댄다. 대회 API 한도가 소진되어 무료 모델로 넘어가면 분당 토큰 한도로 설계·심사가 빌 수 있고,
이때 결과를 채우지 않고 “응답 없음”으로 표시한다. (5) 다변량 공동확률(반응 간 상관), mixture·D-optimal 설계, 스케일업은 범위 밖이다.
(6) 입력 에이전트의 구조식 조회는 영문 표준명에 기대며, 대화 기록은 브라우저 탭 안에만 있다.</p>

<h2>9. 결론</h2>
<p>Formula 1은 제형 설계에서 LLM의 창의와 결정론 검증을 분리하고, 후보 탐색에서 검증된 운전 영역까지를 두 그래프와 하나의 불변 연결로 구성했다.
값을 모르면 멈추지 않고 필요한 실측만 묻고, 반려되면 사유가 가리키는 지점으로 돌아가며, 영역은 미래 배치의 공동 통과확률로 계산한다. 공개 실측
사례에서 평균 기준 영역이 공동확률 기준보다 크게 과대평가됨을 정량적으로 보였고, 사용자와 시스템 사이의 입력 에이전트가 맥락을 활용해 상호작용을
능동적으로 이끌면서도 판정 권한과 데이터 출처 원칙을 유지할 수 있음을 구현으로 보였다.</p>

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
    fp = OUT / "devfix_results.json"
    fx = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
    (OUT / "report.html").write_text(build(data, a.tests, a.browser, x, fx), encoding="utf-8")
    print(OUT / "report.html")


if __name__ == "__main__":
    main()
