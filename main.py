import os
import asyncio
from datetime import datetime, timedelta
from pykrx import stock
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# ==========================================
# [설정] 환경 변수 로드 (중요!)
# ==========================================
# 로컬 테스트용 (python-dotenv 필요)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# API 키 누락 시 에러 방지
if not GOOGLE_API_KEY or not TELEGRAM_TOKEN:
    print("❌ 오류: 환경 변수(GOOGLE_API_KEY, TELEGRAM_TOKEN)가 설정되지 않았습니다.")
    exit(1)

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# ==========================================
# [프롬프트]
# ==========================================
SYSTEM_PROMPT = """
[SYSTEM]
당신은 월스트리트 20년 경력의 시니어 애널리스트입니다.
제공된 [KRX 공식 데이터]를 철저하게 분석하여 조언합니다.
현재 시점은 2025년 11월 22일이라고 가정하거나, 데이터의 기준일을 최우선으로 고려하십시오.

[보고서 양식]
1. 📊 **3줄 요약**: (KRX 데이터 기반 현재 상황 압축)
2. 💡 **핵심 투자 포인트**: (중요 이유 3가지)
3. 📈 **펀더멘탈 분석**: (제공된 PER, PBR, EPS 수치를 동종업계/과거와 비교 평가)
4. ✅ **실행 체크리스트**: (매수/보류/매도 행동 지침)
5. 📚 **용어 한입 설명**: (어려운 용어 1~2개를 초등학생 비유로 1줄 설명)

* 주의: '[OUTPUT FORMAT]' 같은 제목은 출력하지 마세요.
"""

# ==========================================
# [도구 함수] 티커 찾기 및 데이터 크롤링
# ==========================================
def find_ticker_code(stock_name):
    try:
        tickers_kospi = stock.get_market_ticker_list(market="KOSPI")
        for code in tickers_kospi:
            if stock.get_market_ticker_name(code) == stock_name:
                return code, "KOSPI"
        
        tickers_kosdaq = stock.get_market_ticker_list(market="KOSDAQ")
        for code in tickers_kosdaq:
            if stock.get_market_ticker_name(code) == stock_name:
                return code, "KOSDAQ"
        return None, None
    except Exception as e:
        print(f"티커 검색 에러: {e}")
        return None, None

def get_krx_real_data(stock_name):
    try:
        target_code, market_type = find_ticker_code(stock_name)
        if not target_code:
            return None, f"KRX에 등록된 정확한 종목명을 입력해주세요. (입력: {stock_name})"

        end_date = datetime.now().strftime("%Y%m%d") 
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

        df_fund = stock.get_market_fundamental_by_date(fromdate=start_date, todate=end_date, ticker=target_code)
        
        if df_fund.empty:
            return target_code, "최근 데이터를 찾을 수 없습니다."

        recent_data = df_fund.iloc[-1]
        found_date = recent_data.name.strftime("%Y-%m-%d")

        df_price = stock.get_market_ohlcv(fromdate=found_date.replace("-",""), todate=found_date.replace("-",""), ticker=target_code)
        price = f"{df_price.iloc[0]['종가']:,}" if not df_price.empty else "확인불가"

        def fmt(val): return f"{val:,.2f}" if isinstance(val, float) else str(val)

        info_text = (
            f"■ 종목명: {stock_name} ({target_code} / {market_type})\n"
            f"■ 기준일: {found_date}\n"
            f"■ 현재가: {price}원\n"
            f"■ PER: {fmt(recent_data.get('PER', 0))}배 | PBR: {fmt(recent_data.get('PBR', 0))}배\n"
            f"■ EPS: {fmt(recent_data.get('EPS', 0))}원 | BPS: {fmt(recent_data.get('BPS', 0))}원\n"
            f"■ 배당수익률: {fmt(recent_data.get('DIV', 0))}%\n"
        )
        return target_code, info_text
            
    except Exception as e:
        print(f"KRX 에러: {e}")
        return None, f"KRX 데이터 접속 오류: {e}"

# ==========================================
# [봇 핸들러]
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 기업 분석", callback_data='btn_analysis')],
        [InlineKeyboardButton("📈 시장 현황", callback_data='btn_market')],
        [InlineKeyboardButton("📚 용어 공부", callback_data='btn_study')]
    ]
    await update.message.reply_text("📈 월가 AI 애널리스트입니다.", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['mode'] = query.data

    if query.data == 'btn_analysis':
        await query.edit_message_text("🔍 분석할 **종목명**을 입력해주세요.")
    elif query.data == 'btn_market':
        await query.edit_message_text("📈 시장 데이터 분석 중...")
        today = datetime.now().strftime("%Y%m%d")
        try:
            # 코스피(1001) 데이터 조회 시도
            kospi_df = stock.get_index_ohlcv_by_date(today, today, "1001")
            kospi_val = kospi_df.iloc[0]['종가'] if not kospi_df.empty else "휴장/장마감"
            market_info = f"현재 코스피 지수: {kospi_val}"
        except:
            market_info = "지수 조회 불가"
            
        prompt = f"{SYSTEM_PROMPT}\n\n[정보] {market_info}\n오늘 시황을 요약해주세요."
        try:
            response = model.generate_content(prompt)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=response.text)
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"AI 오류: {e}")
            
    elif query.data == 'btn_study':
        await query.edit_message_text("📚 궁금한 주식 용어를 입력하세요.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    user_input = update.message.text

    if not mode:
        await update.message.reply_text("/start 를 눌러 메뉴를 선택해주세요.")
        return

    if mode == 'btn_analysis':
        msg = await update.message.reply_text(f"🔍 '{user_input}' 조회 중...")
        code, stock_info = get_krx_real_data(user_input)
        
        if not code:
            await msg.edit_text(stock_info)
            return
            
        await msg.edit_text(f"✅ 데이터 확보!\n\n{stock_info}\n\n📝 리포트 작성 중...")
        try:
            response = model.generate_content(f"{SYSTEM_PROMPT}\n\n[데이터]\n{stock_info}\n\n분석해주세요.")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=response.text, parse_mode='Markdown')
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"AI 오류: {e}")

    elif mode == 'btn_study':
        msg = await update.message.reply_text("생각 중...")
        try:
            response = model.generate_content(f"'{user_input}' 용어를 초등학생도 알기 쉽게 설명해줘.")
            await msg.edit_text(response.text)
        except:
            await msg.edit_text("오류 발생")

if __name__ == '__main__':
    print("🤖 봇 가동 시작")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
