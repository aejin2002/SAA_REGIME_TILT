import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# strategy.py는 모듈 로딩 시점에 os.environ에서 API 키를 읽으므로, strategy를 import하기 전에
# Streamlit secrets(.streamlit/secrets.toml, 로컬이면 비공개로 git에 안 올라감 / Streamlit Cloud면
# 배포 설정의 Secrets)에 키가 있으면 환경변수로 먼저 주입해준다.
for _key in ("FRED_API_KEY", "FG_KRX_AUTH_KEY"):
    if not os.environ.get(_key):
        try:
            os.environ[_key] = st.secrets[_key]
        except Exception:
            pass

import strategy as strat

# ------------------------------------------------------------------
# 색 (남색 & 화이트 테마 — 주황 없이, 남색/블랙/그레이 + 보석톤 포인트)
# ------------------------------------------------------------------
NAVY = "#122A52"
NAVY_DARK = "#0B1D3A"
NAVY_SOFT = "#3A4D73"
STEEL = "#3D6FA8"
WHITE = "#FFFFFF"
SURFACE = "#F4F6FA"
BORDER = "#E2E6EE"
MUTED = "#5B6B88"

C_BLUE = NAVY              # 최종전략(우리 전략) — 남색
C_BRONZE = "#8C6B46"       # 60/40 — 블랙 대신 차분한 브론즈
C_GRAY = "#AEB4BD"         # SPY — 연한 회색
C_MIST = "#D3D7DD"         # 보조/참고선(오버레이 only) — 가장 옅은 회색, 점선
C_RED = "#9C2B2B"          # 위기오버레이 ON / 스태그플레이션 — 톤다운된 적포도주색
C_EMERALD = "#1E6E5C"      # 리플레이션 — 짙은 에메랄드 (주황 대신)
C_CHARCOAL = "#454B57"     # 디플레이션 / F&G 미보유 — 차콜

REGIME_COLOR = {
    "Goldilocks": NAVY,
    "Reflation": C_EMERALD,
    "Deflation": C_CHARCOAL,
    "Stagflation": C_RED,
}

ASSET_COLOR = {
    "SPY": NAVY, "QQQ": STEEL, "069500.KS": NAVY_DARK,
    "DBC": "#9C6B3E", "GLD": "#AD8A3B",
    "BIL": C_MIST, "IEF": "#7E8798", "TLT": NAVY_SOFT,
    "HYG": C_EMERALD, "LQD": "#54406B", "TIP": "#9C5B6E",
}

st.set_page_config(page_title="Regime Tilt", page_icon="📈", layout="wide")

st.markdown(f"""
<style>
.stApp {{ background-color: {WHITE}; }}
.block-container {{ padding-top: 1.2rem; max-width: 1200px; }}
#MainMenu, footer {{ visibility: hidden; }}

.hero {{
    padding: 2px 0 18px 0;
    border-bottom: 1px solid {BORDER};
    margin-bottom: 22px;
}}
.hero-eyebrow {{
    color: {NAVY_SOFT}; font-size: 0.74rem; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase; margin-bottom: 6px;
}}
.hero h1 {{ margin: 0 0 8px 0; font-size: 2.3rem; font-weight: 500; color: {NAVY}; letter-spacing: -0.015em; }}
.hero p {{ margin: 0; color: {MUTED}; font-size: 0.88rem; }}

.card {{
    background: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 16px 18px;
    box-shadow: 0 1px 3px rgba(18,42,82,0.06);
    height: 100%;
}}
.card-signal {{ min-height: 128px; box-sizing: border-box; }}
.card-label {{ color: {MUTED}; font-size: 0.78rem; font-weight: 600; letter-spacing: .02em; text-transform: uppercase; margin-bottom: 7px; }}
.card-value {{ color: {NAVY}; font-size: 1.7rem; font-weight: 800; line-height: 1.15; }}
.card-sub {{ color: {MUTED}; font-size: 0.8rem; margin-top: 5px; }}

.status-tag {{ font-size: 1.05rem; font-weight: 800; letter-spacing: -0.01em; }}
.status-dot {{ font-size: 0.6em; vertical-align: middle; margin-right: 7px; }}
.regime-name {{ font-size: 1.55rem; font-weight: 800; letter-spacing: -0.01em; }}
.regime-qualifier {{ display: block; font-size: 0.8rem; font-weight: 600; color: {MUTED}; margin-top: 3px; white-space: nowrap; }}

.section-title {{
    color: {NAVY}; font-size: 1.12rem; font-weight: 700;
    margin: 30px 0 10px 0; padding-bottom: 6px; border-bottom: 2px solid {NAVY};
}}
.signal-title {{
    color: {NAVY}; font-size: 0.95rem; font-weight: 700;
    margin: 4px 0 10px 0; letter-spacing: .02em;
}}

[data-testid="stMetricValue"] {{ color: {NAVY}; }}

.footnote {{ color: {MUTED}; font-size: 0.82rem; line-height: 1.6; }}
</style>
""", unsafe_allow_html=True)


