import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
import requests
import re
import io
import json
import warnings

warnings.filterwarnings("ignore")

# ============================================================
# 0. 종목 사전 및 검색
# ============================================================

STOCK_DICT = {
    "삼성전자": "005930", "SK하이닉스": "000660", "NAVER": "035420",
    "카카오": "035720", "LG화학": "051910", "삼성SDI": "006400",
    "셀트리온": "068270", "삼성물산": "028260", "KB금융": "105560", "신한지주": "055550",
    "포스코퓨처엠": "003670", "에코프로비엠": "247540", "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940", "기아": "000270", "현대차": "005380", "현대모비스": "012330",
    "LG전자": "066570", "SK텔레콤": "017670", "KT": "030200", "한화에어로스페이스": "012450",
    "두산에너빌리티": "034020", "포스코홀딩스": "005490", "SK이노베이션": "096770",
    "카카오뱅크": "323410", "크래프톤": "259960", "이글루": "067920", "HLB": "028300",
    "에코프로": "086520", "알테오젠": "196170", "레인보우로보틱스": "277810", "한미반도체": "042700",
    "리노공업": "058470", "삼성전기": "009150", "LG이노텍": "011070", "SK스퀘어": "402340",
    "카카오페이": "377300", "두산로보틱스": "454910", "HD현대중공업": "329180",
    "한화오션": "042660", "HD한국조선해양": "009540",
}

CODE_TO_NAME = {v: k for k, v in STOCK_DICT.items()}

KOSDAQ_CODES = {
    "035420", "035720", "068270", "247540", "003670",
    "067920", "028300", "086520", "196170", "277810",
    "042700", "058470", "323410", "259960", "377300", "454910",
}


def search_stock(query: str) -> list[tuple[str, str]]:
    """종목명/코드 부분 검색 → [(종목명, 코드), ...] 반환"""
    query = query.strip()
    if not query:
        return []
    results = []
    for name, code in STOCK_DICT.items():
        if query in name or query.upper() in name.upper() or query in code:
            results.append((name, code))
    return results


