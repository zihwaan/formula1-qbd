"""07_doe 룰북 — manifest 로더 + AST 화이트리스트 평가기 + 룰 집행기 (명세 v6.1 §7.2–§7.3).

이 모듈이 `ExperimentalDevelopmentGraph`의 판정 권한 전부다. 서비스 코드는 artifact를
RuleContext(dict)로 옮겨 여기로 넘기고, 여기서 나온 verdict와 전이만 따른다. 판정 로직을
코드에 쓰지 않는다 — 규칙은 `database/07_doe/**.csv`의 `when_expression` 한 줄이다.

기존 `formula/checkers/applies_when.py`는 제한된 globals로 **Python `eval`** 을 쓴다.
07_doe에는 그것을 쓰지 않는다(인계 문서 §5). 여기 평가기는 `scripts/validate_07_doe.py`의
`ev()`(참조 구현)를 그대로 승격한 것이다:

- 허용 AST 노드는 manifest `evaluator.allowed_ast_nodes`만. 로드 시 전 규칙을 검사하고,
  하나라도 어기면 **로드 자체가 실패**한다(조용히 규칙을 빼면 그게 곧 미탐이다).
- 빈 컬렉션: `any`→False, `all`→True, `nonempty_all`→False.
- `None`과의 크기 비교·산술·함수 인자 → 미발화가 아니라 `Missing` → 규칙의
  `missing_value_action`(RECORD_NOT_CHECKED, REQUEST_DATA, BLOCK_STAGE …)을 적용한다.
  "값이 없어서 조건이 거짓"으로 읽으면 v3의 NameError 삼킴 사고와 같은 모양이 된다.

집행(§7.3):
- 집행 조건 = manifest 항목 `enforcement_enabled` AND 규칙 `validation_status` ≥ 모드 최소값.
  현재 전 규칙이 DRAFT_PENDING_REVIEW라 **production 모드에서는 아무것도 집행되지 않는 것이
  정상**이다. 데모는 demo(sandbox) 모드로 돈다. 집행되지 않은 규칙도 평가는 하고 기록한다.
- 여러 규칙이 동시에 발화하면 **모든 verdict를 보존**하고, 상태 전이는 가장 강한 effect
  하나로 한다(INVALIDATE/BLOCK_STAGE > REQUEST_DATA > EXCLUDE_POINT/AUGMENT > ROUTE >
  WARNING > PASS). 같은 강도면 `priority` 숫자가 작은 쪽(인계 문서 §7.1의 tie-break).
- 다음 상태는 규칙의 `next_state`가 아니라 **전이표(backtrack_routing_rules.csv, 룰북 #23)**
  에서 `(result_code, from_state)`로 찾는다. 표에 없으면 `UNKNOWN` → WAITING_HUMAN_TRIAGE.
"""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

RULE_COLS = [
    "rule_id", "rulebook_id", "version", "priority", "scope", "stage", "when_expression",
    "required_inputs", "missing_value_action", "gate_effect", "result_code", "next_state",
    "message_ko", "implementation_hint", "human_override", "override_approver_role",
    "rationale", "source_ids", "governance_class", "validation_status", "owner", "effective_from",
]

# 판정 강도 — 명세 §7.2. 숫자가 클수록 강하다.
EFFECT_RANK: Dict[str, int] = {
    "INVALIDATE": 6, "BLOCK_STAGE": 6, "REQUEST_DATA": 5, "EXCLUDE_POINT": 4, "AUGMENT": 4,
    "ROUTE": 3, "WARNING": 2, "PASS": 1,
}
BLOCKING = {"INVALIDATE", "BLOCK_STAGE"}

# 규칙이 참조할 수 있지만 manifest root가 아닌 이름(const, 함수명)은 root 계산에서 뺀다.
_NON_ROOT = {"const"}


class Missing(Exception):
    """None과의 연산 — 규칙 미발화가 아니라 missing_value_action을 적용해야 한다."""


class RulebookLoadError(RuntimeError):
    pass


def _rows(path: Path) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v: str) -> Any:
    if v in ("true", "false"):
        return v == "true"
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


@dataclass
class Rule:
    rule_id: str
    rulebook_id: str
    version: str
    priority: int
    stages: Tuple[str, ...]
    expression: str
    tree: ast.Expression
    roots: frozenset
    missing_value_action: str
    gate_effect: str
    result_code: str
    next_state: str
    message_ko: str
    human_override: str
    override_approver_role: str
    rationale: str
    source_ids: str
    validation_status: str
    file: str
    enforcement_enabled: bool
    row: Dict[str, str] = field(repr=False, default_factory=dict)

    def at(self, stage: str) -> bool:
        return stage in self.stages or "ANY" in self.stages

    @property
    def ref(self) -> str:
        return f"{self.rule_id}@{self.version}"


