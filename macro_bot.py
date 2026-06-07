"""
금융공학회 텔레그램 매크로 봇
- GitHub Actions로 매일 오전 8시 KST 자동 실행
"""

import logging
import asyncio
import os
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode
import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

KST = pytz.timezone("Asia/Seoul")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_yahoo(symbol: str) -> float | None:
    """야후 파이낸스 v8 API로 직접 호출"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1d", "range": "5d"}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        return round(closes[-1], 3) if closes else None
    except Exception as e:
        logger.error(f"야후 API 실패 ({symbol}): {e}")
        return None


def fetch_macro_data() -> dict:
    symbols = {
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
    data = {}
    for key, symbol in symbols.items():
        logger.info(f"  수집 중: {key} ({symbol})")
        data[key] = fetch_yahoo(symbol)
    return data


def fetch_naver_finance_news(n: int = 3) -> list[dict]:
    """
    네이버 금융 경제 뉴스 헤드라인 수집.
    네이버는 HTML 구조를 자주 바꾸므로 셀렉터를 5단계로 시도합니다.
    """
    # 1차: 경제 뉴스 섹션, 2차: 메인 뉴스 페이지 (fallback)
    urls = [
        "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258",
        "https://finance.naver.com/news/mainnews.naver",
    ]
    # 브라우저로 위장 — "Mozilla/5.0 (compatible; MacroBot/1.0)" 은 bot으로 인식되어 차단됨
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://finance.naver.com/",
    }

    for url in urls:
        articles = _parse_naver_news(url, headers, n)
        if articles:
            return articles

    logger.warning("모든 네이버 뉴스 URL에서 기사를 가져오지 못했습니다.")
    return []


def _parse_naver_news(url: str, headers: dict, n: int) -> list[dict]:
    """단일 URL에서 뉴스를 파싱합니다. 셀렉터를 순서대로 시도합니다."""
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        # 네이버 금융 HTML 구조별 셀렉터 (우선순위 순)
        # 구조가 바뀌어도 하나는 걸리도록 다층 배치
        selectors = [
            "dt.articleSubject a",           # 현재 주력 구조
            "li.newsList dt a",              # 리스트형 구조
            "ul.realtimeNewsList li a",      # 실시간 뉴스 구조
            "div.newsWrap a.articleSubject", # 래퍼형 구조
            "a[href*='news_read']",          # href 기반 (최후 수단)
        ]

        seen, articles = set(), []
        for sel in selectors:
            for a in soup.select(sel):
                title = a.get_text(strip=True)
                href  = a.get("href", "")
                # 너무 짧은 텍스트(버튼류), 중복 제거
                if not title or len(title) < 8 or title in seen:
                    continue
                seen.add(title)
                if href and not href.startswith("http"):
                    href = "https://finance.naver.com" + href
                articles.append({"title": title, "url": href})
                if len(articles) >= n:
                    return articles
            if articles:
                return articles  # 한 셀렉터에서 찾으면 바로 반환

    except Exception as e:
        logger.warning(f"네이버 뉴스 파싱 실패 ({url}): {e}")
    return []


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
        "_출처\\: Yahoo Finance \\| 네이버 금융_",
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
    asyncio.run(send_macro_report())
