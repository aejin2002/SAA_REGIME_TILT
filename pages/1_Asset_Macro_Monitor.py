import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# strategy.py가 모듈 로딩 시 os.environ에서 API 키를 읽으므로, import 전에 secrets를 주입.
for _key in ("FRED_API_KEY", "FG_KRX_AUTH_KEY"):
    if not os.environ.get(_key):
        try:
            os.environ[_key] = st.secrets[_key]
        except Exception:
            pass

import strategy as strat
import macro_monitor as mm

# ------------------------------------------------------------------
# 색 (메인 대시보드와 동일 — 남색 & 화이트, 주황 없음)
# ------------------------------------------------------------------
NAVY = "#122A52"
NAVY_DARK = "#0B1D3A"
NAVY_SOFT = "#3A4D73"
WHITE = "#FFFFFF"
BORDER = "#E2E6EE"
MUTED = "#5B6B88"
C_EMERALD = "#1E6E5C"
C_RED = "#9C2B2B"
C_CHARCOAL = "#454B57"
C_MIST = "#D3D7DD"

TREND_COLOR = {
    "Rising": NAVY, "Falling": C_CHARCOAL, "Neutral": MUTED,
    "Accelerating": C_RED, "Reversing": C_EMERALD,
}
TREND_LABEL = {
    "Rising": "Rising", "Falling": "Falling", "Neutral": "Neutral",
    "Accelerating": "Accelerating", "Reversing": "Reversing",
}

st.set_page_config(page_title="Asset & Macro Monitor", page_icon="📡", layout="wide")

st.markdown(f"""
<style>
.stApp {{ background-color: {WHITE}; }}
.block-container {{ padding-top: 1.2rem; max-width: 1200px; }}
#MainMenu, footer {{ visibility: hidden; }}
.hero {{ padding: 2px 0 16px 0; border-bottom: 1px solid {BORDER}; margin-bottom: 18px; }}
.hero-eyebrow {{ color: {NAVY_SOFT}; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; margin-bottom: 6px; }}
.hero h1 {{ margin: 0 0 8px 0; font-size: 2.0rem; font-weight: 500; color: {NAVY}; letter-spacing: -0.015em; }}
.hero p {{ margin: 0; color: {MUTED}; font-size: 0.88rem; }}
.axis-card {{ background: {WHITE}; border: 1px solid {BORDER}; border-radius: 12px; padding: 16px 20px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(18,42,82,0.06); }}
.axis-title {{ color: {NAVY}; font-size: 1.05rem; font-weight: 700; margin-bottom: 8px; }}
.axis-summary {{ color: {NAVY_SOFT}; font-size: 0.92rem; line-height: 1.5; }}
.ind-card {{ background: {WHITE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; min-height: 92px; }}
.ind-value-big {{ color: {NAVY}; font-size: 1.5rem; font-weight: 800; margin-top: 4px; }}
.ind-card-head {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }}
.ind-label {{ color: {NAVY}; font-weight: 700; font-size: 0.88rem; line-height: 1.25; }}
.ind-badge {{ font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 999px; color: {WHITE}; white-space: nowrap; margin-left: 6px; }}
.ind-sub {{ color: {MUTED}; font-size: 0.76rem; margin-top: 2px; }}
.ind-unavail {{ color: {MUTED}; font-size: 0.82rem; font-style: italic; margin-top: 2px; }}
.ind-brief {{ color: {NAVY_SOFT}; font-size: 0.8rem; line-height: 1.45; margin-top: 6px; }}
.ind-brief b {{ color: {NAVY}; }}
.section-title {{ color: {NAVY}; font-size: 1.15rem; font-weight: 700; margin: 26px 0 10px 0; padding-bottom: 6px; border-bottom: 2px solid {NAVY}; }}
.xref-card {{ background: {WHITE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 12px 16px; margin-bottom: 10px; }}
</style>
""", unsafe_allow_html=True)

VKOSPI_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "vkospi_daily.csv")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_market_data():
    return strat.fetch_market_data(VKOSPI_PATH)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_indicators(_cache_bust):
    data = load_market_data()
    return mm.compute_all(data)


