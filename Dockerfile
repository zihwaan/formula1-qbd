# Formula 1 — QbD 제형 설계 검증 엔진 (zihwan.com/f)
#
# 배포 방식은 이 저장소가 사는 홈서버 규약을 따른다: 로컬에서 `formula1:latest`를 빌드하고
# k8s가 `imagePullPolicy: Never`로 그 이미지를 그대로 집어 간다(레지스트리 push 없음).
# 자세한 절차는 ~/zihwan/CLAUDE.md 의 "배포 플레이북" 참고.
#
# Python 3.12 — langgraph/fastapi/sse-starlette가 3.10+를 요구하고, rdkit 휠도 3.12가 가장 안전하다.
FROM python:3.12-slim

# rdkit 휠이 동적으로 링크하는 시스템 라이브러리. slim 이미지엔 없어서 직접 넣어야 한다.
#   libexpat1            rdMolDraw2D import 자체가 실패한다 (libexpat.so.1)
#   libxrender1/libxext6 2D 구조 렌더링
#   libgomp1             OpenMP 런타임
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 libxrender1 libxext6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 의존성을 먼저 설치해 레이어 캐시를 살린다 — 룰북 CSV나 프론트만 고칠 때 재설치하지 않는다.
# 잠금 파일로 설치하므로 대회 제출본과 파드가 같은 버전을 쓴다.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# 애플리케이션 (룰북 CSV·설정·프롬프트가 런타임에 읽히므로 database/·config/ 도 함께 들어간다)
COPY formula/ ./formula/
COPY web/ ./web/
COPY config/ ./config/
COPY database/ ./database/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY pyproject.toml README.md ./

EXPOSE 8000

# 단일 워커. run 상태와 SSE 구독 큐를 프로세스 메모리에 들고 있으므로 워커를 늘리면
# 스트림이 자기 run을 못 찾는다(다중화하려면 먼저 상태를 외부 저장소로 빼야 한다).
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
