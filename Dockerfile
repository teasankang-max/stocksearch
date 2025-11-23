# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.47.2-jammy

# 시스템 로케일 기본 설정(선택)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 먼저 복사 후 설치 (캐시 활용)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 브라우저(크로미움) 보장
RUN playwright install chromium

# 앱 소스 복사
COPY . /app

# 환경변수로 키 주입 가능 (my_keys.py 없는 경우 대비)
# ENV TELEGRAM_TOKEN=""
# ENV GOOGLE_API_KEY=""

CMD ["python", "main.py"]
