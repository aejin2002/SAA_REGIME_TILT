"""
성장×인플레이션 레짐 틸트 전략 — 백테스트 엔진
growth_inflation_regime_tilt_final_simpleFG.ipynb 의 로직을 그대로 포팅.
3개 레이어:
  1) 월별 레짐 배분 (성장×인플레 워크포워드, 레짐별 고정 주식비중 틸트)
  2) 일별 위기 오버레이 (VIX+SPY+HYG 2/3 투표, 상태기계)
  3) 간단 F&G 오버레이 (KODEX200 전용, VKOSPI+KOSPI 모멘텀 점수)
"""
import csv
import os
import re
import time
from datetime import date, datetime, timedelta
from io import StringIO

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ------------------------------------------------------------------
# 설정 (원본 노트북과 동일)
# ------------------------------------------------------------------
ETF_UNIVERSE = ["SPY", "QQQ", "069500.KS", "DBC", "GLD", "IEF", "TLT", "LQD", "TIP"]
EQUITY_ASSETS = {"SPY", "QQQ", "069500.KS"}
NON_EQUITY_ASSETS = [a for a in ETF_UNIVERSE if a not in EQUITY_ASSETS]

# HYG·BIL은 평상시 보유 유니버스(ETF_UNIVERSE)에서는 뺐지만, 위기 오버레이의 신호(HYG 5일 수익률)와
# 대피처(BIL, TBILL_PROXY) 역할로는 계속 씀 — 그래서 가격은 받아오되 평상시 균등비중 대상에서는 제외.
AUX_TICKERS = ["HYG", "BIL"]

ASSET_LABELS = {
    "SPY": "SPY (미국 대형주)", "QQQ": "QQQ (미국 나스닥)",
    "069500.KS": "KODEX200 (코스피200)", "DBC": "DBC (원자재)", "GLD": "GLD (금)",
    "BIL": "BIL (초단기국채·위기 대피처)", "IEF": "IEF (중기국채)", "TLT": "TLT (장기국채)",
    "HYG": "HYG (하이일드채·신용신호용)", "LQD": "LQD (투자등급채)", "TIP": "TIP (물가연동채)",
}

START = "1990-01-01"

REGIME_EQUITY_TARGET = {"Goldilocks": 0.70, "Reflation": 0.60, "Stagflation": 0.40, "Deflation": 0.50}
DEFAULT_EQUITY = 0.60
RECESSION_FP_THRESHOLD = 0.25
MIN_HIST_MONTHS = 36
MIN_REGIME_OBS = 6

REGIME_LABELS_KO = {
    "Goldilocks": "골디락스 (성장↑ 인플레↓)",
    "Reflation": "리플레이션 (성장↑ 인플레↑)",
    "Stagflation": "스태그플레이션 (성장↓ 인플레↑)",
    "Deflation": "디플레이션 (성장↓ 인플레↓)",
}

REGIME_LABELS_EN = {
    "Goldilocks": "Goldilocks · Growth↑ Inflation↓",
    "Reflation": "Reflation · Growth↑ Inflation↑",
    "Stagflation": "Stagflation · Growth↓ Inflation↑",
    "Deflation": "Deflation · Growth↓ Inflation↓",
}

REGIME_NAME_EN = {
    "Goldilocks": "Goldilocks",
    "Reflation": "Reflation",
    "Stagflation": "Stagflation",
    "Deflation": "Deflation",
}

REGIME_QUALIFIER_EN = {
    "Goldilocks": "Growth↑ Inflation↓",
    "Reflation": "Growth↑ Inflation↑",
    "Stagflation": "Growth↓ Inflation↑",
    "Deflation": "Growth↓ Inflation↓",
}

# 개인 API 키 — 코드에 직접 넣지 않고 환경변수(.streamlit/secrets.toml 또는 shell env)로 주입.
# 로컬 실행: .streamlit/secrets.toml 에 FRED_API_KEY = "..." 식으로 적어두면 app.py가 자동으로 읽어옴.
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

CRISIS_DERISK_ASSETS = {"SPY", "QQQ", "069500.KS", "DBC"}
TBILL_PROXY = "BIL"
MIN_HOLD_DAYS = 10
MIN_OFF_STREAK = 5
VIX_LEVEL, VIX_SPIKE = 30, 0.50
SPY_5D_THR, HYG_5D_THR = -0.07, -0.03

SFG_W_VK, SFG_W_MOM = 0.6, 0.4
SFG_PCT_WINDOW = 252
SFG_MOM_DAYS = 20
SFG_ENTRY = 30
SFG_HOLD = 60
FG_OFF_PROXY = "SPY"

# KRX 공식 공공데이터 API — VKOSPI(코스피200 변동성지수) 일별 수집용 (역시 환경변수로 주입)
FG_KRX_AUTH_KEY = os.environ.get("FG_KRX_AUTH_KEY", "")
VKOSPI_IDX_NAME = "코스피 200 변동성지수"
VKOSPI_START = datetime(2010, 1, 1)


# ------------------------------------------------------------------
# 데이터 로딩
# ------------------------------------------------------------------
def try_fetch_fred(series_id, start, end):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return try_fetch_fred_api(series_id, start, end)
        raw = pd.read_csv(StringIO(r.text))
        raw.columns = ["date", series_id]
        raw["date"] = pd.to_datetime(raw["date"])
        raw[series_id] = pd.to_numeric(raw[series_id], errors="coerce")
        raw = raw.dropna().set_index("date")
        s = raw.loc[start:end, series_id]
        return s if len(s) > 24 else None
    except Exception:
        return try_fetch_fred_api(series_id, start, end)