def status_tag(text, color):
    return (f'<span class="status-tag" style="color:{color}">'
            f'<span class="status-dot" style="color:{color}">●</span>{text}</span>')


def regime_tag(name, qualifier, color):
    return (f'<span class="regime-name" style="color:{color}">{name}</span>'
            f'<span class="regime-qualifier">{qualifier}</span>')


def fmt_pct(x, digits=1):
    return f"{x*100:+.{digits}f}%" if pd.notna(x) else "—"


def fmt_pct0(x):
    return f"{x*100:.0f}%" if pd.notna(x) else "—"


VKOSPI_PATH = os.path.join(os.path.dirname(__file__), "data", "vkospi_daily.csv")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_market_data():
    return strat.fetch_market_data(VKOSPI_PATH)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_sensitivity(wf_alloc_log, px, daily_rets, vix_d, vix_ma20):
    gmw = lambda m: strat.month_weights_from_log(wf_alloc_log, m)  # noqa: E731
    return strat.run_sensitivity_grid(px, daily_rets, vix_d, vix_ma20, gmw)


with st.sidebar:
    st.markdown("### 📈 레짐 틸트 대시보드")
    st.caption("성장×인플레이션 레짐 틸트 + 위기오버레이 + 간단 F&G")
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    cost_bps = st.slider("편도 거래비용 (bp)", min_value=0, max_value=30, value=5, step=1,
                          help="자산을 사고팔 때마다 드는 비용(스프레드+수수료 가정). 리밸런싱/오버레이 전환으로 "
                               "발생하는 턴오버(비중 변화량)에 비례해 매일 차감됩니다. 0bp = 거래비용 없음.")
    st.caption(f"왕복 기준 {cost_bps*2}bp 가정 — 리밸런싱·오버레이 전환마다 적용")
    st.markdown("---")
    st.caption(
        "레이어 구성\n\n"
        "1️⃣ 월별 레짐 배분 (성장×인플레)\n\n"
        "2️⃣ 일별 위기 오버레이 (VIX/SPY/HYG)\n\n"
        "3️⃣ 간단 F&G (KODEX200 전용)"
    )

try:
    with st.spinner("매크로·가격 데이터를 불러오는 중입니다 (최초 로딩은 다소 걸릴 수 있어요)..."):
        market_data = load_market_data()
    bt = strat.build_backtest(market_data, one_way_cost_bps=float(cost_bps))
except Exception as e:
    st.error(f"데이터 로딩 또는 백테스트 실행에 실패했습니다: {e}")
    st.stop()

# ------------------------------------------------------------------
# 헤더
# ------------------------------------------------------------------
st.markdown(f"""
<div class="hero">
  <div class="hero-eyebrow">Growth × Inflation Strategy</div>
  <h1>Regime Tilt</h1>
  <p>월별 워크포워드 레짐 배분 · 일별 위기 오버레이 · 간단 F&amp;G(KODEX200) &nbsp;|&nbsp;
     가격데이터 기준일 {bt['price_data_asof'].date()} &nbsp;·&nbsp; 신호월 {bt['latest_signal_month'].strftime('%Y-%m')}
     &nbsp;·&nbsp; 거래비용 편도 {cost_bps}bp 반영</p>
</div>
""", unsafe_allow_html=True)

