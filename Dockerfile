# 1. 호환성이 가장 좋은 Python 3.10 Slim 버전 사용 (Alpine 사용 금지)
FROM python:3.10-slim

# 2. 시스템 패키지 업데이트 및 필수 도구 설치 (git 등)
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. 타임존 설정 (한국 시간)
ENV TZ=Asia/Seoul

# 5. 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 소스 코드 복사
COPY . .

# 7. 봇 실행
CMD ["python", "main.py"]