@dataclass
class Verdict:
    """규칙 1개 × 대상 1개의 평가 결과. 발화하지 않은 규칙도 남긴다(미발화도 판정이다)."""

    rule_id: str
    rule_version: str
    subject: str
    status: str                 # FIRES | NOT_FIRES | MISSING | NOT_CHECKED
    effect: Optional[str]       # 발화 시 gate_effect, 결측 시 missing_value_action에서 유도
    enforced: bool
    result_code: str
    next_state: str
    message: str
    priority: int
    human_override: str
    rulebook_id: str
    missing: str = ""
    overridden: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Evaluation:
    stage: str
    mode: str
    verdicts: List[Verdict]
    decisive: Optional[Verdict]
    reason_code: Optional[str]
    next_state: Optional[str]

    @property
    def fired(self) -> List[Verdict]:
        return [v for v in self.verdicts if v.status in ("FIRES", "MISSING") and v.effect]

    @property
    def enforced(self) -> List[Verdict]:
        return [v for v in self.fired if v.enforced]

    @property
    def blocking(self) -> List[Verdict]:
        return [v for v in self.enforced if v.effect in BLOCKING]

    @property
    def requests(self) -> List[Verdict]:
        return [v for v in self.enforced if v.effect == "REQUEST_DATA" and not v.overridden]

    @property
    def warnings(self) -> List[Verdict]:
        return [v for v in self.enforced if v.effect == "WARNING"]

    def codes(self, *effects: str) -> List[str]:
        return [v.result_code for v in self.enforced if not effects or v.effect in effects]

    def fired_rule(self, rule_id: str, subject: Optional[str] = None) -> bool:
        return any(v.rule_id == rule_id and v.status == "FIRES" and v.enforced
                   and (subject is None or v.subject == subject) for v in self.verdicts)

    def as_dict(self) -> Dict[str, Any]:
        shown = [v.as_dict() for v in self.verdicts if v.status != "NOT_FIRES"]
        return {
            "stage": self.stage, "mode": self.mode,
            "verdicts": shown,
            "evaluated": len(self.verdicts),
            "decisive": self.decisive.as_dict() if self.decisive else None,
            "reason_code": self.reason_code, "next_state": self.next_state,
        }


# ---------------------------------------------------------------------------
# 평가기 — Python eval 없음
# ---------------------------------------------------------------------------
_OPS = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b,
}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
_NULL_OK = (ast.Is, ast.IsNot, ast.Eq, ast.NotEq, ast.In, ast.NotIn)
# None 인자를 받아도 되는 함수 — 컬렉션 판정은 빈 목록처럼, 교집합은 빈 집합처럼 다룬다.
_NONE_ARG_OK = {"any", "all", "nonempty_all", "set_intersects"}


def evaluate(node: ast.AST, ctx: Dict[str, Any], funcs: Dict[str, Callable], consts: Dict[str, Any]) -> Any:
    t = type(node)
    if t is ast.Expression:
        return evaluate(node.body, ctx, funcs, consts)
    if t is ast.Constant:
        return node.value
    if t is ast.Tuple:
        return tuple(evaluate(e, ctx, funcs, consts) for e in node.elts)
    if t is ast.Name:
        return consts if node.id == "const" else ctx.get(node.id)
    if t is ast.Attribute:
        base = evaluate(node.value, ctx, funcs, consts)
        if base is None:
            raise Missing(node.attr)
        if not isinstance(base, dict):
            raise Missing(node.attr)
        return base.get(node.attr)
    if t is ast.BoolOp:
        if isinstance(node.op, ast.And):
            return all(evaluate(v, ctx, funcs, consts) for v in node.values)
        return any(evaluate(v, ctx, funcs, consts) for v in node.values)
    if t is ast.UnaryOp:
        v = evaluate(node.operand, ctx, funcs, consts)
        if isinstance(node.op, ast.Not):
            return not v
        if v is None:
            raise Missing("neg")
        return -v
    if t is ast.BinOp:
        a, b = evaluate(node.left, ctx, funcs, consts), evaluate(node.right, ctx, funcs, consts)
        if a is None or b is None:
            raise Missing("binop")
        return _BIN[type(node.op)](a, b)
    if t is ast.Compare:
        left = evaluate(node.left, ctx, funcs, consts)
        for op, rc in zip(node.ops, node.comparators):
            right = evaluate(rc, ctx, funcs, consts)
            if not isinstance(op, _NULL_OK) and (left is None or right is None):
                raise Missing("compare")
            if not _OPS[type(op)](left, right):
                return False
            left = right
        return True
    if t in (ast.GeneratorExp, ast.ListComp):
        comp = node.generators[0]
        out = []
        for x in (evaluate(comp.iter, ctx, funcs, consts) or []):
            inner = {**ctx, comp.target.id: x}
            if all(evaluate(i, inner, funcs, consts) for i in comp.ifs):
                out.append(evaluate(node.elt, inner, funcs, consts))
        return out
    if t is ast.Call:
        name = node.func.id
        fn = funcs.get(name)
        if fn is None:
            raise NotImplementedError(f"registry에 구현이 없는 함수: {name}")
        args = [evaluate(a, ctx, funcs, consts) for a in node.args]
        if any(a is None for a in args) and name not in _NONE_ARG_OK:
            raise Missing(name)
        result = fn(*args)
        if result is None:
            raise Missing(name)
        return result
    raise NotImplementedError(t.__name__)


