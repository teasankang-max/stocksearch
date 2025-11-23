FROM python:3.11-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180

WORKDIR /app

# 런타임 & 빌드 의존성 (과학패키지/Playwright/Chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata ca-certificates curl wget gnupg \
    build-essential gfortran pkg-config \
    libatlas-base-dev liblapack-dev \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxkbcommon0 libxrandr2 \
    libxshmfence1 libpango-1.0-0 libcairo2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# PyPI 설정(불안정 네트워크 대응용, 원치 않으면 삭제 가능)
RUN python -m pip config set global.index-url https://pypi.org/simple

# 요구사항 파일
COPY requirements.txt /app/requirements.txt

# pip 업그레이드 + 바이너리 휠 우선 설치
RUN pip install --upgrade pip setuptools wheel

# 분할 설치(어디서 막히는지 추적 쉬움 + 캐시 효율)
RUN pip install --no-cache-dir --prefer-binary numpy==1.26.4
RUN pip install --no-cache-dir --prefer-binary pandas==2.2.2
RUN pip install --no-cache-dir --prefer-binary matplotlib==3.8.4 mplfinance==0.12.10b0
RUN pip install --no-cache-dir --prefer-binary pykrx==1.0.46
RUN pip install --no-cache-dir --prefer-binary httpx==0.27.2 python-telegram-bot==20.7 google-generativeai==0.7.2 playwright==1.47.2

# (참고) 한 줄 설치를 원하면 아래로 대체 가능
# RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Playwright 브라우저 설치(의존성 자동설치 시도, 실패 무시)
RUN python -m playwright install-deps chromium || true \
 && python -m playwright install chromium

# 소스 복사
COPY . /app

# 런타임: TELEGRAM_TOKEN / GOOGLE_API_KEY 환경변수 필요
CMD ["python", "main.py"]