if bt["fg_ok"] and bt.get("sfg_data_asof") is not None:
    gap_days = (bt["last_trading_day"] - bt["sfg_data_asof"]).days
    if bt.get("vkospi_added_days", 0) > 0:
        st.info(f"VKOSPI 데이터 {bt['vkospi_added_days']}일치를 KRX 공공데이터 API에서 자동으로 받아와 캐시에 반영했습니다.")
    if gap_days > 10:
        st.warning(
            f"⚠️ VKOSPI 자동 수집을 시도했지만 {bt['sfg_data_asof'].date()}까지만 반영되어 F&G 신호가 {gap_days}일간 갱신되지 않았습니다. "
            f"KRX API 응답이 일시적으로 지연되었을 수 있으니 '데이터 새로고침'으로 다시 시도해보세요.")
else:
    st.warning("⚠️ 간단 F&G(KODEX200) 데이터를 불러오지 못해 해당 레이어는 비활성 상태(항상 보유중)로 처리됩니다.")

# ------------------------------------------------------------------
# 오늘의 시그널 — 레짐 / 비중 / 오버레이 상태를 맨 앞에 크게
# ------------------------------------------------------------------
regime = bt["latest_regime"]
regime_name_en = strat.REGIME_NAME_EN.get(regime, regime)
regime_qualifier_en = strat.REGIME_QUALIFIER_EN.get(regime, "")
regime_color = REGIME_COLOR.get(regime, NAVY_SOFT)
next_equity = strat.REGIME_EQUITY_TARGET.get(regime, strat.DEFAULT_EQUITY)
live_regime_ko = strat.REGIME_LABELS_KO.get(bt["live_regime_this_month"], bt["live_regime_this_month"])

