"""2단계 보고서 PDF — 논문 표 형식(Table 1·3·4·5·6·7·8 · 9·10·11 · Figure 1).

- risk_report: 8단계 산출물 — 프로토타입부터 위험평가·DoE 변수까지(제형 DoE의 출발점).
- final_report: 12단계 산출물 — 위 내용 + 실험 설계 표 · 회귀식 · 반응 곡면(화면에서 받은 그림) · ANOVA.
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
    _p(pdf, "제형·공정 변수 위험평가(표 7·8)에서 CQA에 High로 평가된 변수가 DoE 후보이고, 연구자가 그중 DoE로 볼 변수를 골랐다(최대 4개). "
            "원료 물성의 High 항목(표 5·6)은 원료 규격·관리로 다룬다.")
    recd = {r["variable"]: r["reason"] for r in rec.get("recommended") or []}
    _table(pdf, ["DoE 변수(연구자 선택)", "High인 CQA", "Medium인 CQA", "추천 근거"],
           [[c["variable"], ", ".join(c["high"]) or "—", ", ".join(c["medium"]) or "—", recd.get(c["variable"], "")]
            for c in rec.get("candidates") or [] if c["variable"] in (rec.get("selected") or [])] or [["(없음)", "", "", ""]], [38, 45, 32, 65], 7.6)
    if rec.get("note"):
        _p(pdf, f"추천 메모: {rec['note']}", 8)
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
    _table(pdf, ["Responses", "모형", "Coded equations", "Actual equations"],
           [[r["response"], r["family"] + ("" if r["family"] == r["suggested"] else f" (제안 {r['suggested']})"), r.get("coded_eq", "추정 불가"),
             r.get("actual_eq", "")] for r in reg["responses"]], [30, 26, 105, 106], 7.6)
    _p(pdf, f"요인: {names}. coded x = (X − 중앙) / 반폭(표의 최솟값·최댓값 기준). 모형 제안: 순차 F 검정이 유의한(p < 0.05) 가장 높은 차수.", 8)
    _table(pdf, ["Responses", "모형", "순차 p", "적합결여 p", "R²", "수정 R²", "예측 R²", "선택"],
           [[r["response"], row["model"], _n(row.get("seq_p")), _n(row.get("lof_p")), _n(row.get("r2")), _n(row.get("adj_r2")), _n(row.get("pred_r2")),
             ("선택" if row["model"] == r["family"] else "") + (" · 제안" if row.get("suggested") else "")]
            for r in reg["responses"] for row in r["summary"]["rows"] if not row.get("aliased")], [34, 26, 26, 30, 26, 30, 30, 30], 7.4,
           align=["LEFT", "LEFT"] + ["CENTER"] * 6)
    if images:
        pdf.add_page(orientation="L")
        _h(pdf, "그림 1. 반응 곡면")
        _p(pdf, "10단계에서 선택한 모형의 반응 곡면(화면에서 그린 그림). 빨간 점은 관측값이 곡면 위, 연분홍은 아래, 바닥 점선은 설계점이 받치는 영역.", 8)
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
    return bytes(pdf.output())


__all__ = ["risk_report", "final_report", "STEPS", "TITLE"]