def try_fetch_fred_api(series_id, start, end, tries=6):
    """fredgraph CSV(웹사이트)가 안 될 때 쓰는 대체 경로: FRED API 최신값."""
    try:
        params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json",
                  "observation_start": start, "observation_end": end}
        for k in range(tries):                      # FRED 일시적 5xx 대비 재시도
            r = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=60)
            if r.status_code < 500:
                break
            time.sleep(5 * (k + 1))
        if r.status_code != 200:
            return None
        df = pd.DataFrame(r.json().get("observations", []))
        s = pd.Series(pd.to_numeric(df["value"], errors="coerce").values,
                      index=pd.to_datetime(df["date"]), name=series_id).dropna()
        return s if len(s) > 24 else None
    except Exception:
        return None


def try_fetch_fred_realtime_yoy(series_id, start, end, api_key, tries=6):
    """관측월별 최초 발표일과 '실시간 YoY(%)'.

    YoY = t월 최초발표치 / (t월이 처음 실린 같은 발표본의 t-12월 값) - 1.
    서로 다른 발표본의 최초발표치끼리 나누면 INDPRO 기준연도 변경(재기준) 때 YoY가 최대 20%p 넘게
    틀어지므로, 반드시 같은 발표본 안에서 계산함. t월이 처음 발표될 때 이미 알 수 있는 값이라 PIT.
    반환: DataFrame(index=관측월, columns=[pub, yoy])
    """
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        obs_start = (pd.Timestamp(start) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        params = {
            "series_id": series_id, "api_key": api_key, "file_type": "json",
            # realtime_end는 FRED 서버 날짜(미국 시간) 이후면 400 에러 -> 한국 날짜로 넘기면 폴백돼버림.
            # 9999-12-31은 "현재까지 모든 발표본"이라 결과는 같고 시차 문제가 없음.
            "output_type": 2, "realtime_start": "1776-07-04", "realtime_end": "9999-12-31",
            "observation_start": obs_start, "observation_end": end,
        }
        for k in range(tries):                      # FRED 일시적 5xx 대비 재시도
            r = requests.get(url, params=params, timeout=120)
            if r.status_code < 500:
                break
            time.sleep(5 * (k + 1))
        if r.status_code != 200:
            return None
        rows = {rec["date"]: {k.rsplit("_", 1)[-1]: (float(v) if v not in (None, "", ".") else np.nan)
                              for k, v in rec.items() if k != "date"}
                for rec in r.json().get("observations", [])}
        if not rows:
            return None
        V = pd.DataFrame(rows).T                   # 행: 관측월, 열: 발표일(vintage)
        V.index = pd.to_datetime(V.index)
        V.columns = pd.to_datetime(V.columns, format="%Y%m%d")
        V = V.sort_index().sort_index(axis=1)
        out = []
        for t in V.index:
            pub = V.loc[t].first_valid_index()
            t12 = t - pd.DateOffset(years=1)
            if pub is None or t12 not in V.index:
                continue
            out.append((t, pub, (V.at[t, pub] / V.at[t12, pub] - 1) * 100))
        df = pd.DataFrame(out, columns=["obs", "pub", "yoy"]).set_index("obs").dropna()
        return df if len(df) > 24 else None
    except Exception:
        return None


def try_download_yfinance(tickers, start, end):
    try:
        data = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)
        if data.empty:
            return None
        px = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
        return None if px.isna().all().all() else px
    except Exception:
        return None


def fetch_naver_close(symbol, start="20080101"):
    url = (f"https://api.finance.naver.com/siseJson.naver?symbol={symbol}&requestType=1"
           f"&startTime={start}&endTime=20991231&timeframe=day")
    txt = requests.get(url, timeout=15).text
    rows = re.findall(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*(\d+),\s*([\d.]+)\]', txt)
    return pd.Series({pd.Timestamp(d_): float(c) for d_, o, h, l, c, v, f in rows}).sort_index()


def fetch_vkospi_krx_range(start_date, end_date, auth_key=FG_KRX_AUTH_KEY):
    """KRX 공공데이터 API에서 영업일별 VKOSPI(코스피200 변동성지수)를 수집. 실패한 날은 조용히 건너뜀."""
    base_url = "https://data-dbg.krx.co.kr/svc/apis/idx/drvprod_dd_trd"
    out = {}
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            ds = d.strftime("%Y%m%d")
            try:
                resp = requests.get(base_url, headers={"AUTH_KEY": auth_key}, params={"basDd": ds}, timeout=15)
                if resp.status_code == 200:
                    for item in resp.json().get("OutBlock_1", []):
                        if item.get("IDX_NM") == VKOSPI_IDX_NAME:
                            out[ds] = float(item["CLSPRC_IDX"])
            except Exception:
                pass
            time.sleep(0.15)
        d += timedelta(days=1)
    return out


