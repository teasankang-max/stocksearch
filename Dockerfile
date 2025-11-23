FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# Playwright/Chromium 및 과학 패키지에 필요한 런타임 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg \
    tzdata \
    # chromium 런타임 의존성
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxkbcommon0 libxrandr2 \
    libxshmfence1 libpango-1.0-0 libcairo2 fonts-liberation \
    # 빌드 휠 fallback(혹시 바이너리 휠이 없을 때 대비)
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치: 바이너리 휠 우선 + 재시도 옵션
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefer-binary --retries 5 -r requirements.txt

# Playwright 브라우저 설치(의존성 자동 설치 시도 → 실패해도 계속)
RUN python -m playwright install-deps chromium || true \
 && python -m playwright install chromium

# 앱 소스 복사
COPY . /app

# 런타임에 TELEGRAM_TOKEN / GOOGLE_API_KEY 환경변수 주입 필요
CMD ["python", "main.py"]