st.markdown('<div class="signal-title">📍 오늘의 시그널</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class="card card-signal">
        <div class="card-label">현재 레짐 ({bt['latest_signal_month'].strftime('%Y-%m')} 신호)</div>
        <div>{regime_tag(regime_name_en, regime_qualifier_en, regime_color)}</div>
        <div class="card-sub">{'⚠ 데이터 부족 → 균등비중 폴백' if bt['next_month_is_fallback'] else f"{bt['next_month'].strftime('%Y-%m')} 배분에 적용"}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="card card-signal">
        <div class="card-label">{bt['next_month'].strftime('%Y-%m')} 목표 주식비중</div>
        <div class="card-value">{next_equity:.0%}</div>
        <div class="card-sub">비주식 {1-next_equity:.0%} (국채/크레딧/금/원자재 균등)</div>
    </div>""", unsafe_allow_html=True)
with c3:
    crisis_on = bt["crisis_on_today"]
    badge = status_tag("ON · 위험회피", C_RED) if crisis_on else status_tag("OFF · 정상", C_BLUE)
    st.markdown(f"""<div class="card card-signal">
        <div class="card-label">위기 오버레이 ({bt['last_trading_day'].date()})</div>
        <div>{badge}</div>
        <div class="card-sub">ON시 SPY·QQQ·KODEX200·DBC → BIL</div>
    </div>""", unsafe_allow_html=True)
with c4:
    fg_on = bt["fg_on_today"]
    badge = status_tag("KOSPI 보유중", C_BLUE) if fg_on else status_tag("미보유 → SPY대체", C_CHARCOAL)
    score_txt = f"SCORE {bt['sfg_score_latest']:.1f}" if bt["sfg_score_latest"] is not None else "데이터 없음"
    st.markdown(f"""<div class="card card-signal">
        <div class="card-label">간단 F&amp;G (KODEX200)</div>
        <div>{badge}</div>
        <div class="card-sub">{score_txt} · 기준일 {bt['sfg_data_asof'].date() if bt['sfg_data_asof'] is not None else '-'}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------------------------------------
# 오늘 기준 실제 보유 비중 — 파이차트
# ------------------------------------------------------------------
pc1, pc2 = st.columns([1.3, 1])
with pc1:
    st.markdown(f"**오늘 기준 실제 보유 비중** — 이번달({bt['cur_month'].strftime('%Y-%m')}) 배분은 "
                f"**{live_regime_ko}** 레짐 기준으로 월초 확정, 위기오버레이·F&G 적용 후")
    live = bt["live_alloc_collapsed"].copy()
    live["자산명"] = live["자산"].map(lambda a: strat.ASSET_LABELS.get(a, a))
    live = live.sort_values("비중", ascending=False)
    colors = [ASSET_COLOR.get(a, NAVY_SOFT) for a in live["자산"]]

    fig_pie = go.Figure(go.Pie(
        labels=live["자산명"], values=live["비중"], hole=0.5,
        marker=dict(colors=colors, line=dict(color=WHITE, width=2)),
        textinfo="label+percent", textposition="outside",
        texttemplate="%{label}<br>%{percent}",
        sort=False,
    ))
    fig_pie.update_layout(
        height=430, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        paper_bgcolor=WHITE, plot_bgcolor=WHITE,
        font=dict(color=NAVY, family="system-ui, -apple-system, Segoe UI, sans-serif", size=12),
    )
    st.plotly_chart(fig_pie, use_container_width=True)
with pc2:
    st.markdown("**레이어 적용 메모**")
    st.caption(f"배분 산출 방식: {bt['live_source']}")
    st.caption(f"위 '현재 레짐' 카드는 {bt['latest_signal_month'].strftime('%Y-%m')}에 새로 확정된 신호로 "
               f"{bt['next_month'].strftime('%Y-%m')} 배분에 쓰일 예정이고, 이번달 실제 보유 비중과는 "
               f"다를 수 있습니다 (레짐은 매달 초에 전달 신호로 이미 고정됨).")
    detail = bt["live_alloc_detail"].copy()
    detail = detail[detail["비고"] != ""]
    if len(detail):
        detail["자산"] = detail["자산"].map(lambda a: strat.ASSET_LABELS.get(a, a))
        detail["목표비중"] = detail["목표비중"].map(lambda v: f"{v*100:.1f}%")
        st.caption("오버레이로 리다이렉트된 자산:")
        st.dataframe(detail[["자산", "목표비중", "비고"]], use_container_width=True, hide_index=True)
    else:
        st.caption("오늘은 두 오버레이 모두 정상 상태라 리다이렉트가 없습니다.")

with st.expander("자산별 상세 전체 보기"):
    detail_all = bt["live_alloc_detail"].copy()
    detail_all["자산"] = detail_all["자산"].map(lambda a: strat.ASSET_LABELS.get(a, a))
    detail_all["실제보유자산"] = detail_all["실제보유자산"].map(lambda a: strat.ASSET_LABELS.get(a, a))
    detail_all["목표비중"] = detail_all["목표비중"].map(lambda v: f"{v*100:.1f}%")
    st.dataframe(detail_all, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# 투자 시작일 선택 — 그 날짜부터 투자했다고 가정하고 아래 성과를 재계산
# ------------------------------------------------------------------
st.markdown('<div class="section-title">성과 비교</div>', unsafe_allow_html=True)

full_start = bt["fg_rets"].index[0].date()
full_end = bt["fg_rets"].index[-1].date()

dc1, dc2 = st.columns([1, 2])
with dc1:
    invest_start = st.date_input(
        "투자 시작일 (이 날짜부터 투자했다고 가정)",
        value=full_start, min_value=full_start, max_value=full_end,
    )
with dc2:
    st.caption(
        f"선택한 날짜부터 오늘까지의 수익률만 떼어내 그 시점에 1을 투자했다고 가정하고 "
        f"누적수익·CAGR·Sharpe·MDD를 다시 계산합니다. 전체 기간: {full_start} ~ {full_end}. "
        f"(레짐/오버레이 신호 자체는 그대로이며, 보는 구간만 바뀝니다)"
    )

start_ts = pd.Timestamp(invest_start)
is_full_period = invest_start == full_start


def sliced(rets):
    return rets.loc[rets.index >= start_ts]


fg_view = sliced(bt["fg_rets"])
overlay_view = sliced(bt["overlay_rets"])
bench6040_view = sliced(bt["bench_daily_6040"].loc[bt["fg_rets"].index[0]:])
spy_view = sliced(bt["daily_rets"]["SPY"].loc[bt["fg_rets"].index[0]:])

if len(fg_view) < 5:
    st.warning("선택한 시작일 이후 데이터가 너무 적어 통계를 계산할 수 없습니다. 더 이른 날짜를 선택해주세요.")
    st.stop()

perf_final_view = strat.perf_stats(fg_view, 252)
perf_overlay_view = strat.perf_stats(overlay_view, 252)
perf_6040_view = strat.perf_stats(bench6040_view, 252)
perf_spy_view = strat.perf_stats(spy_view, 252)

perf_rows = [
    ("최종전략 (레짐+위기오버레이+F&G)", perf_final_view),
    ("레짐+위기오버레이 (F&G 없음)", perf_overlay_view),
    ("60/40 (SPY/IEF) 고정", perf_6040_view),
    ("SPY 매수후보유", perf_spy_view),
]
cols = st.columns(len(perf_rows))
for i, (col, (name, p)) in enumerate(zip(cols, perf_rows)):
    with col:
        extra_html = ""
        if i == 0:
            gross_cagr = strat.perf_stats(sliced(bt["fg_rets_gross"]), 252)["CAGR"]
            extra_html = f'<div class="card-sub">거래비용 반영 전 CAGR {fmt_pct(gross_cagr)}</div>'
        card_html = (
            f'<div class="card">'
            f'<div class="card-label">{name}</div>'
            f'<div class="card-value">{fmt_pct(p["CAGR"])}</div>'
            f'<div class="card-sub">CAGR</div>'
            f'<div class="card-sub">Sharpe {p["Sharpe"]:.2f} · Vol {fmt_pct0(p["Vol"])} · MDD {fmt_pct(p["MDD"])}</div>'
            f'{extra_html}</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

st.caption(f"표시 구간: {fg_view.index[0].date()} ~ {fg_view.index[-1].date()} "
           f"({'전체 백테스트 기간' if is_full_period else f'{invest_start} 투자 시작 가정'}, 일별, 워크포워드 — look-ahead 없음)")

# 누적수익 차트 (로그축) + 위기오버레이 ON 구간 음영
fig = go.Figure()
view_start_ts, view_end_ts = fg_view.index[0], fg_view.index[-1]
for s, e in bt["crisis_runs"]:
    if e < view_start_ts or s > view_end_ts:
        continue
    fig.add_vrect(x0=max(s, view_start_ts), x1=min(e, view_end_ts), fillcolor=C_RED, opacity=0.08, line_width=0)

cum_final = perf_final_view["cum"]
cum_overlay = perf_overlay_view["cum"]
cum_6040 = perf_6040_view["cum"]
cum_spy = perf_spy_view["cum"]

fig.add_trace(go.Scatter(x=cum_overlay.index, y=cum_overlay.values, name="레짐+위기오버레이(F&G 없음)",
                          line=dict(color=C_MIST, width=1.3, dash="dot")))
fig.add_trace(go.Scatter(x=cum_6040.index, y=cum_6040.values, name="60/40 (SPY/IEF)",
                          line=dict(color=C_BRONZE, width=1.5)))
fig.add_trace(go.Scatter(x=cum_spy.index, y=cum_spy.values, name="SPY 매수후보유",
                          line=dict(color=C_GRAY, width=1.5)))
fig.add_trace(go.Scatter(x=cum_final.index, y=cum_final.values, name="최종전략",
                          line=dict(color=C_BLUE, width=2.8)))

fig.update_layout(
    height=440, margin=dict(l=10, r=10, t=30, b=10),
    yaxis_type="log", yaxis_title=f"누적수익 (로그축, {fg_view.index[0].date()}=1)",
    plot_bgcolor=WHITE, paper_bgcolor=WHITE,
    font=dict(color=NAVY, family="system-ui, -apple-system, Segoe UI, sans-serif"),
    xaxis=dict(gridcolor=BORDER), yaxis=dict(gridcolor=BORDER),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)
st.caption("음영 구간 = 위기 오버레이 ON (위험회피 상태) · 수익률은 편도 거래비용 반영 후 기준 (60/40·SPY 벤치마크는 거래비용 미반영)")

# ------------------------------------------------------------------
# 연도별 수익률
# ------------------------------------------------------------------
st.markdown('<div class="section-title">연도별 수익률</div>', unsafe_allow_html=True)

yearly_view_src = pd.DataFrame({
    "최종전략": fg_view, "60/40": bench6040_view.fillna(0), "SPY": spy_view.fillna(0),
})
yearly_view = (1 + yearly_view_src).groupby(yearly_view_src.index.year).prod() - 1

fig_y = go.Figure()
fig_y.add_trace(go.Bar(x=yearly_view.index, y=yearly_view["최종전략"] * 100, name="최종전략", marker_color=C_BLUE))
fig_y.add_trace(go.Bar(x=yearly_view.index, y=yearly_view["60/40"] * 100, name="60/40", marker_color=C_BRONZE))
fig_y.add_trace(go.Bar(x=yearly_view.index, y=yearly_view["SPY"] * 100, name="SPY", marker_color=C_GRAY))
fig_y.update_layout(
    barmode="group", height=380, margin=dict(l=10, r=10, t=30, b=10),
    yaxis_title="연간 수익률 (%)",
    plot_bgcolor=WHITE, paper_bgcolor=WHITE,
    font=dict(color=NAVY, family="system-ui, -apple-system, Segoe UI, sans-serif"),
    xaxis=dict(gridcolor=BORDER, type="category"), yaxis=dict(gridcolor=BORDER, zeroline=True, zerolinecolor=BORDER),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
st.plotly_chart(fig_y, use_container_width=True)

n_years_beat_6040 = (yearly_view["최종전략"] > yearly_view["60/40"]).sum()
n_years_beat_spy = (yearly_view["최종전략"] > yearly_view["SPY"]).sum()
st.caption(f"60/40보다 나았던 해: {n_years_beat_6040}/{len(yearly_view)}년 · SPY보다 나았던 해: {n_years_beat_spy}/{len(yearly_view)}년 "
           f"({'선택한 투자기간 기준' if not is_full_period else '전체 기간 기준'})")

# ------------------------------------------------------------------
# 레짐별 배분표
# ------------------------------------------------------------------
st.markdown('<div class="section-title">레짐별 고정 배분 비중</div>', unsafe_allow_html=True)
tabs = st.tabs([strat.REGIME_LABELS_KO[r] for r in ["Goldilocks", "Reflation", "Stagflation", "Deflation"]])
for tab, r in zip(tabs, ["Goldilocks", "Reflation", "Stagflation", "Deflation"]):
    with tab:
        alloc = bt["allocations_by_regime"][r].copy()
        alloc["자산"] = alloc["자산"].map(lambda a: strat.ASSET_LABELS.get(a, a))
        alloc["비중"] = alloc["비중"].map(lambda v: f"{v*100:.1f}%")
        cc1, cc2 = st.columns([1, 2])
        with cc1:
            st.markdown(f"""<div class="card">
                <div class="card-label">주식비중</div>
                <div class="card-value">{strat.REGIME_EQUITY_TARGET[r]:.0%}</div>
            </div>""", unsafe_allow_html=True)
        with cc2:
            st.dataframe(alloc, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# IS/OOS (전체 기간 고정)
# ------------------------------------------------------------------
st.markdown('<div class="section-title">IS / OOS 비교 (7:3 분할, 전체 기간 기준)</div>', unsafe_allow_html=True)
is_oos = bt["is_oos_table"].copy()
for col in ["CAGR", "연변동성", "MDD", "총수익"]:
    is_oos[col] = (is_oos[col] * 100).map(lambda v: f"{v:.1f}%")
is_oos["Sharpe"] = is_oos["Sharpe"].astype(float).round(2)
st.dataframe(is_oos.reset_index(), use_container_width=True, hide_index=True)
for lab, (a, b) in bt["is_oos_periods"].items():
    st.caption(f"{lab}: {a.date()} ~ {b.date()}")

# ------------------------------------------------------------------
# 레짐별 자산 성과 (상세)
# ------------------------------------------------------------------
with st.expander("레짐별 자산 성과 상세 보기"):
    stats = bt["regime_asset_stats"].copy()
    stats["자산"] = stats["자산"].map(lambda a: strat.ASSET_LABELS.get(a, a))
    stats["평균월수익률"] = stats["평균월수익률"].map(lambda v: f"{v*100:.2f}%")
    stats["승률"] = stats["승률"].map(lambda v: f"{v*100:.0f}%")
    stats["월Sharpe"] = stats["월Sharpe"].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
    stats["연환산수익률"] = stats["연환산수익률"].map(lambda v: f"{v*100:.1f}%")
    stats["레짐"] = stats["레짐"].map(lambda r: strat.REGIME_LABELS_KO.get(r, r))
    pick = st.selectbox("레짐 선택", list(strat.REGIME_LABELS_KO.values()))
    st.dataframe(stats[stats["레짐"] == pick].drop(columns=["레짐"]), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# 파라미터 민감도
# ------------------------------------------------------------------
with st.expander("위기 오버레이 파라미터 민감도 (81개 조합, 거래비용 미반영)"):
    st.caption("VIX 레벨/급등폭, SPY·HYG 5일 하락폭을 그리드로 흔들어 결과가 특정 파라미터에 '운 좋게' 맞춰진 건 아닌지 확인")
    if st.button("민감도 분석 실행"):
        with st.spinner("81개 조합을 재계산하는 중..."):
            grid_df = load_sensitivity(bt["wf_alloc_log"], bt["px"], bt["daily_rets"],
                                        bt["vix_d"], bt["vix_d"].rolling(20).mean())
        st.write(
            f"Sharpe 분포: min {grid_df['Sharpe'].min():.2f} · 중앙값 {grid_df['Sharpe'].median():.2f} · "
            f"max {grid_df['Sharpe'].max():.2f}")
        fig_g = go.Figure(go.Histogram(x=grid_df["Sharpe"], nbinsx=20, marker_color=NAVY_SOFT))
        base = grid_df[(grid_df["VIX레벨"] == 30) & (grid_df["VIX급등"] == 0.50) &
                        (grid_df["SPY5일"] == -0.07) & (grid_df["HYG5일"] == -0.03)]
        if len(base):
            fig_g.add_vline(x=base["Sharpe"].iloc[0], line_color=C_RED, line_width=2,
                             annotation_text="원래 조합", annotation_position="top")
        fig_g.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10),
                             plot_bgcolor=WHITE, paper_bgcolor=WHITE,
                             font=dict(color=NAVY), xaxis_title="Sharpe", yaxis_title="조합 수")
        st.plotly_chart(fig_g, use_container_width=True)

# ------------------------------------------------------------------
# 신호 검증 / 레짐 라벨 분포
# ------------------------------------------------------------------
with st.expander("레짐 신호 상세 (성장·인플레 축, PIT 여부)"):
    cc1, cc2 = st.columns(2)
    with cc1:
        st.write(f"성장축: INDPRO YoY vs 12개월 트렌드 — "
                 f"{'실시간 vintage YoY(같은 발표본 기준, 진짜 PIT)' if bt['growth_is_vintage'] else '최종치+1개월 시차 폴백'}")
        st.write(f"인플레축: CPI YoY vs 12개월 트렌드 — "
                 f"{'실시간 vintage YoY(같은 발표본 기준, 진짜 PIT)' if bt['inflation_is_vintage'] else '최종치+1개월 시차 폴백'}")
        st.write(f"NBER 침체월 '성장상승' 오판율: {bt['recession_fp_rate']*100:.0f}% (상한 25%)")
    with cc2:
        counts = bt["merged"]["regime"].value_counts()
        counts.index = [strat.REGIME_LABELS_KO.get(r, r) for r in counts.index]
        st.dataframe(counts.rename("관측 월수"), use_container_width=True)

# ------------------------------------------------------------------
# 한계/주의사항
# ------------------------------------------------------------------
st.markdown('<div class="section-title">한계 (요약)</div>', unsafe_allow_html=True)
st.markdown(f"""
<div class="footnote">
• 거래비용은 리밸런싱/오버레이 전환 시 자산비중 변화량(턴오버)에 편도 {cost_bps}bp를 곱해 근사한 값으로,
  실제 체결 스프레드·수수료·세금(배당소득세 등)과는 차이가 있을 수 있습니다. 60/40·SPY 벤치마크는 거래비용을 반영하지 않았습니다.<br>
• 표본이 작습니다 — 레짐당 수십~백여 개월 수준이며, Reflation/Stagflation은 2008·2020·2021-22 등 특정 소수 구간이 통계를 좌우합니다.<br>
• "Deflation" 레짐은 실제로는 위기 자체보다 위기 직후 반등랠리를 많이 포함합니다 (INDPRO_12mo가 YoY라 전환점에 늦게 반응).<br>
• 오버레이 없는 월별 워크포워드 결과는 60/40 고정배분을 근소하게 넘는 수준으로, 차이가 통계적으로 크다고 보기는 어렵습니다.<br>
• 과거 성과가 미래 수익을 보장하지 않습니다.
</div>
""", unsafe_allow_html=True)
