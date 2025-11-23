# Dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 시스템 패키지: 네트워크/폰트/크롬 런타임에 필요한 최소 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg \
    # playwright 크로미움 런타임 의존성(주요)
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxkbcommon0 libxrandr2 \
    libxshmfence1 libpango-1.0-0 libcairo2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 의존성 설치
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 브라우저 및(가능 시) 의존성 자동 설치
# install-deps는 배포 환경에 따라 생략될 수 있으므로 실패해도 계속 진행
RUN python -m playwright install-deps chromium || true \
 && python -m playwright install chromium

# 앱 소스 복사
COPY . /app

# 런타임에 환경변수(TELEGRAM_TOKEN/GOOGLE_API_KEY) 주입 필요
CMD ["python", "main.py"]
