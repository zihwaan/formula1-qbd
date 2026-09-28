/* 시스템 설명 오버레이 — README(설계 문서)를 흐름 그림으로 옮긴 단계별 워크스루.
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
      title: "요청 하나가 Design Space가 되기까지 — 두 단계, 연결은 후보 하나",
      lead: `시스템은 <b>두 단계</b>로 나뉜다. ① <b>후보 탐색</b>은 요청을 받아 전략을 좁히고
             후보 처방을 경쟁시켜 규칙으로 걸러 <b>후보 목록</b>을 낸다. ② <b>2단계</b>는 연구자가
             그중 <b>하나를 골라 [이 후보로 개발 착수]를 눌렀을 때만</b> 시작해, 그 처방을 프로토타입으로
             QTPP → CQA → 위험평가 → 종합 정리 → 실험 설계 → 회귀식 → 반응 곡면 → ANOVA → <b>공동확률 Design Space</b> →
             확인계획 잠금 → 확인배치까지 간다.
             둘은 내부 상태를 공유하지 않고, 고른 후보의 <b>처방(프로토타입)과 불변 Handoff</b> 하나로만 이어진다 —
             그 사이에서 <b>근거 결손 게이트</b>가 “알고 있는가”를 묻는다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-io">연구자 — 말 · 폼 입력 · 측정값 · 승인</div>
          <div class="f1-flowmark">▲▼</div>
          <div class="f1-box f1-llm"><b>입력 에이전트</b><span>맥락(진행 중인 설계·남은 요청)을 읽고 말을 <b>제안 카드</b>로 —
            숫자·구조식은 사용자 글과 공개 DB에서만, 빠진 값은 되묻고, 실행은 연구자가 누른다</span></div>
          <div class="f1-flowmark">▼ 확인한 카드만 — 사람이 누르는 것과 같은 경로</div>
          <div class="f1-tier t1">
            <header><span>① 후보 탐색 — CandidateDiscoveryGraph</span><span>분 단위</span></header>
            <div class="f1-cols c3">
              <div class="f1-box f1-det"><b>분류 먼저</b><span>BCS/DCS·고체상·가용화·ASD 페이즈 게이트가 전략을 좁힌다</span></div>
              <div class="f1-box f1-llm"><b>병렬 설계</b><span>전략별 후보를 동시에 만들어 경쟁시킨다</span></div>
              <div class="f1-box f1-det"><b>규칙 게이트</b><span>배합금기·공정·규제 규칙표가 반려 — 오차 0%</span></div>
            </div>
            <div class="f1-cols c2" style="margin-top:8px">
              <div class="f1-box f1-jud"><b>동적 심사위원단</b><span>요청에 맞는 심사관만 소집 · 순위만 매기고 반려 권한 없음</span></div>
              <div class="f1-box f1-det"><b>비차단 데이터 요청</b><span>값을 몰라도 후보는 나온다 — 전략이 갈리는 값만 되묻는다</span></div>
            </div>
            <div class="f1-cap">계획이 전략 점수 상위 3개를 고른다(같은 입력 = 같은 계획) ·
              ⟲ 규칙 반려 → <b>사유별 복귀 지점</b>(성분만 / 공정부터 / 전략부터) → 재설계 (최대 5회) ·
              남는 전략이 없으면 목표 재검토 · 출력 = <b>권고 후보 처방 목록</b>(포장 사양 제외)</div>
          </div>
          <div class="f1-flowmark">▼ 연구자가 후보 카드에서 <b>이 후보로 개발 착수</b>를 누를 때만 (1위 자동 진입 없음)</div>
          <div class="f1-box f1-det"><b>근거 결손 게이트</b><span>룰북 통과 = “금기가 없다”일 뿐 — 필수 근거(수분·열 안정성, 배합적합성, 실험 용해도 …)가
            없으면 확인시험 66종에서만 요청 · 결과를 넣으면 즉시 재판정 · 결손을 둔 채 가려면 <b>사유</b>, 부적합이면 착수 불가 (LLM 0회)</span></div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-io">프로토타입 + 불변 Handoff — 고른 후보의 조성(mg · % · 기능) · 공정 · 요청 맥락 · 근거 판정 (Table 1 형식)</div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-tier t3">
            <header><span>② 2단계 — Design Space 도출</span><span>15단계 · 단계마다 승인</span></header>
            <div class="f1-sub f1-chain">
              <div class="f1-pill-sm">QTPP</div><div class="f1-pill-sm">CQA 판별</div>
              <div class="f1-pill-sm">원료 위험평가</div><div class="f1-pill-sm">제형·공정 위험평가</div>
              <div class="f1-pill-sm">종합 정리</div><div class="f1-pill-sm">실험 설계 표</div>
              <div class="f1-pill-sm">회귀식 · 진단</div><div class="f1-pill-sm">반응 곡면</div><div class="f1-pill-sm">ANOVA</div>
              <div class="f1-pill-sm">공동확률 영역</div><div class="f1-pill-sm">확인계획 잠금</div><div class="f1-pill-sm">확인배치 2×2</div>
            </div>
            <div class="f1-cap">초안은 LLM이, 행렬·회귀·ANOVA·영역은 결정론 코드가, 승인은 연구자가 한다.
              지금 단계만 고칠 수 있고, 승인은 결정론 검사가 막는다.</div>
          </div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-cols c2">
            <div class="f1-io">위험평가 보고서 PDF — 8단계 종합 정리에서</div>
            <div class="f1-io win">✓ 최종 보고서 PDF — 회귀식 · 곡면 · ANOVA · Design Space · 확인계획</div>
          </div>
        </div>`,
      note: `뼈대는 <b>“누가 무엇을 정하는가”가 단계마다 고정돼 있다</b>는 점이다. 입력 에이전트는 말을
             입력으로 <b>정리</b>하고, AI는 후보와 초안을 <b>제안</b>하고, 결정론 규칙과 코드가 <b>판정·계산</b>하며, 연구자가 <b>선택·승인</b>한다.
             ①은 “만들기 전에 실패를 걸러내는” 쪽이고, ②는 “실험 데이터로 품질을 좌우하는 변수와 그 영향을 식으로 보이는” 쪽이다.
             ②는 ①의 1위를 자동으로 가져가지 않는다 — 어떤 후보를 개발할지는 연구자의 판단이다.`,
    },

    {
      nav: "화면도 같은 원칙을 따른다",
      kicker: "화면 구성",
      title: "대화 하나에, 다음 단계가 아래로 쌓인다",
      lead: `화면은 대화 하나다. 처음에는 가운데 입력칸만 있고, 말로 요청하면 <b>입력 에이전트</b>가
             설계 실행 카드를 만든다. 그 아래에 <b>실험 데이터 입력</b> 카드가 붙고, [설계 실행]을 누르면
             분자 카드 → 데이터 요청 → 후보 처방이 차례로 이어진다. 후보에서 개발을 시작하면 2단계의
             열다섯 단계가 같은 대화에 한 장씩 쌓인다 — 지난 단계는 요약 한 줄로 접혀 남고 언제든 펼쳐 볼 수 있다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-io win">가운데 입력칸 — 약 이름(또는 SMILES) · 대상 환자 · 제형 · 1회 용량</div>
          <div class="f1-flowmark">▼ 설계 실행 카드 + “실험 데이터값을 입력하시겠습니까?”</div>
          <div class="f1-cols c3">
            <div class="f1-box f1-det"><b>API 물리화학</b><span>구조 · 구조 플래그 · descriptor · 물성 추정 — 가로 한 장</span></div>
            <div class="f1-box"><b>데이터 요청</b><span>전략이 갈리는 값만 — [값 제출] 또는 [전부 건너뛰기]</span></div>
            <div class="f1-box f1-llm"><b>후보 처방</b><span>게이트 판정 · 심사 점수 · [이 후보로 개발 착수]</span></div>
          </div>
          <div class="f1-flowmark">▼ 2단계 — 단계마다 한 장, 지금 단계만 펼쳐진다</div>
          <div class="f1-io">프로토타입 → QTPP → CQA → 위험평가 → 정리 → 종합 정리 → 설계 표 → 회귀식 → 곡면 → ANOVA → 영역 → 확인계획 → 확인배치</div>
          <div class="f1-flowmark">▶ 오른쪽 칼럼</div>
          <div class="f1-io">에이전트 흐름 · 지금 무슨 일이 · 실행 트레이스 — 탭으로 바꾸고, 크게/작게 · 접기</div>
        </div>`,
      note: `화면의 주인공은 결과가 아니라 <b>지금 연구자가 내릴 결정</b>이다. 그래서 행동 카드가 대화 한가운데에 오고,
             그래프·해설·트레이스 같은 관측 정보는 오른쪽 칼럼에 있다(넓은 화면은 처음부터 펼쳐져 있다). 폼에 직접 넣는 길은 입력칸 아래
             <b>직접 입력</b>에, 지난 2단계 study는 위쪽 <b>2단계 기록</b>에 있다. 휴대폰에서는 오른쪽 칼럼이 화면 전체를 덮는 시트로 열린다.`,
    },

    {
      nav: "입력 에이전트 ★",
      kicker: "사용자와 시스템 사이",
      title: "말로 요청하면, 맥락을 읽고 실행할 수 있는 입력으로 정리한다",
      lead: `화면 가운데 입력칸이 곧 <b>입력 에이전트</b>다(폼은 그 아래 “직접 입력”이 보조 경로). 폼을 채우는 대신
             말로 요청하면, 에이전트가 <b>지금 맥락</b> — 진행 중인 설계, 남은 실험 요청, 되돌림 기록 — 을 서버에서 직접 읽고, 그 말을 <b>제안 카드</b>로 바꾼다.
             카드의 [실행]은 사람이 버튼을 누른 것과 똑같은 경로로 간다.`,
      art: `
        <div class="f1-story f1-seq">
          <div class="f1-beat"><div class="who">연구자</div><div class="what"><div class="card">
            “고령자용 로사르탄 캡슐 설계해 줘”</div></div></div>
          <div class="f1-beat fix"><div class="who">에이전트</div><div class="what"><div class="card">
            <b>설계 실행 카드 — 미완성(점선)</b>
            <span class="f1-mono">구조: PubChem CID 3961 (링크) · 용량: 없음 → “1회 용량(mg)이 얼마인가요?”</span></div></div></div>
          <div class="f1-beat"><div class="who">연구자</div><div class="what"><div class="card">“50 mg이야”</div></div></div>
          <div class="f1-beat win"><div class="who">에이전트</div><div class="what"><div class="card">
            <b>앞 대화와 합쳐 완성된 카드</b> <span class="f1-mono">[실행] → 폼을 채워 보여 준 뒤 같은 startRun()으로 시작</span></div></div></div>
          <div class="f1-beat jud"><div class="who">에이전트 (먼저)</div><div class="what"><div class="card">
            설계가 끝나면 권고 후보와 가장 가벼운 남은 요청을 짚고 <b>개발 착수 카드</b>를 낸다 —
            [실행]은 후보 카드의 [이 후보로 개발 착수]와 같은 길로 2단계를 연다</div></div></div>
        </div>
        <div class="f1-cols c3" style="margin-top:10px">
          <div class="f1-box f1-det"><b>숫자는 사용자 글에서만</b><span>카드의 모든 숫자를 최근 발화의 숫자와 대조 — 없으면 빼고 알린다. LLM이 낸 값도 예외 없음</span></div>
          <div class="f1-box f1-det"><b>구조식은 출처가 있는 곳에서만</b><span>사용자 입력 · 내장 사전 · PubChem 조회. 기억으로 쓴 SMILES는 버린다</span></div>
          <div class="f1-box f1-det"><b>지금 가능한 것만</b><span>허용목록 안의 측정 키, 지금 설계의 통과한 후보만. 다른 설계가 시작되면 이전 카드는 잠긴다</span></div>
        </div>`,
      note: `왼쪽 목록 아래의 <b>모델</b>에서 쓸 LLM을 고른다 — 기본은 무료 모델(Groq)이고, 대회 API 모델은
             비밀번호로 접속한 경우에만 고를 수 있다(게스트 접속은 무료 모델만). 고른 모델은 설계·심사·대화·2단계 초안에 함께 쓰인다.<br><br>
             측정값 제출은 LLM보다 <b>규칙이 먼저</b> 잡는다 — 열린 설계가 있고 “Tm 317도”처럼 측정 이름과 숫자가 있으면
             곧바로 제출 카드가 되고, 근거 등급(자체 실측·문헌·사용자 진술)을 골라 제출하면 설계를 다시 돌리지 않고 그 값에
             의존하는 판정만 다시 계산한다.<br><br>
             가드레일은 프롬프트가 아니라 <b>코드</b>다. 에이전트는 어떤 것도 스스로 실행하지 않고,
             판정은 여전히 룰북과 엔진이 한다 — 에이전트가 하는 일은 “말을 시스템이 받을 수 있는 입력으로
             옮기고, 빠진 것을 묻고, 다음에 할 일을 먼저 짚는 것”이다. LLM이 응답하지 않으면 규칙 기반
             해석기가 글에서 값만 읽어 같은 카드를 만들고, 그 사실을 표시한다.`,
    },

    {
      nav: "입구: 분자 계산",
      kicker: "입력 계층",
      title: "검사를 시작하려면, 이 약의 작용기부터 알아야 한다",
      lead: `유당이 위험한지 아닌지는 <b>약에 아민기가 있느냐</b>에 달려 있다.
             이걸 사람이 손으로 적어 넣으면 틀리기 쉽다 — 아세트아미노펜은 이름 때문에 아민처럼 보이지만
             실제로는 아미드다. 그래서 판정의 입력은 <b>분자식(SMILES)에서 계산한다.</b>`,
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
      nav: "분류부터: BCS/DCS ★",
      kicker: "페이즈 게이트",
      title: "처방을 만들기 전에 이 약이 어떤 부류인지부터 정한다",
      lead: `후보를 만들기 <b>전에</b> 먼저 거치는 단계가 있다. 용해도·투과도로
             약을 분류하는 BCS/DCS, 무정형인지 결정형인지(고체상), 가용화가 필요한지, 필요하면
             어떤 공정(예: 분무건조 ASD)을 쓸지 — 이 네 가지를 먼저 정해야 <b>어떤 전략을
             후보로 올릴지</b>가 정해진다. 실측값이 없어도 멈추지 않는다. <b>계산값 → 예측값 →
             측정값</b> 3단계 중 있는 것까지만 쓰고, 나머지는 "잠정(provisional)"이라고
             정직하게 표시한 채로 계속 진행한다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-io">RDKit descriptor + 사용자가 넣은 실측값</div>
          <div class="f1-flowmark">▼</div>
          <div class="f1-tier">
            <header><span>3단계 값 모델</span><span>있는 데까지만 쓴다</span></header>
            <div class="f1-cols c3">
              <div class="f1-box f1-det"><b>A · 계산값</b>
                <span>RDKit descriptor — 결정론, 항상 있음</span></div>
              <div class="f1-box"><b>B · 예측값</b>
                <span>ESOL·GSE 같은 닫힌 형태 공식. logS 두 예측이 1 log 이상 벌어지면
                  "신뢰 낮음" 신호로 처리</span></div>
              <div class="f1-box f1-jud"><b>C · 측정값</b>
                <span>실험이 있어야만 나옴 — 없으면 데이터 요청으로</span></div>
            </div>
          </div>
          <div class="f1-flowmark">▼ Gate 3A → 3B → 4 → 4B, 이 순서로 돈다</div>
          <div class="f1-stack f1-seq">
            <div class="f1-lvl"><span class="n">3A</span><span>BCS/DCS 용해도·투과도 분류 — 이온화하는 약은 예측 하나로 정하지 않고 “미정”(pH 1.2–6.8 용해도 요청)</span><em>bcs_solubility_provisional</em></div>
            <div class="f1-lvl"><span class="n">3B</span><span>고체상 — 결정형/무정형, advisory</span><em>polymorph_control_note</em></div>
            <div class="f1-lvl key"><span class="n">4</span><span>가용화 전략이 필요한가</span><em>sig_enabling_required</em></div>
            <div class="f1-lvl"><span class="n">4B</span><span>필요하면 어떤 ASD 공정인가</span><em>asd_process</em></div>
          </div>
          <div class="f1-flowmark">▼ 켜진 신호로 전략을 채점해 상위 3개를 고른다(strategy_families.csv · 계획 서명)</div>
          <div class="f1-io win">경쟁 전략 목록 — 예: 미분화(MICRO) · 고체분산체(ASD_SDD) · 판정이 안 갈리면 양쪽을 모두 연다</div>
        </div>`,
      note: `이 게이트에는 <b>반려 권한이 없다.</b> "금기가 있는가"를 묻는 배합금기 게이트와
             다르게, 여기는 "전략 후보를 얼마나 넓게/좁게 볼 것인가"만 정한다. 값을 모르면
             — 예를 들어 녹는점(Tm)도 결정형 정보도 없으면 — <b>예측 공식으로 잠정 분류하고
             그대로 진행</b>한다. 대신 "이 값이 있으면 전략이 더 좁아진다"는 요청을
             <span class="f1-mono">데이터 요청</span> 패널에 남긴다. 연구자가 값을 넣으면
             같은 전략 집합이면 신뢰도만 다시 계산하고(LLM 호출 없음), 전략 집합 자체가
             바뀌면 그때만 새로 설계한다 — 값 하나 들어왔다고 매번 처음부터 다시 돌리지 않는다.`,
    },

    {
      nav: "실험 요청",
      kicker: "lab-in-the-loop",
      title: "무엇을, 언제, 왜 묻는가 — 그리고 절대 멈추지 않는다",
      lead: `시스템이 “어떤 실험이 존재하는지” 아는 근거는 <b>측정 카탈로그 20종</b>뿐이다 — 목록에 없는
             시험은 요청하지 않는다. 언제·무엇을·왜 묻는지는 <b>트리거 표 16행</b>에 한 줄씩 적혀 있고,
             한 행은 발동 조건 · 요청할 시험 · 해결 조건 · 사유 · <b>거절했을 때의 대체 경로</b>를 담는다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-cols c2">
            <div class="f1-box f1-det"><b>전략을 좁히는 요청 (계획 전, 한 번)</b><span>결과에 따라 어느 전략을 고를지가 바뀐다 —
              녹는점을 모르면 용융압출과 분무건조를 가를 수 없다</span></div>
            <div class="f1-box f1-det"><b>신뢰도를 높이는 요청 (후보마다)</b><span>이미 고른 전략의 신뢰도만 바뀐다 —
              ASD 후보의 고분자 혼화성</span></div>
          </div>
          <div class="f1-flowmark">▼ 화면에서는</div>
          <div class="f1-stack f1-seq">
            <div class="f1-lvl"><span class="n">1</span><span>시료가 적게 드는 시험부터 — Tier 1(~10 mg: XRPD·DSC·TGA·KF) → Tier 2(~30 mg) → Tier 3</span><span></span></div>
            <div class="f1-lvl"><span class="n">2</span><span>같은 시험을 가리키는 요청은 한 칸으로 — 고체상 세트와 녹는점이 모두 DSC면 DSC 한 번</span><span></span></div>
            <div class="f1-lvl"><span class="n">3</span><span>사유를 구분해 표시 — “예측이 낮거나 모름” vs “예측 간 불일치(1 log 이상)”</span><span></span></div>
            <div class="f1-lvl key"><span class="n">4</span><span>건너뛰기 — 시험별 또는 전체. 예측값으로 계속하고 후보는 provisional 유지</span><em>대체 경로 표시</em></div>
          </div>
          <div class="f1-flowmark">▼ 값이 들어오면</div>
          <div class="f1-cols c2">
            <div class="f1-io">계획 서명이 같다 → 신뢰도 태그만 다시 (LLM 0회)</div>
            <div class="f1-io">서명이 바뀐다 → 새 전략 집합으로 다시 설계</div>
          </div>
        </div>`,
      note: `신뢰도 태그는 AI가 매기지 않는다 — <b>남은 신뢰도 요청이 없을 때만 grounded</b>다. 측정 결과가
             전략의 전제를 부정하면(예: ASD 혼화성 부적합) 되돌림 표가 <b>그 측정을 요구하는 전략만</b> 빼고
             전략 선택으로 돌아간다 — ASD가 실패했다고 미분화 후보까지 지우지 않는다. 계산값·예측값·실측값은
             서로 다른 변수라 실측이 예측을 덮지 않고, BCS 등급은 실측으로만 확정한다.`,
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
          <div class="f1-lvl key"><span class="n">0</span><span>입력 계약 — API 1행 · 요청 용량(유리염기 ±0.5%) · 고정 부형제 · 라벨 1일 최대 용량</span><em>요청한 그 약인가</em></div>
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
      note: `맨 앞의 <b>입력 계약</b>은 “이 조성이 위험한가”보다 먼저 “요청한 그 약·그 용량·그 고정 부형제인가”를 본다 —
             설계 AI가 용량을 무시하거나 주성분을 빠뜨리면 배합금기 규칙은 그걸 모르기 때문이다. 최대 용량은 FDA 라벨 원문과 함께
             저장돼 있고 약물은 이름이 아니라 구조(InChIKey)로 대조한다. 배합비는 MCC·탈크처럼 역할만으로 범위가 안 맞는 부형제를
             출처 있는 매핑표로 따로 판정한다.<br><br>
             폴더 번호만 보면 규제(<code class="f1-mono">05_regulatory</code>)가 마지막 같지만,
             실제로는 <b>소아 안전이 21번으로 가장 먼저 도는 축에 속한다.</b>
             값 몇 개를 조정해서 해결되는 문제가 아니라 성분 자체를 바꿔야 하는 반려라,
             무거운 공정 계산을 하기 전에 먼저 걸러내는 편이 낫기 때문이다.`,
    },

    {
      nav: "반려되면 어디로",
      kicker: "되돌림",
      title: "반려되면 처음부터가 아니라, 사유가 가리키는 자리로 돌아간다",
      lead: `규칙 게이트만 후보를 반려할 수 있다. 반려되면 어느 단계로 돌아갈지는 코드가 아니라
             <b>되돌림 전이표(14행)</b>의 한 행이 정한다 — 반려 판정이 행의 조건에 맞으면 그 행의 복귀 지점으로
             가고, 행이 적은 <b>제약</b>을 쌓는다. 다음 계획과 설계는 그 제약을 벗어날 수 없다.`,
      art: `
        <div class="f1-stack f1-seq">
          <div class="f1-lvl key"><span class="n">GATE</span><span>1대1 배합 금기 · 어린이 안전 상한 · 다성분 상호작용</span><em>같은 전략, 문제 성분만 제외</em></div>
          <div class="f1-lvl flow"><span class="n">G6R</span><span>공정 규칙 미충족 · 공정 경로 배제</span><em>그 전략·경로 제외 → 계획부터</em></div>
          <div class="f1-lvl flow"><span class="n">G4</span><span>실측 BCS II/IV인데 가용화 요소 없음 · 측정이 전략 전제를 부정</span><em>가족 요구 / 전략 제외 → 전략 선택부터</em></div>
        </div>
        <div class="f1-story f1-seq" style="margin-top:10px">
          <div class="f1-beat"><div class="who">RDKit</div><div class="what"><div class="card">
            플루옥세틴 → <span class="f1-mono">secondary_amine</span> 검출</div></div></div>
          <div class="f1-beat reject"><div class="who">게이트</div><div class="what"><div class="card">
            <b>⛔ INC002</b> — 2차 아민 + 유당 → Maillard 갈변 <span class="f1-mono">대안: Mannitol</span></div></div></div>
          <div class="f1-beat fix"><div class="who">되돌림</div><div class="what"><div class="card">
            <b>BT001 → GATE</b> <span class="f1-mono">exclude_ingredient = Lactose monohydrate</span>
            <span class="f1-mono">반성 → “같은 전략으로 성분만 교체, 대안 Mannitol”</span></div></div></div>
          <div class="f1-beat win"><div class="who">예외</div><div class="what"><div class="card">
            유당을 <b>반드시 넣으라고 고정</b>했다면 되돌리지 않는다 → <b>“이 제약으로는 통과가 없다”</b> + 대체 성분 (시나리오 1)</div></div></div>
        </div>`,
      note: `한 라운드에 반려가 여럿이면 <b>가장 깊은 복귀 지점</b>으로 가되 제약은 모두 쌓는다. 같은 자리로
             3번 돌아가도 풀리지 않으면 한 단계 위로 올리고, 전체 5회를 넘으면 사람에게 넘긴다. 제약이 모든
             전략을 지우면 설계하지 않고 <b>목표(QTPP) 재검토</b>로 끝난다.<br><br>
             설계 에이전트도 근거를 읽고 알려진 금기를 피하려 하지만, 판정 권한은 없다 — 현장 제약으로
             <b>반드시 넣어야 하는 성분</b>은 설계자가 회피하지 않고 그대로 넣으며, 걸리는지는 룰북이 판정한다. 다만 걸리려면 <b>두 쪽이 실제로 만나야 한다.</b> 룰북은
             <span class="f1-mono">Lactose monohydrate</span>, 처방은 “유당”이라 적으므로 부형제 마스터를 사전 삼아
             표기·국문명·계열명을 맞춘 뒤 대조한다. 같은 이유로 <b>구조를 못 읽었으면 통과가 아니라 판정 불가</b>다.<br><br>
             통과한 후보의 순위를 매기는 심사관도 출처 원칙을 따른다 — 점수에는 <b>검증된 DOI·PMID 인용</b>이 있어야 하고,
             없으면 그 점수는 무효로 합의에서 빠진다.`,
    },

    {
      nav: "② 2단계: QTPP부터 Design Space까지 ★",
      kicker: "2단계 · Design Space 도출",
      title: "고른 후보 하나를, 회귀식과 검증 가능한 Design Space까지",
      lead: `후보 처방은 “이렇게 만들면 될 것 같다”까지다. 2단계는 그 처방을 <b>프로토타입</b>으로 받아
             ICH Q8의 순서 그대로 간다 — 목표 제품 프로파일(<b>QTPP</b>)을 정하고, 품질특성마다 <b>CQA</b>인지 근거와 함께 가리고,
             원료 물성과 제형·공정 변수가 각 CQA에 얼마나 위험한지 <b>기전으로</b> 평가한다. 코드가 두 행렬을 합쳐 High인 변수를
             <b>DoE 변수 후보</b>로 정리하면(위험평가 보고서), 연구자가 실험 설계 표에 요인을 적어 실험하고, 그 결과로 <b>회귀식 · 반응 곡면 · ANOVA</b>를 만든 뒤,
             미래 배치가 모든 규격을 동시에 통과할 확률로 <b>Design Space</b>를 정하고 확인계획을 결과 전에 잠근다.
             후보의 조성과 요청 맥락(대상 · 용량 · 약물 함량 · 1단계 신호)은 <b>불변 Handoff</b>로 넘어온다.`,
      art: `
        <div class="f1-ladder f1-seq">
          <div class="f1-lvl"><span class="n">1</span>프로토타입 (Table 1) — 성분 · mg · % · 기능. 확인하고 [실행]</div>
          <div class="f1-lvl"><span class="n">2</span>QTPP (Table 3) — LLM 초안 → 행 추가·삭제·수정 → 승인</div>
          <div class="f1-lvl"><span class="n">3</span>CQA (Table 4) — CQA 여부의 논리적 근거, 위험평가에 넣을 CQA 확정</div>
          <div class="f1-lvl"><span class="n">4–5</span>원료 물성 위험평가 (Table 6 근거 → Table 5 행렬)</div>
          <div class="f1-lvl"><span class="n">6–7</span>제형·공정 변수 위험평가 (Table 8 근거 → Table 7 행렬) — 처방의 모든 부형제 + 조절 가능한 공정 파라미터</div>
          <div class="f1-lvl"><span class="n">8</span>종합 정리 — 두 행렬 병합 · DoE 변수 후보(High인 변수, 고르지 않음) · 바로 아래 위험평가 보고서 PDF</div>
          <div class="f1-lvl"><span class="n">9</span>실험 설계 표 (Table 9) — 요인 1–3 · 반응 1–4 · 행은 필요한 만큼, CSV 불러오기 · 엑셀 붙여넣기</div>
          <div class="f1-lvl"><span class="n">10</span>회귀식 (Table 10) — 평균·선형·2FI·2차를 순차 F와 예측 R²로 비교, 과적합 의심이면 수용 사유</div>
          <div class="f1-lvl"><span class="n">11</span>반응 곡면 (Figure 1) — 실험점 · 잔차 · 설계 지지 영역</div>
          <div class="f1-lvl"><span class="n">12</span>ANOVA (Table 11) — 부분 제곱합 · 적합결여 · 순수오차 → 최종 보고서 PDF</div>
          <div class="f1-lvl"><span class="n">13</span>Design Space — 규격 입력 → 미래 배치 공동 통과확률 ≥ 0.90 영역 · 권장 설정점(영역이 없으면 멈춘다)</div>
          <div class="f1-lvl"><span class="n">14</span>확인계획 잠금 — 설정점 · 경계점 · 강건성 + 동시 예측구간, 결과 전에 잠금</div>
          <div class="f1-lvl"><span class="n">15</span>확인배치 — 새 독립 배치 실측 → 규격 통과 × 예측구간 안(2×2) → VERIFIED 또는 영역 무효화</div>
        </div>`,
      note: `행렬(5·7단계)은 사람이 따로 칠하지 않는다 — <b>근거 표의 등급에서 코드가 만든다</b>. 그래서 행렬과 근거가 어긋날 수 없고,
             근거가 빠진 칸이 있으면 승인이 막힌다. 같은 판단을 공유하는 CQA는 근거 한 줄로 묶는다(논문 Table 6·8의 형식).
             회귀·ANOVA는 LLM 없이 계산하며, Monton 2026(CBD 구강붕해정)의 Table 10·11 값을 그대로 재현하는지 테스트로 고정했다.
             논문은 <b>참고 자료</b>다 — 위험 등급처럼 판단인 칸은 논문과 달라도 오답이 아니라 연구자가 근거를 확인할 지점이다.`,
    },

    {
      nav: "영역은 평균이 아니라 미래 배치로",
      kicker: "13단계 · 로르녹시캄 분산정 (Almotairi 2022 실측 15 run)",
      title: "평균으로는 77.2 %가 규격 안이었지만, 미래 배치로 보면 47.6 %다",
      lead: `평균 반응면이 규격 안이라는 것은 “평균적인 배치가 통과한다”는 뜻일 뿐이다. 다음에 만들 배치는 모형의 불확실성과
             배치 간 변동만큼 흔들린다. 그래서 2단계는 반응마다 <b>미래 배치의 예측분포</b>로 통과확률을 구해 곱하고,
             그 <b>공동 통과확률이 0.90 이상</b>인 곳만 Design Space로 본다. 분모는 설계점이 받치는 영역(convex hull)이다.`,
      art: `
        <div class="f1-cols c3 f1-seq">
          <div class="f1-box"><b>평균 반응면 기준</b><span>지지 영역 7,501점 중 <b>77.2 %</b>가 네 규격(분산 ≤ 180 s · 마손도 ≤ 1 % · DE30 ≥ 75 % · AV ≤ 15) 안</span></div>
          <div class="f1-box f1-det"><b>미래 배치 공동확률 ≥ 0.90</b><span>같은 15 run으로 <b>47.6 %</b> — 평균만 보면 약 1.6배 과대평가. 경계는 DE30이 정한다</span></div>
          <div class="f1-box f1-det"><b>권장 설정점</b><span>MCC:만니톨 2.7 · 혼합 12.5분 · 크로스포비돈 6.8 % (공동확률 0.991) — 논문 최적 3:1 · 11분 · 6.23 %는 참고점</span></div>
        </div>`,
      note: `확인계획은 결과를 보기 전에 잠근다 — 설정점 · 경계점 · 강건성(최악 변동) 세 점과 12개 비교의 동시 예측구간(설정점 DE30 71.9–92.8).
             새 독립 배치가 세 점 모두 규격을 통과하고 예측구간 안에 들어와야 VERIFIED이며, 그것도 “내부 사전계획 통과”일 뿐 규제 승인
             설계공간이 아니다. 영역이 비면(예: CBD 논문 규격에서 최대 0.883) 규격을 완화하지 않고 13단계에서 멈춘다.`,
    },

    {
      nav: "누가 무엇을 정하나",
      kicker: "2단계의 권한",
      title: "LLM은 초안을, 코드는 계산과 검사를, 결정은 연구자가",
      lead: `2단계의 모든 단계는 같은 길을 간다 — <b>초안</b>(LLM · 논문 값 · 연구자 입력) → <b>검사</b>(결정론) → <b>승인</b>(연구자).
             지금 단계만 고칠 수 있고, 앞 단계를 다시 열면 뒤 단계는 지우지 않고 <b>“다시 확인 필요”</b>로 표시한다.`,
      art: `
        <div class="f1-cols c3 f1-seq">
          <div class="f1-box f1-llm"><b>LLM — 초안만</b><span>QTPP · CQA 근거 · 위험평가 근거.
            입력에 없는 수치를 쓰면 “출처 확인” 경고가 붙는다. 응답이 없으면 아무것도 채우지 않는다</span></div>
          <div class="f1-box f1-det"><b>코드 — 계산과 검사</b><span>행렬 · 후보 변수(High) · 회귀 · 곡면 · ANOVA · 공동확률 영역 · 확인점.
            빠진 칸, 확정 CQA 밖의 열, 공정 이름을 공정 변수로 쓴 경우, 이름 없는 요인, 추정 불가 모형, 사유 없는 과적합, 빈 영역은 승인 불가</span></div>
          <div class="f1-box"><b>연구자 — 선택과 승인</b><span>행 추가·삭제·수정, 실험 요인 결정(9단계 표), 회귀 모형 선택(제안과 다르면 기록),
            단계마다 승인. 누가 언제 어떤 출처의 몇 번째 판을 승인했는지 이력으로 남는다</span></div>
        </div>`,
      note: `CBD 논문으로 시작한 시연에서는 단계마다 <b>논문 값으로 채우기</b>와 <b>참고 · 논문의 판단</b>이 열려,
             LLM 초안이 논문과 어디서 갈리는지 칸 단위로 볼 수 있다. 논문은 <b>정답지가 아니라 참고 자료</b>다 —
             다른 칸은 오답이 아니라 연구자가 근거를 확인할 지점이고, 결정은 단계마다 연구자의 승인이다.
             수치는 모두 논문(PMC13519653)의 표에서 옮긴 값이다.`,
    },

    {
      nav: "실제로 참고한 연구가 있다",
      kicker: "이 설계의 출처 · Robin (FutureHouse)",
      title: "심사관의 기준은 실제 연구의 지시문을 읽고 정했다",
      lead: `<b>Robin</b>은 비영리 연구소 FutureHouse가 만든 AI 시스템으로, 2026년 국제 학술지
             <b>Nature</b>에 발표됐다. 사람의 개입 없이 스스로 가설을 세우고 실험을 제안해서,
             노년 실명의 주요 원인인 <b>황반변성을 치료할 수 있는 약 후보(ripasudil)를 실제로
             찾아낸</b> 사례다. FutureHouse는 Robin이 AI에게 내리는 지시문(프롬프트) 원문을
             공개했고, 그 원문을 문장 단위로 대조해 후보 탐색의 <b>심사</b>에 반영했다.`,
      art: `
        <div class="f1-arch f1-seq">
          <div class="f1-tier">
            <header><span>Robin 프롬프트 원문</span>
              <span>GitHub Future-House/robin · robin/prompts.py</span></header>
            <div class="f1-said f1-mono">"Prioritize your evaluation based on these key criteria"
              <br>— CANDIDATE_RANKING_SYSTEM_PROMPT</div>
            <div class="f1-said f1-mono">"It is not necessary to propose a follow-up experiment if there is
              nothing significant to follow up on" — FOLLOWUP_SYSTEM_MESSAGE</div>
          </div>
          <div class="f1-flowmark">▼ 후보 탐색의 심사관</div>
          <div class="f1-cols c3">
            <div class="f1-box f1-llm"><b>평가 기준에 순서</b>
              <span>근거 강도 → 잔여 위험 → 실현 가능성 → 참신성. 참신함만으로 점수를 올리지 않는다</span></div>
            <div class="f1-box f1-det"><b>근거로 판단</b>
              <span>표현의 설득력이 아니라 제시된 근거로 — 검증된 문헌 id가 없는 심사는 점수 없음</span></div>
            <div class="f1-box"><b>억지로 채우지 않기</b>
              <span>짚을 것이 없으면 제안을 비워 둔다</span></div>
          </div>
        </div>`,
      note: `반대로 <b>가져오지 않은 것</b>도 있다.
             Robin은 시험 이름을 AI가 자유롭게 짓게 하지만, 여기서는 목록 밖 시험을 버린다(재현 가능한
             출처와 판정 기준이 남지 않기 때문). 쌍대비교 순위 집계도 호출 수가 제곱으로 늘어 쓰지 않았다.`,
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
          <b>이 정책은 그럴듯해 보이는 규칙에도 예외 없이 적용된다.</b><br>
          예를 들어 "아세트아미노펜 + 유당 → 갈변" 같은 판정은 나오지 않는다 — 분자 구조를 계산하면
          아세트아미노펜은 아미드라 반응할 아민이 없기 때문이다. "소아 SLS 10mg 초과" 같은 규칙도
          출처를 추적하면 EMA 기준의 SLS 항목이 <b>경피 투여 전용</b>이고 경구 소아 상한은 존재하지 않아,
          <code class="f1-mono">NO_SOURCE_FOUND / NOT_A_RULE</code>로 읽는 단계에서 빠진다.
          <b>근거가 없는 판정은 하지 않는다 — 그것이 이 시스템이 제공하려는 가치다.</b>
        </div>`,
      note: `규제 기관을 설득해야 하는 분야에서는 "그럴듯한 규칙이 많은 것"보다
             <b>"근거 없는 규칙은 안 돌린다"</b>가 훨씬 중요한 자산이라고 판단했다.`,
    },
  ];

  /* 마지막 단계 끝에 붙는 실행 유도 — 설명이 끝나면 바로 화면을 쓰게 만든다. */
  const CTA = `
    <div class="f1-cta">
      <p><b>이제 직접 돌려 보세요.</b> 가운데 입력칸에 약 이름·대상·제형·용량을 말하면 설계 실행 카드를 만들어 줍니다.
        폼은 입력칸 아래 <b>직접 입력</b>에 있습니다. 시연 카드는 발표 자료의 세 시나리오입니다 — ① <b>로르녹시캄 분산정</b>은 요청부터
        후보 → 개발 착수 → 9단계에서 논문 실측 15 run을 불러와 공동확률 Design Space까지, ② <b>고령자 암로디핀 + 유당 고정</b>은 규칙이
        제약 자체를 반려하는 경우, ③ <b>VX-770</b>은 구조식만 있는 신규물질에서 갈리는 값(DSC)만 되묻는 경우. 네 번째 카드는
        <b>CBD 구강붕해정</b> 논문 표로 2단계를 걷습니다. 규칙 ID를 누르면 <b>원본 CSV 행과 출처</b>가 열립니다.</p>
      <button type="button" id="guide-finish">설명 닫고 실행하기 →</button>
    </div>`;

  /* ── 렌더링 ─────────────────────────────────────────────────────── */
  const el = (id) => document.getElementById(id);
  let index = 0;
  const visited = new Set();

  function buildRail() {
    el("guide-count").textContent = `${STEPS.length}단계 · 약 12분`;
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