st.markdown(f"""
<div class="hero">
  <div class="hero-eyebrow">Multi-Asset Macro Desk View</div>
  <h1>Asset & Macro Monitor</h1>
  <p>레짐 틸트 전략의 보유/신호 자산군별 핵심 매크로 변수를 추적하고, 수준·추세·경제적 의미·자산 영향을 함께 보여줍니다.
     기존 레짐/위기오버레이 로직은 그대로이며, 이 페이지는 추가 모니터링 레이어입니다.</p>
</div>
""", unsafe_allow_html=True)

try:
    with st.spinner("매크로 지표를 FRED 등에서 불러오는 중입니다 (지표 수가 많아 다소 걸릴 수 있어요)..."):
        market_data = load_market_data()
        res = load_indicators(market_data["price_data_asof"])
except Exception as e:
    st.error(f"데이터 로딩 실패: {e}")
    st.stop()

n_avail = sum(1 for v in res.values() if v["available"])
st.caption(f"총 {len(res)}개 지표 중 {n_avail}개 실시간 연동 완료 · 나머지는 무료 공개 API가 없어 '데이터 미확보'로 표시 (확장 가능 구조)")


def fmt_val(v, unit):
    if unit == "%":
        return f"{v:.2f}%"
    if unit == "pt":
        return f"{v:.1f}"
    if unit == "₩":
        return f"₩{v:,.1f}"
    if unit == "$":
        return f"${v:,.2f}"
    if unit == "index":
        return f"{v:,.2f}"
    if unit == "ratio":
        return f"{v:.3f}"
    if unit == "명":
        return f"{v:,.0f}명"
    return f"{v:,.2f}"


def fmt_chg(v, change_unit):
    if pd.isna(v):
        return "—"
    if change_unit == "bp":
        return f"{v:+.0f}bp"
    if change_unit == "pt":
        return f"{v:+.2f}pt"
    return f"{v:+.1f}%"


def _mini_chart(series_1y, key_id, unit):
    """일별 지표용 — 등락이 실제로 보이도록 0 기준으로 채우지 않고 데이터 자체 범위로 자동 스케일,
    축 눈금도 보이게 (전엔 fill=tozeroy + 축 숨김이라 금리·스프레드처럼 0 근처가 아닌 지표는
    변동이 안 보였음)."""
    fig = go.Figure(go.Scatter(
        x=series_1y.index, y=series_1y.values, mode="lines",
        line=dict(color=NAVY, width=2),
    ))
    y_suffix = "%" if unit == "%" else ("pt" if unit == "pt" else "")
    fig.update_layout(
        height=160, margin=dict(l=46, r=12, t=8, b=30),
        plot_bgcolor=WHITE, paper_bgcolor=WHITE, showlegend=False,
        xaxis=dict(gridcolor=BORDER, tickfont=dict(size=9, color=MUTED), nticks=5, showline=True, linecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, tickfont=dict(size=9, color=MUTED), ticksuffix=y_suffix,
                    showline=True, linecolor=BORDER, autorange=True),
    )
    st.plotly_chart(fig, use_container_width=True, key=key_id,
                     config={"displayModeBar": False})


def _interpretation_expander(ind, key, context, trend):
    with st.expander(f"{ind['label']} — 상승/하락 경제적 의미", key=f"exp_{context}_{key}"):
        cur_dir = "rising" if trend in ("Rising", "Accelerating") else ("falling" if trend == "Falling" else None)
        c1, c2 = st.columns(2)
        with c1:
            mark = " ◀ 현재 방향" if cur_dir == "rising" else ""
            st.markdown(f"**상승 시**{mark}")
            st.write(ind["rising"])
        with c2:
            mark = " ◀ 현재 방향" if cur_dir == "falling" else ""
            st.markdown(f"**하락 시**{mark}")
            st.write(ind["falling"])
        if ind.get("data_note"):
            st.caption(f"ℹ️ {ind['data_note']}")


