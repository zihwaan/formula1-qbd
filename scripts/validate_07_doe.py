"""07_doe 룰북 세트 검증기 (v6.1).

사용: python scripts/validate_07_doe.py [database/07_doe] [tests/fixtures/rule_fixtures.json]

정적 검사
  1. manifest(YAML 파서) ↔ 디스크 파일 일치
  2. rule 파일 공통 스키마, rule_id 유일, gate_effect/human_override enum
  3. BLOCK_STAGE·INVALIDATE → human_override == NONE
  4. stage가 manifest stages에 존재 ('A|B' 허용)
  5. when_expression: AST allowlist, 루트·필드·중첩 필드가 context_schema에 존재,
     함수가 registry에 존재하고 인자 수 일치, const.X가 상수표에 존재
  6. 라우팅: next_state가 있는 모든 규칙은 전이표에 (result_code, stage ⊆ from_states, next_state) 행이 있어야 함
  7. source_ids 등록 확인
실행 검사
  8. rule_fixtures.json의 입력으로 규칙을 실제 평가해 기대 결과와 비교 (Python eval 미사용)
"""
import ast, csv, json, pathlib, sys
import yaml

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "database/07_doe")
FIX = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("tests/fixtures/rule_fixtures.json")
RULE_COLS = ["rule_id","rulebook_id","version","priority","scope","stage","when_expression",
 "required_inputs","missing_value_action","gate_effect","result_code","next_state","message_ko",
 "implementation_hint","human_override","override_approver_role","rationale","source_ids",
 "governance_class","validation_status","owner","effective_from"]
EFFECTS = {"PASS","WARNING","REQUEST_DATA","ROUTE","EXCLUDE_POINT","AUGMENT","BLOCK_STAGE","INVALIDATE"}
OVERRIDES = {"NONE","REASON_ONLY","REASON_AND_APPROVER","ALTERNATIVE_EVIDENCE"}
errors, warns = [], []

def rows(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))
def header(p):
    with open(p, encoding="utf-8") as f:
        return next(csv.reader(f))

man = yaml.safe_load((ROOT/"governance"/"rulebook_manifest.yaml").read_text(encoding="utf-8"))
entries = {e["file"].split("07_doe/")[1]: e for e in man["entries"]}
for f in entries:
    if not (ROOT/f).exists(): errors.append(f"manifest 파일 없음: {f}")
on_disk = {str(p.relative_to(ROOT)).replace("\\","/") for p in ROOT.rglob("*.csv")}
for f in on_disk - set(entries): errors.append(f"manifest에 없는 CSV: {f}")

SCHEMA = man["context_schema"]; ROOTS = SCHEMA["roots"]; ENT = SCHEMA["entities"]
FUNCS = man["functions"]; STAGES = set(man["stages"])
ALLOWED = set(man["evaluator"]["allowed_ast_nodes"])
CONSTS = {r["constant_id"]: r["value"] for r in rows(ROOT/"planning"/"statistical_policy_constants.csv")}
SRCS = {r["source_id"] for r in rows(ROOT/"masters"/"statistical_sources.csv")}

def elem(t):
    return t[5:-1] if isinstance(t, str) and t.startswith("list[") else None

class Checker:
    def __init__(self, where): self.where, self.env = where, {}
    def err(self, m): errors.append(f"{self.where}: {m}")
    def check(self, node):
        name = type(node).__name__
        if name not in ALLOWED: self.err(f"허용되지 않은 AST 노드 {name}"); return None
        return getattr(self, "v_"+name, self.generic)(node)
    def generic(self, node):
        for c in ast.iter_child_nodes(node): self.check(c)
        return None
    def v_Name(self, n):
        if n.id in self.env: return self.env[n.id]
        if n.id in ROOTS: return ROOTS[n.id]
        if n.id == "const": return "const"
        self.err(f"알 수 없는 이름 {n.id}"); return None
    def v_Attribute(self, n):
        base = self.check(n.value)
        if base == "const":
            if n.attr not in CONSTS: self.err(f"상수 없음 const.{n.attr}")
            return "num"
        if base is None: return None
        if base not in ENT: self.err(f"{base}에는 필드 접근 불가 (.{n.attr})"); return None
        if n.attr not in ENT[base]: self.err(f"{base}.{n.attr} 필드가 context_schema에 없음"); return None
        return ENT[base][n.attr]
    def _comp(self, gen):
        c = gen.generators[0]
        if len(gen.generators) != 1 or not isinstance(c.target, ast.Name):
            self.err("generator는 for 절 1개, 단순 변수만"); return None
        it = self.check(c.iter); t = elem(it)
        if it is not None and t is None: self.err(f"generator 대상이 목록이 아님: {it}")
        self.env[c.target.id] = t
        for cond in c.ifs: self.check(cond)
        r = self.check(gen.elt); self.env.pop(c.target.id, None); return r
    def v_GeneratorExp(self, n): self._comp(n); return "gen"
    def v_ListComp(self, n): r = self._comp(n); return f"list[{r or 'str'}]"
    def v_Call(self, n):
        if not isinstance(n.func, ast.Name): self.err("메서드 호출 금지"); return None
        fn = n.func.id
        if fn not in FUNCS: self.err(f"registry에 없는 함수 {fn}"); return None
        ar = FUNCS[fn]["arity"]
        if n.keywords: self.err(f"{fn}: 키워드 인자 금지")
        if ar == "gen":
            if len(n.args) != 1 or not isinstance(n.args[0], ast.GeneratorExp): self.err(f"{fn}: generator 1개 필요")
        elif ar != -1 and len(n.args) != ar: self.err(f"{fn}: 인자 {ar}개 필요, {len(n.args)}개")
        for a in n.args: self.check(a)
        return FUNCS[fn]["returns"]