@st.cache_data(ttl=600, show_spinner=False)
def fetch_naver_finance_summary(stock_code: str) -> dict:
    """네이버 증권에서 재무 요약 데이터 스크래핑"""
    from bs4 import BeautifulSoup

    result = {
        "PER": None, "추정PER": None, "PBR": None,
        "EPS": None, "추정EPS": None, "BPS": None,
        "배당수익률": None, "시가총액": None, "시가총액_억": 0,
        "52주고가": None, "52주저가": None,
        "ROE": None, "외국인소진율": None,
        "상장주식수": 0, "현재가": 0,
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    # --- main 페이지: PER, PBR, EPS, BPS, 배당수익률, 52주, 시가총액, ROE ---
    try:
        url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")

        def _parse_num(tag_id: str) -> str | None:
            tag = soup.select_one(f"#{tag_id}")
            if tag:
                return tag.get_text(strip=True)
            return None

        result["PER"] = _parse_num("_per")
        result["추정PER"] = _parse_num("_cns_per")
        result["PBR"] = _parse_num("_pbr")
        result["EPS"] = _parse_num("_eps")
        result["추정EPS"] = _parse_num("_cns_eps")
        result["배당수익률"] = _parse_num("_dvr")

        # BPS: per_table 내 PBR|BPS 행 → "2.95배l60,632원" 형식
        per_table = soup.select_one("table.per_table")
        if per_table:
            for tr in per_table.select("tr"):
                txt = tr.get_text(strip=True)
                if "BPS" in txt:
                    td_text = tr.select("td")[-1].get_text(strip=True)
                    parts = td_text.split("l")
                    if len(parts) >= 2:
                        bps_nums = re.findall(r"[\d,]+", parts[1])
                        if bps_nums:
                            result["BPS"] = bps_nums[0]

        # 52주 고가/저가
        tab = soup.select_one("#tab_con1")
        if tab:
            for tr in tab.select("tr"):
                td_list = tr.select("td")
                for td in td_list:
                    td_text = td.get_text(strip=True)
                    parts = td_text.split("l")
                    if len(parts) == 2:
                        left_nums = re.findall(r"[\d,]+", parts[0])
                        right_nums = re.findall(r"[\d,]+", parts[1])
                        if left_nums and right_nums:
                            left_val = int(left_nums[0].replace(",", ""))
                            right_val = int(right_nums[0].replace(",", ""))
                            if left_val > right_val and "52" in tr.get_text():
                                result["52주고가"] = left_nums[0]
                                result["52주저가"] = right_nums[0]

        # 시가총액
        ms = soup.select_one("#_market_sum")
        if ms:
            nums = re.findall(r"[\d,]+", ms.get_text(strip=True))
            if len(nums) >= 2:
                result["시가총액"] = f"{nums[0]}조 {nums[1]}억"
                jo = int(nums[0].replace(",", ""))
                eok = int(nums[1].replace(",", ""))
                result["시가총액_억"] = jo * 10000 + eok
            elif nums:
                result["시가총액"] = f"{nums[0]}억"
                result["시가총액_억"] = int(nums[0].replace(",", ""))

        # 현재가
        now_price = soup.select_one("p.no_today span.blind")
        if now_price:
            price_text = now_price.get_text(strip=True).replace(",", "")
            if price_text.isdigit():
                result["현재가"] = int(price_text)

        # 상장주식수
        if tab:
            for tr in tab.select("tr"):
                th = tr.select_one("th, em")
                if th and "상장주식" in th.get_text(strip=True):
                    tds = tr.select("td")
                    if tds:
                        val = tds[0].get_text(strip=True).replace(",", "")
                        if val.isdigit():
                            result["상장주식수"] = int(val)
                            break

        if result["상장주식수"] == 0 and result["현재가"] > 0 and result["시가총액_억"] > 0:
            result["상장주식수"] = int(result["시가총액_억"] * 100_000_000 / result["현재가"])

        # ROE
        cop = soup.select_one("div.section.cop_analysis")
        if cop:
            for tr in cop.select("tr"):
                if "ROE" in tr.get_text(strip=True):
                    tds = tr.select("td")
                    vals = [td.get_text(strip=True) for td in tds if td.get_text(strip=True)]
                    if vals:
                        result["ROE"] = vals[-1]
                    break
    except Exception:
        pass

    # --- coinfo 페이지: 외국인소진율 ---
    try:
        url2 = f"https://finance.naver.com/item/coinfo.naver?code={stock_code}"
        resp2 = requests.get(url2, headers=headers, timeout=10)
        resp2.encoding = "euc-kr"
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        for tr in soup2.select("tr"):
            txt = tr.get_text(strip=True)
            if "소진율" in txt and "B/A" in txt:
                tds = tr.select("td")
                for td in tds:
                    v = td.get_text(strip=True)
                    if "%" in v:
                        result["외국인소진율"] = v
                        break
    except Exception:
        pass

    return result


@st.cache_data(ttl=600, show_spinner=False)
def get_real_stock_meta(stock_code: str) -> "StockMeta":
    """네이버 증권 데이터 기반 실제 StockMeta 생성"""
    naver = fetch_naver_finance_summary(stock_code)
    name = CODE_TO_NAME.get(stock_code, stock_code)

    total_shares = naver.get("상장주식수", 0) or 0
    market_cap = naver.get("시가총액_억", 0) or 0

    if total_shares > 0:
        floating_shares = int(total_shares * 0.65)
        floating_ratio = 65.0
    else:
        floating_shares = 0
        floating_ratio = 0.0

    return StockMeta(
        code=stock_code,
        name=name,
        market_cap=market_cap,
        total_shares=total_shares,
        floating_shares=floating_shares,
        floating_ratio=floating_ratio,
    )


INVESTOR_IS_FOREIGN = {
    "금융투자": False, "보험": False, "투신": False, "사모": False,
    "은행": False, "기타금융": False, "연기금 등": False,
    "기타법인": False, "개인": False,
    "외국인": True, "기타외국인": True,
}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_krx_investor_data(stock_code: str, days: int = 20) -> pd.DataFrame | None:
    try:
        from pykrx import stock as krx_stock

        end = datetime.now()
        start = end - timedelta(days=int(days * 2))
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        df_buy = krx_stock.get_market_trading_volume_by_date(start_str, end_str, stock_code, on="매수", detail=True)
        df_sell = krx_stock.get_market_trading_volume_by_date(start_str, end_str, stock_code, on="매도", detail=True)
        df_buy_val = krx_stock.get_market_trading_value_by_date(start_str, end_str, stock_code, on="매수", detail=True)
        df_sell_val = krx_stock.get_market_trading_value_by_date(start_str, end_str, stock_code, on="매도", detail=True)

        if df_buy.empty:
            return None

        df_buy = df_buy.tail(days)
        df_sell = df_sell.tail(days)
        df_buy_val = df_buy_val.tail(days)
        df_sell_val = df_sell_val.tail(days)

        exclude_cols = {"기관합계", "전체"}
        investors = [c for c in df_buy.columns if c not in exclude_cols]

        records = []
        for date_idx in df_buy.index:
            for inv in investors:
                buy_vol = int(df_buy.at[date_idx, inv]) if inv in df_buy.columns else 0
                sell_vol = int(df_sell.at[date_idx, inv]) if inv in df_sell.columns else 0
                buy_amt = int(df_buy_val.at[date_idx, inv]) if inv in df_buy_val.columns else 0
                sell_amt = int(df_sell_val.at[date_idx, inv]) if inv in df_sell_val.columns else 0
                records.append({
                    "date": date_idx,
                    "broker": inv,
                    "buy_volume": abs(buy_vol),
                    "sell_volume": abs(sell_vol),
                    "net_volume": buy_vol - sell_vol,
                    "buy_amount": abs(buy_amt),
                    "sell_amount": abs(sell_amt),
                    "is_foreign": INVESTOR_IS_FOREIGN.get(inv, False),
                })

        return pd.DataFrame(records) if records else None
    except Exception:
        return None


KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_krx_broker_data(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    try:
        json_url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        bld_candidates = [
            "dbms/MDC/STAT/standard/MDCSTAT23700",
            "dbms/MDC/STAT/standard/MDCSTAT23701",
        ]

        for bld in bld_candidates:
            params = {
                "bld": bld,
                "locale": "ko_KR",
                "inqTpCd": "1",
                "trdVolVal": "2",
                "askBid": "3",
                "strtDd": start_date,
                "endDd": end_date,
                "isuCd": stock_code,
                "isuCd2": stock_code,
                "mktId": "ALL",
                "share": "1",
                "money": "1",
            }
            resp = requests.post(json_url, data=params, headers=KRX_HEADERS, timeout=15)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    items = data.get("output", data.get("OutBlock_1", data.get("block1", [])))
                    if items and len(items) > 0:
                        return pd.DataFrame(items)
                except (json.JSONDecodeError, ValueError):
                    continue

        otp_url = "http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
        for bld in bld_candidates:
            params = {
                "locale": "ko_KR",
                "inqTpCd": "1",
                "trdVolVal": "2",
                "askBid": "3",
                "strtDd": start_date,
                "endDd": end_date,
                "isuCd": stock_code,
                "isuCd2": stock_code,
                "mktId": "ALL",
                "share": "1",
                "money": "1",
                "csvxls_isNo": "false",
                "name": "fileDown",
                "url": bld,
            }
            otp_resp = requests.post(otp_url, data=params, headers=KRX_HEADERS, timeout=10)
            otp = otp_resp.text
            if len(otp) < 10:
                continue

            down_url = "http://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"
            csv_resp = requests.post(down_url, data={"code": otp}, headers=KRX_HEADERS, timeout=15)
            if csv_resp.status_code == 200 and len(csv_resp.content) > 100:
                try:
                    df = pd.read_csv(io.BytesIO(csv_resp.content), encoding="euc-kr")
                    if not df.empty:
                        return df
                except Exception:
                    continue
    except Exception:
        pass
    return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_naver_broker_data(stock_code: str) -> pd.DataFrame | None:
    try:
        from bs4 import BeautifulSoup
        url = f"https://finance.naver.com/item/frgn.naver?code={stock_code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")

        tables = soup.select("table.type2")
        if not tables:
            return None

        rows = []
        for table in tables:
            for tr in table.select("tr"):
                tds = tr.select("td")
                if len(tds) >= 6:
                    try:
                        broker = tds[0].get_text(strip=True)
                        buy = int(tds[1].get_text(strip=True).replace(",", "").replace("+", ""))
                        sell = int(tds[2].get_text(strip=True).replace(",", "").replace("+", ""))
                        if broker and buy > 0:
                            rows.append({
                                "broker": broker,
                                "buy_volume": buy,
                                "sell_volume": sell,
                                "net_volume": buy - sell,
                                "buy_amount": 0,
                                "sell_amount": 0,
                                "is_foreign": False,
                                "date": datetime.now(),
                            })
                    except (ValueError, IndexError):
                        continue
        if rows:
            return pd.DataFrame(rows)
    except Exception:
        pass
    return None


def normalize_krx_broker_df(raw_df: pd.DataFrame) -> pd.DataFrame | None:
    if raw_df is None or raw_df.empty:
        return None

    col_map = {}
    for col in raw_df.columns:
        col_lower = str(col).strip()
        if "회원사" in col_lower or "거래원" in col_lower or "투자자" in col_lower:
            col_map[col] = "broker"
        elif "매수" in col_lower and "매도" not in col_lower:
            col_map[col] = "buy_volume"
        elif "매도" in col_lower:
            col_map[col] = "sell_volume"
        elif "순매수" in col_lower:
            col_map[col] = "net_volume"

    if "broker" not in col_map.values():
        return None

    df = raw_df.rename(columns=col_map)

    for num_col in ["buy_volume", "sell_volume", "net_volume"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(
                df[num_col].astype(str).str.replace(",", "").str.replace("+", ""),
                errors="coerce",
            ).fillna(0).astype(int)

    if "buy_volume" in df.columns and "sell_volume" in df.columns and "net_volume" not in df.columns:
        df["net_volume"] = df["buy_volume"] - df["sell_volume"]
    if "buy_amount" not in df.columns:
        df["buy_amount"] = 0
    if "sell_amount" not in df.columns:
        df["sell_amount"] = 0
    if "is_foreign" not in df.columns:
        df["is_foreign"] = False
    if "date" not in df.columns:
        df["date"] = datetime.now()

    return df


BROKER_NAMES = [
    "골드만삭스", "JP모건", "모건스탠리", "CLSA", "메릴린치", "UBS", "크레디트스위스", "씨티그룹", "도이치", "노무라",
    "미래에셋", "삼성증권", "NH투자", "키움증권", "한국투자", "KB증권", "신한투자", "대신증권", "하나증권", "메리츠증권",
]

FOREIGN_BROKERS = {
    "골드만삭스", "JP모건", "모건스탠리", "CLSA", "메릴린치", "UBS", "크레디트스위스", "씨티그룹", "도이치", "노무라"
}


@dataclass
class StockMeta:
    code: str
    name: str
    market_cap: float
    total_shares: int
    floating_shares: int
    floating_ratio: float


class KISApiMockup:
    def __init__(self, app_key: str = "", app_secret: str = "", account: str = ""):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account = account
        self._authenticated = False

    def authenticate(self) -> bool:
        self._authenticated = True
        return True

    def get_broker_trades(self, stock_code: str, days: int = 20) -> pd.DataFrame:
        np.random.seed(hash(stock_code) % 2**31)
        dates = pd.bdate_range(end=datetime.now(), periods=days)
        records = []
        for date in dates:
            for broker in BROKER_NAMES:
                is_foreign = broker in FOREIGN_BROKERS
                base_vol = np.random.randint(5000, 80000) if is_foreign else np.random.randint(1000, 40000)
                buy_vol = int(base_vol * np.random.uniform(0.3, 1.8))
                sell_vol = int(base_vol * np.random.uniform(0.3, 1.5))
                records.append({
                    "date": date,
                    "broker": broker,
                    "buy_volume": buy_vol,
                    "sell_volume": sell_vol,
                    "net_volume": buy_vol - sell_vol,
                    "buy_amount": buy_vol * np.random.randint(5000, 150000),
                    "sell_amount": sell_vol * np.random.randint(5000, 150000),
                    "is_foreign": is_foreign,
                })
        return pd.DataFrame(records)

    def get_stock_meta(self, stock_code: str) -> StockMeta:
        np.random.seed(hash(stock_code) % 2**31)
        total = np.random.randint(10_000_000, 500_000_000)
        flt_ratio = np.random.uniform(0.3, 0.75)
        return StockMeta(
            code=stock_code,
            name=f"종목_{stock_code}",
            market_cap=np.random.randint(500, 100000),
            total_shares=total,
            floating_shares=int(total * flt_ratio),
            floating_ratio=round(flt_ratio * 100, 1),
        )


class AccumulationEngine:
    @staticmethod
    def grade1_buy_strength(broker_df: pd.DataFrame) -> tuple[str, float]:
        total_buy = broker_df["buy_volume"].sum()
        total_sell = broker_df["sell_volume"].sum()
        if total_sell == 0:
            ratio = 999.0
        else:
            ratio = (total_buy / total_sell) * 100

        if ratio > 300:
            grade = "A"
        elif ratio >= 150:
            grade = "B"
        elif ratio >= 100:
            grade = "C"
        else:
            grade = "D"
        return grade, round(ratio, 1)

    @staticmethod
    def grade2_total_accumulation(broker_df: pd.DataFrame, floating_shares: int) -> tuple[str, float]:
        if floating_shares <= 0:
            return "D", 0.0
        total_net = broker_df["net_volume"].sum()
        pct = (total_net / floating_shares) * 100

        if pct > 5:
            grade = "A"
        elif pct >= 3:
            grade = "B"
        elif pct >= 1:
            grade = "C"
        else:
            grade = "D"
        return grade, round(pct, 2)

    @staticmethod
    def grade3_top_broker_concentration(
        broker_df: pd.DataFrame, floating_shares: int, top_n: int = 2
    ) -> tuple[str, float, list[str]]:
        if floating_shares <= 0:
            return "D", 0.0, []
        broker_net = broker_df.groupby("broker")["net_volume"].sum().sort_values(ascending=False)
        top_brokers = broker_net.head(top_n)
        top_sum = top_brokers.sum()
        pct = (top_sum / floating_shares) * 100
        names = top_brokers.index.tolist()

        if pct > 5:
            grade = "A"
        elif pct >= 3:
            grade = "B"
        elif pct >= 1:
            grade = "C"
        else:
            grade = "D"
        return grade, round(pct, 2), names

    @staticmethod
    def calc_accumulation_ratio(broker_df: pd.DataFrame, floating_shares: int) -> float:
        if floating_shares <= 0:
            return 0.0
        total_net = broker_df["net_volume"].sum()
        return round((total_net / floating_shares) * 100, 2)

    @staticmethod
    def divergence_index(broker_df: pd.DataFrame, price_series: pd.Series) -> float:
        if len(price_series) < 4:
            return 1.0
        mid = len(price_series) // 2
        price_first = price_series.iloc[:mid].mean()
        price_second = price_series.iloc[mid:].mean()
        if price_first == 0:
            return 1.0
        delta_price = (price_second - price_first) / price_first

        dates_sorted = sorted(broker_df["date"].unique())
        mid_d = len(dates_sorted) // 2
        first_dates = set(dates_sorted[:mid_d])
        second_dates = set(dates_sorted[mid_d:])

        amt_first = broker_df[broker_df["date"].isin(first_dates)]["buy_amount"].sum()
        amt_second = broker_df[broker_df["date"].isin(second_dates)]["buy_amount"].sum()
        if amt_first == 0:
            return 1.0
        delta_amount = (amt_second - amt_first) / amt_first

        if abs(delta_price) < 0.001:
            return abs(delta_amount) * 100 if delta_amount > 0 else 1.0
        return round(delta_amount / delta_price, 2)

    @staticmethod
    def estimate_whale_avg_cost(broker_df: pd.DataFrame) -> float:
        total_amount = broker_df.loc[broker_df["net_volume"] > 0, "buy_amount"].sum()
        total_vol = broker_df.loc[broker_df["net_volume"] > 0, "buy_volume"].sum()
        if total_vol == 0:
            return 0
        return round(total_amount / total_vol, 0)

    @staticmethod
    def daily_grades(broker_df: pd.DataFrame, floating_shares: int, window: int = 5) -> pd.DataFrame:
        dates = sorted(broker_df["date"].unique())
        results = []
        for i, d in enumerate(dates):
            start_idx = max(0, i - window + 1)
            window_dates = dates[start_idx : i + 1]
            window_df = broker_df[broker_df["date"].isin(window_dates)]

            g1, r1 = AccumulationEngine.grade1_buy_strength(window_df)
            g2, r2 = AccumulationEngine.grade2_total_accumulation(window_df, floating_shares)
            g3, r3, top = AccumulationEngine.grade3_top_broker_concentration(window_df, floating_shares)
            acc_ratio = AccumulationEngine.calc_accumulation_ratio(window_df, floating_shares)

            results.append(
                {
                    "날짜": pd.Timestamp(d).strftime("%Y-%m-%d"),
                    "종합등급": f"{g1}{g2}{g3}",
                    "1등급": f"{g1} ({r1}%)",
                    "2등급": f"{g2} ({r2}%)",
                    "3등급": f"{g3} ({r3}%)",
                    "매집비": f"{acc_ratio}%",
                    "주포창구": ", ".join(top[:2]) if top else "-",
                }
            )
        return pd.DataFrame(results)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_data(ticker: str, period_days: int = 120) -> Optional[pd.DataFrame]:
    try:
        end = datetime.now()
        start = end - timedelta(days=int(period_days * 1.8))
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return None
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if col[1] == "" else col[0] for col in df.columns]
        df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
        return df.tail(period_days)
    except Exception:
        return None


def calc_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    for w in [20, 60, 120, 240]:
        df[f"ma{w}"] = df["close"].rolling(window=w, min_periods=1).mean()
    return df


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


SCANNER_TICKERS_KR = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "035420.KS": "NAVER", "035720.KS": "카카오",
    "051910.KS": "LG화학", "006400.KS": "삼성SDI", "068270.KS": "셀트리온", "028260.KS": "삼성물산",
    "105560.KS": "KB금융", "055550.KS": "신한지주", "003670.KS": "포스코퓨처엠", "247540.KS": "에코프로비엠",
    "373220.KS": "LG에너지솔루션", "207940.KS": "삼성바이오로직스", "000270.KS": "기아", "005380.KS": "현대차",
}

