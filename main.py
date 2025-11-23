# -*- coding: utf-8 -*-
import os
import re
import io
import asyncio
import logging
import warnings
import inspect
from datetime import datetime, timedelta
from difflib import get_close_matches
from typing import Optional, Tuple

import pandas as pd
from pykrx import stock  # KRX 데이터
import google.generativeai as genai

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from telegram.request import HTTPXRequest

# pykrx 경고 줄이기
warnings.filterwarnings("ignore", category=UserWarning, module="pykrx")

# -----------------------------
# 비밀키 로드 (my_keys 모듈 또는 환경변수)
# -----------------------------
try:
    import my_keys as secrets  # GOOGLE_API_KEY, TELEGRAM_TOKEN
    GOOGLE_API_KEY = secrets.GOOGLE_API_KEY
    TELEGRAM_TOKEN = secrets.TELEGRAM_TOKEN
except Exception:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

if not GOOGLE_API_KEY or not TELEGRAM_TOKEN:
    raise RuntimeError("GOOGLE_API_KEY 또는 TELEGRAM_TOKEN이 설정되지 않았습니다.")

# -----------------------------
# 로깅 (조용 + 토큰 마스킹)
# -----------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING").upper()
level = getattr(logging, LOG_LEVEL, logging.WARNING)