def load_and_update_vkospi_cache(csv_path, end=None):
    """로컬 CSV 캐시를 읽고, 캐시의 마지막 날짜 다음날부터 오늘(또는 end)까지만 KRX API로
    증분 수집해서 캐시 파일에 반영. 매번 전체를 새로 받지 않고 모자란 날짜만 채우는 방식이라
    사용자가 수동으로 vkospi_daily.csv를 갱신할 필요가 없음."""
    cache = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                cache[row["date"]] = float(row["vkospi"])

    end_dt = datetime.combine(pd.Timestamp(end).date() if end else date.today(), datetime.min.time())
    last_dt = datetime.strptime(max(cache), "%Y%m%d") if cache else (VKOSPI_START - timedelta(days=1))
    incr_start = last_dt + timedelta(days=1)

    added = 0
    if incr_start <= end_dt:
        new_vk = fetch_vkospi_krx_range(incr_start, end_dt)
        if new_vk:
            cache.update(new_vk)
            added = len(new_vk)

    if added:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "vkospi"])
            for d in sorted(cache):
                w.writerow([d, cache[d]])

    s = pd.Series({pd.Timestamp(d_): v for d_, v in cache.items()}).sort_index()
    return s, added


# ------------------------------------------------------------------
# 축 생성
# ------------------------------------------------------------------
def monthly_index(s):
    s = s.copy()
    s.index = s.index.to_period("M").to_timestamp()
    return s.groupby(level=0).last()


def build_yoy_trend_axis(raw, lag_months, trend_window):
    s = monthly_index(raw)
    value = s.shift(lag_months).pct_change(12) * 100
    trend = value.rolling(trend_window).mean()
    return pd.DataFrame({"value": value, "trend": trend, "rising": value > trend}).dropna()


def build_axis_from_vintage(realtime_yoy, trend_window):
    """실시간 YoY(관측월 기준) -> 월별 축. 인덱스 = 그 상태를 알 수 있게 된 달(결정 월).

    추세는 관측월 기준 직전 trend_window개 YoY 평균 (미발표 달이 있어도 끊기지 않게 최소 trend_window-2개).
    각 달 말에 그때까지 발표된 가장 최근 관측치의 상태를 씀(as-of). 새 발표가 없는 달은 직전 상태 유지.
    """
    yoy = realtime_yoy["yoy"].asfreq("MS")
    trend = yoy.rolling(trend_window, min_periods=trend_window - 2).mean()
    st = pd.DataFrame({"value": yoy, "trend": trend, "rising": yoy > trend}).dropna()
    st["obs"] = st.index
    st["pub"] = realtime_yoy.loc[st.index, "pub"]
    last_pub_month = st["pub"].max() + pd.offsets.MonthEnd(0)
    decision = pd.date_range(st["pub"].min() + pd.offsets.MonthEnd(0), last_pub_month, freq="ME")
    m = pd.merge_asof(pd.DataFrame({"decision": decision}), st.sort_values("pub"),
                      left_on="decision", right_on="pub", direction="backward").dropna(subset=["rising"])
    m.index = m["decision"].dt.to_period("M").dt.to_timestamp()
    m["rising"] = m["rising"].astype(bool)
    return m[["value", "trend", "rising", "obs", "pub"]]


def label_regime(growth_rising, inflation_rising):
    if growth_rising and not inflation_rising:
        return "Goldilocks"
    elif growth_rising and inflation_rising:
        return "Reflation"
    elif not growth_rising and inflation_rising:
        return "Stagflation"
    else:
        return "Deflation"


# ------------------------------------------------------------------
# 배분 로직
# ------------------------------------------------------------------
def build_equal_weight_fallback():
    return pd.DataFrame({
        "자산": ETF_UNIVERSE,
        "구분": ["주식" if a in EQUITY_ASSETS else "비주식" for a in ETF_UNIVERSE],
        "비중": [1.0 / len(ETF_UNIVERSE)] * len(ETF_UNIVERSE),
    })


def build_tilt_allocation(regime_name):
    equity_total = REGIME_EQUITY_TARGET.get(regime_name, DEFAULT_EQUITY)
    equities = [a for a in ETF_UNIVERSE if a in EQUITY_ASSETS]
    rows = [{"자산": a, "구분": "주식", "비중": equity_total / len(equities)} for a in equities]
    rows += [{"자산": a, "구분": "비주식", "비중": (1 - equity_total) / len(NON_EQUITY_ASSETS)}
             for a in NON_EQUITY_ASSETS]
    return pd.DataFrame(rows)