SCANNER_TICKERS_US = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
    "AMZN": "Amazon", "META": "Meta", "TSLA": "Tesla", "TSM": "TSMC",
}


def run_scanner(tickers: dict, period: int, use_real_data: bool = True) -> tuple[pd.DataFrame, str]:
    engine = AccumulationEngine()
    rows = []
    scan_source = "시뮬레이션 데이터"

    for ticker_key, name in tickers.items():
        code = ticker_key.split(".")[0] if "." in ticker_key else ticker_key
        is_kr = ticker_key.endswith(".KS") or ticker_key.endswith(".KQ") or code in STOCK_DICT.values()

        if is_kr and use_real_data:
            meta = get_real_stock_meta(code)
        else:
            api_mock = KISApiMockup()
            meta = api_mock.get_stock_meta(ticker_key)

        broker_df = None
        src = "시뮬레이션"
        if is_kr and use_real_data:
            broker_df = fetch_krx_investor_data(code, days=period)
            if broker_df is not None and not broker_df.empty:
                src = "KRX(pykrx)"
            else:
                broker_df = fetch_naver_broker_data(code)
                if broker_df is not None and not broker_df.empty:
                    src = "네이버"

        if broker_df is None or broker_df.empty:
            api_mock = KISApiMockup()
            broker_df = api_mock.get_broker_trades(ticker_key, days=period)
            src = "시뮬레이션"

        if src != "시뮬레이션":
            scan_source = "실데이터 기반"

        g1, r1 = engine.grade1_buy_strength(broker_df)
        g2, r2 = engine.grade2_total_accumulation(broker_df, meta.floating_shares)
        g3, r3, top_brokers = engine.grade3_top_broker_concentration(broker_df, meta.floating_shares)
        acc = engine.calc_accumulation_ratio(broker_df, meta.floating_shares)
        combined = f"{g1}{g2}{g3}"
        score = sum(4 if g == "A" else 3 if g == "B" else 2 if g == "C" else 1 for g in [g1, g2, g3])

        rows.append(
            {
                "종목코드": code,
                "종목명": name,
                "시총(억)": f"{meta.market_cap:,}",
                "종합등급": combined,
                "점수": score,
                "매집비(%)": acc,
                "매수강도(%)": r1,
                "전체점유(%)": r2,
                "주포집중(%)": r3,
                "주포창구": ", ".join(top_brokers[:2]),
                "소스": src,
            }
        )
    result = pd.DataFrame(rows).sort_values("점수", ascending=False).reset_index(drop=True)
    return result, scan_source


