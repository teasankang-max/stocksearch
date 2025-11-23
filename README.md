# KRX 월가 AI 애널리스트 텔레그램 봇

KRX 공식 데이터(pykrx) 기반 기업 분석 + Gemini 리포트 + 일봉 차트 + 마켓맵(코스피/코스닥) 스크린샷 전송(Playwright) 봇.

## 주요 기능
- 기업 분석: KRX 실데이터 조회, PER/PBR/EPS/BPS/DIV, 최근 영업일 기준가, 일봉 차트 이미지(mplfinance), Gemini 리포트
- 시장 현황: 코스피 지수 최근 영업일 기준 조회 + 요약 코멘트(Gemini)
- 마켓맵: 한국경제 마켓맵(코스피/코스닥) “영역만” 캡처하여 이미지 전송(Playwright + Chromium)

## 요구 사항
- Python 3.10+ (Windows/WSL/Linux/ macOS), 권장 가상환경
- Telegram Bot Token, Google API Key (Gemini)
- 마켓맵 캡처용: Playwright + Chromium

## 설치

### 1) 저장소 클론
```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