for f, e in entries.items():
    if e["kind"] == "rule" and header(ROOT/f) != RULE_COLS: errors.append(f"{f}: 공통 스키마 불일치")

ids, rule_index = set(), {}
for f, e in entries.items():
    data = rows(ROOT/f)
    for r in data:
        key = r.get("rule_id") or next(iter(r.values()))
        for sid in [x.strip() for x in (r.get("source_ids") or "").split(";") if x.strip()]:
            if not sid.startswith("SPEC:") and sid not in SRCS: errors.append(f"{f}:{key} 미등록 source_id {sid}")
    if e["kind"] != "rule": continue
    for r in data:
        rid = r["rule_id"]
        if rid in ids: errors.append(f"중복 rule_id {rid}")
        ids.add(rid); rule_index[rid] = r
        if r["gate_effect"] not in EFFECTS: errors.append(f"{rid} gate_effect {r['gate_effect']}")
        if r["human_override"] not in OVERRIDES: errors.append(f"{rid} human_override {r['human_override']}")
        if r["gate_effect"] in ("BLOCK_STAGE","INVALIDATE") and r["human_override"] != "NONE":
            errors.append(f"{rid} 차단 규칙인데 override 허용")
        for s in r["stage"].split("|"):
            if s not in STAGES: errors.append(f"{rid} 알 수 없는 stage {s}")
        if r["next_state"] and r["next_state"] not in STAGES: errors.append(f"{rid} 알 수 없는 next_state {r['next_state']}")
        try: tree = ast.parse(r["when_expression"], mode="eval")
        except SyntaxError: errors.append(f"{rid} when_expression 파싱 실패"); continue
        Checker(rid).check(tree)

routes = {}
for r in rows(ROOT/"verification"/"backtrack_routing_rules.csv"):
    fr = r["from_states"].split(";")
    for s in fr:
        if s != "*" and s not in STAGES: errors.append(f"전이표 {r['reason_code']} from_state {s}")
    if r["next_state"] not in STAGES: errors.append(f"전이표 {r['reason_code']} next_state {r['next_state']}")
    routes.setdefault(r["reason_code"], []).append((set(fr), r["next_state"]))
for rid, r in rule_index.items():
    if not r["next_state"]: continue
    ok = any(nxt == r["next_state"] and ("*" in fr or set(r["stage"].split("|")) <= fr)
             for fr, nxt in routes.get(r["result_code"], []))
    if not ok: errors.append(f"{rid}: ({r['result_code']}, {r['stage']}) → {r['next_state']} 전이표에 없음")

EVID = {r["evidence_status"]: r for r in rows(ROOT/"governance"/"evidence_governance_rules.csv")}
CAPS = man["backend_capabilities"]
class Missing(Exception): pass
def num(v):
    try: return float(v)
    except (TypeError, ValueError): return v
CONSTV = {k: (v == "true" if v in ("true","false") else num(v)) for k, v in CONSTS.items()}

def make_funcs(mode):
    def evidence_permits(status, use):
        v = EVID.get(status, {}).get(use, "DENY")
        if v == "DEMO_ONLY": return man["modes"][mode]["evidence_DEMO_ONLY"] == "ALLOW"
        return v.startswith("ALLOW")
    def backend_supports(plan):
        cap = CAPS.get(plan.get("design_type"), {"supported": False})
        if not cap.get("supported"): return False
        k = plan.get("n_factors", 0)
        if not (cap.get("min_factors", 0) <= k <= cap.get("max_factors", 99)): return False
        if cap.get("factor_types") == "continuous only" and plan.get("n_categorical", 0) > 0: return False
        return not (plan.get("has_mixture") or plan.get("has_hard_to_change"))
    def nonempty_all(it):
        it = list(it); return len(it) > 0 and all(it)
    return {"len": len, "abs": abs, "min": min, "max": max, "sum": sum, "any": any, "all": all,
            "nonempty_all": nonempty_all, "count": lambda it: sum(1 for x in it if x),
            "distinct_count": lambda it: len(set(it)),
            "set_intersects": lambda a, b: bool(set(a or []) & set(b or [])),
            "matrix_rank": lambda plan: plan["_matrix_rank"],
            "evidence_permits": evidence_permits, "backend_supports": backend_supports}