def grade_color(grade: str) -> str:
    colors = {"A": "#00FF88", "B": "#FFD700", "C": "#FF4444", "D": "#888888"}
    return colors.get(grade, "#FFFFFF")


def combined_grade_color(combined: str) -> str:
    a_count = combined.count("A")
    d_count = combined.count("D")
    if a_count == 3:
        return "#00FF88"
    if a_count == 2:
        return "#66DDAA"
    if a_count == 1:
        return "#FFD700"
    if d_count >= 2:
        return "#888888"
    return "#FF4444"


def render_grade_badge(grade: str, label: str, value: str) -> str:
    color = grade_color(grade)
    return f"""
    <div style="text-align:center; padding:8px; border-radius:10px;
                border:2px solid {color}; background:rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.1);">
        <div style="font-size:11px; color:#999;">{label}</div>
        <div style="font-size:28px; font-weight:bold; color:{color};">{grade}</div>
        <div style="font-size:12px; color:#CCC;">{value}</div>
    </div>"""


def render_metric_card(title: str, value: str, color: str = "#FFFFFF") -> str:
    return f"""
    <div style="text-align:center; padding:12px; border-radius:10px;
                background:#1A1D23; border:1px solid #333;">
        <div style="font-size:11px; color:#999;">{title}</div>
        <div style="font-size:22px; font-weight:bold; color:{color};">{value}</div>
    </div>"""