def render_indicator_card(key, context):
    """지표 1개를 카드로. 일별 지표는 차트, 주/월/분기별 지표는 숫자(현재·직전·YoY)만 —
    주기가 긴 지표는 포인트가 적어 억지로 그래프를 그리면 오히려 안 읽혀서 숫자 비교가 더 명확함.
    데이터 미확보 지표는 그 자리에서 바로 상승/하락 해석을 브리핑."""
    ind = res.get(key)
    if ind is None:
        return
    label = ind["label"]

    if not ind["available"]:
        note = ind.get("data_note", "")
        st.markdown(f"""
<div class="ind-card">
  <div class="ind-card-head"><span class="ind-label">{label}</span>
     <span class="ind-badge" style="background:{MUTED}">데이터 미확보</span></div>
  <div class="ind-unavail">{note}</div>
  <div class="ind-brief"><b>상승 시(일반 해석)</b> — {ind['rising']}</div>
  <div class="ind-brief"><b>하락 시(일반 해석)</b> — {ind['falling']}</div>
</div>""", unsafe_allow_html=True)
        return

    trend = ind["trend"]
    badge_color = TREND_COLOR.get(trend, MUTED)
    assets_txt = " · ".join(strat.ASSET_LABELS.get(a, a) for a in ind.get("assets", []))

    if ind["freq"] != "D":
        prev_txt = (f"직전 {fmt_val(ind['prev'], ind['unit'])} ({ind['prev_date'].date()})"
                    if pd.notna(ind["prev"]) and ind["prev_date"] is not None else "직전값 없음")
        yoy_txt = fmt_chg(ind["chg_12m"], ind["change_unit"])
        st.markdown(f"""
<div class="ind-card">
  <div class="ind-card-head"><span class="ind-label">{label}</span>
     <span class="ind-badge" style="background:{badge_color}">{TREND_LABEL[trend]}</span></div>
  <div class="ind-value-big">{fmt_val(ind['latest'], ind['unit'])}</div>
  <div class="ind-sub">{prev_txt} · YoY {yoy_txt}</div>
  <div class="ind-sub">1M {fmt_chg(ind['chg_1m'], ind['change_unit'])} ·
     3M {fmt_chg(ind['chg_3m'], ind['change_unit'])} ·
     6M {fmt_chg(ind['chg_6m'], ind['change_unit'])}</div>
  {f'<div class="ind-sub">관련 자산: {assets_txt}</div>' if assets_txt else ''}
</div>""", unsafe_allow_html=True)
        _interpretation_expander(ind, key, context, trend)
        return

    st.markdown(f"""
<div class="ind-card">
  <div class="ind-card-head"><span class="ind-label">{label}</span>
     <span class="ind-badge" style="background:{badge_color}">{TREND_LABEL[trend]}</span></div>
  <div class="ind-sub">현재 {fmt_val(ind['latest'], ind['unit'])} ({ind['data_date'].date()}) ·
     1M {fmt_chg(ind['chg_1m'], ind['change_unit'])} · 3M {fmt_chg(ind['chg_3m'], ind['change_unit'])} ·
     6M {fmt_chg(ind['chg_6m'], ind['change_unit'])}</div>
</div>""", unsafe_allow_html=True)
    full_series = ind["series"]
    cutoff = full_series.index[-1] - pd.Timedelta(days=365)
    series_1y = full_series.loc[full_series.index >= cutoff]
    _mini_chart(series_1y, key_id=f"chart_{context}_{key}", unit=ind["unit"])
    if assets_txt:
        st.caption(f"관련 자산: {assets_txt}")
    _interpretation_expander(ind, key, context, trend)


def render_indicator_grid(keys, context, n_cols=3):
    """지표 여러 개를 한 화면에서 그래프까지 한눈에 — 카드 그리드로 배치."""
    cols = st.columns(n_cols, gap="medium")
    for i, key in enumerate(keys):
        with cols[i % n_cols]:
            render_indicator_card(key, context)


# ------------------------------------------------------------------
# A. Macro Regime Dashboard
# ------------------------------------------------------------------
st.markdown('<div class="section-title">A. Macro Regime Dashboard</div>', unsafe_allow_html=True)

