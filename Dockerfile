# 농구 연습 계획 Agent (웹 화면 + /query API)
# 빌드: docker build -t basketball-agent .
# 실행: docker run --rm -p 8000:8000 --env-file .env \
#         -v basketball_data:/app/data -v basketball_chroma:/app/chroma_db basketball-agent
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성을 먼저 설치해 코드만 바뀔 때 빌드 캐시를 쓴다
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY web ./web
COPY data ./data
COPY evaluation ./evaluation

# 키가 든 .env는 이미지에 넣지 않는다 (--env-file로 전달)
# 계정·기록·계획 DB(data/)와 검색 인덱스(chroma_db/)는 볼륨에 둔다
RUN useradd --create-home app && mkdir -p /app/chroma_db && chown -R app:app /app
USER app
VOLUME ["/app/data", "/app/chroma_db"]

EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