logging.basicConfig(
    level=level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

for noisy in ("httpx", "httpcore", "telegram", "telegram.ext", "apscheduler"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

class RedactTokenFilter(logging.Filter):
    pattern = re.compile(r'bot(\d+):[A-Za-z0-9_-]+')
    def filter(self, record):
        try:
            record.msg = self.pattern.sub(r'bot\\1:[REDACTED]', str(record.msg))
        except Exception:
            pass
        return True

for h in logging.getLogger().handlers:
    h.addFilter(RedactTokenFilter())

# -----------------------------
# Gemini 설정 (요청대로 고정)
# -----------------------------
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# -----------------------------
# 리포트 프롬프트 (용어 설명 제거)
# -----------------------------
SYSTEM_PROMPT = """
[SYSTEM]
당신은 월스트리트 20년 경력의 시니어 애널리스트입니다.
제공된 [KRX 공식 데이터]를 철저하게 분석하여 조언합니다.
데이터의 '기준일'을 최우선으로 고려하세요.

[보고서 양식]

📊 3줄 요약: (KRX 데이터 기반 현재 상황 압축)
💡 핵심 투자 포인트: (중요 이유 3가지)
📈 펀더멘탈 분석: (제공된 PER, PBR, EPS 수치를 동종업계/과거와 비교 평가)
✅ 실행 체크리스트: (매수/보류/매도 행동 지침)
주의: '[OUTPUT FORMAT]' 같은 제목은 출력하지 마세요.
""".strip()

# -----------------------------
# 유틸
# -----------------------------
def _safe_num(val, digits: int = 2) -> str:
    if val is None:
        return "정보없음"
    try:
        if pd.isna(val):
            return "정보없음"
    except Exception:
        pass
    try:
        if isinstance(val, int) or (isinstance(val, float) and float(val).is_integer()):
            return f"{int(val):,}"
        return f"{float(val):,.{digits}f}"
    except Exception:
        return str(val)

def _fmt_pct(val) -> str:
    s = _safe_num(val, 2)
    return f"{s}%" if s != "정보없음" else s

def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")

async def _genai_text(prompt: str) -> str:
    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        return (resp.text or "").strip()
    except Exception as e:
        logging.exception("Gemini 호출 오류")
        return f"(AI 응답 오류: {e})"

def _get_ohlcv_by_date(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
    try:
        return stock.get_market_ohlcv(fromdate, todate, ticker)
    except Exception:
        return stock.get_market_ohlcv_by_date(fromdate, todate, ticker)

# -----------------------------
# KRX 도구 함수
# -----------------------------
def find_ticker_code(stock_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    stock_name = (stock_name or "").strip()
    if not stock_name:
        return None, None, "정확한 종목명을 입력해주세요. (예: 삼성전자, NAVER, 에코프로비엠)"

    try:
        tickers_kospi = stock.get_market_ticker_list(market="KOSPI")
        tickers_kosdaq = stock.get_market_ticker_list(market="KOSDAQ")

        for code in tickers_kospi:
            if stock.get_market_ticker_name(code) == stock_name:
                return code, "KOSPI", None
        for code in tickers_kosdaq:
            if stock.get_market_ticker_name(code) == stock_name:
                return code, "KOSDAQ", None

        all_names = [stock.get_market_ticker_name(c) for c in (tickers_kospi + tickers_kosdaq)]
        candidates = get_close_matches(stock_name, all_names, n=5, cutoff=0.6)
        if candidates:
            return None, None, "혹시 이 중에 있나요? " + ", ".join(candidates)
        return None, None, "KRX에 등록된 정확한 종목명을 입력해주세요."

    except Exception as e:
        logging.exception("티커 검색 에러")
        return None, None, f"티커 검색 에러: {e}"

def get_latest_fundamental_and_price(ticker: str, lookback_days: int = 14):
    end_date = _today_yyyymmdd()
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")

    df_fund = stock.get_market_fundamental_by_date(fromdate=start_date, todate=end_date, ticker=ticker)
    if df_fund.empty:
        return None, None, None

    recent_row = df_fund.iloc[-1]
    found_date = recent_row.name.strftime("%Y-%m-%d")
    dstr = found_date.replace("-", "")

    df_price = _get_ohlcv_by_date(dstr, dstr, ticker)
    price = None if df_price.empty else df_price.iloc[0].get("종가", None)

    return recent_row, found_date, price

def build_stock_info_text(stock_name: str, ticker: str, market: str, row: pd.Series, found_date: str, price) -> str:
    per = _safe_num(row.get("PER"))
    pbr = _safe_num(row.get("PBR"))
    eps = _safe_num(row.get("EPS"))
    bps = _safe_num(row.get("BPS"))
    div = _fmt_pct(row.get("DIV"))
    price_s = "확인불가" if price is None else f"{int(price):,}"

    info = (
        f"■ 종목명: {stock_name} ({ticker} / {market})\n"
        f"■ 기준일: {found_date} (최근 영업일)\n"
        f"■ 현재가: {price_s}원\n"
        f"■ PER: {per}배\n"
        f"■ PBR: {pbr}배\n"
        f"■ EPS: {eps}원\n"
        f"■ BPS: {bps}원\n"
        f"■ 배당수익률: {div}\n"
        f"(출처: KRX 정보데이터시스템)"
    )
    return info

def get_krx_real_data(stock_name: str) -> Tuple[Optional[str], str]:
    try:
        code, market, hint = find_ticker_code(stock_name)
        if not code:
            return None, hint or f"KRX에 등록된 정확한 종목명을 입력해주세요. (입력: {stock_name})"

        row, found_date, price = get_latest_fundamental_and_price(code)
        if row is None:
            return code, "최근 데이터를 찾을 수 없습니다. (거래정지/휴장 가능)"
        info_text = build_stock_info_text(stock_name, code, market, row, found_date, price)
        return code, info_text
    except Exception as e:
        logging.exception("KRX 데이터 에러")
        return None, f"KRX 데이터 접속 오류: {e}"

def get_recent_index_close(index_code: str = "1001", lookback_days: int = 14) -> Tuple[Optional[int], Optional[str]]:
    for i in range(lookback_days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        df = stock.get_index_ohlcv_by_date(d, d, index_code)
        if not df.empty:
            return int(df.iloc[0]["종가"]), datetime.strptime(d, "%Y%m%d").strftime("%Y-%m-%d")
    return None, None

# -----------------------------
# 차트 생성: 캔들(가능시) 또는 종가 라인
# -----------------------------
def make_daily_chart_image(ticker: str, lookback_days: int = 180) -> Optional[bytes]:
    try:
        end_date = _today_yyyymmdd()
        start_date = (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        if df.empty:
            return None
        df = df.copy()
        df.index = pd.to_datetime(df.index)

        buf = io.BytesIO()
        try:
            import mplfinance as mpf
            mpf_df = df.rename(columns={"시가":"Open","고가":"High","저가":"Low","종가":"Close","거래량":"Volume"})
            mpf.plot(mpf_df, type="candle", volume=True, style="yahoo",
                     mav=(5,20,60), figsize=(10,6),
                     savefig=dict(fname=buf, dpi=150, bbox_inches="tight"))
            buf.seek(0)
            return buf.getvalue()
        except Exception:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10,4))
            plt.plot(df.index, df["종가"], label="Close", color="#2E86DE")
            plt.title("일봉 종가 추이")
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(buf, format="png", dpi=150)
            plt.close()
            buf.seek(0)
            return buf.getvalue()
    except Exception:
        logging.exception("차트 생성 오류")
        return None

# -----------------------------
# 마켓맵 스크린샷 (요소만 캡처)
# -----------------------------
MARKET_URL = {
    "KOSPI": "https://markets.hankyung.com/marketmap/kospi",
    "KOSDAQ": "https://markets.hankyung.com/marketmap/kosdaq",
}

MARKETMAP_SELECTORS = [
    "#marketMap",
    "div.marketmap",
    "div.market-map",
    "div.marketmap__container",
    "section.marketmap",
    "div[class*='marketmap']",
    "div[class*='market-map']",
    "div[class*='treemap']",
    "#treemap",
    ".treemap",
    "section[class*='market'] div[class*='map']",
]

async def get_marketmap_element_screenshot(market: str) -> Optional[bytes]:
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except Exception:
        logging.warning("Playwright 미설치/로드 실패. 이미지 대신 링크로 안내합니다.")
        return None

    url = MARKET_URL[market]
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1  # 용량 절감
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            target = None
            # 셀렉터들에서 탐색
            for sel in MARKETMAP_SELECTORS:
                try:
                    loc_all = page.locator(sel)
                    cnt = await loc_all.count()
                    if cnt > 0:
                        candidate = loc_all.first
                        await candidate.wait_for(state="visible", timeout=5000)
                        box = await candidate.bounding_box()
                        if box and box["width"] >= 300 and box["height"] >= 200:
                            target = candidate
                            break
                except PWTimeout:
                    continue
                except Exception:
                    continue

            # 가장 큰 canvas fallback
            if target is None:
                canvases = page.locator("canvas")
                n = await canvases.count()
                best_i, best_area = -1, 0
                for i in range(n):
                    try:
                        bb = await canvases.nth(i).bounding_box()
                        if bb:
                            area = bb["width"] * bb["height"]
                            if area > best_area:
                                best_area = area
                                best_i = i
                    except Exception:
                        pass
                if best_i >= 0 and best_area > 0:
                    target = canvases.nth(best_i)

            if target is None:
                await browser.close()
                return None

            img = await target.screenshot(type="jpeg", quality=80)  # 요소만 캡처
            await browser.close()
            return img

    except Exception:
        logging.exception("마켓맵 스크린샷 실패")
        return None

# -----------------------------
# 키보드/메뉴
# -----------------------------
def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 기업 분석", callback_data='btn_analysis')],
            [InlineKeyboardButton("📈 시장 현황", callback_data='btn_market')],
            [InlineKeyboardButton("🗺️ 코스피", callback_data='map_kospi'),
             InlineKeyboardButton("🗺️ 코스닥", callback_data='map_kosdaq')],
        ]
    )

async def send_home_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await context.bot.send_message(
        chat_id=chat_id,
        text="메뉴를 선택하세요. (마켓맵은 영역만 캡처하여 전송합니다)",
        reply_markup=home_keyboard()
    )

# -----------------------------
# 텔레그램 핸들러
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 기본 모드 리셋
    context.user_data['mode'] = None
    await send_home_menu(context, update.effective_chat.id)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'btn_analysis':
        context.user_data['mode'] = 'btn_analysis'
        await query.edit_message_text(
            "🔍 KRX에서 분석할 <b>정확한 종목명</b>을 입력해주세요.\n(예: 삼성전자, NAVER, 에코프로비엠)",
            parse_mode="HTML"
        )

    elif query.data == 'btn_market':
        context.user_data['mode'] = 'btn_market'
        await query.edit_message_text("📈 KRX 시장 데이터 분석 중...")

        kospi_val, kospi_date = get_recent_index_close("1001")
        market_info = (
            f"현재 코스피 지수: {kospi_val:,} (기준일: {kospi_date})"
            if kospi_val is not None else
            "시장 지수 조회 실패"
        )

        prompt = f"{SYSTEM_PROMPT}\n\n[정보] {market_info}\n오늘 한국 증시 시황을 요약하고 간단히 전망해주세요."
        text = await _genai_text(prompt)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        await send_home_menu(context, update.effective_chat.id)

    elif query.data in ('map_kospi', 'map_kosdaq'):
        market = "KOSPI" if query.data == 'map_kospi' else "KOSDAQ"
        await query.edit_message_text(f"🗺️ {market} 마켓맵 렌더링 중... 잠시만요.")
        img = await get_marketmap_element_screenshot(market)
        url = MARKET_URL[market]

        if img:
            try:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=img,
                    caption=f"{market} 마켓맵 (출처: 한국경제)\n{url}"
                )
            except Exception:
                logging.exception("텔레그램 이미지 전송 실패")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"이미지 전송 지연으로 링크로 안내합니다: {url}"
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"마켓맵 이미지를 생성하지 못했습니다. 링크로 확인해주세요:\n{url}"
            )
        await send_home_menu(context, update.effective_chat.id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    user_input = (update.message.text or "").strip()

    if mode != 'btn_analysis':
        await send_home_menu(context, update.effective_chat.id)
        return

    # 기업 분석 모드
    msg = await update.message.reply_text(f"🔍 '{user_input}' KRX 데이터 조회 중...\n(잠시만 기다려주세요)")
    code, stock_info = get_krx_real_data(user_input)

    if not code:
        await msg.edit_text(stock_info)
        return

    await msg.edit_text(
        f"✅ 데이터 확보 완료!\n\n{stock_info}\n\n🖼️ 일봉 차트 생성 중...",
        parse_mode="HTML"
    )

    # 일봉 차트 전송
    chart_bytes = await asyncio.to_thread(make_daily_chart_image, code)
    if chart_bytes:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=chart_bytes,
            caption=f"📈 {user_input} 일봉 차트"
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="차트 생성에 실패했습니다. (mplfinance 설치 권장)"
        )

    # AI 리포트
    final_prompt = f"""
{SYSTEM_PROMPT}

[분석대상] {user_input}
[KRX 공식 데이터]
{stock_info}

위 팩트 데이터를 기반으로 투자자를 위한 리포트를 작성하세요.
데이터에 '정보없음'이나 0이 많다면 그 이유도 설명하세요.
""".strip()

    text = await _genai_text(final_prompt)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text
    )
    # 분석 끝나면 홈 메뉴
    await send_home_menu(context, update.effective_chat.id)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Unhandled exception", exc_info=context.error)
    # 사용자에게 불필요한 에러 메시지는 보내지 않음