AXIS_KEYS = {
    "growth": ["INDPRO", "ICSA", "ISM_MFG", "ISM_SVC", "GDPNOW"],
    "inflation": ["CPI_CORE", "PCE_CORE", "BREAKEVEN_10Y", "FORWARD_5Y5Y", "AHE"],
    "policy": ["FEDFUNDS", "UST_2Y", "REAL_YIELD_10Y", "SOFR", "M2_US"],
    "credit": ["HY_OAS", "IG_OAS", "VIX", "MOVE_PROXY", "NFCI"],
    "sentiment": ["AAII", "COT", "PUTCALL", "BOFA_FMS"],
}

for axis in mm.AXIS_ORDER:
    summary = mm.AXIS_SUMMARY_FN[axis](res)
    st.markdown(f"""
<div class="axis-card">
  <div class="axis-title">{mm.AXIS_LABELS[axis]}</div>
  <div class="axis-summary">{summary}</div>
</div>""", unsafe_allow_html=True)
    render_indicator_grid(AXIS_KEYS[axis], context=f"axis_{axis}")

# ------------------------------------------------------------------
# B. Asset-specific Dashboard
# ------------------------------------------------------------------
st.markdown('<div class="section-title">B. Asset-specific Dashboard</div>', unsafe_allow_html=True)
st.caption("보유 자산 패널을 펼치면 핵심 지표·추세·경제적 해석·관련 ETF 영향을 확인할 수 있습니다.")

for asset_key, label in mm.ASSET_LABELS.items():
    with st.expander(label):
        n_asset_avail = sum(1 for k in mm.ASSET_PANEL_KEYS[asset_key] if res.get(k, {}).get("available"))
        st.caption(f"{len(mm.ASSET_PANEL_KEYS[asset_key])}개 지표 중 {n_asset_avail}개 실시간 연동")
        render_indicator_grid(mm.ASSET_PANEL_KEYS[asset_key], context=f"asset_{asset_key}")

# ------------------------------------------------------------------
# C. Crisis Overlay 연계
# ------------------------------------------------------------------
st.markdown('<div class="section-title">기존 Crisis Overlay와의 연계</div>', unsafe_allow_html=True)
st.caption("기존 위기오버레이 신호(VIX/SPY/HYG 2표 중 2표)는 그대로 둔 채, 신규 매크로 지표가 "
           "같은 방향을 가리키는지 추가로 보여줍니다. 상충한다고 매매 신호는 아니며, 모니터링 참고용입니다.")

bt = strat.build_backtest(market_data, one_way_cost_bps=5.0)
crisis_on = bool(bt["crisis_on_today"])
st.markdown(f"""<div class="xref-card">
<b>현재 위기오버레이 상태:</b> {'🔴 ON (위험회피)' if crisis_on else '🟢 OFF (정상)'}
(기준일 {bt['last_trading_day'].date()})
</div>""", unsafe_allow_html=True)


def xref_row(title, legs, verdict_fn):
    vals = []
    ok = True
    for key in legs:
        ind = res.get(key)
        if not ind or not ind["available"]:
            ok = False
            break
        vals.append(ind["trend"])
    if not ok:
        st.markdown(f"""<div class="xref-card"><b>{title}</b><br>
        <span class="ind-unavail">관련 지표 중 일부가 데이터 미확보라 교차확인 불가.</span></div>""",
                    unsafe_allow_html=True)
        return
    verdict = verdict_fn(*vals)
    st.markdown(f"""<div class="xref-card"><b>{title}</b><br>{verdict}</div>""", unsafe_allow_html=True)


def _v(key):
    return res[key]["latest"] if res.get(key, {}).get("available") else None


xref_row(
    "VIX ↑ + HY OAS ↑ → 주식·신용 동반 스트레스 여부",
    ["VIX", "HY_OAS"],
    lambda vt, ht: (
        f"VIX {TREND_LABEL[vt]}, HY OAS {TREND_LABEL[ht]} — "
        + ("두 지표 모두 확대 방향으로 정렬돼 있어 주식·신용시장이 동반 스트레스를 받고 있다는 신호가 겹칩니다."
           if vt in ("Rising", "Accelerating") and ht in ("Rising", "Accelerating")
           else "두 지표가 같은 방향으로 정렬되어 있지 않아 동반 스트레스 신호는 약합니다.")
    ),
)

