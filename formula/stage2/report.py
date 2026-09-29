"""2단계 보고서 PDF — 논문 표 형식(Table 1·3·4·5·6·7·8 · 9·10·11 · Figure 1).

- risk_report: 8단계 산출물 — 프로토타입부터 위험평가 종합 정리까지(제형 DoE의 출발점).
- final_report: 12단계(ANOVA) 뒤 — 위 내용 + 실험 설계 표 · 회귀식 · 반응 곡면(화면에서 받은 그림) · ANOVA, 있으면 Design Space · 확인계획 · 확인배치.
승인된 단계만 싣고, 표마다 출처(LLM 초안 · 논문 값 · 연구자 수정 · 코드 계산)와 승인 기록을 붙인다. 폰트는 나눔고딕(OFL, fonts/OFL.txt).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fpdf import FPDF
from fpdf.fonts import FontFace

from formula.stage2.model import STEPS, TITLE

FONTS = Path(__file__).resolve().parent / "fonts"
SRC_KO = {"upstream": "1단계 후보 처방", "llm": "LLM 초안", "paper": "논문 값", "user": "연구자 입력", "code": "코드 계산",
          "llm+user": "LLM 초안 → 연구자 수정", "paper+user": "논문 값 → 연구자 수정", "upstream+user": "1단계 처방 → 연구자 수정",
          "code+user": "코드 계산 → 연구자 선택"}
KIND = {"material": "원료 물성", "formulation": "Formulation variables", "process": "Process variable"}


class _PDF(FPDF):
    def __init__(self, title: str, kind: str):
        super().__init__(format="A4")
        self.doc_title, self.kind = title, kind
        self.add_font("NG", "", str(FONTS / "NanumGothic-Regular.ttf"))
        self.add_font("NG", "B", str(FONTS / "NanumGothic-Bold.ttf"))
        self.set_auto_page_break(True, margin=16)
        self.set_margins(15, 15, 15)

    def normalize_text(self, text):
        # 나눔고딕에 없는 수학 기호 −(U+2212)를 모든 출력 경로(cell · multi_cell · 표 · 머리말)에서 '-'로
        return super().normalize_text(str(text).replace("\u2212", "-"))

    def header(self):
        if self.page_no() > 1:
            self.set_font("NG", "", 7.5)
            self.set_text_color(110)
            self.cell(0, 5, f"{self.kind} — {self.doc_title}", align="L")
            self.ln(7)
            self.set_text_color(0)

    def footer(self):
        self.set_y(-12)
        self.set_font("NG", "", 7.5)
        self.set_text_color(110)
        self.cell(0, 5, f"{self.page_no()} · Formula 1 · 연구자 승인 기록이 붙은 개발 초기 문서(규제 제출 문서 아님)", align="C")
        self.set_text_color(0)


def _h(pdf, text, size=11.5):
    pdf.set_font("NG", "B", size)
    pdf.multi_cell(0, 6.5, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _p(pdf, text, size=9):
    pdf.set_font("NG", "", size)
    pdf.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def _meta(pdf, st, step):
    s = st["steps"][step]
    ap = [a for a in st["approvals"] if a["step"] == step and a["version"] == s["version"]]
    pdf.set_font("NG", "", 7.5)
    pdf.set_text_color(90)
    who = f"승인 {ap[-1]['by']} · {ap[-1]['at'][:16].replace('T', ' ')} UTC" if ap else "미승인"
    llm = f" · {s['llm']['provider']}" if s.get("llm") and s["llm"].get("provider") and "llm" in (s["source"] or "") else ""
    src = SRC_KO.get(s["source"], s["source"])
    if (st.get("origin") or {}).get("kind") == "cbd_paper" and str(s["source"] or "").startswith("upstream"):
        src = src.replace("1단계 후보 처방", "논문 Table 1").replace("1단계 처방", "논문 Table 1")     # 논문 프로토타입으로 시작한 study
    paper = (s.get("data") or {}).get("paper") if isinstance(s.get("data"), dict) else None
    if paper:                                         # 9단계 논문 실측값 채우기 — 어느 논문의 몇 번 표인지
        src += f" — {paper.get('citation')} {paper.get('locator') or ''}".rstrip()
    pdf.multi_cell(0, 4, f"출처: {src}{llm} · v{s['version']} · {who}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(2)


def _table(pdf, head, rows, widths, size=7.8, align=None, group=None):
    pdf.set_font("NG", "", size)
    hs = FontFace(emphasis="BOLD", fill_color=(242, 244, 246))
    with pdf.table(col_widths=widths, width=sum(widths), headings_style=hs, line_height=size * 0.52, num_heading_rows=2 if group else 1,
                   text_align=align or "LEFT", borders_layout="SINGLE_TOP_LINE", padding=1.2) as t:
        if group:
            r = t.row()
            for text, span in group:
                r.cell(text, colspan=span, align="CENTER")
        r = t.row()
        for h in head:
            r.cell(h)
        for row in rows:
            r = t.row()
            for c in row:
                if isinstance(c, dict):
                    r.cell(_safe(c.get("text", "")), rowspan=c.get("rowspan", 1), colspan=c.get("colspan", 1))
                else:
                    r.cell(_safe(c))
    pdf.ln(3)


def _safe(v) -> str:
    """나눔고딕에 없는 글자(수학 기호 −)를 대체한다."""
    return "" if v is None else str(v).replace("\u2212", "-")


def _n(v, d=4):
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        if isinstance(v, float) and abs(v) and (abs(v) < 1e-3 or abs(v) >= 1e6):
            return f"{v:.3e}"
        return f"{v:.{d}f}" if isinstance(v, float) else str(v)
    return str(v)


def _g(v):
    return "" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))


def _cover(pdf, st, kind):
    pdf.add_page()
    pdf.set_font("NG", "B", 17)
    pdf.multi_cell(0, 9, kind, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NG", "", 11)
    pdf.multi_cell(0, 6.5, st["title"], align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NG", "", 8.5)
    pdf.set_text_color(90)
    src = st.get("source") or {}
    pdf.multi_cell(0, 5, f"study {st['study_id']} · 작성 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · 원천: "
                         f"{src.get('citation') or src.get('candidate_ref') or src.get('locator') or ''}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(4)


def _risk_sections(pdf, st):
    s = st["steps"]
    rec = s["recommend"]["data"] or {}
    _h(pdf, "요약 — 제형 DoE의 출발점")
    _p(pdf, "제형·공정 변수 위험평가(표 7·8)에서 하나 이상의 CQA에 High로 평가된 변수다. 실험 설계(요인)는 이 정리를 보고 연구자가 정한다. "
            "Medium만 있는 변수는 관리·모니터링 대상이고, 원료 물성의 High 항목(표 5·6)은 원료 규격·관리로 다룬다.")
    _table(pdf, ["DoE 변수 후보(High인 제형·공정 변수)", "구분", "High인 CQA", "Medium인 CQA"],
           [[c["variable"], "공정" if c.get("kind") == "process" else "제형", ", ".join(c["high"]) or "—", ", ".join(c["medium"]) or "—"]
            for c in rec.get("candidates") or []] or [["(없음)", "", "", ""]], [56, 14, 62, 48], 7.6)
    if rec.get("watch"):
        _table(pdf, ["Medium만 있는 변수(관리·모니터링)", "Medium인 CQA"],
               [[x["variable"], ", ".join(x["medium"]) or "—"] for x in rec["watch"]], [70, 110])
    if rec.get("material_controls"):
        _table(pdf, ["원료 관리 대상 물성", "High인 CQA", "Medium인 CQA"],
               [[x["variable"], ", ".join(x["high"]) or "—", ", ".join(x["medium"]) or "—"] for x in rec["material_controls"]], [55, 75, 50])
    p = s["prototype"]["data"]
    _h(pdf, "표 1. 프로토타입 처방")
    _meta(pdf, st, "prototype")
    ings = p.get("ingredients", [])
    rows = [[i["name"], _g(i.get("mg")), _g(i.get("pct")), i.get("function") or i.get("role")] for i in ings]
    rows.append(["Total", _g(round(sum(i.get("mg") or 0 for i in ings), 3)), _g(round(sum(i.get("pct") or 0 for i in ings), 3)), ""])
    _table(pdf, ["Ingredients", "Amount per tablet (mg)", "Percentage (%)", "Function"], rows, [55, 38, 32, 55])
    h = (st.get("source") or {}).get("handoff") or {}
    if h:
        ev = h.get("evidence") or {}
        _p(pdf, f"1단계 Handoff(불변, fingerprint {h.get('fingerprint')}): 후보 {h.get('candidate_id')} · {h.get('strategy') or ''} · 요청 “{h.get('request') or ''}” · "
                f"대상 {h.get('target_population') or '—'} · 1회 용량 {_g(h.get('dose_mg')) + ' mg' if h.get('dose_mg') is not None else '—'} · "
                f"약물 함량 {_g(h.get('drug_loading_pct')) + ' %' if h.get('drug_loading_pct') is not None else '—'}.", 8)
        if ev:
            if ev.get("open"):
                _p(pdf, "근거 결손 게이트: 결손 " + str(len(ev["open"])) + "건(" + ", ".join(f"{g['label']} {g['test_id']}" for g in ev["open"])
                   + f") — 결과 없이 진행, 연구자 사유: {ev.get('waiver') or ''}", 8)
            else:
                _p(pdf, "근거 결손 게이트: 선행 확인시험 근거 충족.", 8)
    _h(pdf, "표 3. QTPP")
    _meta(pdf, st, "qtpp")
    rows, prev = [], None
    for it in s["qtpp"]["data"]["items"]:
        rows.append(["" if it["element"] == prev else it["element"], it.get("sub_element") or "", it["target"], it.get("justification") or ""])
        prev = it["element"]
    _table(pdf, ["QTPP elements", "", "Target", "Justification"], rows, [30, 26, 64, 60], 7.4)
    _h(pdf, "표 4. CQA")
    _meta(pdf, st, "cqa")
    _table(pdf, ["Quality attributes", "Target", "Is this a CQA?", "Justification", "위험평가"],
           [[(x.get("category") + " — " if x.get("category") else "") + x["attribute"], x["target"], "Yes" if x["is_cqa"] else "No", x["justification"],
             "포함" if x.get("in_risk_assessment") else (x.get("exclusion_reason") or "—")] for x in s["cqa"]["data"]["items"]], [36, 38, 16, 62, 28], 7.2)

    def matrix(step, title):
        m = s[step]["data"]
        pdf.add_page(orientation="L")
        _h(pdf, title)
        _meta(pdf, st, step)
        rank = {"material": 0, "formulation": 1, "process": 2}
        cols = sorted(range(len(m["variables"])), key=lambda j: (rank.get(m["variables"][j].get("kind"), 1), j))
        n = len(cols)
        w0 = 62
        wv = min(30, (267 - w0) / max(n, 1))
        grp, api = [("", 1)], (s["prototype"]["data"] or {}).get("api") or "API"
        for kind, gl in (("material", f"{api} raw material attributes"), ("formulation", "Formulation variables"), ("process", "Process variable")):
            k = sum(1 for j in cols if m["variables"][j].get("kind") == kind)
            if k:
                grp.append((gl, k))
        _table(pdf, ["Product CQAs"] + [m["variables"][j]["name"] for j in cols],
               [[cq] + [m["levels"][i][j] or "—" for j in cols] for i, cq in enumerate(m["cqas"])], [w0] + [wv] * n, 8,
               align=["LEFT"] + ["CENTER"] * n, group=grp)

    def just(step, title):
        pdf.add_page(orientation="P")
        _h(pdf, title)
        _meta(pdf, st, step)
        rows: List[List[Any]] = []
        order: Dict[str, List[Dict[str, Any]]] = {}
        for it in s[step]["data"]["items"]:
            order.setdefault(it["variable"], []).append(it)
        for var, its in order.items():
            for k, it in enumerate(its):
                rows.append(([{"text": var, "rowspan": len(its)}] if k == 0 else []) + ["\n".join(it["cqas"]), f"{it['text']} ({it['level']})"])
        _table(pdf, ["Variables", "Product CQAs", "Justification"], rows, [38, 40, 102], 7.4)

    matrix("rm_matrix", "표 5. 원료 물성 초기 위험평가")
    just("rm_just", "표 6. 원료 물성 초기 위험평가의 근거")
    matrix("fp_matrix", "표 7. 제형·공정 변수 초기 위험평가")
    just("fp_just", "표 8. 제형·공정 변수 초기 위험평가의 근거")


def risk_report(st: Dict[str, Any]) -> bytes:
    pdf = _PDF(st["title"], "초기 위험평가 보고서")
    _cover(pdf, st, "초기 위험평가 보고서")
    _risk_sections(pdf, st)
    return bytes(pdf.output())


def final_report(st: Dict[str, Any], images: Optional[Dict[str, bytes]] = None) -> bytes:
    pdf = _PDF(st["title"], "Design Space 도출 보고서")
    _cover(pdf, st, "Design Space 도출 보고서")
    _risk_sections(pdf, st)
    s = st["steps"]
    d = s["design"]["data"]
    pdf.add_page(orientation="L")
    _h(pdf, "표 9. 실험 설계와 run별 반응")
    _meta(pdf, st, "design")
    fh = [f"{f['name']}" + (f" ({f['unit']})" if f.get("unit") else "") for f in d["factors"]]
    rh = [f"{r['name']}" + (f" ({r['unit']})" if r.get("unit") else "") for r in d["responses"]]
    grp = [("", 2), ("Factors", len(fh)), ("Responses", len(rh))]
    n = 2 + len(fh) + len(rh)
    _table(pdf, ["Standard order", "Run order"] + fh + rh,
           [[_g(r.get("std")), _g(r.get("run"))] + [_g(v) for v in r["x"]] + [_g(v) for v in r["y"]] for r in d["rows"]],
           [267 / n] * n, 7.8, align=["CENTER"] * n, group=grp)
    reg = s["regression"]["data"]
    pdf.add_page(orientation="L")
    _h(pdf, "표 10. 반응별 회귀식(coded · actual)")
    _meta(pdf, st, "regression")
    names = "; ".join(f"X{i + 1} = {f['name']}" + (f" ({f['unit']})" if f.get("unit") else "") + f" [{_g(f['low'])}–{_g(f['high'])}]"
                      for i, f in enumerate(reg["factors"]))
    ok = lambda r: r.get("status", "SELECTED") == "SELECTED" and not r.get("aliased")   # noqa: E731
    _table(pdf, ["Responses", "모형", "Coded equations", "Actual equations"],
           [[r["response"], r["family"] + ("" if r["family"] == r["suggested"] else f" (제안 {r['suggested']})"),
             r.get("coded_eq", "추정 불가") if ok(r) else ("요인으로 설명되지 않음 — 검증 게이트 불합격" if r["family"] == "Mean" or not r.get("coded_eq")
                                                         else f"[게이트 불합격 · 참고] {r['coded_eq']}"),
             r.get("actual_eq", "") if ok(r) else (f"관측 {_g(round((r.get('observed') or {}).get('min', 0), 4))}–{_g(round((r.get('observed') or {}).get('max', 0), 4))}"
                                                  if r["family"] == "Mean" or not r.get("actual_eq") else f"[참고] {r['actual_eq']}")]
            for r in reg["responses"]], [30, 26, 105, 106], 7.6)
    _p(pdf, f"요인: {names}. coded x = (X − 중앙) / 반폭(표의 최솟값·최댓값 기준). 모형 선택: 후보(Mean · Linear · 2FI · Pure quadratic · Quadratic · "
            "Reduced quadratic)를 AICc로 줄 세우고(최소 + 2 이내면 항 수가 적은 쪽 먼저) 검증 게이트(모형 p < 0.05 · 적합결여 p ≥ 0.05 · "
            "조정 R² − 예측 R² ≤ 0.2 · 예측 R² > 0)를 처음 통과한 모형. 평균 모형까지 내려가거나 연구자·논문이 고른 모형이 게이트를 못 넘으면 "
            "그 반응은 영역·ANOVA에 쓰지 않고, 곡면에는 게이트 통과 반응이 하나라도 있을 때 참고로만 그린다.", 8)
    gate_txt = lambda row: ("통과" if (row.get("gate") or {}).get("passed") else ("—" if row["model"] == "Mean" else "불합격"))   # noqa: E731
    _table(pdf, ["Responses", "모형", "항", "모형 p", "적합결여 p", "조정 R²", "예측 R²", "AICc", "게이트", "선택"],
           [[r["response"], row["model"], str(row["n_terms"]), _n(row.get("model_p")), _n(row.get("lof_p")), _n(row.get("adj_r2")), _n(row.get("pred_r2")),
             _n(row.get("aicc")), gate_txt(row), " · ".join(x for x in ("선택" if row["model"] == r["family"] else "", "제안" if row.get("suggested") else "") if x)]
            for r in reg["responses"] for row in r["summary"]["rows"]], [30, 30, 12, 24, 26, 24, 24, 26, 20, 26], 7.2,
           align=["LEFT", "LEFT"] + ["CENTER"] * 8)
    if images:
        pdf.add_page(orientation="L")
        _h(pdf, "그림 1. 반응 곡면")
        _p(pdf, "10단계에서 선택한 모형의 반응 곡면(화면에서 그린 그림) — 게이트 통과 반응이 하나라도 있으면 모든 반응을 그리며, 불합격 반응(표 10의 "
                "[참고])은 참고용이다. 빨간 점은 관측값이 곡면 위, 연분홍은 아래, 바닥 점선은 설계점이 받치는 영역.", 8)
        keys = sorted(images)
        w, gap = 84, 4
        x0, y0 = pdf.l_margin, pdf.get_y()
        for n_, k in enumerate(keys):
            col, row = n_ % 3, n_ // 3
            if row and col == 0 and y0 + (row + 1) * (w * 0.78 + 8) > 190:
                pdf.add_page(orientation="L")
                y0 = pdf.get_y() - row * (w * 0.78 + 8)
            x, y = x0 + col * (w + gap), y0 + row * (w * 0.78 + 8)
            pdf.image(io.BytesIO(images[k]), x=x, y=y, w=w)
            pdf.set_xy(x, y + w * 0.74)
            pdf.set_font("NG", "", 7)
            pdf.cell(w, 4, k, align="C")
        pdf.set_y(y0 + ((len(keys) + 2) // 3) * (w * 0.78 + 8))
    an = s["anova"]["data"]
    pdf.add_page(orientation="P")
    _h(pdf, "표 11. 반응별 ANOVA")
    _meta(pdf, st, "anova")
    rows = []
    for r in an["responses"]:
        if r.get("unexplained"):
            o = r.get("observed") or {}
            rows.append([{"text": f"{r['response']} — 요인으로 설명되지 않음(검증 게이트 불합격: {'; '.join(r.get('gate_why') or []) or '평균 모형'}) · "
                                  f"관측 {_g(round(o.get('min', 0), 4))}–{_g(round(o.get('max', 0), 4))}", "colspan": 6}])
            continue
        if r.get("aliased"):
            continue
        rows.append([{"text": f"{r['response']} — {r['family']}", "colspan": 6}])
        for row in r["rows"]:
            sig = "*" if row.get("p") is not None and row["p"] < 0.05 and row["source"] not in ("Lack of fit",) else ""
            rows.append([("   " if row.get("level") else "") + row["source"], _n(row.get("ss")), str(row["df"]), _n(row.get("ms")),
                         _n(row.get("f")), (_n(row.get("p")) + sig) if row.get("p") is not None else ""])
        rows.append([{"text": f"R² {r['r2']:.4f} · 수정 R² {r['adj_r2']:.4f} · 예측 R² {r['pred_r2']:.4f} · 표준편차 {r['std_dev']:.4g} · 평균 {r['mean']:.4g}",
                      "colspan": 6}])
    _table(pdf, ["Source", "Sum of squares", "df", "Mean square", "F-value", "p-value"], rows, [40, 30, 14, 30, 30, 36], 7.6,
           align=["LEFT", "RIGHT", "CENTER", "RIGHT", "RIGHT", "RIGHT"])
    _p(pdf, "* p < 0.05. 항의 제곱합은 부분(Type III) 제곱합, 잔차 = 적합결여 + 순수오차(같은 설정의 반복 run).", 8)
    _space_sections(pdf, st)
    return bytes(pdf.output())


ROLE_KO = {"SETPOINT": "설정점", "BOUNDARY": "경계점", "ROBUSTNESS": "강건성(최악 변동)", "REFERENCE": "참고 배치"}
VERDICT_KO = {"VERIFIED": "VERIFIED — 내부 사전계획 통과(규제 승인 설계공간 아님)", "INVALIDATED": "영역 무효화 — 진단 필요",
              "INCOMPLETE": "실측값 미완"}


def _space_sections(pdf, st: Dict[str, Any]) -> None:
    s = st["steps"]
    sd = s["space"]["data"] if s.get("space") else None
    if not sd or not sd.get("region"):
        return
    r = sd["region"]
    pdf.add_page(orientation="L")
    _h(pdf, "Design Space — Overlay plot(평균 예측 기준 영역 · control space · 최적점)")
    _meta(pdf, st, "space")
    try:
        from formula.stage2 import space as SPc
        png = SPc.render(s["design"]["data"], s["regression"]["data"], [x for x in sd["specs"] if x.get("op") in SPc.OPS and
                         all(x.get(k) is not None for k in {"LE": ("upper",), "GE": ("lower",), "BETWEEN": ("lower", "upper")}[x["op"]])],
                         fixed=sd.get("slice"), fmt="png", caption=True, dpi=170)
        pdf.image(io.BytesIO(png), x=pdf.l_margin, w=pdf.w - pdf.l_margin - pdf.r_margin)
    except Exception as exc:   # noqa: BLE001 — 그림이 실패해도 표는 남긴다
        _p(pdf, f"(Overlay plot을 그리지 못했습니다: {str(exc)[:120]})", 8)
    pdf.add_page(orientation="P")
    _table(pdf, ["반응", "목표", "근거"], [[x["response"] + (f" ({x['unit']})" if x.get("unit") else ""),
                                          {"LE": f"≤ {_g(x.get('upper'))}", "GE": f"≥ {_g(x.get('lower'))}",
                                           "BETWEEN": f"{_g(x.get('lower'))}–{_g(x.get('upper'))}"}.get(x["op"], "목표 없음"),
                                          x.get("basis") or ""] for x in sd["specs"]], [45, 40, 95], 8)
    ap = r.get("approval") or {}
    op = r.get("optimum") or {}
    sl = r.get("slice") or {}
    rows = [["판정", ("승인 가능 — " if ap.get("approvable") else "승인 불가 — ") + (ap.get("reason") or "")],
            ["영역 기준", "게이트 통과 반응의 평균 예측이 모든 목표 만족(논문과 같은 기준) · 실험 범위(설계점 convex hull) 안"],
            ["게이트 통과 반응", ", ".join(r.get("gate_passed") or []) or "없음"]]
    if sl:
        rows.append(["단면 고정 요인", f"{sl.get('name')} = " + " · ".join(_g(v) for v in sl.get("levels_actual") or []) + (" (자동: 효과가 가장 작은 요인)" if sl.get("auto") else "")])
    rows.append(["단면별 평균 기준 영역", " · ".join(f"{_g(x.get('level_actual')) if x.get('level_actual') is not None else '전체'}: {100 * x['ds_fraction']:.1f} %"
                                           for x in r.get("slices") or [])])
    if r.get("control_space"):
        rows.append(["control space", " · ".join(f"{k} {_g(v[0])}–{_g(v[1])}" if isinstance(v, list) else f"{k} {_g(v)}" for k, v in r["control_space"].items())])
    if op:
        rows.append(["최적 처방", " · ".join(f"{k} {_g(v)}" for k, v in op["actual"].items()) + f" (새 배치 통과확률 {op['joint']:.3f})"])
    aux = r.get("aux") or {}
    rows.append(["보조: 새 배치 통과확률", f"최대 {aux.get('max_joint', 0):.3f} · 0.9 이상 {100 * aux.get('joint_ge_09_fraction', 0):.1f} % — 판정에 쓰지 않음"])
    _table(pdf, ["지표", "값"], rows, [48, 132], 8.0)
    for nt in r.get("unexplained") or []:
        _p(pdf, ("주의 · " if nt.get("level") == "warn" else "· ") + nt["text"], 8)
    _p(pdf, "control space = 노랑 ∩ 실험 범위 격자(축마다 41점)에 들어가는 가장 넓은 축 정렬 직사각형(가로·세로 3칸 이상). 최적 처방 = control space 안에서 "
            "실험 범위 경계로부터 0.1 coded 이상 떨어진 점 중 새 배치가 모든 목표를 만족할 확률(반응별 t 예측분포 통과확률의 곱, 독립 가정)이 가장 큰 점. "
            "승인 불가는 평균 기준 영역이 없거나 control space를 만들 수 없을 때뿐이다.", 8)
    vp = (s.get("vplan") or {}).get("data") or {}
    plan = vp.get("plan") or {}
    if plan.get("points"):
        _h(pdf, "확인계획" + (f" — {vp['locked_at'][:16].replace('T', ' ')} UTC 잠금 · {vp.get('plan_hash')}" if vp.get("locked_at") else " (미잠금)"), 10.5)
        pol = plan.get("pi_policy") or {}
        rows = []
        for pt in plan["points"]:
            for n, pr in pt["predicted"].items():
                rows.append([ROLE_KO.get(pt["role"], pt["role"]) if n == next(iter(pt["predicted"])) else "",
                             " · ".join(f"{_g(v)}" for v in pt["settings"].values()) if n == next(iter(pt["predicted"])) else "",
                             n + (" †" if pr.get("unexplained") else ""), pr["spec"], _g(round(pr["mean"], 3)) if pr.get("mean") is not None else "",
                             (f"{_g(round(pr['pi_lower'], 3))}–{_g(round(pr['pi_upper'], 3))}" + (" *" if pr.get("pi_truncated") else "")) if pr.get("pi_lower") is not None else ""])
        _table(pdf, ["확인점", "설정(" + " · ".join((r.get("optimum") or {}).get("actual", {}).keys()) + ")", "반응", "규격", "예측 평균", "예측구간"],
               rows, [26, 40, 30, 26, 26, 32], 7.6)
        _p(pdf, f"예측구간: {pol.get('comparisons')}개 비교(필수 확인점 3 × 게이트 통과 반응)의 Bonferroni 동시구간, 개별 수준 {100 * pol.get('per_comparison_level', 0):.2f} %. "
                "* 하한이 음수라 0에서 자름. † 요인으로 설명되지 않는 반응 — 목표만 판정(구간은 관측 평균의 95 % 예측구간, 참고). "
                "참고 배치는 결과가 이미 공개돼 승격·무효화 근거로 쓰지 않는다.", 8)
    vd = (s.get("verify") or {}).get("data") or {}
    j = vd.get("judgement") or {}
    if j.get("rows") and any(x.get("observed") is not None for x in j["rows"]):
        _h(pdf, "확인배치 판정 — 규격 통과 × 예측구간", 10.5)
        _table(pdf, ["확인점", "반응", "실측", "예측구간", "규격", "판정"],
               [[ROLE_KO.get(x["role"], x["role"]), x["response"], _g(x.get("observed")), f"{_g(round(x['pi'][0], 3))}–{_g(round(x['pi'][1], 3))}" if x.get("pi") else "",
                 "통과" if x.get("spec_pass") else ("실패" if x.get("spec_pass") is False else ""), {"PASS_IN": "통과 · 구간 안", "PASS_OUT": "통과 · 구간 밖",
                 "FAIL_IN": "실패 · 구간 안", "FAIL_OUT": "실패 · 구간 밖", "PASS_NA": "통과(목표만)", "FAIL_NA": "실패(목표만)"}.get(x.get("cell"), "")]
                for x in j["rows"]], [30, 30, 24, 34, 20, 42], 7.8)
        _p(pdf, f"결론: {VERDICT_KO.get(j.get('verdict'), j.get('verdict'))}. " + " ".join(j.get("advice") or []), 8.5)


__all__ = ["risk_report", "final_report", "STEPS", "TITLE"]