def build_main_chart(price_df: pd.DataFrame, broker_df: pd.DataFrame, floating_shares: int, show_mas: list) -> go.Figure:
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.25, 0.20],
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}]],
    )

    fig.add_trace(
        go.Candlestick(
            x=price_df["date"],
            open=price_df["open"],
            high=price_df["high"],
            low=price_df["low"],
            close=price_df["close"],
            increasing_line_color="#FF4444",
            decreasing_line_color="#4488FF",
            increasing_fillcolor="#FF4444",
            decreasing_fillcolor="#4488FF",
            name="가격",
            whiskerwidth=0.5,
        ),
        row=1,
        col=1,
    )

    ma_colors = {"ma20": "#FFD700", "ma60": "#FF6B6B", "ma120": "#4ECDC4", "ma240": "#9B59B6"}
    ma_labels = {"ma20": "20일(세력선)", "ma60": "60일(업황선)", "ma120": "120일(실적선)", "ma240": "240일(장기선)"}
    for ma in show_mas:
        if ma in price_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=price_df["date"],
                    y=price_df[ma],
                    mode="lines",
                    name=ma_labels.get(ma, ma),
                    line=dict(color=ma_colors.get(ma, "#FFF"), width=1.5),
                    opacity=0.8,
                ),
                row=1,
                col=1,
            )

    dates_sorted = sorted(broker_df["date"].unique())
    daily_acc = []
    for d in dates_sorted:
        d_df = broker_df[broker_df["date"] <= d]
        net = d_df["net_volume"].sum()
        daily_acc.append(round((net / floating_shares) * 100, 2) if floating_shares > 0 else 0)

    vol_colors = ["#FF4444" if price_df.iloc[i]["close"] >= price_df.iloc[i]["open"] else "#4488FF" for i in range(len(price_df))]

    fig.add_trace(go.Bar(x=price_df["date"], y=price_df["volume"], name="거래량", marker_color=vol_colors, opacity=0.4), row=2, col=1)

    acc_dates = [pd.Timestamp(d) for d in dates_sorted[: len(daily_acc)]]
    fig.add_trace(
        go.Scatter(
            x=acc_dates,
            y=daily_acc,
            mode="lines+markers",
            name="누적 매집비(%)",
            line=dict(color="#00FF88", width=2.5),
            marker=dict(size=4),
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    rsi = calc_rsi(price_df["close"])
    fig.add_trace(go.Scatter(x=price_df["date"], y=rsi, mode="lines", name="RSI(14)", line=dict(color="#E67E22", width=1.5)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="#FF4444", opacity=0.4, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#4488FF", opacity=0.4, row=3, col=1)

    fig.update_layout(
        height=750,
        template="plotly_dark",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        margin=dict(l=60, r=20, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
        xaxis_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
    )
    fig.update_yaxes(title_text="가격", row=1, col=1, gridcolor="#222")
    fig.update_yaxes(title_text="거래량", row=2, col=1, gridcolor="#222")
    fig.update_yaxes(title_text="매집비(%)", row=2, col=1, secondary_y=True, gridcolor="#222")
    fig.update_yaxes(title_text="RSI", row=3, col=1, gridcolor="#222", range=[0, 100])
    fig.update_xaxes(gridcolor="#222")

    return fig


def build_broker_chart(broker_df: pd.DataFrame) -> go.Figure:
    broker_net = broker_df.groupby("broker")["net_volume"].sum().sort_values(ascending=True)
    colors = ["#00FF88" if v > 0 else "#FF4444" for v in broker_net.values]

    fig = go.Figure(
        go.Bar(
            x=broker_net.values,
            y=broker_net.index,
            orientation="h",
            marker_color=colors,
            text=[f"{v:,.0f}" for v in broker_net.values],
            textposition="auto",
            textfont=dict(size=10),
        )
    )
    fig.update_layout(
        height=500,
        template="plotly_dark",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        margin=dict(l=100, r=20, t=30, b=30),
        xaxis_title="순매수량",
        yaxis_title="",
        xaxis=dict(gridcolor="#222"),
    )
    return fig


def build_accumulation_heatmap(broker_df: pd.DataFrame) -> go.Figure:
    pivot = broker_df.pivot_table(index="broker", columns="date", values="net_volume", aggfunc="sum").fillna(0)
    top_brokers = pivot.abs().sum(axis=1).nlargest(10).index
    pivot = pivot.loc[top_brokers]

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[d.strftime("%m/%d") for d in pivot.columns],
            y=pivot.index,
            colorscale=[[0, "#FF4444"], [0.5, "#1A1D23"], [1, "#00FF88"]],
            zmid=0,
            text=np.round(pivot.values / 1000, 1),
            texttemplate="%{text}K",
            textfont=dict(size=9),
            hovertemplate="창구: %{y}<br>날짜: %{x}<br>순매수: %{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=400,
        template="plotly_dark",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        margin=dict(l=100, r=20, t=30, b=30),
    )
    return fig


def main():
    st.set_page_config(page_title="매집비 분석 대시보드", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

    st.markdown(
        """
    <style>
        .stApp { background-color: #0E1117; }
        section[data-testid="stSidebar"] { background-color: #1A1D23; }
        .grade-aaa { color: #00FF88; font-size: 48px; font-weight: bold; text-align: center; }
        .signal-buy { background: rgba(0,255,136,0.15); border: 1px solid #00FF88;
                      border-radius: 8px; padding: 10px; text-align: center; }
        .signal-sell { background: rgba(255,68,68,0.15); border: 1px solid #FF4444;
                       border-radius: 8px; padding: 10px; text-align: center; }
        .signal-hold { background: rgba(255,215,0,0.15); border: 1px solid #FFD700;
                       border-radius: 8px; padding: 10px; text-align: center; }
        div[data-testid="stMetric"] { background: #1A1D23; padding: 12px; border-radius: 10px; border: 1px solid #333; }
        .fn-guide-btn a {
            display: inline-block; padding: 8px 20px; border-radius: 8px;
            background: linear-gradient(135deg, #1a73e8, #4285f4);
            color: #fff !important; text-decoration: none; font-weight: bold; font-size: 14px;
        }
        .fn-guide-btn a:hover { background: linear-gradient(135deg, #1558b0, #3275e4); }
    </style>""",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown("## 매집비 분석 설정")
        st.markdown("---")

        market = st.radio("시장 선택", ["한국 (KRX)", "미국 (US)"], horizontal=True)

        if market == "한국 (KRX)":
            stock_input = st.text_input("종목명 또는 코드", value="삼성전자", help="예: 삼성전자, 하이닉스, 005930")

            resolved_code = None
            stock_input_stripped = stock_input.strip()

            if stock_input_stripped in STOCK_DICT:
                resolved_code = STOCK_DICT[stock_input_stripped]
            elif stock_input_stripped in CODE_TO_NAME:
                resolved_code = stock_input_stripped
            else:
                matches = search_stock(stock_input_stripped)
                if matches:
                    resolved_code = matches[0][1]
                    if len(matches) > 1:
                        st.caption(f"검색 결과: {', '.join(n for n, c in matches[:5])}")
                elif stock_input_stripped.isdigit() and len(stock_input_stripped) == 6:
                    resolved_code = stock_input_stripped

            if resolved_code:
                suffix = ".KQ" if resolved_code in KOSDAQ_CODES else ".KS"
                ticker = resolved_code + suffix
                display_name = CODE_TO_NAME.get(resolved_code, resolved_code)
                st.success(f"{display_name} ({ticker})")
            else:
                st.warning("종목을 찾을 수 없습니다. 6자리 코드를 직접 입력해주세요.")
                ticker = "005930.KS"
        else:
            ticker = st.text_input("종목 코드", value="NVDA", help="예: NVDA, AAPL, TSLA, MSFT")

        analysis_period = st.slider("분석 기간 (거래일)", 5, 60, 20)
        chart_period = st.slider("차트 표시 기간 (거래일)", 30, 240, 120)

        st.markdown("---")
        st.markdown("#### 이동평균선 표시")
        show_ma20 = st.checkbox("20일선 (세력선)", value=True)
        show_ma60 = st.checkbox("60일선 (업황선)", value=True)
        show_ma120 = st.checkbox("120일선 (실적선)", value=False)
        show_ma240 = st.checkbox("240일선 (장기선)", value=False)

        st.markdown("---")
        st.markdown("#### 필터 설정")
        cap_range = st.slider("시가총액 필터 (억원)", 0, 100000, (0, 100000), step=500)
        float_range = st.slider("유통주식수 필터 (만주)", 0, 50000, (0, 50000), step=100)

        st.markdown("---")
        st.caption("v2.1 | 수급 데이터 정량화 시스템")
        st.caption("주가: yfinance | 수급: KRX (pykrx) → 네이버")
        st.caption("재무: 네이버 증권 | 등급: ABCD 4등급")

    _ = (cap_range, float_range)

    st.markdown("# 매집비 분석 대시보드")
    st.caption("수급 데이터 정량화를 통한 세력 매집비 분석 시스템")

    tab_analysis, tab_scanner, tab_broker, tab_guide = st.tabs(["종목 분석", "수급 스캐너", "창구 분석", "매매 가이드"])

    with tab_analysis:
        with st.spinner("데이터 로딩 중..."):
            price_df = fetch_price_data(ticker, chart_period)

        if price_df is None or price_df.empty:
            st.error(f"'{ticker}' 종목의 데이터를 가져올 수 없습니다. 종목 코드를 확인해주세요.")
            st.stop()

        price_df = calc_moving_averages(price_df)

        is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")
        krx_code = ticker.split(".")[0] if is_kr else None

        if is_kr and krx_code:
            meta = get_real_stock_meta(krx_code)
        else:
            api = KISApiMockup()
            meta = api.get_stock_meta(ticker)

        broker_df = None
        data_label = "시뮬레이션 데이터"
        if is_kr and krx_code:
            broker_df = fetch_krx_investor_data(krx_code, days=analysis_period)
            if broker_df is not None and not broker_df.empty:
                data_label = "KRX 투자자별 실제 데이터 (pykrx)"

            if broker_df is None or broker_df.empty:
                end_d = datetime.now().strftime("%Y%m%d")
                start_d = (datetime.now() - timedelta(days=int(analysis_period * 2))).strftime("%Y%m%d")
                raw = fetch_krx_broker_data(krx_code, start_d, end_d)
                broker_df = normalize_krx_broker_df(raw)
                if broker_df is not None and not broker_df.empty:
                    data_label = "KRX 회원사별 실제 데이터"

            if broker_df is None or broker_df.empty:
                broker_df = fetch_naver_broker_data(krx_code)
                if broker_df is not None and not broker_df.empty:
                    data_label = "네이버 증권 거래원 데이터"

        if broker_df is None or broker_df.empty:
            api_mock = KISApiMockup()
            broker_df = api_mock.get_broker_trades(ticker, days=analysis_period)
            data_label = "시뮬레이션 데이터"

        source_color = "#28a745" if "실제" in data_label or "KRX" in data_label or "네이버" in data_label else "#ffc107"
        st.markdown(
            f'<div style="text-align:right; font-size:12px; color:{source_color}; margin-bottom:8px;">📡 {data_label}</div>',
            unsafe_allow_html=True,
        )

        engine = AccumulationEngine()
        g1, r1 = engine.grade1_buy_strength(broker_df)
        g2, r2 = engine.grade2_total_accumulation(broker_df, meta.floating_shares)
        g3, r3, top_brokers = engine.grade3_top_broker_concentration(broker_df, meta.floating_shares)
        acc_ratio = engine.calc_accumulation_ratio(broker_df, meta.floating_shares)
        di = engine.divergence_index(broker_df, price_df["close"])
        whale_cost = engine.estimate_whale_avg_cost(broker_df)
        combined = f"{g1}{g2}{g3}"
        current_price = price_df["close"].iloc[-1]

        col_grade, col_detail = st.columns([1, 3])
        with col_grade:
            color = combined_grade_color(combined)
            st.markdown(
                f"""
            <div style="text-align:center; padding:20px; border-radius:15px;
                        border:3px solid {color}; background:rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08);">
                <div style="font-size:13px; color:#999;">종합 매집 등급</div>
                <div style="font-size:56px; font-weight:bold; color:{color}; letter-spacing:4px;">{combined}</div>
                <div style="font-size:14px; color:#CCC;">매집비 {acc_ratio}%</div>
            </div>""",
                unsafe_allow_html=True,
            )

        with col_detail:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(render_grade_badge(g1, "1등급: 매수강도", f"{r1}%"), unsafe_allow_html=True)
            with c2:
                st.markdown(render_grade_badge(g2, "2등급: 전체점유", f"{r2}%"), unsafe_allow_html=True)
            with c3:
                st.markdown(render_grade_badge(g3, "3등급: 주포집중", f"{r3}%"), unsafe_allow_html=True)
            with c4:
                di_color = "#00FF88" if di > 1.5 else "#FFD700" if di > 1 else "#FF4444"
                st.markdown(render_metric_card("발산지수 (DI)", f"{di}", di_color), unsafe_allow_html=True)

        m1, m2, m3, m4, m5 = st.columns(5)
        price_change = ((current_price / price_df["close"].iloc[-2]) - 1) * 100 if len(price_df) > 1 else 0
        m1.metric("현재가", f"{current_price:,.0f}", f"{price_change:+.2f}%")
        m2.metric("세력 추정 평단", f"{whale_cost:,.0f}")
        margin = ((current_price / whale_cost) - 1) * 100 if whale_cost > 0 else 0
        margin_label = "안전마진" if margin > 0 else "이격도"
        m3.metric(margin_label, f"{margin:+.1f}%")
        m4.metric("주포 창구", top_brokers[0] if top_brokers else "-")
        m5.metric("유통주식수", f"{meta.floating_shares:,}")

        is_korean = ticker.endswith(".KS") or ticker.endswith(".KQ")
        if is_korean:
            stock_code = ticker.split(".")[0]
            with st.expander("📋 재무 요약 & FN가이드 (네이버 증권)", expanded=False):
                naver_info = fetch_naver_finance_summary(stock_code)

                fc1, fc2, fc3, fc4 = st.columns(4)
                per_display = naver_info["추정PER"] or naver_info["PER"]
                per_label = "추정PER" if naver_info["추정PER"] else "PER"
                fc1.metric(per_label, f"{per_display}배" if per_display else "-")
                fc2.metric("PBR", f"{naver_info['PBR']}배" if naver_info["PBR"] else "-")
                fc3.metric("시가총액", naver_info["시가총액"] or "-")
                fc4.metric("배당수익률", f"{naver_info['배당수익률']}%" if naver_info["배당수익률"] else "-")

                fc5, fc6, fc7, fc8 = st.columns(4)
                fc5.metric("52주 고가", naver_info["52주고가"] or "-")
                fc6.metric("52주 저가", naver_info["52주저가"] or "-")
                fc7.metric("ROE", f"{naver_info['ROE']}%" if naver_info["ROE"] else "-")
                eps_display = naver_info["추정EPS"] or naver_info["EPS"]
                eps_label = "추정EPS" if naver_info["추정EPS"] else "EPS"
                fc8.metric(eps_label, f"{eps_display}원" if eps_display else "-")

                fc9, fc10, _, _ = st.columns(4)
                fc9.metric("BPS", f"{naver_info['BPS']}원" if naver_info["BPS"] else "-")
                fc10.metric("외국인소진율", naver_info["외국인소진율"] or "-")

                naver_url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
                fn_url = (
                    "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&giession=0&cID=&MenuYn=Y"
                    f"&ReportGB=&NewMenuID=101&stkGb=701&strResearchYN=&fid=&fid2=&symbol={stock_code}&mio=N"
                )
                st.markdown(
                    f'<div class="fn-guide-btn"><a href="{naver_url}" target="_blank">네이버 증권 →</a>&nbsp;&nbsp;'
                    f'<a href="{fn_url}" target="_blank">FN가이드 →</a></div>',
                    unsafe_allow_html=True,
                )

        ma20_val = price_df["ma20"].iloc[-1] if "ma20" in price_df.columns else 0
        ma20_up = price_df["ma20"].iloc[-1] > price_df["ma20"].iloc[-3] if len(price_df) > 3 else False

        if combined.count("A") >= 2 and ma20_up and current_price > ma20_val:
            signal_class = "signal-buy"
            signal_text = "매수 관심 구간 - 매집 등급 우수 + 20일선 우상향 정배열"
        elif combined.count("D") >= 2 or (combined.count("C") + combined.count("D") >= 2 and (not ma20_up or current_price < ma20_val)):
            signal_class = "signal-sell"
            signal_text = "경계 구간 - 매집 등급 하락 또는 이평선 역배열"
        else:
            signal_class = "signal-hold"
            signal_text = "관망 구간 - 추가 확인 필요"

        st.markdown(f'<div class="{signal_class}"><b>{signal_text}</b></div>', unsafe_allow_html=True)

        mas_to_show = []
        if show_ma20:
            mas_to_show.append("ma20")
        if show_ma60:
            mas_to_show.append("ma60")
        if show_ma120:
            mas_to_show.append("ma120")
        if show_ma240:
            mas_to_show.append("ma240")

        fig = build_main_chart(price_df, broker_df, meta.floating_shares, mas_to_show)
        st.plotly_chart(fig, width="stretch")

        st.markdown("### 최근 등급 변화 추이")
        daily_df = engine.daily_grades(broker_df, meta.floating_shares)
        st.dataframe(
            daily_df.tail(10).style.map(
                lambda v: "color: #00FF88" if "A" in str(v) and "(" not in str(v)
                else "color: #FFD700" if "B" in str(v) and "(" not in str(v)
                else "color: #FF4444" if "C" in str(v) and "(" not in str(v)
                else "color: #888888" if "D" in str(v) and "(" not in str(v)
                else "",
                subset=["종합등급"],
            ),
            width="stretch",
            hide_index=True,
            height=390,
        )

    with tab_scanner:
        st.markdown("### 실시간 수급 스캐너")
        st.caption("전체 종목을 매집비 등급 기준으로 스캔합니다. (한국: KRX/pykrx 실데이터, 미국: 시뮬레이션)")

        scan_col1, scan_col2 = st.columns([1, 1])
        with scan_col1:
            scan_market = st.radio("스캔 시장", ["한국 주요종목", "미국 주요종목"], horizontal=True, key="scan_mkt")
        with scan_col2:
            scan_period = st.slider("스캔 기간 (거래일)", 5, 40, 20, key="scan_period")

        use_real = scan_market == "한국 주요종목"
        if st.button("스캔 실행", type="primary", width="stretch"):
            tickers = SCANNER_TICKERS_KR if scan_market == "한국 주요종목" else SCANNER_TICKERS_US
            with st.spinner("종목 스캔 중... (실데이터 조회 시 다소 시간이 걸릴 수 있습니다)"):
                scan_result, scan_source = run_scanner(tickers, scan_period, use_real_data=use_real)

            st.caption(f"데이터 소스: {scan_source}")

            aaa = scan_result[scan_result["종합등급"].str.count("A") == 3]
            if not aaa.empty:
                st.success(f"AAA 등급 포착: {', '.join(aaa['종목명'].tolist())}")

            def color_grade_row(row):
                grade = row["종합등급"]
                a_count = grade.count("A")
                if a_count == 3:
                    return ["background-color: rgba(0,255,136,0.15)"] * len(row)
                if a_count == 2:
                    return ["background-color: rgba(102,221,170,0.08)"] * len(row)
                return [""] * len(row)

            st.dataframe(scan_result.style.apply(color_grade_row, axis=1), width="stretch", hide_index=True, height=500)

    with tab_broker:
        st.markdown(f"### 창구별 순매수 분석 ({ticker})")
        st.caption(f"데이터 소스: {data_label}")

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            st.markdown("#### 창구별 누적 순매수")
            broker_fig = build_broker_chart(broker_df)
            st.plotly_chart(broker_fig, width="stretch")

        with bcol2:
            st.markdown("#### 외국계 vs 국내 비교")
            foreign_df = broker_df[broker_df["is_foreign"]]
            domestic_df = broker_df[~broker_df["is_foreign"]]
            f_net = foreign_df["net_volume"].sum()
            d_net = domestic_df["net_volume"].sum()

            fig_pie = go.Figure(
                go.Pie(
                    labels=["외국계 순매수", "국내 순매수"],
                    values=[max(f_net, 0), max(d_net, 0)],
                    marker=dict(colors=["#00FF88", "#FFD700"]),
                    hole=0.5,
                    textinfo="label+percent",
                )
            )
            fig_pie.update_layout(height=400, template="plotly_dark", paper_bgcolor="#0E1117", margin=dict(l=20, r=20, t=30, b=30))
            st.plotly_chart(fig_pie, width="stretch")

        st.markdown("#### 일별 창구 히트맵 (상위 10개)")
        heatmap_fig = build_accumulation_heatmap(broker_df)
        st.plotly_chart(heatmap_fig, width="stretch")

        st.markdown("#### 창구별 상세 데이터")
        broker_summary = (
            broker_df.groupby("broker")
            .agg(총매수=("buy_volume", "sum"), 총매도=("sell_volume", "sum"), 순매수=("net_volume", "sum"), 매수금액=("buy_amount", "sum"))
            .sort_values("순매수", ascending=False)
            .reset_index()
        )
        broker_summary.columns = ["창구명", "총매수량", "총매도량", "순매수량", "매수금액(원)"]
        broker_summary["매수금액(원)"] = broker_summary["매수금액(원)"].apply(lambda x: f"{x:,.0f}")
        st.dataframe(broker_summary, width="stretch", hide_index=True)

    with tab_guide:
        st.markdown("### 매집비 매매 가이드")
        st.markdown(
            """
        #### 등급 체계 (ABCD 4등급)

        | 등급 | 항목 | A 조건 | B 조건 | C 조건 | D 조건 |
        |:---:|:---:|:---:|:---:|:---:|:---:|
        | **1등급** | 매수강도 | 매수/매도 > 300% | 150~300% | 100~150% | < 100% |
        | **2등급** | 전체점유 | 유통주식 대비 > 5% | 3~5% | 1~3% | < 1% |
        | **3등급** | 주포집중 | 상위2 창구 > 5% | 3~5% | 1~3% | < 1% |

        ---
        #### 이동평균선 해석

        | 이평선 | 명칭 | 전략적 의미 |
        |:---:|:---:|:---|
        | **20일** | 세력선 | 우상향 시 단기 수급 주도권이 세력에게 있음 |
        | **60일** | 업황/재료선 | 상승 추세 유지 시 매집 데이터 신뢰도 상승 |
        | **120일** | 반기 실적선 | 주가가 이 위에 있을 때 기관 매집 의미 큼 |
        | **240일** | 장기 추세선 | 시세의 시작점 확인 및 대바닥 판단 |

        ---
        #### 매매 시그널 조건

        **매수 시그널 (강력)**
        - 종합 등급 AA 이상 (2개 이상 A)
        - 20일 이동평균선 우상향 + 주가 위 안착
        - 발산 지수(DI) > 1.5

        **매수 시그널 (보통)**
        - 종합 등급 AB 이상
        - 매집비 수치 3% 이상
        - 주포 창구가 외국계

        **경계/매도 시그널**
        - 매집비 등급 D등급으로 하락
        - 주포 창구의 순매도 전환
        - 주가가 세력 추정 평단 하회 + 등급 하락 동반

        ---
        #### 종목 유형별 전략

        **대형주 (시총 5,000억 이상)**
        - 분석 기간: 20~40 거래일
        - AA 등급 이상 시 추세 추종 홀딩
        - 주포 창구 이탈 전까지 보유 유지

        **작전주/스몰캡 (시총 5,000억 이하)**
        - 분석 기간: 12~24 거래일 (짧게)
        - 가격-수급 발산 확인 필수
        - 세력 추정 평단 대비 안전마진 확보 시 진입

        ---
        #### 발산 분석 (Divergence)
        ```
        DI_pa = ΔAmount_acc / ΔPrice_avg
        ```
        - **DI > 1.5**: 세력 강력 매집 중 (적극 매수 구간)
        - **DI = 1.0~1.5**: 보통 (관망)
        - **DI < 1.0**: 수급 약화 (주의)

        ---
        #### 데이터 소스

        | 소스 | 설명 |
        |:---:|:---|
        | **KRX (pykrx)** | 투자자별 거래량/대금 (금융투자, 외국인, 개인 등) |
        | **KRX 데이터 서비스** | 회원사별 매매현황 (개별 증권사 단위) |
        | **네이버 증권** | 거래원 테이블, 재무 요약 (PER, PBR, ROE 등) |
        | **FN가이드** | 기업 펀더멘털 상세 (외부 링크) |
        | **yfinance** | 주가 차트 데이터 (캔들, 이동평균선) |

        ---
        #### 주의사항
        - 매집비 분석은 참고 지표이며 투자의 최종 결정은 본인의 판단입니다
        - 유통주식수는 상장주식수의 65% 추정치를 사용합니다
        - API 데이터는 장중/장마감 후 업데이트 시점에 따라 달라질 수 있습니다
        """
        )


if __name__ == "__main__":
    main()