xref_row(
    "10Y 실질금리 ↑ + 기대인플레 ↓ → 금 가격 압력 여부",
    ["REAL_YIELD_10Y", "BREAKEVEN_10Y"],
    lambda ryt, bet: (
        f"10Y 실질금리 {TREND_LABEL[ryt]}, 10Y 기대인플레 {TREND_LABEL[bet]} — "
        + ("실질금리 상승과 기대인플레 하락이 겹쳐 금의 보유 기회비용이 높아지는 조합입니다."
           if ryt in ("Rising", "Accelerating") and bet in ("Falling",)
           else "금 가격에 대한 뚜렷한 방향성 조합은 아닙니다.")
    ),
)

xref_row(
    "Broad Dollar ↑ + 원/달러 ↑(원화 약세) → 외국인 수급 부담 여부",
    ["DXY_BROAD", "USDKRW"],
    lambda dxt, krt: (
        f"Broad Dollar {TREND_LABEL[dxt]}, 원/달러 {TREND_LABEL[krt]} — "
        + ("달러 강세와 원화 약세가 동시에 나타나고 있어 외국인 입장의 원화자산 수급 부담 가능성에 유의할 구간입니다."
           if dxt in ("Rising", "Accelerating") and krt in ("Rising", "Accelerating")
           else "달러·원화 방향이 뚜렷하게 같은 쪽으로 정렬되어 있지는 않습니다.")
    ),
)

xref_row(
    "10Y 금리 ↑ + 채권 변동성(대용) ↑ → 채권시장 변동성 확대 여부",
    ["UST_10Y", "MOVE_PROXY"],
    lambda uyt, mvt: (
        f"10Y 금리 {TREND_LABEL[uyt]}, 채권 변동성 대용지표 {TREND_LABEL[mvt]} — "
        + ("금리 상승과 변동성 확대가 겹쳐 있어 채권시장이 민감하게 반응하는 국면일 수 있습니다."
           if uyt in ("Rising", "Accelerating") and mvt in ("Rising", "Accelerating")
           else "금리·변동성 방향이 뚜렷하게 같은 쪽으로 정렬되어 있지는 않습니다.")
    ),
)

st.markdown(f"""
<div class="xref-card" style="border-color:{BORDER}; color:{MUTED}; font-size:0.85rem;">
⚠️ 위 교차확인은 참고용 모니터링 정보이며, 기존 레짐 틸트·위기오버레이의 실제 매매 신호를 변경하지 않습니다.
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="section-title">한계 (요약)</div>', unsafe_allow_html=True)
st.markdown(f"""
<div style="color:{MUTED}; font-size:0.85rem; line-height:1.6;">
• 이 페이지의 지표 중 상당수(ISM PMI, GDPNow, AAII, COT, Put/Call, BofA FMS, SOX, Forward PE, CDX 등)는
  유료 라이선스/비공개 데이터원이라 무료 공개 API가 없어 현재 "데이터 미확보" 상태입니다. 임의로 수치를 만들지 않았습니다.<br>
• MOVE Index는 ICE BofA 독점 지수라 자체 보유 TLT 가격으로 만든 실현변동성 대용치로 표시했습니다 (실제 MOVE와 다름).<br>
• DTWEXBGS는 좁은 의미의 DXY(ICE 선물 인덱스)가 아니라 Fed의 Broad Dollar Index입니다.<br>
• 월별/주별 지표는 발표 주기상 최신 관측일이 오늘보다 늦을 수 있으며(예: CPI는 약 1개월 시차), 각 지표 카드의 "관측일"을 기준으로 해석해야 합니다.<br>
• 1M/3M/6M 변화는 각 지표 자체의 발표 주기를 기준으로 계산했으며, Look-ahead bias 없이 과거 시점까지의 값만 사용합니다.
</div>
""", unsafe_allow_html=True)