OPS = {ast.Eq: lambda a,b: a == b, ast.NotEq: lambda a,b: a != b, ast.Lt: lambda a,b: a < b,
       ast.LtE: lambda a,b: a <= b, ast.Gt: lambda a,b: a > b, ast.GtE: lambda a,b: a >= b,
       ast.In: lambda a,b: a in b, ast.NotIn: lambda a,b: a not in b,
       ast.Is: lambda a,b: a is b, ast.IsNot: lambda a,b: a is not b}
BIN = {ast.Add: lambda a,b: a+b, ast.Sub: lambda a,b: a-b, ast.Mult: lambda a,b: a*b, ast.Div: lambda a,b: a/b}
NULL_OK = (ast.Is, ast.IsNot, ast.Eq, ast.NotEq, ast.In, ast.NotIn)

def ev(n, ctx, F):
    t = type(n)
    if t is ast.Expression: return ev(n.body, ctx, F)
    if t is ast.Constant: return n.value
    if t is ast.Tuple: return tuple(ev(e, ctx, F) for e in n.elts)
    if t is ast.Name: return CONSTV if n.id == "const" else ctx.get(n.id)
    if t is ast.Attribute:
        b = ev(n.value, ctx, F)
        if b is None: raise Missing(n.attr)
        return b.get(n.attr)
    if t is ast.BoolOp:
        if isinstance(n.op, ast.And): return all(ev(v, ctx, F) for v in n.values)
        return any(ev(v, ctx, F) for v in n.values)
    if t is ast.UnaryOp:
        v = ev(n.operand, ctx, F)
        if isinstance(n.op, ast.Not): return not v
        if v is None: raise Missing("neg")
        return -v
    if t is ast.BinOp:
        a, b = ev(n.left, ctx, F), ev(n.right, ctx, F)
        if a is None or b is None: raise Missing("binop")
        return BIN[type(n.op)](a, b)
    if t is ast.Compare:
        left = ev(n.left, ctx, F)
        for op, rc in zip(n.ops, n.comparators):
            right = ev(rc, ctx, F)
            if not isinstance(op, NULL_OK) and (left is None or right is None): raise Missing("compare")
            if not OPS[type(op)](left, right): return False
            left = right
        return True
    if t in (ast.GeneratorExp, ast.ListComp):
        c = n.generators[0]; out = []
        for x in (ev(c.iter, ctx, F) or []):
            c2 = {**ctx, c.target.id: x}
            if all(ev(i, c2, F) for i in c.ifs): out.append(ev(n.elt, c2, F))
        return out
    if t is ast.Call:
        fn = F.get(n.func.id)
        if fn is None: raise NotImplementedError(n.func.id)
        args = [ev(a, ctx, F) for a in n.args]
        if any(a is None for a in args) and n.func.id not in ("any","all","nonempty_all","set_intersects"): raise Missing(n.func.id)
        return fn(*args)
    raise NotImplementedError(t.__name__)

ORDER = man["validation_status_order"]
def enforcement_allowed(rule, mode):
    return ORDER.index(rule["validation_status"]) >= ORDER.index(man["modes"][mode]["enforce_min_validation_status"])

fx_pass = fx_fail = 0
if FIX.exists():
    for fx in json.loads(FIX.read_text(encoding="utf-8")):
        mode = fx.get("mode", "demo"); r = rule_index.get(fx["rule_id"])
        if r is None: errors.append(f"fixture {fx['id']}: 규칙 {fx['rule_id']} 없음"); continue
        if fx["expect"] in ("ENFORCED", "NOT_ENFORCED"):
            got = "ENFORCED" if enforcement_allowed(r, mode) else "NOT_ENFORCED"
        else:
            try:
                got = "FIRES" if ev(ast.parse(r["when_expression"], mode="eval"), fx["context"], make_funcs(mode)) else "NOT_FIRES"
            except Missing:
                got = "MISSING"
        if got == fx["expect"]: fx_pass += 1
        else: fx_fail += 1; errors.append(f"fixture {fx['id']} ({fx['rule_id']}): 기대 {fx['expect']}, 실제 {got} — {fx['note']}")
else:
    warns.append(f"fixture 파일 없음: {FIX}")

print(f"files={len(entries)} rules={len(ids)} fixtures_pass={fx_pass} fixtures_fail={fx_fail} errors={len(errors)} warnings={len(warns)}")
for e in errors: print("ERROR", e)
for w in warns: print("WARN ", w)
sys.exit(1 if errors else 0)
