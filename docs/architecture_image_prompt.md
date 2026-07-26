# Formula 1 — 전체 아키텍처 이미지 생성 프롬프트

가로(landscape) 방향으로 에이전트 시스템 전체 흐름을 한눈에 볼 수 있는 아키텍처
다이어그램/인포그래픽을 AI로 생성하기 위한 상세 프롬프트다.

> 💡 텍스트 라벨이 많은 아키텍처 도해는 **Ideogram 3.0**, **GPT-Image (ChatGPT)**,
> **Recraft** 처럼 글자 렌더링이 정확한 모델에서 가장 잘 나온다. Midjourney는 분위기는
>좋지만 글자가 깨지므로, Midjourney를 쓸 경우 아래 라벨을 나중에 직접 얹는 것을 권장한다.
> 화면비는 **16:9 (또는 21:9 와이드)** 로 지정할 것.

---

## 1) 메인 프롬프트 (모든 라벨이 한글로 렌더링되도록 작성)

> 이미지 안의 **모든 텍스트가 한글**로 나오도록 지시문을 포함했다. 영어 장면 묘사 +
> 큰따옴표 안의 한글 라벨을 그대로 그리게 하는 방식이 Ideogram/GPT-Image에서 가장 정확하다.
> 아래 블록을 통째로 복사해 입력할 것.

```
Horizontal (16:9) flat-vector architecture diagram of a multi-agent AI system for
drug-formulation design. Left-to-right flow, 5 stages, bold arrows, rounded cards,
light background, one accent color per stage (purple, blue, green, orange, teal).
Render ALL text in KOREAN (Noto Sans KR), exactly as quoted, no English.

Title: "Formula 1 — 자기조직형 멀티 에이전트 제형 설계 시스템"

1 (gray) 입력: "신약 API(SMILES) · In-silico 예측 · 전처방 데이터 · 자연어 요구"
2 (purple) 지휘: "총괄 오케스트레이터"  +  "반성 에이전트"
3 (blue) 병렬 설계: "직접타정" · "습식과립" · "가용화 전략"
4 (green) "규칙 검사 도구벨트 (오차 0%)" fed by CSV icon "규칙표 CSV";
  (orange) "동적 심사위원단": "소아 안전" · "가용화" · "규제(+RAG)";
  diamond below: "합의 도출"
5 (teal) "Wet-lab 실험" → "실험 결과 재입력" → "피드백 해석기"

One bold dashed teal arrow curves from "피드백 해석기" (far right) back to
"반성 에이전트", labeled "자가수정 루프". Clean, presentation-ready, no people.
```

> ⚠️ 한글은 이미지 모델이 종종 깨뜨린다. 라벨이 뭉개지면: ① 라벨 개수를 줄여
> 재생성하거나, ② 도해는 영문/무텍스트로 뽑은 뒤 아래 3)의 라벨 표를 참고해 한글을 직접
> 얹거나, ③ mermaid/draw.io로 그리는 편이 확실하다.

---

## 2) 다이어그램 도구(mermaid/draw.io)로 직접 그릴 때의 구조 명세

이미지 생성이 텍스트를 깨뜨릴 때를 대비한 정확한 구조 정의. 좌→우 5열.

| 열 | 계층 | 노드 | 색 |
|---|---|---|---|
| 1 | 입력 | API(SMILES)+In-silico 예측+전처방 데이터+자연어 요구 | 회색 |
| 2 | 지휘 | 오케스트레이터 / 반성 에이전트 | 보라 |
| 3 | 설계(병렬) | 직접타정 / 습식과립 / 가용화 | 파랑 |
| 4a | 검증(정량) | 규칙 도구벨트 6전략 ← 규칙표 CSV | 초록 |
| 4b | 검증(정성) | 동적 심사위원단(소아/가용화/규제+RAG) | 주황 |
| 4c | 합의 | 하드페일 게이트 + 가중 심사점수 | 회색 |
| 5 | closed-loop | Wet-lab 실험(human) → 결과 재입력 → 피드백 해석기 | 청록 |

**핵심 화살표 흐름:**
`입력 → 오케스트레이터 → (설계 A/B/C 병렬) → 도구벨트+심사단 → 합의`
`합의 --반려--> 반성 에이전트 --개선지시--> 오케스트레이터` (내부 재설계 루프)
`합의 --통과--> Wet-lab 실험 → 결과 재입력 → 피드백 해석기`
`피드백 해석기 ==자가수정 루프(점선, 최대 5회)==> 반성 에이전트` (실물 실험까지 포함한 바깥 closed-loop)

가장 강조할 시각 요소는 **맨 오른쪽 피드백 해석기에서 왼쪽 반성 에이전트로 되돌아가는
큰 곡선 화살표**다. 이 한 줄이 "가상 설계 → wet-lab → 실험결과 재입력 → AI 자가수정"이라는
closed-loop 정체성을 한눈에 보여준다.
