/* 시스템 설명 오버레이 — README(설계 문서)를 흐름 그림으로 옮긴 8단계 워크스루.
   CDN·라이브러리 없이 HTML/CSS/SVG만 쓴다(허브 파드에서 외부 요청 없이 떠야 하므로).
   내용의 근거는 README.md 각 장이며, 수치·규칙 ID는 database/ 의 실제 행을 인용한다. */

(function () {
  const SEEN_KEY = "f1_guide_seen_v1";

  /* ── 단계 정의 ───────────────────────────────────────────────────────
     kicker: 상단 라벨 · title: 제목 · lead: 도입 문단 · art: 그림 · note: 마무리 강조 */
  const STEPS = [
    {
      nav: "왜 이 문제인가",
      kicker: "문제",
      title: "약을 만드는 과정에서, 제형 설계가 자주 터진다",
      lead: `새로운 약 하나를 세상에 내놓기까지 보통 <b>10년 이상, 수조 원</b>이 든다.
             약효를 내는 주성분을 찾아도 끝이 아니다. 사람이 삼킬 수 있는 형태 —
             정제·캡슐·시럽 — 로 만들어야 비로소 약이 되고, 이 단계를
             <b>제형(製劑) 설계</b>라고 부른다. 주성분 하나로는 알약이 굳지 않으니
             여러 첨가제(부형제)를 섞는데, <b>바로 그 조합에서 사고가 난다.</b>`,
      art: `
        <div class="f1-timeline f1-seq">
          <div class="f1-tl">후보물질 발굴<small>수천 개 중 극소수</small></div>
          <div class="f1-tl hot">제형 설계<small>← 여기</small></div>
          <div class="f1-tl">비임상<small>동물·독성</small></div>
          <div class="f1-tl">임상 1·2·3<small>수년</small></div>
          <div class="f1-tl">허가·생산<small>규제 심사</small></div>
        </div>
        <div class="f1-fails f1-seq">
          <div class="f1-box f1-fail"><b><span class="f1-emoji">⚗️</span>화학적 충돌</b>
            <span>주성분과 첨가제가 반응해 약이 갈변하거나 분해된다</span></div>
          <div class="f1-box f1-fail"><b><span class="f1-emoji">🏭</span>공정 실패</b>
            <span>가루를 눌러 알약으로 찍을 때 부서지거나 기계에 들러붙는다</span></div>
          <div class="f1-box f1-fail"><b><span class="f1-emoji">📕</span>규제 초과</b>
            <span>나라별 첨가제 상한을 넘긴다. 어린이용은 기준이 훨씬 엄격하다</span></div>
        </div>`,
      note: `지금까지 제약 현장은 이 문제를 <b>실험실에서 직접 만들어 보고, 실패하면 다시 설계하는</b>
             방식으로 풀었다. 한 번의 실험에 드는 시간과 비용이 크고, 그 시행착오를 수십 번 반복한다.
             이 값비싼 시행착오를 실험실이 아니라 <b>컴퓨터 안에서 미리 끝내자</b>는 것이 출발점이다.`,
    },

    {
      nav: "챗봇으론 안 되는 이유",
      kicker: "함정",
      title: "그럴듯하게 말하는 것과, 실제로 맞는 것은 다르다",
      lead: `"AI가 똑똑하니 좋은 처방을 물어보면 되지 않나?" 여기에 함정이 있다.
             거대언어모델은 <b>환각(hallucination)</b> — 존재하지 않는 사실을 자신 있게 지어내는 현상 —
             을 보인다. 일어나지 않는 화학 반응을 매끄럽게 설명하고, 만들 수 없는 처방을 태연히 제시하며,
             <b>규제 수치까지 지어낸다.</b>`,
      art: `
        <div class="f1-versus f1-seq">
          <div class="f1-quote bad">
            <div class="f1-qhead">✕ LLM에게 통째로 맡기면</div>
            <div class="f1-said">"SLS는 소아 기준 <b>15mg</b>까지 안전합니다.
              유당과 함께 배합하셔도 문제없습니다."</div>
            <span class="f1-badge bad">환각</span>
            <span class="f1-badge soft">근거 없음</span>
            <div class="f1-cap">문장은 매끄럽지만 수치의 출처가 없다.
              제약에서 이 오차는 곧 제품 폐기와 허가 반려다.</div>
          </div>
          <div class="f1-quote good">
            <div class="f1-qhead">✓ 규칙표에 근거를 물으면</div>
            <div class="f1-said f1-mono">rule_id: INC002<br>
              excipient: Lactose<br>
              risk_group: Secondary Amine<br>
              mechanism: Maillard 반응 → 갈변<br>
              verification_status: VERIFIED<br>
              alternative: Mannitol</div>
            <span class="f1-badge good">출처 추적됨</span>
            <span class="f1-badge good">항상 같은 판정</span>
            <div class="f1-cap">한 줄마다 어디서 온 수치인지가 붙어 있고,
              판정은 백 번 돌려도 같다.</div>
          </div>
        </div>`,
      note: `<b>창의적인 아이디어를 내는 능력</b>과 <b>그 아이디어가 안전하고 규정에 맞는지 빈틈없이 검증하는 능력</b>은
             서로 다른 일이다. 후자를 말 잘하는 AI에게 통째로 맡기는 것은 위험하다.`,
    },

    {
      nav: "핵심 아이디어",
      kicker: "설계 원칙",
      title: "창의는 AI가, 검증은 규칙이",
      lead: `그래서 역할을 둘로 나눴다. <b>새로운 처방을 상상하고 만드는 일은 AI에게</b>,
             <b>그것이 맞는지 검사하는 일은 "절대 틀리지 않는 규칙"에게</b> 맡긴다.
             이 분업이 시스템 전체의 골격이다.`,
      art: `
        <div class="f1-split f1-seq">
          <div class="f1-half ai">
            <h4>AI 에이전트가 하는 일</h4>
            <p>규칙만으로는 결코 할 수 없는 것</p>
            <ul>
              <li>천문학적인 조합 공간에서 쓸 만한 후보를 상상</li>
              <li>안정성·복용 편의·단가·규제 사이의 타협점 찾기</li>
              <li>룰북에 없는 새로운 상황을 판단</li>
            </ul>
          </div>
          <div class="f1-guard">
            <div>가드레일</div>
            <div class="bar"></div>
            <div>안에서<br>자유롭게</div>
          </div>
          <div class="f1-half rule">
            <h4>결정론적 규칙이 하는 일</h4>
            <p>AI의 추측이 끼어들면 위험한 것</p>
            <ul>
              <li>"SLS가 소아 상한을 넘는가?" 같은 수치 판정</li>
              <li>같은 입력이면 항상 같은 결과 (오차 0%)</li>
              <li>근거가 확인된 규칙 행만 반려를 만들 수 있음</li>
            </ul>
          </div>
        </div>
        <div class="f1-cap">규칙은 "이건 틀렸어"까지만 말할 수 있고, 새로운 답을 만들어 내지는 못한다.
          둘은 경쟁 관계가 아니라 서로의 빈틈을 메우는 <b>역할 분담</b>이다.</div>`,
      note: `판단의 성격에 따라 검사를 두 종류로 나눈다. <b>숫자로 답이 떨어지는 것</b>("SLS가 10mg 이하인가")은
             계산기가, <b>맥락을 읽어야 하는 것</b>("이 조합이 어린이가 먹기에 자연스러운가")은 심사 에이전트가 맡는다.
             새 규칙표가 들어오면 시스템이 둘 중 어느 쪽인지 보고 알맞은 검사에 자동으로 연결한다.`,
    },

    {
      nav: "전체 흐름 ★",
      kicker: "시스템 구조",
      title: "요청 하나가 처방이 되기까지",
      lead: `에이전트 구성이 <b>고정돼 있지 않다.</b> 미리 정해 둔 AI를 매번 똑같이 돌리는 게 아니라,
             요청이 들어올 때마다 그 상황에 필요한 전문가를 그때그때 불러 팀을 새로 꾸린다
             — <b>자기조직형 멀티 에이전트</b>. 아래가 그 전체 흐름이다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-io">사용자 요청 · 주성분 · 대상 환자 · 제형 · 자연어 요구</div>
          <div class="f1-flowmark">▼</div>

          <div class="f1-tier t1">
            <header><span>① 지휘 계층</span><span>Control Plane</span></header>
            <div class="f1-cols c2">
              <div class="f1-box f1-llm"><b>총괄 오케스트레이터</b>
                <span>요청을 분석해 이번 설계에 필요한 전문가 팀 구성을 스스로 결정</span></div>
              <div class="f1-box f1-llm"><b>반성 에이전트</b>
                <span>반려의 근본 원인을 짚고 재설계 방향을 지시 (최대 5회)</span></div>
            </div>
          </div>
          <div class="f1-flowmark">▼ 팀 소집</div>

          <div class="f1-tier t2">
            <header><span>② 설계 계층 — 병렬 후보 경쟁</span><span>Generators</span></header>
            <div class="f1-cols c3">
              <div class="f1-box"><b>설계 A</b><span>직접타정 전략</span></div>
              <div class="f1-box"><b>설계 B</b><span>습식과립 전략</span></div>
              <div class="f1-box"><b>설계 C</b><span>가용화 전략</span></div>
            </div>
            <div class="f1-cap">초안을 하나만 만들지 않는다. 서로 다른 전략으로 동시에 만들어
              경쟁시키고, 검증을 가장 잘 통과하는 후보가 살아남는다.</div>
          </div>
          <div class="f1-flowmark">▼</div>

          <div class="f1-tier t3">
            <header><span>③ 규칙 게이트 — 금기가 있는가</span><span>Deterministic + Dynamic Jury</span></header>
            <div class="f1-cols c2">
              <div class="f1-box f1-det"><b>규칙 검사 도구벨트 · 오차 0%</b>
                <div class="f1-sub" style="margin-top:7px">
                  <div class="f1-pill-sm">배합 금기</div>
                  <div class="f1-pill-sm">공정 실패</div>
                  <div class="f1-pill-sm">규제 상한</div>
                </div>
                <span style="display:block;margin-top:7px">AI의 추측이 없다. 몇 번을 돌려도 같은 결과.
                  단, 통과는 “위반을 <b>발견하지 못했다</b>”는 뜻이다</span>
              </div>
              <div class="f1-box f1-jud"><b>동적 심사위원단 · 상황따라 N명</b>
                <div class="f1-sub" style="margin-top:7px">
                  <div class="f1-pill-sm">👶 소아 안전 심사관</div>
                  <div class="f1-pill-sm">💧 가용화 전략 심사관</div>
                  <div class="f1-pill-sm dashed">… 조건 맞으면 추가 소집</div>
                </div>
                <span style="display:block;margin-top:7px">통과한 후보만 넘어온다. <b>반려 권한은 없다</b></span>
              </div>
            </div>
          </div>
          <div class="f1-flowmark">▼ 통과한 후보만</div>

          <div class="f1-tier t3">
            <header><span>④ 근거 게이트 — 실행할 만큼 아는가</span><span>Evidence Readiness</span></header>
            <div class="f1-cols c3">
              <div class="f1-box f1-det"><b>프로토콜 전 필수</b>
                <span>없으면 전략이 바뀐다 → 실행 보류</span></div>
              <div class="f1-box f1-det"><b>병행 수행</b>
                <span>전략은 그대로 · 중단/변경 기준과 함께</span></div>
              <div class="f1-box f1-det"><b>배치 후 조건부</b>
                <span>첫 배치 결과를 보고 필요하면</span></div>
            </div>
            <div class="f1-cap">반려 권한이 아니라 <b>보류 권한</b>을 가진 게이트다.
              선행 근거가 비면 실행 가능한 프로토콜 대신 <b>확인시험 프로토콜</b>이 나간다.</div>
          </div>
          <div class="f1-flowmark">▼</div>

          <div class="f1-io">합의 도출 — 결정론 하드페일 + 심사 가중점수 → <b>권고 후보 처방</b></div>
          <div class="f1-cols c3" style="margin-top:2px">
            <div class="f1-loop">⟲ 규칙 반려 → 반성 에이전트 → ① 로</div>
            <div class="f1-loop">⟲ 확인시험 결과 → 입력·근거 계층으로</div>
            <div class="f1-io win">✓ 연구자 승인 → 실행 가능 프로토콜</div>
          </div>
        </div>`,
      note: `구조의 뼈대는 <b>게이트가 둘</b>이라는 점이다. 규칙 게이트는 “금기가 있는가”를 묻고 반려하며,
             근거 게이트는 “알고 있는가”를 묻고 보류한다. 자료가 없어서 규칙이 아무것도 못 잡은 경우를
             통과로 읽지 않기 위해서다. 여기에 <b>심사위원단에 고정 명단이 없다</b>는 점이 더해진다 —
             대상이 소아라면 소아 안전 심사관이, 난용성 약(BCS II·IV)이면 가용화 심사관이 그 자리에서
             만들어지고 나머지는 아예 생성되지 않는다.`,
    },

    {
      nav: "입구: 분자 계산",
      kicker: "입력 계층",
      title: "검사를 시작하려면, 이 약의 작용기부터 알아야 한다",
      lead: `유당이 위험한지 아닌지는 <b>약에 아민기가 있느냐</b>에 달려 있다.
             이걸 사람이 손으로 적어 넣으면 틀린다 — 실제로 이 프로젝트의 초기 데모가 그렇게 틀렸다.
             그래서 지금은 <b>분자식(SMILES)에서 시작한다.</b>`,
      art: `
        <div class="f1-pipe f1-seq">
          <div>
            <div class="f1-smiles">SMILES<br>CC(=O)Nc1ccc(O)cc1</div>
            <div class="f1-cap" style="margin-top:7px">RDKit이 받는 유일한 입력</div>
          </div>
          <div class="f1-branches">
            <div class="f1-branch"><span class="tick">├─</span>
              <div><b>descriptor 9종 계산</b>
                <span>분자량 151.2 · logP 1.35 · TPSA 49.3 …</span></div></div>
            <div class="f1-branch"><span class="tick">├─</span>
              <div><b>염 제거 → parent 추출</b>
                <span>besylate·HCl 같은 염은 벗겨낸 뒤 매칭</span></div></div>
            <div class="f1-branch"><span class="tick">├─</span>
              <div><b>SMARTS 구조 플래그</b>
                <span>fr_* fragment 카운트와 교차검증 — 불일치하면 경고</span></div></div>
            <div class="f1-branch low"><span class="tick">└─</span>
              <div><b>물성 추정 (저신뢰)</b>
                <span>용해도·투과도 → <b>BCS 분류 확정에는 쓰지 않음</b></span></div></div>
          </div>
        </div>
        <div class="f1-flagcmp f1-seq">
          <div class="f1-box">
            <b>Acetaminophen</b>
            <div class="f1-flagline on"><i class="dot"></i>is_amide_not_amine</div>
            <div class="f1-flagline off"><i class="dot"></i>has_primary_amine</div>
            <div class="f1-flagline off"><i class="dot"></i>has_secondary_amine</div>
            <span>이름은 "아미노"페놀 유도체지만 실제로는 <b>아미드</b> — 반응할 유리 아민이 없다</span>
          </div>
          <div class="f1-box">
            <b>Fluoxetine HCl</b>
            <div class="f1-flagline off"><i class="dot"></i>is_amide_not_amine</div>
            <div class="f1-flagline off"><i class="dot"></i>has_primary_amine</div>
            <div class="f1-flagline on"><i class="dot"></i>has_secondary_amine</div>
            <span>2차 아민 — 유당과 Maillard 반응을 일으킨다</span>
          </div>
        </div>
        <div class="f1-cap">같은 유당 처방인데 <b>주성분에 따라 판정이 갈린다.</b>
          아세트아미노펜은 반려 없음, 플루옥세틴은 INC002 반려.</div>`,
      note: `마지막 갈래가 중요하다. logP로 용해도를 <b>추정할 수는</b> 있지만 그건 경향일 뿐이고,
             규칙표에도 <code class="f1-mono">confidence=low · 실측 우선</code>이라고 못 박혀 있다.
             그래서 이 시스템은 <b>추정값으로 BCS 등급을 확정하지 않는다.</b> 실측이 들어왔을 때만 분류하고,
             없으면 "사람 판단 필요"로 넘긴다. 계산할 수 있다고 해서 판정해도 되는 것은 아니다.`,
    },

    {
      nav: "검사 순서",
      kicker: "실행 순서",
      title: "규칙표를 아무 순서로나 돌릴 수는 없다",
      lead: `"직접타정 규칙"은 <b>직접타정이 선택된 뒤에야</b> 의미가 있고, 그 선택은 유동성 등급이 나온 뒤에야
             가능하다. 그래서 규칙표마다 실행 우선순위가 붙어 있고, <b>앞 단계가 만든 값이 뒷 단계의
             발동 조건으로 흘러 들어간다.</b>`,
      art: `
        <div class="f1-stack f1-seq">
          <div class="f1-lvl"><span class="n">0</span><span>참조 마스터 — 부형제 마스터 · descriptor 정의 · SMARTS 정의</span><span></span></div>
          <div class="f1-lvl"><span class="n">5</span><span>API 물성 임계값 — Ro5 / Veber 경고 밴드</span><span></span></div>
          <div class="f1-lvl flow"><span class="n">10</span><span>유동성 등급 — 안식각 48°</span><em>→ flow_character = "Poor"</em></div>
          <div class="f1-lvl flow"><span class="n">11</span><span>공정 경로 분기 — 직접타정 배제</span><em>→ selected_route = "DG"</em></div>
          <div class="f1-lvl key"><span class="n">20</span><span>배합 금기 (1:1)</span><em>성분을 바꿔야 하는 반려</em></div>
          <div class="f1-lvl key"><span class="n">21</span><span>소아 안전 상한</span><em>먼저 걸러낸다</em></div>
          <div class="f1-lvl"><span class="n">22</span><span>색소 · 향료</span><span></span></div>
          <div class="f1-lvl"><span class="n">30</span><span>다성분 상호작용</span><span></span></div>
          <div class="f1-lvl flow"><span class="n">40</span><span>선택된 공정의 세부 규칙</span><em>← selected_route 참조</em></div>
          <div class="f1-lvl"><span class="n">45</span><span>부형제 배합비</span><span></span></div>
          <div class="f1-lvl"><span class="n">50</span><span>코팅 · 잔류용매</span><span></span></div>
          <div class="f1-lvl"><span class="n">60</span><span>BCS 분류 → 전략</span><span></span></div>
          <div class="f1-lvl"><span class="n">70</span><span>포장 · 안정성 · 분석법</span><span></span></div>
        </div>`,
      note: `폴더 번호만 보면 규제(<code class="f1-mono">05_regulatory</code>)가 마지막 같지만,
             실제로는 <b>소아 안전이 21번으로 가장 먼저 도는 축에 속한다.</b>
             값 몇 개를 조정해서 해결되는 문제가 아니라 성분 자체를 바꿔야 하는 반려라,
             무거운 공정 계산을 하기 전에 먼저 걸러내는 편이 낫기 때문이다.`,
    },

    {
      nav: "실제로 이렇게 돌았다",
      kicker: "동작 예시",
      title: "설계 → 반려 → 재설계 → 통과",
      lead: `요청: <b>"소아용 플루옥세틴 정제를 설계하라."</b>
             아래는 실제 실행 트레이스를 따라간 것이다. 이 화면 오른쪽에서 직접 돌려 볼 수 있다.`,
      art: `
        <div class="f1-story f1-seq">
          <div class="f1-beat"><div class="who">RDKit</div><div class="what"><div class="card">
            구조 플래그 검출 <span class="f1-mono">Fluoxetine → ['has_secondary_amine']</span></div></div></div>

          <div class="f1-beat"><div class="who">route</div><div class="what"><div class="card">
            유동성 등급으로 공정 후보를 좁힌다 <span class="f1-mono">경쟁 전략: DC, WG</span></div></div></div>

          <div class="f1-beat"><div class="who">설계</div><div class="what"><div class="card">
            가장 흔한 희석제로 초안을 만든다
            <span class="f1-mono">cand-0-DC · cand-0-WG — 희석제 Lactose monohydrate</span></div></div></div>

          <div class="f1-beat reject"><div class="who">게이트</div><div class="what"><div class="card">
            <b>⛔ INC002 반려</b> — 2차 아민 + 유당 → Maillard 반응
            <span class="f1-mono">cand-0-DC 반려 (판정 11 · 위반 2)</span></div></div></div>

          <div class="f1-beat fix"><div class="who">반성</div><div class="what"><div class="card">
            <b>chemical 계층에서 2건 반려 — 성분 선택 재검토 필요</b>
            <span class="f1-mono">지시 → Mannitol</span>
            <span class="f1-mono">(반려 사유에 담긴 alternative_excipient_name 이 그대로 재설계 지시가 된다)</span></div></div></div>

          <div class="f1-beat win"><div class="who">설계·게이트</div><div class="what"><div class="card">
            <b>✓ 통과</b> <span class="f1-mono">cand-1-DC — 희석제 Mannitol · 통과 (판정 10 · 위반 1)</span></div></div></div>

          <div class="f1-beat jud"><div class="who">소집</div><div class="what"><div class="card">
            <b>심사관 2명만 소집됐다</b>
            <span class="f1-mono">REV001 소아 안전 — 조건 target_population=='pediatric'</span>
            <span class="f1-mono">REV003 공정 실현성 — 조건 always</span>
            <span class="f1-mono">REV002 가용화 심사관은 조건 불일치 → 아예 생성되지 않음</span></div></div></div>

          <div class="f1-beat win"><div class="who">합의</div><div class="what"><div class="card">
            <b>선정 cand-1-DC</b> <span class="f1-mono">가중치 {REV001: 0.545, REV003: 0.455}</span></div></div></div>
        </div>`,
      note: `주목할 점 — <b>설계 에이전트는 금기를 미리 피하지 않는다.</b> 가장 흔한 희석제인 유당으로 초안을
             만들고, 검증이 그걸 잡아낸다. 설계자가 검증의 일을 대신하면 시스템이 무엇을 잡아내는지 보이지 않기
             때문이다. 실험실에서라면 "만들어 보고 갈변을 확인한 뒤 다시 설계하는" 데 며칠이 걸렸을 과정이고,
             <b>이 판정은 몇 번을 다시 돌려도 똑같이 나온다.</b><br><br>
             다만 걸리려면 <b>두 쪽이 실제로 만나야 한다.</b> 룰북은 <span class="f1-mono">Lactose monohydrate</span>라
             적고 처방은 "유당"이라 적는데, 글자가 같은지만 보던 동안 이 규칙은 조용히 통과했다(2026-08 수정).
             지금은 부형제 마스터를 사전 삼아 표기·국문명·계열명을 맞춘다. 같은 이유로,
             <b>구조를 못 읽었으면 통과가 아니라 판정 불가</b>다 — SMILES 오타 하나로 작용기가 0개가 되면
             구조 기반 금기는 발동할 수 없고, 그 침묵을 합격으로 세면 게이트가 있으나 마나가 된다.`,
    },

    {
      nav: "실행 전: 알아야 실행한다 ★",
      kicker: "근거 충족 게이트",
      title: "금기가 없다는 것과, 실행해도 된다는 것은 다르다",
      lead: `규칙표는 <b>알고 있는 값</b>에 대해서만 위반을 판정한다. 값 자체가 없으면 규칙은 아무것도
             잡지 못하고, 그 침묵이 “안전하다”로 읽힌다. 신약 주성분에서는 이게 일상이다 —
             수분 안정성도, 배합적합성도, 실험 용해도도 없는 상태로 개발이 시작되기 때문이다.
             그래서 규칙 게이트 뒤에 <b>질문을 하나 더</b> 둔다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-cols c2">
            <div class="f1-box f1-det"><b>규칙 게이트</b>
              <span>금기·규제 위반이 있는가 → 있으면 <b>반려</b> (재설계로)</span></div>
            <div class="f1-box f1-det"><b>근거 게이트</b>
              <span>실행할 만큼 아는가 → 모르면 <b>보류</b> (확인시험 먼저)</span></div>
          </div>
          <div class="f1-flowmark">▼ 후보마다 근거 결손을 계산한다 (LLM 호출 0회)</div>

          <div class="f1-tier">
            <header><span>요구는 시점으로 나뉜다</span><span>16종 · 데이터로 관리</span></header>
            <div class="f1-cols c3">
              <div class="f1-box f1-det"><b>프로토콜 전 필수</b>
                <span>수계 공정인데 수분 안정성 없음 · 난용성 전략인데 실험 용해도 없음 ·
                  BCS가 예측 기반 · 아민 + 환원당인데 배합적합성 없음</span></div>
              <div class="f1-box"><b>병행 수행</b>
                <span>판별력 있는 용출법 확립 · 시료 용액 안정성.
                  <b>중단/변경 기준</b>을 함께 낸다</span></div>
              <div class="f1-box"><b>배치 후 조건부</b>
                <span>입도–용출 상관 · 잔사 고체상 · 불순물 응답계수 —
                  첫 배치 결과를 본 뒤에</span></div>
            </div>
            <div class="f1-cap">요구는 <b>실제 확인시험 66종 안의 시험만</b> 가리킬 수 있다.
              없는 시험을 가리키는 행은 읽는 단계에서 버려지므로,
              모든 요청에 방법·판정 기준·ICH/USP 출처가 붙는다.</div>
          </div>
          <div class="f1-flowmark">▼</div>

          <div class="f1-cols c3">
            <div class="f1-box"><b>실행 불가 초안</b><span>선행 근거 비어 있음.
              처방과 근거는 보이지만 실행하면 안 된다</span></div>
            <div class="f1-box"><b>검토용 프로토콜</b><span>선행 근거 충족.
              연구자 검토 대기</span></div>
            <div class="f1-box f1-det"><b>실행 가능 프로토콜</b><span>연구자가 승인함.
              누가 언제 승인했는지 함께 기록</span></div>
          </div>
          <div class="f1-flowmark">▼ 확인시험 결과를 넣으면 그 자리에서 다시 계산</div>
          <div class="f1-io">적합 → 근거 충족 · <b>부적합 → 근거가 채워진 게 아니라 전제가 부정된 것</b>
            (그 전략은 배제)</div>
        </div>`,
      note: `<b>시스템은 스스로 마지막 칸으로 넘어가지 않는다.</b> 근거가 다 채워져도 승인은 사람이 하고,
             근거가 빈 상태에서 승인을 요청하면 서버가 거부한다. 이 되먹임은 다음 장의 배치 결과 되먹임과
             <b>돌아가는 곳이 다르다</b> — 확인시험 결과는 “무엇을 아는가”를 바꾸므로 입력·근거 계층으로,
             배치 결과는 “무엇이 잘못됐는가”를 알려 주므로 설계·프로토콜 개정으로 간다.`,
    },

    {
      nav: "만든 뒤: 다음 실험 지시",
      kicker: "Lab-in-the-loop",
      title: "AI가 결과를 읽고, 다음 실험을 지시한다",
      lead: `근거가 채워지고 연구자가 승인해 프로토콜이 실행 가능해지면, 연구원이 배치를 제조한다.
             나머지 절반은 그 뒤에 온다.
             연구원이 실험 결과를 자연어로 적어 넣으면, AI가 수치를 판독하고 규칙이 규격 이탈을
             판정한 뒤, <b>다음에 무슨 실험을 해야 하는지 AI가 지시한다.</b> 사람은 판단의 병목이
             아니라 벤치에서 그 실험을 수행하는 쪽으로 들어온다 —
             <b>lab-in-the-loop</b> 구조다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-io">연구원이 쓴 실험 노트 (자연어)</div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-tier">
            <header><span>① 판독</span><span>LLM</span></header>
            <div class="f1-box f1-llm"><b>문장에서 측정값만 옮긴다</b>
              <span>"30분 용출 62%, 경도 38N, 불순물 0.9%, 표면 갈변"
                → dissolution=62 · hardness=38 · impurity=0.9 + 관찰 1건.
                <b>없는 값은 지어내지 않는다</b> — 못 읽은 표현은 못 읽었다고 표시한다.</span></div>
          </div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-tier">
            <header><span>② 판정</span><span>결정론 규칙</span></header>
            <div class="f1-box f1-det"><b>규격 이탈 계산 — 같은 데이터면 같은 결과</b>
              <span>용출 62% &lt; 80% 이탈 · 경도 38N &lt; 40N 이탈 …
                규칙표가 이탈마다 원인 해석과 재설계 방향을 함께 갖고 있다.</span></div>
          </div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-tier">
            <header><span>③ 지시</span><span>LLM + 확인시험 마스터 66종</span></header>
            <div class="f1-cols c2">
              <div class="f1-box f1-llm"><b>가설</b>
                <span>이번 결과를 설명하는 인과를 세운다</span></div>
              <div class="f1-box f1-det"><b>후보는 실제 66종뿐</b>
                <span>AI는 그 안에서 고를 뿐 시험을 발명하지 못한다.
                  목록 밖 test_id는 화면에 나가기 전에 버려진다.</span></div>
            </div>
            <div class="f1-sub">
              <div class="f1-pill-sm">1 · T_DISS_PROFILE — 용출 프로파일 <b>근거 FDA</b></div>
              <div class="f1-pill-sm">2 · T_M9_DISS — 비교용출 <b>근거 ICH M9 3.2</b></div>
              <div class="f1-pill-sm">3 · T_FORCED — 강제분해 <b>근거 ICH Q14/Q2</b></div>
            </div>
          </div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-io win">사람이 벤치에서 수행 → 결과를 다시 넣는다 (루프)</div>
        </div>`,
      note: `설계 루프와 <b>역할 분담이 똑같다.</b> 창의(판독·가설·시험 선정)는 AI가, 판정(규격 이탈)은
             규칙이 맡는다. 그리고 지시의 후보를 실제 확인시험 마스터로 묶어 두었기 때문에,
             모든 "다음 실험"에는 ICH·USP·FDA 출처가 붙는다 — 지어낸 실험을 지시할 수 없다.`,
    },

    {
      nav: "근거 없는 규칙은 안 돈다",
      kicker: "차별점",
      title: "출처를 못 찾은 규칙은, 실행되지 않는다",
      lead: `규칙표의 각 줄에는 그 수치를 <b>어디서 가져왔는지</b>가 함께 적혀 있다.
             약대생 팀이 규칙 하나하나에 출처를 추적해 붙였고, 추적에 실패한 것은 실패했다고 정직하게 기록했다.
             엔진은 그 기록(<code class="f1-mono">verification_status</code>)을 읽고 스스로 판단한다.`,
      art: `
        <div class="f1-policy f1-seq">
          <div class="f1-prow use"><span class="st">VERIFIED / _PRIMARY / _SECONDARY</span>
            <span class="to">→</span><span class="act">그대로 판정에 사용 — 반려를 만들 수 있다</span></div>
          <div class="f1-prow prov"><span class="st">PROVISIONAL / STRUCTURAL_VERIFIED</span>
            <span class="to">→</span><span class="act">사용하되 결과에 "잠정값" 표기</span></div>
          <div class="f1-prow down"><span class="st">UNVERIFIED / SCHEMA_ONLY</span>
            <span class="to">→</span><span class="act"><b>반려는 못 시킴</b> — 심사관 이관으로 강등</span></div>
          <div class="f1-prow esc"><span class="st">ESCALATION_REQUIRED</span>
            <span class="to">→</span><span class="act">사람에게 이관</span></div>
          <div class="f1-prow drop"><span class="st">NO_SOURCE_FOUND / NOT_A_RULE / LEGACY</span>
            <span class="to">→</span><span class="act"><b>로딩 단계에서 아예 제외</b> — 메모리에 올라오지도 않는다</span></div>
        </div>
        <div class="guide-note warn" style="margin-top:16px">
          <b>이 정책은 만들어지자마자 우리 자신의 데모를 반려했다.</b><br>
          원래 이 문서의 예시는 "아세트아미노펜 + 유당 → 갈변"이었다. 그런데 분자 구조를 계산해 보니
          아세트아미노펜은 아미드라 반응할 아민이 없었다. 두 번째 반려 사유였던 "소아 SLS 10mg 초과"도,
          출처를 추적해 보니 EMA 기준의 SLS 항목은 <b>경피 투여 전용</b>이고 경구 소아 상한은 존재하지 않아
          그 행은 <code class="f1-mono">NO_SOURCE_FOUND / NOT_A_RULE</code>로 폐기됐다.
          <b>근거가 없는 판정은 하지 않는다는 원칙이 우리 편의보다 먼저 적용된 셈이고, 그것이 이 프로젝트가
          팔려는 바로 그 가치다.</b>
        </div>`,
      note: `규제 기관을 설득해야 하는 분야에서는 "그럴듯한 규칙이 많은 것"보다
             <b>"근거 없는 규칙은 안 돌린다"</b>가 훨씬 중요한 자산이라고 판단했다.`,
    },
  ];

  /* 마지막 단계 끝에 붙는 실행 유도 — 설명이 끝나면 바로 화면을 쓰게 만든다. */
  const CTA = `
    <div class="f1-cta">
      <p><b>이제 직접 돌려 보세요.</b> 입력줄 아래 <b>시연 시나리오</b> 버튼이 각각 다른 경로를
        밟습니다 — 규칙이 제약을 반려하는 경우, 인구군에 따라 심사관이 바뀌는 경우 등.<br>
        트레이스의 규칙 발동을 클릭하면 <b>원본 CSV 행과 출처 문헌</b>이 열리고,
        오른쪽 <b>Lab-in-the-loop</b>에 실험 결과를 자연어로 넣으면 다음 실험을 지시합니다.</p>
      <button type="button" id="guide-finish">설명 닫고 실행하기 →</button>
    </div>`;

  /* ── 렌더링 ─────────────────────────────────────────────────────── */
  const el = (id) => document.getElementById(id);
  let index = 0;
  const visited = new Set();

  function buildRail() {
    el("guide-count").textContent = `${STEPS.length}단계 · 약 5분`;
    el("guide-nav").innerHTML = STEPS.map((s, i) => `<li data-i="${i}">${s.nav}</li>`).join("");
    el("guide-dots").innerHTML = STEPS.map((_, i) => `<i data-i="${i}"></i>`).join("");
    document.querySelectorAll("#guide-nav li, #guide-dots i").forEach((node) => {
      node.onclick = () => show(Number(node.dataset.i));
    });
  }

  function show(i) {
    index = Math.max(0, Math.min(STEPS.length - 1, i));
    visited.add(index);
    const step = STEPS[index];

    el("guide-body").innerHTML = `
      <div class="guide-kicker">${step.kicker}</div>
      <h2>${step.title}</h2>
      <p class="guide-lead">${step.lead}</p>
      <div class="guide-art">${step.art}</div>
      ${step.note ? `<div class="guide-note">${step.note}</div>` : ""}
      ${index === STEPS.length - 1 ? CTA : ""}`;
    el("guide-body").scrollTop = 0;

    // 그림 요소를 순서대로 등장시켜 "흐름"이 눈으로 따라가지게 한다.
    el("guide-body").querySelectorAll(".f1-seq").forEach((group) => {
      [...group.children].forEach((child, n) => {
        child.style.animationDelay = `${60 + n * 70}ms`;
      });
    });

    document.querySelectorAll("#guide-nav li").forEach((li, n) => {
      li.classList.toggle("on", n === index);
      li.classList.toggle("seen", n !== index && visited.has(n));
    });
    document.querySelectorAll("#guide-dots i").forEach((dot, n) => {
      dot.classList.toggle("on", n === index);
    });

    el("guide-prev").disabled = index === 0;
    el("guide-next").textContent = index === STEPS.length - 1 ? "닫기 ✓" : "다음 →";

    const finish = el("guide-finish");
    if (finish) finish.onclick = close;
  }

  let lastFocus = null;

  function open(startAt) {
    lastFocus = document.activeElement;
    el("guide").hidden = false;
    document.body.style.overflow = "hidden";
    show(typeof startAt === "number" ? startAt : 0);
    // 스크린리더·키보드 사용자가 오버레이 안에서 시작하도록 포커스를 옮긴다.
    el("guide-next").focus();
  }

  function close() {
    el("guide").hidden = true;
    document.body.style.overflow = "";
    try { localStorage.setItem(SEEN_KEY, "1"); } catch (e) { /* 사생활 모드 등 — 무시 */ }
    // 열기 버튼으로 포커스를 되돌린다(안 그러면 body로 떨어져 탭 순서가 끊긴다).
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    else el("guide-open").focus();
    lastFocus = null;
  }

  /* 모달 안에서 Tab이 배경으로 새지 않게 가둔다. */
  function trapFocus(e) {
    const focusable = el("guide").querySelectorAll(
      'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  buildRail();
  el("guide-open").onclick = () => open(0);
  el("guide-close").onclick = close;
  el("guide-close-rail").onclick = close;
  el("guide-prev").onclick = () => show(index - 1);
  el("guide-next").onclick = () => (index === STEPS.length - 1 ? close() : show(index + 1));
  el("guide").onclick = (e) => { if (e.target.id === "guide") close(); };

  document.addEventListener("keydown", (e) => {
    if (el("guide").hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowRight") show(index + 1);
    else if (e.key === "ArrowLeft") show(index - 1);
    else if (e.key === "Tab") trapFocus(e);
  });

  // ?guide=4 처럼 특정 단계를 바로 열 수 있다 — 설명 한 대목만 공유할 때 쓴다.
  const requested = new URLSearchParams(location.search).get("guide");
  if (requested !== null) {
    open(Math.max(0, Number(requested) - 1) || 0);
    return;
  }

  // 첫 방문이면 자동으로 띄운다 — 처음 온 사람은 이 시스템이 뭔지 모른다.
  let seen = false;
  try { seen = localStorage.getItem(SEEN_KEY) === "1"; } catch (e) { seen = false; }
  if (!seen) open(0);
})();