# -----------------------------
# 앱 빌더 (타임아웃/과부하 최소화)
# -----------------------------
def build_app():
    # 텔레그램 요청 타임아웃 확대 (이미지 전송 안정화)
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=120.0,
        write_timeout=120.0,
        pool_timeout=30.0,
    )

    builder = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request)
    try:
        builder = builder.concurrent_updates(2)  # 동시 처리 제한
    except Exception:
        pass

    app = builder.build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    return app

# -----------------------------
# 엔트리 포인트 (수동 초기화 → 폴링)
# -----------------------------
async def runner():
    logging.info("🤖 봇 실행 중... (KRX/리포트/차트/마켓맵)")
    app = build_app()

    await app.initialize()
    await app.start()

    sp = app.updater.start_polling
    kwargs = {"poll_interval": 2.0, "timeout": 120, "drop_pending_updates": True}
    if inspect.iscoroutinefunction(sp):
        await sp(**kwargs)
    else:
        sp(**kwargs)

    # 대기
    wait_fn = getattr(app.updater, "wait", None)
    idle_fn = getattr(app.updater, "idle", None)
    if callable(wait_fn):
        if inspect.iscoroutinefunction(wait_fn):
            await wait_fn()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, wait_fn)
    elif callable(idle_fn):
        if inspect.iscoroutinefunction(idle_fn):
            await idle_fn()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, idle_fn)
    else:
        await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(runner())
