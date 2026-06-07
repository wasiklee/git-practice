"""
금융공학회 텔레그램 매크로 봇
- GitHub Actions로 매일 오전 8시 KST 자동 실행
"""

import logging
import asyncio
import sys
import os
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import yfinance as yf
from telegram import Bot
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# GitHub Secrets에서 자동으로 읽어옴
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

KST = pytz.timezone("Asia/Seoul")

TICKERS = {
    "US2Y":   "^IRX",
    "US10Y":  "^TNX",
    "US30Y":  "^TYX",
    "NASDAQ": "^IXIC",
    "SP500":  "^GSPC",
    "KOSPI":  "^KS11",
    "KOSDAQ": "^KQ11",
    "DXY":    "DX-Y.NYB",
    "USDKRW": "KRW=X",
    "GOLD":   "GC=F",
    "WTI":    "CL=F",
}


def fetch_yf_price(ticker: str) -> float | None:
    try:
        data = yf.download(ticker, period="5d", interval="1d",
                           progress=False, auto_adjust=True)
        if data.empty:
            return None
        return float(data["Close"].dropna().iloc[-1])
    except Exception as e:
        logger.warning(f"yfinance 실패 ({ticker}): {e}")
        return None


def fetch_macro_data() -> dict:
    data = {}
    for key, ticker in TICKERS.items():
        logger.info(f"  수집 중: {key} ({ticker})")
        data[key] = fetch_yf_price(ticker)
    return data


def fetch_naver_finance_news(n: int = 3) -> list[dict]:
    url = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MacroBot/1.0)"}
    articles = []
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        seen = set()
        for a in soup.select("dl dt:not(.ad) a"):
            title = a.get_text(strip=True)
            href  = a.get("href", "")
            if not title or title in seen or len(title) < 8:
                continue
            seen.add(title)
            if href and not href.startswith("http"):
                href = "https://finance.naver.com" + href
            articles.append({"title": title, "url": href})
            if len(articles) >= n:
                break

        if not articles:
            for a in soup.select("ul.newsList li a"):
                title = a.get_text(strip=True)
                href  = a.get("href", "")
                if not title or title in seen or len(title) < 8:
                    continue
                seen.add(title)
                if href and not href.startswith("http"):
                    href = "https://finance.naver.com" + href
                articles.append({"title": title, "url": href})
                if len(articles) >= n:
                    break
    except Exception as e:
        logger.warning(f"뉴스 크롤링 실패: {e}")
    return articles[:n]


def fmt(val: float | None, decimals: int = 2, prefix: str = "", suffix: str = "") -> str:
    if val is None:
        return "N/A"
    return f"{prefix}{val:,.{decimals}f}{suffix}"


def escape_md(text: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def build_message(data: dict, news: list[dict]) -> str:
    now = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M KST")

    lines = [
        "📊 *금융공학회 모닝 매크로 브리핑*",
        f"🗓 {escape_md(now)}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🇺🇸 *미국채 금리*",
        f"  • 2년물  \\: `{fmt(data.get('US2Y'),  3, suffix=' %')}`",
        f"  • 10년물 \\: `{fmt(data.get('US10Y'), 3, suffix=' %')}`",
        f"  • 30년물 \\: `{fmt(data.get('US30Y'), 3, suffix=' %')}`",
        "",
        "📈 *미국 지수 \\(전일 종가\\)*",
        f"  • NASDAQ \\: `{fmt(data.get('NASDAQ'), 2)}`",
        f"  • S\\&P500 \\: `{fmt(data.get('SP500'),  2)}`",
        "",
        "🇰🇷 *국내 지수 \\(전일 종가\\)*",
        f"  • KOSPI  \\: `{fmt(data.get('KOSPI'),  2)}`",
        f"  • KOSDAQ \\: `{fmt(data.get('KOSDAQ'), 2)}`",
        "",
        "💱 *환율 / 달러*",
        f"  • 달러인덱스 \\: `{fmt(data.get('DXY'),    3)}`",
        f"  • 원달러환율 \\: `{fmt(data.get('USDKRW'), 2, suffix=' ₩')}`",
        "",
        "🪙 *원자재 \\(전일 종가\\)*",
        f"  • 금 선물  \\: `{fmt(data.get('GOLD'), 2, prefix='$')}`",
        f"  • WTI 원유 \\: `{fmt(data.get('WTI'),  2, prefix='$')}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "📰 *네이버 금융 주요 뉴스*",
    ]

    if news:
        for i, article in enumerate(news, 1):
            title = escape_md(article["title"])
            url   = article["url"]
            lines.append(f"  {i}\\. [{title}]({url})")
    else:
        lines.append("  뉴스를 불러오지 못했습니다\\.")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "_출처\\: yfinance \\| 네이버 금융_",
    ]

    return "\n".join(lines)


async def send_macro_report():
    logger.info("=" * 40)
    logger.info("매크로 리포트 생성 시작")

    data = fetch_macro_data()
    news = fetch_naver_finance_news(3)
    msg  = build_message(data, news)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )
    logger.info("✅ 텔레그램 전송 완료")


if __name__ == "__main__":
    # GitHub Actions에서는 스케줄러 없이 바로 1회 실행
    asyncio.run(send_macro_report())