def _roots(tree: ast.AST) -> frozenset:
    """규칙이 요구하는 context root 이름들 (generator 바인딩 변수·const·함수명 제외)."""
    bound, names, called = set(), set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.comprehension) and isinstance(n.target, ast.Name):
            bound.add(n.target.id)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            called.add(n.func.id)
        elif isinstance(n, ast.Name):
            names.add(n.id)
    return frozenset(names - bound - called - _NON_ROOT)


# ---------------------------------------------------------------------------
# 룰북
# ---------------------------------------------------------------------------
class DoeRulebook:
    """manifest + 22개 CSV + 마스터 7종. 로드는 한 번, 판정은 몇 번이든."""

    def __init__(self, root: Path):
        self.root = Path(root)
        man_path = self.root / "governance" / "rulebook_manifest.yaml"
        self.manifest = yaml.safe_load(man_path.read_text(encoding="utf-8"))
        self.version = str(self.manifest.get("version"))
        self.allowed_nodes = set(self.manifest["evaluator"]["allowed_ast_nodes"])
        self.stages = list(self.manifest["stages"])
        self.modes = self.manifest["modes"]
        self.status_order = list(self.manifest["validation_status_order"])
        self.capabilities = self.manifest.get("backend_capabilities", {})
        self.entries = {e["id"]: e for e in self.manifest["entries"]}
        self.tables: Dict[str, List[Dict[str, str]]] = {}
        self.rules: List[Rule] = []
        self._load()

    # -- 로드 ----------------------------------------------------------------
    def _path(self, entry: Dict[str, Any]) -> Path:
        rel = entry["file"].split("07_doe/", 1)[1]
        return self.root / rel

    def _load(self) -> None:
        for eid, entry in sorted(self.entries.items(), key=lambda kv: kv[1].get("load_order", 0)):
            if not entry.get("load_enabled", True):
                continue
            path = self._path(entry)
            if not path.exists():
                raise RulebookLoadError(f"manifest 파일 없음: {path}")
            rows = _rows(path)
            self.tables[eid] = rows
            if entry["kind"] != "rule":
                continue
            with open(path, encoding="utf-8") as f:
                header = next(csv.reader(f))
            if header != RULE_COLS:
                raise RulebookLoadError(f"{path.name}: 공통 룰 스키마 불일치")
            for r in rows:
                tree = ast.parse(r["when_expression"], mode="eval")
                bad = {type(n).__name__ for n in ast.walk(tree)} - self.allowed_nodes
                if bad:
                    raise RulebookLoadError(f"{r['rule_id']}: 허용되지 않은 AST 노드 {sorted(bad)}")
                if r["gate_effect"] in BLOCKING and r["human_override"] != "NONE":
                    raise RulebookLoadError(f"{r['rule_id']}: 차단 규칙인데 override 허용")
                self.rules.append(Rule(
                    rule_id=r["rule_id"], rulebook_id=r["rulebook_id"], version=r["version"],
                    priority=int(float(r["priority"] or 999)),
                    stages=tuple(r["stage"].split("|")), expression=r["when_expression"],
                    tree=tree, roots=_roots(tree),
                    missing_value_action=r["missing_value_action"], gate_effect=r["gate_effect"],
                    result_code=r["result_code"], next_state=r["next_state"],
                    message_ko=r["message_ko"], human_override=r["human_override"],
                    override_approver_role=r["override_approver_role"], rationale=r["rationale"],
                    source_ids=r["source_ids"], validation_status=r["validation_status"],
                    file=str(path.relative_to(self.root)),
                    enforcement_enabled=bool(entry.get("enforcement_enabled", True)), row=r,
                ))
        self.by_id = {r.rule_id: r for r in self.rules}
        self.consts = {r["constant_id"]: _num(r["value"]) for r in self.tables["statistical_policy_constants"]}
        self.evidence = {r["evidence_status"]: r for r in self.tables["evidence_governance_rules"]}
        self.routes: Dict[str, List[Tuple[set, str, Dict[str, str]]]] = {}
        for r in self.tables["backtrack_routing_rules"]:
            self.routes.setdefault(r["reason_code"], []).append(
                (set(r["from_states"].split(";")), r["next_state"], r))

    # -- 조회 ----------------------------------------------------------------
    def master(self, name: str) -> List[Dict[str, str]]:
        return self.tables.get(name, [])

    def const(self, name: str) -> Any:
        return self.consts[name]

    def enforcement_allowed(self, rule: Rule, mode: str) -> bool:
        minimum = self.modes[mode]["enforce_min_validation_status"]
        try:
            ok = self.status_order.index(rule.validation_status) >= self.status_order.index(minimum)
        except ValueError:
            ok = False
        return ok and rule.enforcement_enabled and rule.validation_status != "RETIRED"

    def evidence_permits(self, status: Optional[str], use: str, mode: str) -> bool:
        value = self.evidence.get(status or "UNKNOWN", {}).get(use, "DENY")
        if value == "DEMO_ONLY":
            return self.modes[mode]["evidence_DEMO_ONLY"] == "ALLOW"
        return value.startswith("ALLOW")

    def route(self, reason_code: str, from_state: str) -> Tuple[str, str, str]:
        """(reason_code, from_state) → (reason_code, next_state, side_effect). 없으면 UNKNOWN."""
        for states, nxt, row in self.routes.get(reason_code, []):
            if "*" in states or from_state in states:
                return reason_code, nxt, row.get("artifact_side_effect", "")
        _, nxt, row = self.routes["UNKNOWN"][0]
        return "UNKNOWN", nxt, row.get("artifact_side_effect", "")

    def backend_supports(self, plan: Dict[str, Any]) -> bool:
        cap = self.capabilities.get(plan.get("design_type"), {"supported": False})
        if not cap.get("supported"):
            return False
        k = plan.get("n_factors") or 0
        if not (cap.get("min_factors", 0) <= k <= cap.get("max_factors", 99)):
            return False
        if cap.get("factor_types") == "continuous only" and (plan.get("n_categorical") or 0) > 0:
            return False
        return not (plan.get("has_mixture") or plan.get("has_hard_to_change"))

    def rules_at(self, stage: str, rulebooks: Optional[Sequence[str]] = None) -> List[Rule]:
        return [r for r in self.rules if r.at(stage) and (rulebooks is None or r.rulebook_id in rulebooks
                                                          or _file_id(r.file) in rulebooks)]

    # -- 판정 ----------------------------------------------------------------
    def functions(self, mode: str, helpers: Optional[Dict[str, Callable]] = None) -> Dict[str, Callable]:
        def nonempty_all(it):
            it = list(it or [])
            return len(it) > 0 and all(it)

        funcs: Dict[str, Callable] = {
            "len": len, "abs": abs, "min": min, "max": max,
            "sum": lambda it: sum(it), "any": lambda it: any(it or []),
            "all": lambda it: all(it or []), "nonempty_all": nonempty_all,
            "count": lambda it: sum(1 for x in it if x),
            "distinct_count": lambda it: len(set(it)),
            "set_intersects": lambda a, b: bool(set(x for x in (a or []) if x) & set(x for x in (b or []) if x)),
            "evidence_permits": lambda status, use: self.evidence_permits(status, use, mode),
            "backend_supports": self.backend_supports,
            "matrix_rank": lambda plan: plan.get("_matrix_rank"),
        }
        funcs.update(helpers or {})
        return funcs

    def evaluate(self, stage: str, subjects: Iterable[Tuple[str, Dict[str, Any]]], *,
                 mode: str = "demo", rulebooks: Optional[Sequence[str]] = None,
                 rule_ids: Optional[Sequence[str]] = None,
                 helpers: Optional[Dict[str, Callable]] = None,
                 overrides: Optional[set] = None) -> Evaluation:
        """stage에 걸린 규칙을 대상마다 평가한다.

        대상 context에 규칙이 요구하는 root가 하나라도 없으면 그 규칙은 **이 대상에 해당하지
        않는다**(평가 안 함). root는 있는데 값이 None이면 평가하고 Missing으로 처리한다 —
        서비스는 "모름"을 None으로 넣어야 하고, root를 빼서 규칙을 피하면 안 된다.
        """
        funcs = self.functions(mode, helpers)
        rules = [r for r in self.rules_at(stage, rulebooks) if rule_ids is None or r.rule_id in rule_ids]
        verdicts: List[Verdict] = []
        seen: set = set()
        for label, ctx in subjects:
            for rule in rules:
                if not rule.roots <= set(ctx):
                    continue
                # 여러 대상이 **같은 객체**를 root로 공유하면(예: 요인 전체 목록) 판정도 같다 — 한 번만 남긴다
                key = (rule.rule_id, tuple(id(ctx[r]) for r in sorted(rule.roots)))
                if key in seen:
                    continue
                seen.add(key)
                v = self._one(rule, label, ctx, funcs, mode)
                if overrides and ((rule.rule_id, label) in overrides or (rule.rule_id, "*") in overrides) \
                        and v.effect not in BLOCKING and rule.human_override != "NONE":
                    v.overridden = True   # 연구자 override — 기록은 남기고 전이 결정에서만 뺀다
                verdicts.append(v)
        decisive = _strongest(verdicts)
        reason, nxt = None, None
        if decisive and decisive.status == "FIRES" and decisive.next_state:
            reason, nxt, _ = self.route(decisive.result_code, stage)
        elif decisive and decisive.status == "MISSING" and decisive.next_state and (
                decisive.effect == self.by_id[decisive.rule_id].gate_effect
                or decisive.result_code == self.by_id[decisive.rule_id].missing_value_action):
            # 결측이 규칙 자신의 효과와 같을 때(예: REQUEST_DATA 규칙이 값을 몰라 다시 자료를 요청)만
            # 그 전이를 따른다. 결측 때문에 무효화·분석 경로로 가지는 않는다.
            reason, nxt, _ = self.route(decisive.result_code, stage)
        return Evaluation(stage, mode, verdicts, decisive, reason, nxt)

    def _one(self, rule: Rule, label: str, ctx: Dict[str, Any], funcs, mode: str) -> Verdict:
        enforced = self.enforcement_allowed(rule, mode)
        base = dict(rule_id=rule.rule_id, rule_version=rule.version, subject=label, enforced=enforced,
                    result_code=rule.result_code, next_state=rule.next_state, message=rule.message_ko,
                    priority=rule.priority, human_override=rule.human_override,
                    rulebook_id=rule.rulebook_id)
        try:
            fired = bool(evaluate(rule.tree, ctx, funcs, self.consts))
        except Missing as exc:
            action = rule.missing_value_action
            effect = action if action in EFFECT_RANK else None
            if effect is None and action in self.routes:
                # 결측 처리 자체가 reason code인 경우(예: SA001·SA004의 INCONCLUSIVE) — 전이표로 라우팅한다
                code, nxt, _ = self.route(action, rule.stages[0])
                base.update(result_code=code, next_state=nxt)
                return Verdict(status="MISSING", effect="ROUTE", missing=f"{action}:{exc}", **base)
            status = "MISSING" if effect else "NOT_CHECKED"
            return Verdict(status=status, effect=effect, missing=f"{action}:{exc}", **base)
        if fired:
            return Verdict(status="FIRES", effect=rule.gate_effect, **base)
        return Verdict(status="NOT_FIRES", effect=None, **base)


def _file_id(path: str) -> str:
    return Path(path).stem


def _strongest(verdicts: List[Verdict]) -> Optional[Verdict]:
    live = [v for v in verdicts if v.enforced and v.effect and not v.overridden
            and v.status in ("FIRES", "MISSING")]
    if not live:
        return None
    return sorted(live, key=lambda v: (-EFFECT_RANK[v.effect], v.priority, v.rule_id))[0]


@lru_cache(maxsize=4)
def load_rulebook(root: str) -> DoeRulebook:
    return DoeRulebook(Path(root))
