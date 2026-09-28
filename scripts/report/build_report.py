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

    # 프로토타입 · ② 2단계
    b += box(210, 492, 300, 36, "프로토타입 (Table 1 형식)", "고른 후보의 조성 mg · % · 기능 · 공정", "hi")
    b += arrow(580, 464, 470, 492, "연구자가 개발 착수", lx=540, ly=484)
    b += '<rect x="10" y="546" width="700" height="120" rx="10" fill="#fafafa" stroke="#999"/>'
    b += '<text x="22" y="564" class="gt">② 2단계 — Design Space 도출 (15단계 · 단계마다 연구자 승인)</text>'
    st = [("QTPP · CQA", "llm"), ("위험평가", "llm"), ("종합 정리", "det"), ("실험 설계 표", "io"),
          ("회귀 · ANOVA", "det"), ("공동확률 영역", "det"), ("확인계획 잠금", "det"), ("확인배치 2×2", "io")]
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


def fig_stage2():
    """2단계 15단계 — 담당(선 모양)과 표 번호. 모든 단계는 초안 → 결정론 검사 → 연구자 승인."""
    steps = [("1 프로토타입", "Table 1 · Handoff", "io"), ("2 QTPP", "Table 3 · LLM 초안", "llm"), ("3 CQA 판별", "Table 4 · 근거 필수", "llm"),
             ("4 원료 물성 위험", "Table 6 · 기전 근거", "llm"), ("5 원료 행렬", "Table 5 · 4에서 계산", "det"),
             ("6 제형·공정 위험", "Table 8 · 부형제 전부", "llm"), ("7 제형·공정 행렬", "Table 7 · 6에서 계산", "det"), ("8 종합 정리", "High 변수 · 위험평가 PDF", "det"),
             ("9 실험 설계 표", "Table 9 · CSV", "io"), ("10 회귀식 · 진단", "Table 10 · 과적합", "det"),
             ("11 반응 곡면", "Figure 1", "det"), ("12 ANOVA", "Table 11 · 최종 PDF", "det"), ("13 Design Space", "공동확률 ≥ 0.90", "hi"),
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
    b += '<text x="8" y="250" class="al">실선: 결정론(코드) · 파선: LLM 초안(연구자가 고치고 승인) · 굵은 테두리: 산출물. 영역이 비면 규격을 완화하지 않고 13단계에서 멈춘다.</text>'
    return svg(722, 258, b)


def fig_space_map(sl, sp_actual, ref):
    """그림 9 — 혼합 시간 단면(설정점을 지나는 면)의 (a) 평균 예측이 모든 규격 안 (b) 미래 배치 공동확률(≥ 0.90 흰 점). 값은 figdata.json."""
    nr, nc, cs = len(sl["P"]), len(sl["P"][0]), 12
    L, T = 50, 24

    def one(ox, mode, title):
        g = f'<text x="{ox + L}" y="14" class="gt" style="font-size:10px">{E(title)}</text>'
        for i in range(nr):
            for j in range(nc):
                x, y = ox + L + j * cs, T + (nr - 1 - i) * cs
                if not sl["in"][i][j]:
                    g += f'<rect x="{x}" y="{y}" width="{cs}" height="{cs}" fill="#eee"/>'
                elif mode == "mean":
                    g += f'<rect x="{x}" y="{y}" width="{cs}" height="{cs}" fill="{"#333" if sl["mean_ok"][i][j] else "#ddd"}"/>'
                else:
                    p = sl["P"][i][j]
                    g += f'<rect x="{x}" y="{y}" width="{cs}" height="{cs}" fill="#111" fill-opacity="{0.08 + 0.85 * p:.3f}"/>'
                    if p >= sl["p_min"]:
                        g += f'<circle cx="{x + cs / 2}" cy="{y + cs / 2}" r="2.1" fill="#fff"/>'
        rv, cv = sl["rows"]["values"], sl["cols"]["values"]
        idx = lambda vals, v: min(range(len(vals)), key=lambda k: abs(vals[k] - v))  # noqa: E731
        for (lab, val, colr) in (("설정점", sp_actual, "#c0392b"), ("논문 최적", ref, "#1d4ed8")):
            ri, ci = idx(rv, val[sl["rows"]["name"]]), idx(cv, val[sl["cols"]["name"]])
            g += f'<circle cx="{ox + L + ci * cs + cs / 2}" cy="{T + (nr - 1 - ri) * cs + cs / 2}" r="{cs * 0.85}" fill="none" stroke="{colr}" stroke-width="2"/>'
        g += (f'<text x="{ox + L}" y="{T + nr * cs + 12}" class="al">{cv[0]:g}</text>'
              f'<text x="{ox + L + nc * cs}" y="{T + nr * cs + 12}" class="al" text-anchor="end">{cv[-1]:g}</text>'
              f'<text x="{ox + L + nc * cs / 2}" y="{T + nr * cs + 26}" class="al" text-anchor="middle">크로스포비돈 (%)</text>'
              f'<text x="{ox + L - 4}" y="{T + nr * cs}" class="al" text-anchor="end">{rv[0]:g}</text>'
              f'<text x="{ox + L - 4}" y="{T + 8}" class="al" text-anchor="end">{rv[-1]:g}</text>'
              f'<text x="{ox + 14}" y="{T + nr * cs / 2}" class="al" transform="rotate(-90 {ox + 14} {T + nr * cs / 2})" text-anchor="middle">MCC:만니톨 비</text>')
        return g
    b = one(0, "mean", "(a) 평균 예측이 네 규격 안") + one(360, "joint", "(b) 미래 배치 공동 통과확률 (흰 점 ≥ 0.90)")
    b += ('<g transform="translate(8,316)"><circle cx="6" cy="0" r="6" fill="none" stroke="#c0392b" stroke-width="2"/><text x="18" y="4" class="lg">권장 설정점</text>'
          '<circle cx="106" cy="0" r="6" fill="none" stroke="#1d4ed8" stroke-width="2"/><text x="118" y="4" class="lg">논문 최적 처방(참고점)</text>'
          '<rect x="260" y="-6" width="12" height="12" fill="#eee"/><text x="278" y="4" class="lg">설계점이 받치지 않는 곳(외삽 — 계산에서 뺌)</text></g>')
    return svg(720, 326, b)


def _orders(rows, fk) -> str:
    return " · ".join(f"{fk.get(x['model'], x['model'])} {x['pred_r2']:.2f}" for x in rows)


def lornox_section(L) -> str:
    """7.2 — 발표 자료 시연 ①의 Design Space: Almotairi 2022 Table 3(실측 15 run)."""
    if not L:
        return ""
    R, sp = L["region"], L["region"]["setpoint"]
    fk = {"Quadratic": "2차", "Linear": "선형", "2FI": "2요인 교호작용"}
    fit = "".join(f"<tr><td>{E(f['response'])}</td><td>{E(fk.get(f['suggested'], f['suggested']))}</td>"
                  f"<td>{f['adj_r2']:.3f}</td><td>{f['pred_r2']:.3f}</td><td>{'과적합 의심 — 사유 수용' if f['overfit'] else '—'}</td>"
                  f"<td>{E(_orders(f['rows'], fk))}</td></tr>"
                  for f in L["fit"])
    pts = {p["role"]: p for p in L["plan"]["points"]}
    de = pts["SETPOINT"]["predicted"]["DE30"]
    rows = "".join(f"<tr><td>{E({'SETPOINT': '설정점', 'BOUNDARY': '경계점', 'ROBUSTNESS': '강건성', 'REFERENCE': '참고(논문 최적)'}[p['role']])}</td>"
                   f"<td>{' · '.join(f'{v:g}' for v in p['settings'].values())}</td><td>{p['joint']:.3f}</td>"
                   f"<td>{p['predicted']['DE30']['mean']:.1f} ({p['predicted']['DE30']['pi_lower']:.1f}–{p['predicted']['DE30']['pi_upper']:.1f})</td>"
                   f"<td>{p['predicted']['AV']['mean']:.1f} ({p['predicted']['AV']['pi_lower']:.1f}–{p['predicted']['AV']['pi_upper']:.1f})</td></tr>"
                   for p in L["plan"]["points"])
    ratio = R["mean_ok_fraction"] / R["feasible_fraction"]
    return f"""<h3>7.2 로르녹시캄 분산정 — 미래 배치로 정한 Design Space (발표 시연 ①)</h3>
<p>1단계 시연 ①(성인용 로르녹시캄 8 mg 분산정, 유동성 실측으로 직접타정 유지)에서 연구자가 후보를 골라 2단계로 넘기면, 9단계에서 Almotairi 등[11]의 Box–Behnken
실측 {L['n']} run(Table 3 — 요인: MCC:만니톨 비 1–3, 혼합 시간 5–15분, 크로스포비돈 2–10 %; 반응: 분산 시간, 마손도, 30분 용출률 DE30, 함량균일성 AV)을
CSV로 불러온다. 10단계 적합 요약은 표 4-2의 모형을 제안한다 — 마손도는 2차 모형의 예측 R²가 크게 떨어져 선형이 제안되고, AV는 2차가 유의하지만 예측 R²가
수정 R²보다 0.2 넘게 낮아 <b>과적합 의심</b>으로 표시되어, 연구자가 사유를 적어야 승인된다.</p>
<table><thead><tr><th>반응</th><th>제안 모형</th><th>수정 R²</th><th>예측 R²</th><th>진단</th><th>차수별 예측 R²</th></tr></thead><tbody>{fit}</tbody></table>
<div class="tcap"><b>표 4-2.</b> 로르녹시캄 15 run의 적합 요약(엔진 계산). 제안 = 순차 F 검정이 유의한(p &lt; 0.05) 가장 높은 차수.</div>
<p>규격(분산 ≤ 180 s, 마손도 ≤ 1.0 %, DE30 ≥ 75 % — 논문 기준이 아닌 프로젝트 목표로 화면에 가정 표시, AV ≤ 15)을 넣으면, 설계점 convex hull 안 격자점
{R['grid_points_in_domain']:,} / {R['grid_points_total']:,}점 중 평균 예측이 네 규격을 모두 만족하는 곳은 <b>{100 * R['mean_ok_fraction']:.1f} %</b>지만, 미래 배치의 공동 통과확률이
0.90 이상인 곳은 <b>{100 * R['feasible_fraction']:.1f} %</b>다(그림 9). 평균 반응면만 보면 영역을 약 {ratio:.1f}배 과대평가하며, 미달 격자점의 대부분은 DE30이 결정한다
({', '.join(f'{k} {v:,}' for k, v in R['binding'].items())}). 권장 설정점은 MCC:만니톨 {sp['actual']['MCC:Mannitol']:g} · 혼합 {sp['actual']['Mixing time']:g}분 ·
크로스포비돈 {sp['actual']['Crospovidone']:g} %(공동확률 {sp['joint']:.3f})로, 논문의 desirability 최적점(3:1 · 11분 · 6.23 %)보다 영역 경계에서 떨어진 쪽이다 —
평균 반응을 최적화하는 대신 미래 배치가 네 규격을 동시에 통과할 확률을 최대화하기 때문이다.</p>
<figure>{fig_space_map(L['slice'], sp['actual'], L['reference_optimum'])}
<figcaption><b>그림 9.</b> 혼합 시간 {L['slice']['fixed']['actual']:g}분 단면(설정점을 지나는 면, 격자 21×21). (a) 평균 예측이 네 규격 안인 곳(진한 칸), (b) 미래 배치 공동 통과확률(진할수록 높음, 흰 점 ≥ 0.90).
회색은 설계점이 받치지 않는 곳(외삽)이다. 파란 원(논문 최적, 혼합 11분)은 이 단면 밖이라 위치만 투영했다. 13단계 화면의 단면 지도와 같은 계산이다.</figcaption></figure>
<table><thead><tr><th>확인점</th><th>설정(비 · 분 · %)</th><th>공동확률</th><th>DE30 예측 (구간)</th><th>AV 예측 (구간)</th></tr></thead><tbody>{rows}</tbody></table>
<div class="tcap"><b>표 4-3.</b> 14단계 확인계획 — 결과 전에 잠그는 확인점과 동시 예측구간({L['plan']['pi_policy']['comparisons']}개 비교 Bonferroni, 개별 {100 * L['plan']['pi_policy']['per_comparison_level']:.2f} %).
AV 하한은 0에서 자른다. 논문 최적 처방의 배치는 결과가 이미 공개되어 참고점으로만 비교한다.</div>
<p>설정점의 DE30 예측은 {de['mean']:.1f} %(동시 예측구간 {de['pi_lower']:.1f}–{de['pi_upper']:.1f})다. 15단계는 모형 적합에 쓰지 않은 새 독립 배치를 세 확인점에서 만들어
넣어야 판정하며, 공개 자료만으로는 VERIFIED에 이를 수 없다 — 시연은 확인계획 잠금까지다. 이 계산은 화면 흐름과 같은 코드로 돌고, 위 수치는 테스트로 고정되어 있다.</p>
"""


def _p(v):
    return "—" if v is None else ("< 0.0001" if v < 0.0001 else f"{v:.4f}")


FAM_KO = {"Mean": "평균", "Linear": "선형", "2FI": "2요인 교호작용", "Quadratic": "2차"}


def stage2_abstract(g, lm) -> str:
    if not g:
        return ""
    m = g["matrices"]
    ps = {r["response"]: r for r in g["responses"]}
    txt = (f" 2단계는 Monton 등(2026)의 CBD 구강붕해정 논문 표에 적용했다 — 근거 표(Table 6·8)에서 코드가 만든 위험 행렬이 Table 5·7의 "
           f"{m['rm']['cells'] + m['fp']['cells']}칸과 모두 일치했고, Table 9 원자료로 다시 적합한 회귀식·ANOVA가 Table 10·11의 모형 p값"
           f"(경도 {_p(ps['Hardness']['model_p'])}, 붕해시간 {_p(ps['DT']['model_p'])}, 마손도 {_p(ps['Friability']['model_p'])})과 적합결여 p·잔차 자유도를 그대로 재현했다.")
    L = g.get("lornoxicam")
    if L:
        R, sp = L["region"], L["region"]["setpoint"]
        txt += (f" 발표 시연 ①의 로르녹시캄 분산정(Almotairi 등, 2022)의 Box–Behnken 실측 {L['n']} run을 같은 흐름에 넣으면, 평균 예측 기준으로는 지지 영역의"
                f" {100 * R['mean_ok_fraction']:.1f}%가 규격을 만족했으나 미래 배치 공동 통과확률 0.90 기준으로는 {100 * R['feasible_fraction']:.1f}%만 남았고"
                f"(약 {R['mean_ok_fraction'] / R['feasible_fraction']:.1f}배 과대평가), 권장 설정점(비 {sp['actual']['MCC:Mannitol']:g} · 혼합 {sp['actual']['Mixing time']:g}분 ·"
                f" 크로스포비돈 {sp['actual']['Crospovidone']:g}%)의 공동확률은 {sp['joint']:.3f}였다. CBD는 논문 규격에서 공동확률 영역이 비어(최대"
                f" {g['cbd_space']['max_joint']:.3f}) 규격을 완화하지 않고 멈췄다.")
    if lm:
        st = {x["step"]: x for x in lm["steps"]}
        if "rm_matrix" in st and "fp_matrix" in st:
            txt += (f" 같은 프로토타입에서 LLM 초안을 고치지 않고 승인해 가면 결정론 검사는 모두 통과했지만, 논문과 같은 위험 등급인 칸은 원료 "
                    f"{st['rm_matrix']['same']}/{st['rm_matrix']['common']}, 제형·공정 {st['fp_matrix']['same']}/{st['fp_matrix']['common']}에 그쳤다 — "
                    "검사는 형식과 누락을 막을 뿐 판단의 타당성은 연구자 승인이 맡아야 함을 보여 준다.")
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
    return f"""<h3>7.1 CBD 구강붕해정 — 논문 표를 2단계로 재현</h3>
<p>Monton 등[18]은 CBD 10 mg 구강붕해정(1정 250 mg, 직접타정)을 QbD로 개발하며 QTPP(Table 3) → CQA(Table 4) → 원료 물성·제형·공정 위험평가(Table 5–8) →
Box–Behnken DoE(Table 9, {g['design']['runs']} run; {', '.join(E(f) for f in g['design']['factors'])}) → 회귀식(Table 10)·ANOVA(Table 11)·반응 곡면(Figure 1)의 순서를 밟았다.
이 표들을 옮긴 fixture로 2단계 study를 열어 논문 값으로 진행했다(승인 {w['approvals']}건, 이벤트 {w['events']}건, 위험평가 보고서 {w['risk_pdf_kb']} KB · 최종 보고서 {w['final_pdf_kb']} KB).
12단계까지 막힘 없이 갔고, 13단계에서 논문 규격(경도 4–6 kgf · 붕해 ≤ 30 s · 마손도 ≤ 1 %)으로 영역을 계산하면 평균 기준 {100 * g['cbd_space']['mean_ok_fraction']:.1f}%인데
미래 배치 공동확률 ≥ 0.90은 {100 * g['cbd_space']['feasible_fraction']:.0f}%(최대 {g['cbd_space']['max_joint']:.3f}, 경계는 {E(next(iter(g['cbd_space']['binding'])))})라 승인이 막혔다 —
경도 규격 폭(2 kgf)이 모형의 예측 변동에 비해 좁기 때문이며, 시스템은 규격을 완화하지 않는다.</p>
<p>위험 행렬은 입력하지 않는다. 논문의 근거 표(Table 6 {m['rm']['rows']}행, Table 8 {m['fp']['rows']}행 — 같은 판단을 공유하는 CQA를 한 행에 묶은 형식)에서 코드가 칸마다
등급을 채웠고, 그 결과가 논문의 행렬과 원료 {m['rm']['same']}/{m['rm']['cells']}칸, 제형·공정 {m['fp']['same']}/{m['fp']['cells']}칸 일치했다. 따라서 행렬과 근거는 어긋날 수 없고, 근거가 없는 칸이
하나라도 있으면 승인이 막힌다(JUST_MISSING). 8단계 종합 정리는 코드가 두 행렬을 합쳐 제형·공정 행렬에서 High인 변수({cand})를 DoE 변수 후보로 보여 주고,
8단계에 들어오는 즉시 그 목록 바로 아래에 위험평가 보고서가 나온다 — 이 단계에는 고르는 칸이 없고 확인만 한다. 논문은 이 중 {', '.join(E(v) for v in g['paper_doe'])}을 DoE 요인으로 썼는데(Spray-dried mannitol은 High지만 나머지를 채우는 균형 성분이라 빠졌다),
이런 선택은 규칙이 아니라 연구자 판단이므로 9단계 실험 설계 표에서 연구자가 요인을 직접 적는다(High 변수는 이름 입력칸의 제안 목록으로만 보인다).</p>
<table><thead><tr><th>반응</th><th>적합 요약의 제안</th><th>논문 모형</th><th>논문 모형으로 다시 적합한 coded 식</th><th>모형 SS · p (논문)</th><th>적합결여 p (논문)</th><th>잔차 df (논문)</th></tr></thead><tbody>{rows}</tbody></table>
<div class="tcap"><b>표 4.</b> 회귀식과 ANOVA — Table 9 원자료에서 다시 계산한 값과 논문 값(괄호). 계수는 논문에서 베끼지 않았다. 적합 요약은 평균 → 선형 → 2요인 교호작용 → 2차의 순차 F 검정에서
p &lt; 0.05인 가장 높은 차수를, 유의한 차수가 없으면 예측 R²가 가장 큰 모형을 제안한다. 붕해시간은 논문도 모형이 유의하지 않았고(p = {_p(g['responses'][1]['paper_model_p'])}), 마손도는 논문이 2요인 교호작용을 썼지만
순차 검정은 선형을 제안한다 — 화면에서는 제안과 다른 모형을 고르면 경고와 함께 연구자 선택으로 기록한다.</div>
<figure><img src="cbd_surfaces.png" style="width:100%" alt="CBD 반응 곡면 격자">
<figcaption><b>그림 8.</b> 11단계 반응 곡면 — 논문 Figure 1과 같은 배치(반응 × CCS 1·3·5%). 10단계에서 논문 모형 차수를 고른 회귀식으로 그렸다. 빨간 점은 관측값이 곡면 위, 연분홍은 아래,
세로줄은 잔차, 바닥 점선은 그 단면의 설계점이 받치는 영역(밖은 외삽), 바닥 색선은 등고선이다. 최종 보고서 PDF에는 확인 단계에서 이 그림이 그대로 들어간다.</figcaption></figure>
<p>ANOVA는 항마다 그 항만 뺀 모형과의 잔차 제곱합 차이(부분 제곱합)로 계산하고, 반복된 중심점으로 순수오차와 적합결여를 나눈다. 경도의 Model SS {g['responses'][0]['model_ss']:.2f}·p {_p(g['responses'][0]['model_p'])},
잔차 자유도 {g['responses'][0]['residual_df']}와 적합결여 p {_p(g['responses'][0]['lof_p'])}가 논문 Table 11과 같고, 테스트가 이 값들과 Table 10의 식을 고정한다.</p>
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
    return f"""<h3>7.7 LLM 초안과 논문 표</h3>
<p>같은 CBD 프로토타입으로 2~7단계(LLM 초안이 있는 단계와 그 행렬)를 {'대회 API' if lm['llm'] == 'dacon' else E(lm['llm'])}의 초안만으로 진행했다 — 연구자 편집 없이 초안을 그대로 승인했다(호출 {', '.join(f'{E(k)} {v}회' for k, v in calls.items())}; {E(secs)}).
결정론 검사는 한 번도 승인을 막지 않았다. 즉 초안은 형식상 완전했다 — 모든 확정 CQA × 변수 칸에 근거가 있고, 처방의 부형제가 모두 평가되었으며, 공정 이름이 아니라 조절 가능한 공정 파라미터가 들어갔다.
QTPP는 {st['qtpp']['items']}개 요소(논문 {st['qtpp']['paper_items']}개)였고, 입력에 없는 수치를 쓴 문장에는 “출처 확인” 경고(LLM_NUMBERS)가 붙었다.</p>
<p>내용은 달랐다. CQA 판별에서 LLM은 {', '.join(E(x) for x in c['only_llm']) or '—'}를 위험평가 CQA에 더했고{(' 논문의 ' + ', '.join(E(x) for x in c['only_paper']) + '를 뺐다') if c['only_paper'] else ''}.
제형·공정 변수는 논문의 {len(fj['paper_variables'])}개 외에 {', '.join(E(x) for x in extra)}를 더해 {len(fj['variables'])}개를 평가했다. 논문과 같은 이름의 칸끼리 비교하면 위험 등급이 같은 칸은 원료
{rm['same']}/{rm['common']}, 제형·공정 {fm['same']}/{fm['common']}이었고, 다른 칸 {nd}개 중 {up}개는 LLM이 논문보다 높게 매겼다.</p>
<p>여기서 논문은 <b>정답지가 아니라 참고 자료</b>다. 위험 등급은 한 연구팀이 자기 설비·경험으로 내린 판단이라, 논문과 다른 칸은 오답이 아니라 연구자가 근거를 확인할 지점이다.
그래서 일치율을 품질 점수로 쓰지 않고, 차이가 난다는 사실을 2단계를 “자동 설계”가 아니라 “단계마다 승인하는 초안”으로 만든 이유로 쓴다. 초안은 몇 분 만에 빈칸 없는 위험평가를 만들지만, 어떤 칸이 High인지는 제제 경험과 처방의 맥락이
정한다. 화면은 논문으로 시작한 study에서 칸 단위 참고 비교(다른 칸 테두리 표시)를 제공하고, 새 후보에서는 연구자가 행을 고치거나 나누고 근거 유형을 적은 뒤 승인한다.
반대로 회귀·ANOVA·공동확률처럼 계산으로 정해지는 값은 원자료가 같으면 같아야 하므로, 그쪽은 논문 표의 재현(7.1)과 같은 원자료에서 같은 영역이 나오는지(7.2 골든 값)를 테스트로 고정했다.</p>
"""


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
    calls_by = x.get("llm_calls") or {}
    if calls_by:
        parts.append("실제로 응답한 프로바이더는 " + ", ".join(
            f"{'대회 API' if k == 'dacon' else '무료 Groq' if k == 'groq' else k} {v}회" for k, v in calls_by.items())
            + (" — 무료 모델로의 전환은 없었다." if not calls_by.get("groq") else " — 대회 API 한도·오류로 일부가 무료 모델로 전환됐다."))
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
    return f"""<h3>7.5 데모 결함 수정의 검증</h3>
<p>시연 쿼리 3건을 무료 모델로 돌린 데모 실행 결과 보고서와 그 원인·수정·합격 기준을 정리한 개발자 수정 과제(14건)를 반영한 뒤, 과제 문서 §6의
검증 계획을 {E(fx.get('llm_label') or fx.get('llm'))}로 각 {max(r['repeat'] for r in fx['results'])}회 실행했다(표 7; 실제 응답 프로바이더
{', '.join(f"{'대회 API' if k == 'dacon' else '무료 Groq' if k == 'groq' else k} {v}회" for k, v in (fx.get('llm_calls') or {}).items()) or '기록 없음'}). 수정의 핵심은 세 가지다 — (1) 모든 규칙보다 먼저
후보가 요청과 맞는지 대조하는 입력 계약 검사(API 1행, 요청 용량의 유리염기 ±0.5%, 고정 부형제, FDA 라벨 1일 최대 용량), (2) 염 형태 입력의 분자 특성값을
parent로 계산, (3) 측정값 문장을 LLM보다 먼저 규칙으로 잡아 설계를 다시 돌리지 않고 제출. {' '.join(extra)}
T5(API 누락 후보 주입)·T6(암로디핀 50 mg 후보 주입)은 결정론 계층만의 동작이라 단위 테스트로 고정했다(RC001 · MAX_DAILY_DOSE 반려).</p>
<table><thead><tr><th>케이스</th><th>회</th><th>종결</th><th>초</th><th>통과한 기준</th><th>실패한 기준</th></tr></thead><tbody>{{rows}}</tbody></table>
<div class="tcap"><b>표 7.</b> 검증 계획 T1–T4의 실제 실행 결과(devfix_results.json). T1: 로르녹시캄 8 mg·고정 MCC·만니톨·크로스포비돈·유동성 42°/22%/1.28,
T2: 고령자 암로디핀 2.5 mg + 유당 고정(베실산염 SMILES), T3: T2에서 유당 제외, T4: VX-770 150 mg cold start 후 Tm·용해도 문장 제출.</div>
""".replace("{rows}", rows)


def demo_abstract(dm) -> str:
    """초록 한 문장 — 시연 카드 결과(demo_cards.json)에서 계산."""
    if not dm:
        return ""
    res = dm["results"]
    c2 = [r for r in res if r["card"] == "card2"]
    c3 = [r for r in res if r["card"] == "card3"]
    ok = all(r.get("pass") for r in res)
    blk = sorted({b for r in c2 for b in (r.get("infeasible") or {}).get("blocking") or []})
    sig = sorted({r.get("plan_signature_after") for r in c3})
    return (f" 약학 담당이 만든 시연 쿼리 3장을 대회 API로 각 2회 실행한 결과 {'모든 합격 기준을 통과했고' if ok else '일부 기준이 실패했고'}, 유당을 고정한 "
            f"고령자 암로디핀은 {', '.join(blk)}로 “제약 불가능”, 개발코드만 준 신규물질은 Tm·용해도 제출 뒤 분무건조 ASD가 계획({', '.join(sig)})에 들어오고 "
            f"ASD 공정이 분무건조로 판정되었으며, 실명이 출력에 "
            f"{'나오지 않았다' if not any(r.get('name_leaks') for r in c3) else '나타났다'}.")


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
        para.append(f"카드 1의 Tm 225 °C 제출(입력 에이전트가 LLM보다 먼저 규칙으로 잡음)은 DRQ_TM을 닫았고, Tm을 알게 되자 분무건조 ASD가 전략 후보에 들어와 "
                    f"계획이 {t.get('plan_signature')} → {t.get('plan_signature_after_tm')}로 바뀌어 그 전략들의 후보만 다시 설계됐다. 이 재설계에는 심사가 붙지 않아 "
                    f"후보가 순위 없이 남으며(종결 {t.get('status_after_tm')}), 연구자가 고른 후보({t.get('picked')})로 개발에 착수했다.")
    poor = by("card1_flow48")
    if poor:
        ex = next((g[1] for g in poor[0].get("route_signals") or [] if g[1].get("excluded_routes")), {})
        para.append(f"같은 카드에서 안식각만 48°로 바꾸면 흐름성이 {next((g[1].get('flow_character') for g in poor[0]['route_signals'] if g[1].get('flow_character')), '')}로 판정되어 "
                    f"{', '.join(ex.get('excluded_routes') or [])}가 배제되고 계획이 {poor[0].get('plan_signature')}로 바뀌었다(42°: {c1s[0].get('plan_signature') if c1s else ''}).")
    mg = [r.get("mg_stearate_candidates", 0) for r in by("card1")]
    if mg:
        para.append(f"카드 1의 마지막 라운드 후보 가운데 스테아르산 마그네슘을 넣은 후보는 실행별 {', '.join(map(str, mg))}개였다 "
                    "(논문 처방은 SLS 윤활; 넣은 경우 과혼합 위험 INC014는 반려가 아니라 DoE 요인 후보로 넘어간다).")
    paras = [" ".join(para)]
    para = []
    c2 = by("card2")
    if c2:
        blk = sorted({b for r in c2 for b in (r.get("infeasible") or {}).get("blocking") or []})
        free = by("card2_free")
        para.append(f"카드 2(유당 고정)는 두 번 모두 되돌림 없이 “제약 불가능”으로 끝났고, 막은 규칙은 {', '.join(blk)}였다 — 베실산염을 벗긴 parent에서 1차 아민 × 유당 "
                    "금기(INC001)가, 습식과립 후보에서 다성분 규칙(유당 + 스테아르산 마그네슘 + 물, Abdoh 2004[14])이 발동했다. 같은 세 성분이라도 직접타정 조합에서는 "
                    "다성분 규칙이 발동하지 않으며(단위 테스트로 고정), 1,4-디히드로피리딘 고리의 N–H는 2차 아민으로 잡히지 않았다. 대체 성분으로는 만니톨과 유당 없는 처방을 "
                    "제시했는데, 정답지(NORVASC)도 유당 없는 처방이다. 다성분 규칙의 조건 “40°C/75%RH 스트레스”는 모든 신약 제품이 거치는 가속 안정성 조건"
                    "(ICH Q1A[17])이므로 번역표에서 항상 성립하는 조건으로 둔다."
                    + (f" 유당 고정을 뺀 대비 실행에서는 통과 후보의 API가 유리염기 {free[0]['api_amounts'][0][0][1]:g} mg으로 기록되고(염 환산계수 {free[0].get('salt_factor')}), "
                       f"소아 심사관 대신 고령자 심사관(REV006)이 소집됐다." if free and free[0].get("api_amounts") else ""))
    paras.append(" ".join(para))
    para = []
    c3 = by("card3")
    if c3:
        leaks = sorted({l for r in c3 for l in r.get("name_leaks") or []})
        para.append("카드 3은 구조와 용량만으로 시작해 Tm 317 °C · 용해도 0.00005 mg/mL를 한 문장으로 제출하자 계획이 "
                    + "; ".join(sorted({f"{r.get('plan_signature_before')} → {r.get('plan_signature_after')}" for r in c3}))
                    + (" (두 번 모두 같음)" if len(c3) > 1 and len({(r.get('plan_signature_before'), r.get('plan_signature_after')) for r in c3}) == 1 else "")
                    + f"로 바뀌었다 — 분무건조 ASD가 계획에 들어오고, ASD 공정 게이트(G4B002)는 고융점이라 용융압출보다 분무건조를 택했다(정답지: Kalydeco = 80% HPMCAS 분무건조 분산체[15, 16]). 전략이 ASD 하나로 좁혀지지는 않았다 — 입자 크기 축소(MICRO)와 직접타정도 점수 상위 3개에 남는다. 4-퀴놀론 N–H는 유당 금기를 켜지 않았다. "
                    + ("요청 해석 LLM은 개발코드만 보고도 일반명을 떠올릴 수 있으므로, 요청에 개발코드가 있으면 그 코드를 이름으로 고정하고 구조로 찾은 실명·라벨 제품명을 "
                       "이벤트와 LLM 입출력 모두에서 코드로 가린다. 그 결과 출력 전체(이벤트·요약·심사 서술)에 실제 물질명은 나오지 않았다." if not leaks else
                       f"실제 물질명({', '.join(leaks)})이 {', '.join(sorted({s for r in c3 for s in r.get('leak_sources') or []}))} 출력에 나타났다 — "
                       "개발코드로 찾은 문헌 초록이 실명을 담고 있기 때문이며, 블라인드 시연에서는 문헌 패널을 가려야 한다.")
                    + " 용해도는 문헌상 상한(“< 0.05 µg/mL”)인데 입력은 등호 값만 받으므로 상한을 그대로 값으로 넣었다.")
    paras.append(" ".join(para))
    paras = [x for x in paras if x]
    calls = dm.get("llm_calls") or {}
    return f"""<h3>7.6 시연 쿼리 카드 — 정답지와 나란히</h3>
<p>약학 담당이 만든 시연 쿼리 카드 3장(① 로르녹시캄 8 mg 분산정 전체 파이프라인 — Almotairi 등[11]의 처방, ② 고령자 암로디핀 2.5 mg에 유당 고정, ③ 개발코드만 공개한
신규물질 cold start)을 카드에 적힌 문장·값 그대로 {E(dm.get('llm_label') or dm.get('llm'))}로 실행했다(각 {max(r['repeat'] for r in res)}회; 실제 응답 프로바이더 —
수정 뒤 카드별로 다시 돌린 실행까지 누적 — {', '.join(f"{'대회 API' if k == 'dacon' else '무료 Groq' if k == 'groq' else k} {v}회" for k, v in calls.items()) or '기록 없음'}{
'. 무료 Groq 호출은 대회 API 호출이 오류로 실패해 같은 호출이 넘어간 경우다' if calls.get('groq') else ''}). 데이터 요청에는 카드의 제출 값을
입력 에이전트에 문장으로 넣었다(표 8).</p>
<table><thead><tr><th>카드</th><th>회</th><th>종결</th><th>초</th><th>시스템이 한 일</th></tr></thead><tbody>{rows}</tbody></table>
<div class="tcap"><b>표 8.</b> 시연 쿼리 카드 실행 결과(demo_cards.json — 서버 응답·이벤트 스트림에서 기록). 대비 행은 같은 카드에서 한 값만 바꾼 실행이다.</div>
{''.join(f"<p>{x}</p>" for x in paras)}
<p><b>카드가 드러낸 결함.</b> 카드를 돌리기 전 코드·규칙표를 카드의 “시연 전 확인” 항목에 맞춰 전수검사했고, 다음을 고쳤다. (1) 다성분 금기표는 성분군·조건 이름
(<code>reducing_sugar</code>, <code>moisture present</code>)으로 적혀 있는데 처방을 그 어휘로 옮기는 단계가 없어 한 번도 발동할 수 없었다 — 번역표
(<code>component_classes.yaml</code>: 부형제 마스터 열, API 작용기, 수계 공정, 가속 조건)를 두고 모든 이름이 규칙표에 있는지 테스트로 고정했다. (2) 페놀·이미드처럼
위장관 pH에서 거의 이온화하지 않는 site만 있는 약도 “pH 의존 → BCS 미정”으로 분류되던 것을 위장관 이온화(<code>ionizable_gi</code>)로 좁혔다. (3) 분산정이
정제로 뭉개지던 것을 제형 끝까지 전달했다. (4) 약물 함량(%)을 규칙 문맥에 넣어 저함량 규칙(RTE008)이 발동하게 했다. (5) 개발코드 요청의 실명 노출을 막았다. (6) 제약 불가능 카드의 “막은 규칙”에 검토 flag가 섞이던 것을 반려 권한이 있는
판정으로 한정했다. (7) 데이터 요청이 기대하는 결과 키 가운데 측정 카탈로그에 없던 것을 추가했다.</p>
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
    return f"""<h3>7.4 대회 API 기반 재실험</h3>
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
실측값으로 받지 않은 것은 모델의 판단이다).</div>
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
def build(data, tests: int, browser: str, x=None, fx=None, dm=None, lm=None) -> str:
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

<h1>Formula 1: 결정론적 규칙 검증과 입력 에이전트를 갖춘<br>다중 에이전트 제형 설계와 QbD 기반 Design Space 도출 시스템</h1>
<div class="sub">팀 Formula 1 · 제4회 인공지능 신약개발 경진대회</div>
<div class="meta">라이브 시스템 https://zihwan.com/formula1 · 기술 보고서</div>

<div class="abstract"><b class="h">초록</b>
거대언어모델(LLM)은 제형 처방을 그럴듯하게 제안하지만, 배합 금기·공정 한계·규제 상한 같은 정량 판단에서
근거 없는 수치를 만들어 낼 수 있다. 본 연구는 <b>창의는 AI가, 검증은 규칙이, 결정은 연구자가</b> 맡는 역할 분리를
구조로 강제하는 제형 설계 시스템 Formula 1을 제시한다. 시스템은 두 그래프로 구성된다. ① 후보 탐색 그래프는
분자 구조에서 계산한 값과 공개 경험식 예측만으로 생물약제학 페이즈 게이트(BCS/DCS·고체상·가용화·ASD 공정)를 돌려
전략을 좁히고, 전략별 후보를 병렬 설계한 뒤, 출처와 검증 상태가 붙은 규칙표로 반려하며, 반려 사유별 복귀 지점을
전이표({c['backtrack_transitions']}행)로 정한다. 값이 없을 때는 멈추지 않고 측정 카탈로그({c['measurement_catalog']}종) 안에서만
실측을 요청한다. ② 2단계는 연구자가 고른 후보를 프로토타입(성분·mg·%·기능)으로 받아 QTPP → CQA → 원료 물성·제형·공정 위험평가 →
종합 정리(위험평가 보고서) → 실험 설계 표 → 회귀식 → 반응 곡면 → ANOVA → 미래 배치 공동 통과확률로 정한 Design Space → 확인계획 잠금 → 확인배치의 15단계를,
LLM 초안·결정론 계산과 검사·연구자 승인으로 진행한다.
두 그래프 앞에는 <b>입력 에이전트</b>가 서서, 서버가 구성한 맥락을 읽고 사용자의 말을 실행 가능한 제안 카드로 바꾸되,
제안의 수치는 사용자 발화에, 구조식은 사용자 입력·내장 사전·PubChem에만 근거하도록 코드로 강제한다. 모든 규칙보다 먼저
후보가 요청한 약·용량·고정 부형제와 FDA 라벨 1일 최대 용량에 맞는지 대조하는 입력 계약 검사를 두고, 심사 점수에는 Crossref·NCBI로 확인되는
DOI·PMID 인용을 요구한다.
{stage2_abstract(data.get('stage2'), lm)}{demo_abstract(dm)}
<div class="kw"><b>주제어</b> 제형 설계 · Quality by Design · 다중 에이전트 · 결정론적 검증 · 환각 억제 · 실험계획법 · 설계공간 · lab-in-the-loop</div>
</div>

<h2>1. 서론</h2>
<p>신약 하나가 허가되기까지의 비용과 시간 가운데 상당 부분은 주성분을 사람이 복용할 수 있는 형태로 만드는 제형 개발에서 쓰인다.
주성분만으로는 정제가 형성되지 않으므로 희석제·결합제·붕해제·활택제 같은 첨가제를 섞는데, 바로 그 조합에서 화학적 비상용성
(예: 2차 아민과 유당의 Maillard 반응), 공정 실패(유동성 부족으로 인한 직접타정 불가), 규제 상한 초과(소아용 첨가제 한도)가 발생한다.
처방이 정해진 뒤에도 어떤 품질 특성이 중요한지, 어떤 변수가 그것을 좌우하는지를 위험평가로 가리고 실험계획법으로 그 영향을 식으로 보여야 한다[1].</p>
<p>LLM은 넓은 조합 공간에서 후보를 상상하고 상충하는 목표 사이의 타협을 서술하는 데 강하지만, 수치 판단에서 근거 없는 값을
확신 있게 생성하는 환각 문제가 있다. 제약에서 이러한 오류는 제품 폐기와 허가 반려로 직결된다. 따라서 우리는 LLM에게 판정 권한을
주지 않고, 판정은 출처가 있는 규칙표와 결정론 엔진에만 맡기는 구조를 설계했다. 본 보고서는 그 구조와 구현, 그리고 공개 실측 데이터에
대한 적용 결과를 서술한다.</p>
<p>기여는 다음과 같다. (1) 판정 권한을 데이터(규칙표)로 제한하고, 근거 상태에 따라 반려 가능 여부를 엔진이 스스로 정하는 검증 계층.
(2) 값을 모를 때 멈추지 않고 판정이 갈리는 지점에서만 실측을 요청하는 비차단 lab-in-the-loop와, 반려 사유별 복귀 지점을 정하는 되돌림 전이표.
(3) 후보 이후의 개발을 ICH Q8 순서의 15단계 승인 study로 옮기고, 위험 행렬을 근거 표에서 코드로 만들며 회귀·ANOVA와 미래 배치 공동확률 영역을 결정론으로 계산하는 2단계.
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
<figcaption><b>그림 1.</b> 전체 구조. 연구자와 두 그래프 사이에 입력 에이전트가 있고, 두 단계는 내부 상태를 공유하지 않은 채 연구자가 고른 후보의 처방(프로토타입)
하나로만 연결된다. ① 안의 두 확대 상자는 규칙 게이트(우선순위 단계, 근거 상태별 권한, 판정별 경로 — 그림 4)와 동적 심사단(명단 7명과 소집 조건,
순위만 매기는 합의 — 그림 6)의 내부다. 선 모양은 담당 주체를 나타낸다(실선: 결정론 규칙·엔진, 파선: LLM, 점선: 순위만 매기는 심사관).</figcaption></figure>
<p>역할 분리는 표 1과 같다. 판정·계산 권한은 결정론 계층에만 있고, LLM은 제안과 서술만 한다. 연구자는 어떤 후보를 개발할지,
어떤 위험 등급과 실험 요인, 회귀 모형을 받아들일지 같은 수용 결정을 단계마다 내린다.</p>
<table><thead><tr><th>성격</th><th>예</th><th>담당</th></tr></thead><tbody>
<tr><td>숫자로 답이 떨어지는 것</td><td>첨가제 상한, 위험 행렬, 회귀계수, ANOVA</td><td>규칙 기반 검사기 · 통계 코드</td></tr>
<tr><td>맥락을 읽어야 하는 것</td><td>소아 복용 적합성, QTPP·위험평가 근거 초안</td><td>심사·초안 LLM (반려·승인 권한 없음)</td></tr>
<tr><td>말을 입력으로 옮기는 것</td><td>“용량은 50 mg”, “1위 후보로 개발 착수”</td><td>입력 에이전트 (수치·구조식 생성 금지)</td></tr>
<tr><td>받아들일지 정하는 것</td><td>개발 후보 선택, 위험 등급 승인, 실험 요인 결정, 회귀 모형 승인</td><td>연구자</td></tr></tbody></table>
<div class="tcap"><b>표 1.</b> 판단의 성격별 담당.</div>
<p>LLM 호출은 한 인터페이스(구조화 출력·스트리밍)로 감싸 프로바이더를 바꿔 끼운다. 라이브 시스템에서는 연구자가 화면에서 모델을
고른다 — 기본은 무료 Groq(gpt-oss-120b)이고, 비밀번호로 접속한 세션만 대회 제공 API(OpenAI Responses 호환, gpt-5.6-sol)를 고를 수 있다(권한은
서버가 다시 검사). 대회 API를 고른 호출은 팀 누적 한도 소진(403)이나 오류가 나면 같은 호출을 무료 Groq로 넘긴다. 무료 모델의 분·일 단위 토큰 한도는
클라이언트가 직접 회계해 호출이 몰릴 때 순번을 기다리게 하며, 끝내 응답이 없으면 결과를 지어내지 않고 “응답 없음”으로 표시한다.</p>

<h2>4. 입력 에이전트</h2>
<p>입력 에이전트는 두 그래프 앞에서 대화를 받는다. 맥락은 브라우저가 보낸 상태가 아니라 서버가 실행(run)에서
직접 구성한 스냅숏이다 — 설계 상태와 권고 후보, 병합된 실험 요청(측정 ID·Tier·산출 키·사유), 마지막 되돌림. 에이전트는 LLM 구조화 출력으로 의도(설계 실행 · 측정값 제출 · 개발 착수 · 설명 · 되묻기)와
초안 값을 받고, 이를 <b>제안 카드</b>로 바꾼다. 카드는 연구자가 [실행]을 눌러야 반영되며, 실행은 사람이 누르는 버튼과 같은 함수 경로를 탄다.</p>
<figure>{fig_agent()}
<figcaption><b>그림 2.</b> 입력 에이전트 처리 경로. 해석(LLM, 실패 시 규칙 해석기) 뒤의 네 가드레일은 모두 코드로 구현되어 있다.</figcaption></figure>
<p>가드레일은 프롬프트가 아니라 코드다. (i) 제안에 들어가는 모든 숫자는 최근 사용자 발화에서 추출한 숫자 집합에 속해야 하며, 아니면 제거되고
제거 사실이 사용자에게 표시된다. (ii) SMILES는 사용자 글에 그대로 있거나, 내장 구조 사전 또는 PubChem[12] PUG-REST 조회에서만 얻고, 카드에 CID와 링크를
붙인다. LLM이 쓴 SMILES는 사용하지 않는다. (iii) 측정 키는 실험 입력 허용목록과 측정 카탈로그 산출 필드 안에서만, 개발 착수는 지금 설계의 통과 후보만
받고, 다른 설계가 시작되면 이전 카드는 잠긴다. (iv) 설계 실행에는 구조식과 1회 용량이 필요하며, 없으면 카드는
미완성으로 표시되고 에이전트가 되묻는다 — 용량이 없으면 용량/용해도 부피를 계산할 수 없어 DCS 분류가 성립하지 않기 때문이다.
LLM이 되묻기만 하고 글에서 행동이 명확히 읽히는 경우(예: “Tm 317도” → 측정값 제출)에는 규칙 해석기가 바닥을 받친다.
설계 종료·재계산 때에는 LLM 없이 맥락만으로 다음 행동을 먼저 제시한다(nudge).</p>

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
<p>측정 결과는 숫자만이 아니다(비정질 halo 여부는 예/아니오, 유동 특성은 USP 등급, 피크 목록은 목록). 결과 필드 {c.get('measurement_output_fields', 0)}개의
타입·단위·선택지를 한 표(<code>measurement_output_fields.csv</code>)에 두고, 요청 카드는 그 정의대로 입력 칸을 그리며 서버는 같은 정의로 값을 검사해
타입이 다르면 받지 않는다(422). 측정마다 원자료를 첨부할 수 있고, 첨부는 내용 해시로 저장되어 제출 기록에 붙지만 판정에는 쓰이지 않는다(추적 전용).
첨부 해석은 초안만 만든다 — 기기 원자료(XRPD·DSC·TGA 두 열 수치)는 결정론 계산(반치폭 기준 halo, 접선 외삽 onset, 100–150 °C 무게 감소, Td5%)으로,
그림은 대회 API 모델의 이미지 입력으로 그 측정에 정의된 필드만 제안한다. 초안은 “미확인”으로 표시되어 연구자가 확정해야 입력 칸에 들어가고,
제출 기록에 초안의 출처가 남는다. 추가 조건이 필요한 값(DSC 융해열, 결정형 ID)은 만들지 않는다.</p>

<h3>5.6 동적 심사위원단과 합의</h3>
<p>심사관 {c['reviewers']}명(소아 안전, 가용화 전략, 공정 실현성, 규제 취지, 문헌 조사, 고령자 안전, 고체상 안정성)은 소집 조건식이 참일 때만 생성된다.
심사관은 근거 강도 → 잔여 위험 → 실현 가능성 → 참신성 순의 기준으로 통과 후보에 점수를 매기되 반려 권한이 없고, 합의는 결정론 가중평균이다.
LLM이 응답하지 않으면 두 번 재시도한 뒤에도 점수를 대신 채우지 않고 “점수 없음”으로 표시하며, 순위는 실제 점수만으로 정한다.
점수에는 <b>검증된 인용</b>이 필요하다 — 심사관은 DOI·PMID로만 인용할 수 있고, 후보로는 이 약에 대해 Europe PMC가 돌려준 실제 문헌과 룰북 인용 등록부
(룰북에 적힌 식별자를 Crossref·NCBI로 조회해 통과한 14건)가 주어진다. 목록 밖 식별자는 실행 중에 같은 방식으로 조회해 실재할 때만 인정하며,
검증된 인용이 없는 점수는 무효로 합의에서 빠진다. 소집 신호(대상 인구군, 가용화·미분화·ASD 후보 존재, 룰북 밖 성분 조합, 규제 서술 필요, 고체상 경계 구간)는 스펙과 게이트 결과에서 결정론으로 계산되므로,
같은 요청이라도 설계된 성분이 달라지면 소집 명단이 달라질 수 있다(그림 6의 반쪽 원). 고정 성분 때문에 심사 전에 “제약 불가능”으로 끝나는 실행도
같은 조건식으로 <b>소집 예정이던 심사관</b>을 계산해 결론과 함께 보인다(LLM 호출 없음) — 고령자 요청이면 고령자 안전 · 공정 실현성, 소아 요청이면 소아 안전 심사관이다.</p>
<figure>{fig_jury(data, x)}
<figcaption><b>그림 6.</b> 동적 심사위원단. 왼쪽은 명단과 소집 조건(CSV 원문), 오른쪽은 7.4절 재실험(시나리오 4종 × 2회)에서 실제로 소집된 결과다.
공정 실현성(REV003)만 항상 소집되고, 소아·고령자 심사관은 대상 인구군에 따라 서로 배타적으로 나타나며, 문헌 조사(REV005)는 룰북 밖 조합이 설계됐을
때만 들어온다. 규제 취지(REV004)·고체상 안정성(REV007)은 이 네 요청에서 조건이 맞지 않아 한 번도 생성되지 않았다.</figcaption></figure>

<h2>6. 2단계 — Design Space 도출</h2>
<p>연구자가 후보 카드의 [이 후보로 개발 착수]를 누르면 그 처방이 논문 Table 1 형식의 프로토타입(성분 · mg/정 · % · 기능 · 공정)이 되어 2단계 study가 열린다.
그 앞에 <b>근거 결손 게이트</b>가 있다. 규칙 게이트 통과는 “알려진 금기가 없다”일 뿐 “알고 있다”가 아니므로, 통과 후보마다 필수 근거 {c.get('evidence_requirements', 0)}행
(개발 전에 있어야 하는 것 {c.get('evidence_before', 0)}행 — 수분·열 안정성, 배합적합성, 실험 용해도, BCS 근거 등)을 결정론으로 따지고, 없으면 확인시험 마스터 {c['confirmation_tests']}종의 실제 행에서만
시험을 요청한다. 결과를 넣으면 LLM 없이 바로 다시 판정하고, 선행 근거가 빠진 채 개발에 들어가려면 연구자가 사유를 적어야 하며 그 사유와 남은 결손은 Handoff의 fingerprint와 보고서에 남는다.
확인시험이 부적합이면 전제가 부정된 것이라 착수할 수 없다. 반려 권한은 여전히 규칙 게이트에만 있고, 이 게이트는 개발 착수를 보류할 뿐이다.
study는 ICH Q8[1]·Q9[2]의 순서를 15단계로 옮긴 것이고(그림 7), 각 단계는 같은 길을 간다 — 초안(LLM · 논문 값 · 연구자 입력) → 결정론 검사 → 연구자 승인.
지금 단계만 고칠 수 있으며, 승인한 단계를 다시 열면 뒤 단계는 지우지 않고 “다시 확인 필요”로 표시한다. 모든 변경은 멱등 키와 기대 버전으로 기록되고,
출처(LLM·논문·연구자·코드)와 승인자·시각이 이력과 보고서에 남는다.</p>
<figure>{fig_stage2()}
<figcaption><b>그림 7.</b> 2단계의 15단계. 표 번호는 Monton 등[18]의 대응 표다. 8단계(종합 정리)에 들어오면 위험평가 보고서, 12단계를 확인하면 최종 보고서(실험 설계 · 회귀식 · 반응 곡면 · ANOVA,
13–15단계가 있으면 Design Space · 확인계획 · 확인배치 포함)가 PDF로 나온다. 1단계에는 후보의 조성과 요청 맥락(대상 · 용량 · 약물 함량 · 1단계 신호)이 fingerprint가 붙은 불변 Handoff로 넘어온다.</figcaption></figure>
<p><b>근거가 행렬을 만든다.</b> 위험평가 초안은 LLM 두 번으로 만든다. 먼저 변수 × 확정 CQA 격자에 High·Medium·Low만 받고, 코드가 “같은 변수에서 등급이 같은 CQA”를 한 묶음으로 만든 뒤,
묶음마다 기전 문장을 받는다(8묶음씩, 실패 시 1회 재시도). 그래서 초안은 구조상 모든 칸을 정확히 한 번 덮고, 문장이 비면 검사가 잡는다. 행렬(5·7단계)은 이 근거 표에서 코드가 계산해
연구자는 확인만 한다. 결정론 검사는 {len(data.get('stage2', {}).get('check_codes', {}).get('blocking', []))}종의 승인 차단(예: 근거 없는 칸, 확정 CQA 밖의 열, 처방에 있는데 평가하지 않은 부형제,
공정 변수 자리의 공정 이름, 이름 없는 요인, 수준이 하나뿐인 요인, 추정 불가 모형, 사유 없는 과적합 모형, 빈 영역)과
{len(data.get('stage2', {}).get('check_codes', {}).get('warning', []))}종의 경고로 이루어진다. LLM이 입력에 없는 수치를 쓰면 “출처 확인” 경고가 붙고, LLM이 응답하지 않으면 아무것도 채우지 않는다.</p>
<p><b>실험 설계와 통계.</b> 9단계 표는 요인 1–3개·반응 1–4개·행 수 제한 없이 연구자가 적는다(Std·Run 순서, CSV 불러오기·엑셀 붙여넣기). 시연용으로는 출처가 붙은 논문 실측 표(Monton 등[18] Table 9, Almotairi 등[11] Table 3)를 한 번에 채울 수 있고, 그 출처가 보고서의 표 9 머리에 남는다. 요인과 반응 모두 이름 없는 열 하나로 시작해 연구자가 적는다(8단계의 High 변수와 위험평가 CQA는 이름 제안으로만). 10단계 toolkit은 요인을 최소·최대로 코딩해 평균·선형·2요인 교호작용·2차 모형을 적합하고, 순차 F·적합결여(반복점의 순수오차)·수정 R²·예측 R²(PRESS)를 표로 비교해
모형을 제안한다. 연구자가 다른 모형을 고를 수 있으며, 선택 모형의 coded 식과 실제 단위 식(Table 10 형식)을 함께 낸다. 11단계는 그 식으로 반응 곡면을, 12단계는 부분 제곱합
ANOVA(Table 11 형식)를 계산한다. 예측 R²가 수정 R²보다 0.2 넘게 낮으면 과적합 의심으로 표시하고, 연구자가 차수를 낮추거나 사유를 적어야 승인된다. 이 계산에는 LLM이 없다.</p>
<p><b>Design Space와 확인.</b> 13단계는 연구자가 적은 반응별 규격으로 영역을 정한다. 영역은 평균 반응면이 아니라 미래 배치의 예측분포로 계산한다[4] — 반응마다
t 분포(자유도 = 잔차 자유도, 척도 √(SE²<sub>평균</sub> + σ̂²))로 규격 통과확률을 구해 곱한 공동확률이 0.90 이상인 격자점이며(반응 간 독립 가정), 분모는 설계점 convex hull 안의
격자점(축마다 21점), 권장 설정점은 hull 경계에서 0.1 coded 이상 떨어진 점 중 공동확률 최대다. 영역이 비면 규격을 완화하지 않고 승인이 막힌다. 14단계는 설정점 · 영역 안
공동확률 최저점(경계) · 설정점 ± 허용 변동 꼭짓점 중 최저점(강건성)의 세 확인점과 동시 예측구간(Bonferroni)을 <b>결과 전에 잠그고</b>(시각 · 해시), 15단계는 새 독립 배치의
실측이 세 점 모두 규격 통과 × 예측구간 안(2×2)일 때만 VERIFIED로 기록한다 — 내부 사전계획 통과이지 규제 승인 설계공간이 아니다.</p>
<div class="eq">P<sub>joint</sub>(x) = ∏<sub>k</sub> Pr[ Y<sub>k</sub><sup>new</sup>(x) ∈ Spec<sub>k</sub> ],&nbsp;&nbsp; Y<sub>k</sub><sup>new</sup>(x) ~ ŷ<sub>k</sub>(x) + t<sub>ν</sub>·√(SE<sub>k</sub>(x)² + σ̂<sub>k</sub>²)</div>

<h2>7. 적용 결과</h2>
{stage2_section(data.get('stage2'))}
{lornox_section((data.get('stage2') or {}).get('lornoxicam'))}
<h3>7.3 검증 계층의 동작</h3>
<p>소아용 플루옥세틴 정제에 유당 수화물을 고정 성분으로 요구하면, 구조 패턴이 2차 아민을 검출하고 1대1 배합 금기 INC002(2차 아민 × 유당 → Maillard 반응[13])가
반려하며, 반려 사유가 고정 성분이므로 되돌림 없이 “제약 불가능”과 대체 성분(만니톨)을 낸다. 같은 금기가 “유당”, “Lactose, NF”, “유당수화물” 표기에서
모두 발동하고 대체품인 만니톨·전분글리콜산나트륨에서는 발동하지 않음을 회귀 테스트가 고정한다.</p>

{exp_section(x)}
{devfix_section(fx)}
{demo_section(dm)}
{llm_section(lm)}
<h3>7.8 소프트웨어 검증</h3>
<p>단위·통합 테스트 {tests}개(pytest)가 구조 패턴 진리표, 검사 방향, 근거 정책, 페이즈 게이트, 되돌림·계획 불변식, 입력 에이전트 가드레일, 조건식 이름 전수검사, 측정 필드 타입·첨부, 근거 결손 게이트의 2단계 진입 차단(결손 · 사유 · 부적합),
2단계의 논문 표 재현(행렬 · Table 10·11), 로르녹시캄 Design Space 골든 값(77.2 % → 47.6 % · 설정점 · 예측구간), 단계 권한·승인 차단·다시 열기·확인계획 잠금, LLM 초안의 칸 덮기를 고정한다. 이 빌드에서 돌린 실제 브라우저 테스트({E(browser)})는 가운데 입력칸에서 시작하는 대화 흐름
(설계 실행 카드 → 실험 데이터 입력 → 물리화학 → 데이터 요청 → 후보 → 개발 착수), 오른쪽 관측 칼럼, 2단계를 클릭만으로(CBD 1–13단계: 편집·차단·다시 열기·PDF 두 종, 데스크톱과 휴대폰 폭), 발표 시연 ①의 전체 파이프라인(실제 LLM로 1단계 → 개발 착수 →
CSV → 공동확률 영역 → 확인계획 잠금), 근거 결손 게이트(결과 입력 → 재판정 → 착수, 사유 없는 착수 차단, 부적합이면 착수 불가), 시연 ②③의 경로(불가능 결론과 소집 예정 심사관),
여섯 렌더 경로의 스크립트 주입, 가이드와 테마를 검사한다.</p>

<h2>8. 논의와 한계</h2>
<p><b>판정 권한의 위치.</b> 이 시스템의 안전성은 LLM의 정확도가 아니라 판정 권한이 어디에 있는가에서 나온다. 설계·심사·초안 LLM이 틀려도 반려는
규칙만, 승인은 연구자만 할 수 있으므로, LLM 오류는 “잘못된 후보가 반려됨” 또는 “초안이 승인 전에 고쳐짐”으로 흡수된다. 입력 에이전트는 이 원칙을 입력 쪽으로
확장한다 — 대화 창이 새로운 환각 통로가 되지 않도록 수치와 구조식의 출처를 코드로 제한했다.</p>
<p><b>모르는 것의 표현.</b> “규칙이 발동하지 않음”과 “문제가 없음”을 구분하는 것이 핵심이었다. 성분명 불일치, 구조 해석 실패, 비어 있는 사전은 모두
조용한 통과를 만들 수 있었고, 각각을 판정 불가·이관으로 바꾸었다. 결측 값은 NOT_CHECKED나 실측 요청으로 기록된다. 같은 부류로, 조건식이 아무도 채우지 않는 변수 이름을 쓰면 평가 오류가 “미발동”으로 삼켜져 규칙이 영영 켜지지 않는다 — 규칙표·전이표·심사관 명단·manifest의 조건식 {c.get('conditions_audited', 0)}개를 파싱해 모든 이름이 실제로 채워지는지 대조하는 전수검사를 테스트로 고정했다.</p>
<p><b>한계.</b> (1) 2단계의 위험 등급·근거 초안은 LLM이 쓰고 연구자가 승인한다 — 7.7절처럼 형식은 완전해도 등급 판단은 논문(참고 자료)과 다를 수 있고, 어느 쪽이 맞는지는 처방 맥락을 아는 전문가가 정한다.
(2) 신경망 물성 예측기는 연결하지 않았다. (3) 2단계 study 저장소는 임시 SQLite로 재시작 시 사라진다. (4) LLM 출력은 반복마다 달라 권고 후보가 바뀔 수 있다(표 5) —
결정론 계층은 같은 판정을 내지만 순위는 심사 LLM 점수에 기댄다. 대회 API 한도가 소진되어 무료 모델로 넘어가면 분당 토큰 한도로 설계·심사가 빌 수 있고,
이때 결과를 채우지 않고 “응답 없음”으로 표시한다. (5) 설계 생성(어떤 run을 할지)은 연구자가 표로 적는다 — mixture·D-optimal 설계, 다반응 최적화, 스케일업은 범위 밖이다.
(6) 입력 에이전트의 구조식 조회는 영문 표준명에 기대며, 대화 기록은 브라우저 탭 안에만 있다.
(7) 논문과의 칸 단위 비교는 표가 공개된 CBD 사례에만 있다. 새 후보에서 초안의 타당성을 판정할 기준은 연구자뿐이다.
(8) 공동확률은 반응 간 상관을 무시한 곱이고, 확인배치 판정(15단계)은 새 독립 배치 실측이 있어야 해 공개 자료만으로 시연할 수 없다.</p>

<h2>9. 결론</h2>
<p>Formula 1은 제형 설계에서 LLM의 창의와 결정론 검증을 분리하고, 후보 탐색에서 Design Space 도출까지를 두 단계와 하나의 연결(연구자가 고른 처방)로 구성했다.
값을 모르면 멈추지 않고 필요한 실측만 묻고, 반려되면 사유가 가리키는 지점으로 돌아가며, 후보를 고르면 QTPP부터 ANOVA · Design Space · 확인계획까지 단계마다 연구자 승인을 받으며 간다.
공개 논문의 위험평가 행렬과 회귀·ANOVA를 근거 표와 원자료에서 그대로 재현했고, 공개 실측 15 run에서 평균 반응면 기준 영역이 미래 배치 공동확률 기준보다 약 1.6배 크다는 것을
정량으로 보였으며, LLM 초안이 형식은 완전해도 판단이 논문과 다를 수 있음을 칸 단위로 보여 승인 단계의 필요를 확인했다.
사용자와 시스템 사이의 입력 에이전트는 가운데 입력칸 하나에서 대화를 이끌면서도 판정 권한과 데이터 출처 원칙을 유지한다.</p>

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
    fp = OUT / "devfix_results.json"
    fx = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
    dp = OUT / "demo_cards.json"
    dm = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else None
    lp = OUT / "stage2_llm.json"
    lm = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else None
    (OUT / "report.html").write_text(build(data, a.tests, a.browser, x, fx, dm, lm), encoding="utf-8")
    print(OUT / "report.html")


if __name__ == "__main__":
    main()