def build_regime_asset_stats(df_subset):
    rows = []
    for regime_name, group in df_subset.groupby("regime"):
        for asset in ETF_UNIVERSE:
            r = group[asset].dropna()
            if len(r) < 3:
                continue
            rows.append({
                "레짐": regime_name, "자산": asset, "관측월수": len(r),
                "평균월수익률": r.mean(), "승률": (r > 0).mean(),
                "월Sharpe": r.mean() / r.std() if r.std() > 0 else np.nan,
                "연환산수익률": (1 + r.mean()) ** 12 - 1,
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# 성과 통계
# ------------------------------------------------------------------
def perf_stats(rets, periods_per_year=12):
    rets = rets.dropna()
    cum = (1 + rets).cumprod()
    n_years = len(rets) / periods_per_year
    cagr = cum.iloc[-1] ** (1 / n_years) - 1 if n_years > 0 else np.nan
    vol = rets.std() * np.sqrt(periods_per_year)
    sharpe = (rets.mean() * periods_per_year) / vol if vol > 0 else np.nan
    mdd = (cum / cum.cummax() - 1).min()
    return {"cum": cum, "CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "MDD": mdd, "rets": rets}


# ------------------------------------------------------------------
# 기간 분석 (특정 구간에서 뭐가 이득/마이너스였는지, 오버레이가 도움이 됐는지)
# ------------------------------------------------------------------
def asset_contributions(weights_df, daily_rets, start=None, end=None):
    """weights_df(시점x자산 실제 보유비중) × 그날 수익률을 더해 자산별 '수익 기여도'를 근사.
    컴파운딩을 무시한 선형 근사치라 정확한 분해는 아니지만, 어떤 자산이 그 구간 수익에
    플러스/마이너스로 기여했는지 순위를 매기는 용도로는 충분함 ("대충 분석")."""
    w = weights_df
    if start is not None:
        w = w.loc[w.index >= pd.Timestamp(start)]
    if end is not None:
        w = w.loc[w.index <= pd.Timestamp(end)]
    aligned = daily_rets.reindex(index=w.index, columns=w.columns).fillna(0.0)
    contrib = (w * aligned).sum(axis=0)
    return contrib.sort_values(ascending=False)


def worst_drawdown_window(rets):
    """rets 구간 안에서 가장 깊었던 낙폭의 고점/저점/회복일(없으면 None)과 낙폭(%)을 반환."""
    cum = (1 + rets).cumprod()
    roll_max = cum.cummax()
    dd = cum / roll_max - 1
    trough = dd.idxmin()
    peak = cum.loc[:trough].idxmax()
    peak_value = cum.loc[peak]
    after = cum.loc[trough:]
    recovered = after[after >= peak_value]
    recovery = recovered.index[0] if len(recovered) else None
    return {"peak": peak, "trough": trough, "recovery": recovery, "dd": dd.min()}


# ------------------------------------------------------------------
# 간단 F&G (규칙 A)
# ------------------------------------------------------------------
def sfg_pct252(s):
    return 100 * s.rolling(SFG_PCT_WINDOW).rank(pct=True)


def sfg_build_score(kospi, vk):
    df = pd.DataFrame({"kospi": kospi, "vk": vk.reindex(kospi.index)})
    df["v_score"] = 100 - sfg_pct252(df.vk.dropna()).reindex(df.index)
    df["m_score"] = sfg_pct252(df.kospi.pct_change(SFG_MOM_DAYS))
    df["score"] = SFG_W_VK * df.v_score + SFG_W_MOM * df.m_score
    return df[df.vk.notna()]


def sfg_backtest_positions(df, entry=SFG_ENTRY, hold=SFG_HOLD):
    s, idx = df.score.values, df.index
    n = len(df)
    trades_, inm_, i = [], np.zeros(n, bool), 0
    while i < n - 1:
        if s[i] < entry:
            ei = i + 1
            xi = min(ei + hold, n - 1)
            done = ei + hold <= n - 1
            trades_.append(dict(신호일=idx[i], 진입일=idx[ei], 청산일=idx[xi], 진입점수=round(s[i], 1),
                                 상태="만기" if done else "보유중"))
            inm_[ei + 1:xi + 1] = True
            i = xi
        else:
            i += 1
    return pd.DataFrame(trades_), pd.Series(inm_, index=idx)


# ------------------------------------------------------------------
# 위기 오버레이 상태기계
# ------------------------------------------------------------------
def run_crisis_overlay(vix_d, vix_ma20, spy_5d, hyg_5d, vix_level=VIX_LEVEL, vix_spike=VIX_SPIKE,
                        spy_thr=SPY_5D_THR, hyg_thr=HYG_5D_THR, vote_need=2,
                        min_hold=MIN_HOLD_DAYS, min_off=MIN_OFF_STREAK):
    vix_cond = (vix_d > vix_level) & ((vix_d / vix_ma20 - 1) > vix_spike)
    equity_cond = spy_5d <= spy_thr
    credit_cond = hyg_5d <= hyg_thr
    vote = vix_cond.astype(int) + equity_cond.astype(int) + credit_cond.astype(int)
    raw_on = (vote >= vote_need).fillna(False).astype(bool)
    lagged_on = raw_on.shift(1).fillna(False).astype(bool)

    state, days_since_on, consec_off = False, 0, 0
    states = []
    for sig in lagged_on:
        if state:
            if sig:
                days_since_on, consec_off = 0, 0
            else:
                days_since_on += 1
                consec_off += 1
            if days_since_on >= min_hold and consec_off >= min_off:
                state = False
                days_since_on, consec_off = 0, 0
        else:
            if sig:
                state = True
                days_since_on, consec_off = 0, 0
        states.append(state)
    return pd.Series(states, index=lagged_on.index), vote


def crisis_on_runs(crisis_state):
    runs = []
    cur = crisis_state.iloc[0]
    start = crisis_state.index[0]
    prev = start
    for d, v in crisis_state.items():
        if v != cur:
            if cur:
                runs.append((start, prev))
            cur, start = v, d
        prev = d
    if cur:
        runs.append((start, prev))
    return runs


# ------------------------------------------------------------------
# 거래비용 (턴오버 기반)
# ------------------------------------------------------------------
DEFAULT_ONE_WAY_COST_BPS = 5.0


def compute_turnover_costs(weights_df, one_way_cost_bps):
    """weights_df: 시점 x 자산, 실제 보유비중(오버레이 반영 후). 하루(또는 한달) 전 대비 비중 변화의
    절대값 합(턴오버)에 편도 거래비용을 곱해 비용 시리즈를 만든다. 첫 시점은 현금에서 진입하는 비용."""
    if weights_df.empty:
        return pd.Series(dtype=float)
    diffs = weights_df.diff()
    diffs.iloc[0] = weights_df.iloc[0]
    turnover = diffs.abs().sum(axis=1)
    if one_way_cost_bps <= 0:
        return turnover * 0.0
    return turnover * (one_way_cost_bps / 10000.0)


def build_daily_weights(px_index, wf_alloc_log, crisis_state, fg_in_position=None):
    """3개 레이어를 반영한 실제 보유비중(자산별, 오버레이로 리다이렉트된 결과까지 합산)을
    매 거래일마다 만든다. 턴오버/거래비용 계산과 파이차트에 모두 재사용."""
    rows, days = [], []
    for d in px_index:
        m = d.to_period("M").to_timestamp()
        w = month_weights_from_log(wf_alloc_log, m)
        if w is None:
            continue
        on = bool(crisis_state.get(d, False))
        fg_on = bool(fg_in_position.get(d, True)) if fg_in_position is not None else True
        eff = {}
        for asset, weight in w.items():
            if on and asset in CRISIS_DERISK_ASSETS:
                src = TBILL_PROXY
            elif fg_in_position is not None and asset == "069500.KS" and not fg_on:
                src = FG_OFF_PROXY
            else:
                src = asset
            eff[src] = eff.get(src, 0.0) + weight
        rows.append(eff)
        days.append(d)
    holding_cols = list(dict.fromkeys(ETF_UNIVERSE + [TBILL_PROXY, FG_OFF_PROXY]))
    return pd.DataFrame(rows, index=days).reindex(columns=holding_cols).fillna(0.0)


def portfolio_returns_from_weights(weights_df, daily_rets):
    aligned = daily_rets.reindex(index=weights_df.index, columns=weights_df.columns).fillna(0.0)
    return (weights_df * aligned).sum(axis=1)


# ------------------------------------------------------------------
# 1단계: 네트워크 데이터 수집 (레짐/비용 파라미터와 무관 — 캐시 대상)
# ------------------------------------------------------------------
def fetch_market_data(vkospi_csv_path, end=None):
    end = end or date.today().isoformat()
    d = {"end": end}

    indpro_raw = try_fetch_fred("INDPRO", START, end)
    cpi_raw = try_fetch_fred("CPIAUCSL", START, end)
    usrec_raw = try_fetch_fred("USREC", START, end)
    indpro_vintage = try_fetch_fred_realtime_yoy("INDPRO", START, end, FRED_API_KEY)
    cpi_vintage = try_fetch_fred_realtime_yoy("CPIAUCSL", START, end, FRED_API_KEY)
    if indpro_raw is None or cpi_raw is None or usrec_raw is None:
        raise RuntimeError("FRED 매크로 데이터 로딩 실패 (네트워크 확인 필요)")

    all_tickers = ETF_UNIVERSE + [t for t in AUX_TICKERS if t not in ETF_UNIVERSE]
    px = try_download_yfinance(all_tickers, START, end)
    if px is None:
        raise RuntimeError("yfinance ETF 가격 로딩 실패 (네트워크 확인 필요)")
    px = px[all_tickers].dropna(how="all").ffill().dropna()

    vix_raw = try_fetch_fred("VIXCLS", START, end)
    if vix_raw is None:
        raise RuntimeError("VIXCLS 로딩 실패")
    vix_d = vix_raw.reindex(px.index).ffill()

    fg_ok = True
    vk_added = 0
    try:
        sfg_vk, vk_added = load_and_update_vkospi_cache(vkospi_csv_path, end=end)
        sfg_kospi = fetch_naver_close("KOSPI")[:sfg_vk.index[-1]]
        sfg_df = sfg_build_score(sfg_kospi, sfg_vk)
        sfg_trades, fg_in_position = sfg_backtest_positions(sfg_df)
        fg_in_position_aligned = fg_in_position.reindex(px.index).astype(object).ffill().fillna(True).astype(bool)
    except Exception:
        fg_ok = False
        sfg_df = pd.DataFrame(columns=["score"])
        sfg_trades = pd.DataFrame()
        fg_in_position_aligned = pd.Series(True, index=px.index)

    d.update(dict(
        indpro_raw=indpro_raw, cpi_raw=cpi_raw, usrec_raw=usrec_raw,
        indpro_vintage=indpro_vintage, cpi_vintage=cpi_vintage,
        growth_is_vintage=indpro_vintage is not None, inflation_is_vintage=cpi_vintage is not None,
        px=px, price_data_asof=px.index[-1], daily_rets=px.pct_change(),
        vix_d=vix_d, vix_ma20=vix_d.rolling(20).mean(),
        spy_5d=px["SPY"].pct_change(5), hyg_5d=px["HYG"].pct_change(5),
        fg_ok=fg_ok, vkospi_added_days=vk_added,
        sfg_df=sfg_df, sfg_trades=sfg_trades, fg_in_position_aligned=fg_in_position_aligned,
    ))

    if fg_ok and len(sfg_df):
        sfg_last = sfg_df.index[-1]
        d["sfg_data_asof"] = sfg_last
        d["sfg_score_latest"] = sfg_df.score.iloc[-1]
        if len(sfg_trades) and sfg_trades.iloc[-1]["상태"] == "보유중":
            tr = sfg_trades.iloc[-1]
            held = sfg_df.index.get_loc(sfg_last) - sfg_df.index.get_loc(tr["진입일"])
            d["sfg_status_text"] = f"보유중 (진입 {tr['진입일'].date()}, {held}거래일 경과, 청산까지 {SFG_HOLD-held}거래일)"
        else:
            sc = sfg_df.score.iloc[-1]
            d["sfg_status_text"] = ("미보유 — 신호 있음(다음 거래일 매수 대상)" if sc < SFG_ENTRY else "미보유 — 대기")
    else:
        d["sfg_data_asof"] = None
        d["sfg_score_latest"] = None
        d["sfg_status_text"] = "데이터 없음"

    return d


# ------------------------------------------------------------------
# 2단계: 레짐 라벨링 + 백테스트 + 거래비용 반영 (순수 계산 — 빠름, 캐시 불필요)
# ------------------------------------------------------------------
def build_backtest(data, one_way_cost_bps=DEFAULT_ONE_WAY_COST_BPS):
    out = {"end": data["end"], "cost_bps": one_way_cost_bps}
    px = data["px"]
    daily_rets = data["daily_rets"]
    out["px"] = px
    out["daily_rets"] = daily_rets
    out["price_data_asof"] = data["price_data_asof"]
    out["growth_is_vintage"] = data["growth_is_vintage"]
    out["inflation_is_vintage"] = data["inflation_is_vintage"]

    monthly_px = px.resample("ME").last()
    monthly_rets = monthly_px.pct_change()

    # 축 생성
    growth_axis = (build_axis_from_vintage(data["indpro_vintage"], 12)
                   if data["indpro_vintage"] is not None and len(data["indpro_vintage"]) > 24
                   else build_yoy_trend_axis(data["indpro_raw"], 1, 12))
    inflation_axis = (build_axis_from_vintage(data["cpi_vintage"], 12)
                       if data["cpi_vintage"] is not None and len(data["cpi_vintage"]) > 24
                       else build_yoy_trend_axis(data["cpi_raw"], 1, 12))
    out["growth_axis"] = growth_axis
    out["inflation_axis"] = inflation_axis

    usrec_m = monthly_index(data["usrec_raw"])
    rec_months = usrec_m[usrec_m == 1].index
    common = growth_axis.index.intersection(rec_months)
    out["recession_fp_rate"] = growth_axis.loc[common, "rising"].mean() if len(common) else np.nan

    # 레짐 라벨링
    regime_macro = growth_axis[["rising"]].rename(columns={"rising": "growth_rising"}).join(
        inflation_axis[["rising"]].rename(columns={"rising": "inflation_rising"}), how="inner"
    ).dropna()
    regime_macro["regime"] = [label_regime(g, i) for g, i in
                               zip(regime_macro["growth_rising"], regime_macro["inflation_rising"])]
    out["regime_macro"] = regime_macro

    regime_series = regime_macro["regime"].copy()
    regime_series.index = (regime_series.index.to_period("M") + 1).to_timestamp()

    rets_idx = monthly_rets.copy()
    rets_idx.index = rets_idx.index.to_period("M").to_timestamp()

    merged = rets_idx.join(regime_series.rename("regime"), how="inner").dropna(subset=["regime"])
    out["merged"] = merged
    out["regime_asset_stats"] = build_regime_asset_stats(merged)

    # 워크포워드 월별 배분
    equal_weight_fallback = build_equal_weight_fallback()
    bt_months = rets_idx.loc[merged.index[0]:merged.index[-1]].index

    tilt_rets_gross, n_fallback = [], 0
    wf_alloc_log = {}
    monthly_weight_rows = []
    prev_m = None
    for m in bt_months:
        row = rets_idx.loc[m]
        if m in merged.index:
            hist = merged[merged.index < m]
            regime_now = merged.loc[m, "regime"]
            if len(hist) >= MIN_HIST_MONTHS and (hist["regime"] == regime_now).sum() >= MIN_REGIME_OBS:
                alloc = build_tilt_allocation(regime_now)
            else:
                alloc = equal_weight_fallback
                n_fallback += 1
        else:
            regime_now, alloc = wf_alloc_log[prev_m]
        wf_alloc_log[m] = (regime_now, alloc)
        prev_m = m
        w_dict = dict(zip(alloc["자산"], alloc["비중"]))
        monthly_weight_rows.append(w_dict)
        r = sum(w_dict.get(a, 0.0) * row[a] for a in ETF_UNIVERSE if pd.notna(row.get(a)))
        tilt_rets_gross.append(r)

    tilt_rets_gross = pd.Series(tilt_rets_gross, index=bt_months)
    monthly_weights_df = pd.DataFrame(monthly_weight_rows, index=bt_months).reindex(columns=ETF_UNIVERSE).fillna(0.0)
    tilt_cost = compute_turnover_costs(monthly_weights_df, one_way_cost_bps)
    tilt_rets = tilt_rets_gross - tilt_cost.reindex(tilt_rets_gross.index).fillna(0.0)

    out["tilt_rets"] = tilt_rets
    out["wf_alloc_log"] = wf_alloc_log
    out["n_fallback_months"] = n_fallback
    out["bt_months"] = bt_months

    # 위기 오버레이 (일별)
    vix_d, vix_ma20 = data["vix_d"], data["vix_ma20"]
    spy_5d, hyg_5d = data["spy_5d"], data["hyg_5d"]
    crisis_state, vote = run_crisis_overlay(vix_d, vix_ma20, spy_5d, hyg_5d)
    out["crisis_state"] = crisis_state
    out["crisis_runs"] = crisis_on_runs(crisis_state)
    out["vix_d"] = vix_d

    # 레짐+위기오버레이 (F&G 없음)
    overlay_weights = build_daily_weights(px.index, wf_alloc_log, crisis_state, fg_in_position=None)
    overlay_gross = portfolio_returns_from_weights(overlay_weights, daily_rets)
    overlay_cost = compute_turnover_costs(overlay_weights, one_way_cost_bps)
    overlay_rets = (overlay_gross - overlay_cost).dropna()
    out["overlay_rets"] = overlay_rets
    out["overlay_rets_gross"] = overlay_gross.dropna()

    # 레짐+위기오버레이+F&G (최종전략)
    fg_ok = data["fg_ok"]
    fg_in_position_aligned = data["fg_in_position_aligned"]
    out["fg_ok"] = fg_ok
    out["vkospi_added_days"] = data["vkospi_added_days"]
    out["sfg_df"] = data["sfg_df"]
    out["sfg_trades"] = data["sfg_trades"]
    out["fg_in_position_aligned"] = fg_in_position_aligned
    out["sfg_data_asof"] = data["sfg_data_asof"]
    out["sfg_score_latest"] = data["sfg_score_latest"]
    out["sfg_status_text"] = data["sfg_status_text"]

    fg_weights = build_daily_weights(px.index, wf_alloc_log, crisis_state, fg_in_position=fg_in_position_aligned)
    fg_gross = portfolio_returns_from_weights(fg_weights, daily_rets)
    fg_cost = compute_turnover_costs(fg_weights, one_way_cost_bps)
    fg_rets = (fg_gross - fg_cost).dropna()
    out["fg_rets"] = fg_rets
    out["fg_rets_gross"] = fg_gross.dropna()
    out["fg_weights"] = fg_weights
    out["fg_cost_total"] = fg_cost.reindex(fg_rets.index).fillna(0.0).sum()
    n_years_fg = len(fg_rets) / 252
    out["fg_cost_annualized"] = out["fg_cost_total"] / n_years_fg if n_years_fg > 0 else np.nan

    # 레짐 배분만 (오버레이 전혀 없음, 일별) — 기간 분석에서 "오버레이가 이 구간에서 도움이 됐는지" 비교용
    no_crisis_state = pd.Series(False, index=crisis_state.index)
    regime_only_weights = build_daily_weights(px.index, wf_alloc_log, no_crisis_state, fg_in_position=None)
    regime_only_gross = portfolio_returns_from_weights(regime_only_weights, daily_rets)
    regime_only_cost = compute_turnover_costs(regime_only_weights, one_way_cost_bps)
    out["regime_only_rets"] = (regime_only_gross - regime_only_cost).dropna()

    bench_daily_6040 = 0.6 * daily_rets["SPY"] + 0.4 * daily_rets["IEF"]
    out["bench_daily_6040"] = bench_daily_6040

    # 레짐별 배분표 + 오늘 기준 신호
    out["allocations_by_regime"] = {r: build_tilt_allocation(r) for r in REGIME_EQUITY_TARGET}

    latest_month = regime_macro.index[-1]
    latest_regime = regime_macro["regime"].iloc[-1]
    next_month = (latest_month.to_period("M") + 1).to_timestamp()
    if len(merged) >= MIN_HIST_MONTHS and (merged["regime"] == latest_regime).sum() >= MIN_REGIME_OBS:
        next_alloc = build_tilt_allocation(latest_regime)
        next_is_fallback = False
    else:
        next_alloc = equal_weight_fallback
        next_is_fallback = True

    out["latest_signal_month"] = latest_month
    out["latest_regime"] = latest_regime
    out["next_month"] = next_month
    out["next_month_alloc"] = next_alloc
    out["next_month_is_fallback"] = next_is_fallback

    last_day = px.index[-1]
    cur_month = last_day.to_period("M").to_timestamp()
    w_today = month_weights_from_log(wf_alloc_log, cur_month)
    live_source = "월별워크포워드"
    if w_today is None:
        w_today = dict(zip(next_alloc["자산"], next_alloc["비중"]))
        live_source = "레짐직접계산(폴백)"
        live_regime_this_month = latest_regime
    else:
        live_regime_this_month, _ = wf_alloc_log[cur_month]
    crisis_on_today = bool(crisis_state.iloc[-1])
    fg_on_today = bool(fg_in_position_aligned.iloc[-1])

    live_rows = []
    for asset in ETF_UNIVERSE:
        weight = w_today.get(asset, 0.0)
        src = asset
        note = ""
        if crisis_on_today and asset in CRISIS_DERISK_ASSETS:
            src = TBILL_PROXY
            note = "위기오버레이 ON → BIL로 대체"
        elif asset == "069500.KS" and not fg_on_today:
            src = FG_OFF_PROXY
            note = "F&G 미보유 → SPY로 대체"
        live_rows.append({"자산": asset, "목표비중": weight, "실제보유자산": src, "비고": note})
    live_alloc = pd.DataFrame(live_rows)
    live_alloc_collapsed = live_alloc.groupby("실제보유자산")["목표비중"].sum().reset_index()
    live_alloc_collapsed.columns = ["자산", "비중"]

    out["live_alloc_detail"] = live_alloc
    out["live_alloc_collapsed"] = live_alloc_collapsed
    out["live_source"] = live_source
    out["live_regime_this_month"] = live_regime_this_month
    out["cur_month"] = cur_month
    out["crisis_on_today"] = crisis_on_today
    out["fg_on_today"] = fg_on_today
    out["last_trading_day"] = last_day

    # 성과 지표 (거래비용 반영 후 기준)
    out["perf_final"] = perf_stats(fg_rets, 252)
    out["perf_final_gross"] = perf_stats(out["fg_rets_gross"], 252)
    out["perf_overlay_only"] = perf_stats(overlay_rets, 252)
    out["perf_tilt_monthly"] = perf_stats(tilt_rets, 12)
    out["perf_spy"] = perf_stats(daily_rets["SPY"].loc[fg_rets.index], 252)
    out["perf_6040"] = perf_stats(bench_daily_6040.loc[fg_rets.index], 252)

    # 연도별 수익률
    yearly_src = pd.DataFrame({
        "최종전략": fg_rets,
        "60/40": bench_daily_6040.loc[fg_rets.index].fillna(0),
        "SPY": daily_rets["SPY"].loc[fg_rets.index].fillna(0),
    })
    yearly = (1 + yearly_src).groupby(yearly_src.index.year).prod() - 1
    out["yearly_returns"] = yearly
    out["yearly_src"] = yearly_src

    # IS/OOS 7:3
    IS_RATIO = 0.7
    split_idx = int(len(fg_rets) * IS_RATIO)
    oos_start = fg_rets.index[split_idx]
    periods = {"IS (앞 70%)": (fg_rets.index[0], fg_rets.index[split_idx - 1]),
               "OOS (뒤 30%)": (oos_start, fg_rets.index[-1])}
    series_all = {
        "최종전략(레짐+위기오버레이+F&G)": fg_rets,
        "레짐+위기오버레이(F&G 없음)": overlay_rets,
        "60/40(SPY/IEF)": bench_daily_6040.loc[fg_rets.index].dropna(),
        "SPY 매수후보유": daily_rets["SPY"].loc[fg_rets.index].dropna(),
    }

    def period_stats(x):
        e = (1 + x).cumprod()
        vol = x.std() * np.sqrt(252)
        return {"CAGR": e.iloc[-1] ** (252 / len(x)) - 1, "연변동성": vol,
                "Sharpe": x.mean() * 252 / vol if vol > 0 else np.nan,
                "MDD": (e / e.cummax() - 1).min(), "총수익": e.iloc[-1] - 1}

    rows = {}
    for lab, (a, b) in periods.items():
        for name, s in series_all.items():
            rows[(lab, name)] = period_stats(s.loc[a:b])
    is_oos_tbl = pd.DataFrame(rows).T
    is_oos_tbl.index.set_names(["구간", "전략"], inplace=True)
    out["is_oos_table"] = is_oos_tbl
    out["is_oos_periods"] = periods
    out["is_oos_series"] = series_all

    return out


def month_weights_from_log(wf_alloc_log, month_ts):
    if month_ts not in wf_alloc_log:
        return None
    _, alloc = wf_alloc_log[month_ts]
    return dict(zip(alloc["자산"], alloc["비중"]))


def run_sensitivity_grid(px, daily_rets, vix_d, vix_ma20, get_month_weights, crisis_state_dummy=None):
    spy_5d = px["SPY"].pct_change(5)
    hyg_5d = px["HYG"].pct_change(5)

    def run_one(vl, vs, st, ht):
        state, vote = run_crisis_overlay(vix_d, vix_ma20, spy_5d, hyg_5d, vix_level=vl, vix_spike=vs,
                                          spy_thr=st, hyg_thr=ht)
        rets, days = [], []
        for d in px.index:
            m = d.to_period("M").to_timestamp()
            w = get_month_weights(m)
            if w is None:
                continue
            on = bool(state.get(d, False))
            r = 0.0
            for asset, weight in w.items():
                src_asset = TBILL_PROXY if (on and asset in CRISIS_DERISK_ASSETS) else asset
                ret = daily_rets[src_asset].get(d, np.nan) if src_asset in daily_rets.columns else np.nan
                if pd.notna(ret):
                    r += weight * ret
            rets.append(r)
            days.append(d)
        rets = pd.Series(rets, index=days).dropna()
        cum = (1 + rets).cumprod()
        n_years = len(rets) / 252
        cagr = cum.iloc[-1] ** (1 / n_years) - 1
        vol = rets.std() * np.sqrt(252)
        sharpe = (rets.mean() * 252) / vol if vol > 0 else np.nan
        mdd = (cum / cum.cummax() - 1).min()
        return cagr, sharpe, mdd, int(state.sum())

    grid_results = []
    for vl in [25, 30, 35]:
        for vs in [0.30, 0.50, 0.70]:
            for st in [-0.05, -0.07, -0.09]:
                for ht in [-0.02, -0.03, -0.04]:
                    cagr, sharpe, mdd, on_days = run_one(vl, vs, st, ht)
                    grid_results.append({"VIX레벨": vl, "VIX급등": vs, "SPY5일": st, "HYG5일": ht,
                                          "CAGR": cagr, "Sharpe": sharpe, "MDD": mdd, "ON일수": on_days})
    return pd.DataFrame(grid_results)
