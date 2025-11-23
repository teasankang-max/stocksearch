FROM mcr.microsoft.com/playwright/python:v1.47.2-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 브라우저 설치
RUN playwright install chromium

COPY . /app

# 런타임에 Secrets를 환경변수로 주입해야 함
CMD ["python", "main.py"]
