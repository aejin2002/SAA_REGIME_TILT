"""
Asset & Macro Monitor — 데이터/해석 엔진

기존 strategy.py(레짐 틸트 백테스트)는 건드리지 않고, 그 위에 얹는 별도 모듈.
FRED에서 확보 가능한 지표만 실제로 받아오고, 확보 불가능한 지표는 "데이터 미확보"로
명시적으로 표시한다(임의 생성 금지). 각 지표는 상승/하락 각각의 경제적 의미와 관련 ETF를
같이 들고 있어서, 단순 등락색 표시가 아니라 해석을 보여준다.
"""
from datetime import date

import numpy as np
import pandas as pd

import strategy as strat

# ------------------------------------------------------------------
# 지표 레지스트리
# ------------------------------------------------------------------
# transform: "level"(그대로) | "yoy"(전년동월비, 월별 레벨 시리즈용) | "price_ratio"(가격비율) | "realized_vol"(실현변동성, MOVE 대용)
# change_unit: "bp"(금리·스프레드류) | "pt"(지수포인트) | "pct"(가격류 변화율)

IND = {
    # ---------------- Growth ----------------
    "INDPRO": dict(label="산업생산 (INDPRO, YoY)", axis="growth", fred="INDPRO", freq="M", transform="yoy",
        unit="%", change_unit="pt", assets=[],
        rising="산업생산 증가율 상승은 제조업 생산활동이 가속화되고 있다는 신호로, 경기 확장 국면을 시사할 수 있음.",
        falling="산업생산 증가율 둔화·마이너스 전환은 제조업 생산활동 위축을 의미하며, 경기 둔화 또는 침체 초입 신호일 수 있음."),
    "ICSA": dict(label="신규 실업수당 청구건수 (주간)", axis="growth", fred="ICSA", freq="W", transform="level",
        unit="명", change_unit="pct", assets=[],
        rising="신규 실업수당 청구 증가는 해고가 늘고 있다는 뜻으로, 노동시장이 식어가는 선행 신호로 흔히 해석됨.",
        falling="신규 실업수당 청구 감소는 노동시장이 여전히 타이트하다는 신호로, 경기 저항력이 유지되고 있음을 시사."),
    "ISM_MFG": dict(label="ISM 제조업 PMI", axis="growth", fred=None, freq="M", transform="level",
        unit="pt", change_unit="pt", assets=[],
        rising="50을 넘으면 제조업 확장 국면. 추가 상승은 신규주문·생산 가속을 의미.",
        falling="50을 밑돌면 제조업 수축 국면. 추가 하락은 경기 둔화 심화를 의미.",
        data_note="ISM이 2016년 이후 FRED 등 공공 API에 실시간 재배포를 허용하지 않아 무료로 받을 수 있는 경로가 없음."),
    "ISM_SVC": dict(label="ISM 서비스업 PMI", axis="growth", fred=None, freq="M", transform="level",
        unit="pt", change_unit="pt", assets=[],
        rising="50을 넘으면 서비스업 확장. 미국 GDP의 70%+가 서비스업이라 이 지표의 가중치가 큼.",
        falling="50을 밑돌면 서비스업 수축. 제조업보다 서비스업 둔화가 실제 소비경기 둔화에 더 가까운 신호.",
        data_note="ISM 제조업 PMI와 동일한 사유로 FRED 무료 API 미제공."),
    "GDPNOW": dict(label="Atlanta Fed GDPNow (실시간 GDP 나우캐스트)", axis="growth", fred=None, freq="D", transform="level",
        unit="%", change_unit="pt", assets=[],
        rising="나우캐스트 상향은 들어오는 데이터들이 예상보다 강하다는 의미.",
        falling="나우캐스트 하향은 들어오는 데이터들이 예상보다 약하다는 의미.",
        data_note="Atlanta Fed가 자체 웹사이트로만 공개하며 공개 API를 제공하지 않음 (atlantafed.org에서 수동 확인 필요)."),

    # ---------------- Inflation ----------------
    "CPI_CORE": dict(label="Core CPI (YoY)", axis="inflation", fred="CPILFESL", freq="M", transform="yoy",
        unit="%", change_unit="pt", assets=["TIP"],
        rising="근원 CPI 상승률 확대는 식품·에너지를 제외한 기조적 물가압력이 강해지고 있다는 신호로, Fed의 금리인하 운신폭을 좁힘.",
        falling="근원 CPI 상승률 둔화는 디스인플레이션 진행을 의미하며, Fed의 정책완화 여지를 넓힘."),
    "PCE_CORE": dict(label="Core PCE (YoY)", axis="inflation", fred="PCEPILFE", freq="M", transform="yoy",
        unit="%", change_unit="pt", assets=["TIP"],
        rising="Fed가 공식 타겟으로 쓰는 지표. 상승은 Fed 2% 목표와의 괴리 확대를 의미해 긴축적 스탠스 유지 명분이 됨.",
        falling="2%를 향해 하락하면 Fed의 금리인하 명분이 강화됨."),
    "BREAKEVEN_10Y": dict(label="10Y Breakeven Inflation", axis="inflation", fred="T10YIE", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["TIP", "TLT", "GLD"],
        rising="시장이 반영하는 향후 10년 평균 기대인플레이션이 높아지는 신호. 인플레이션 리스크 프리미엄 확대로 해석될 수 있음.",
        falling="기대인플레이션 하락 또는 디스인플레이션 우려 반영. 단, 급락은 경기둔화 우려(수요 위축)를 반영하는 경우도 있어 원인 구분이 필요."),
    "FORWARD_5Y5Y": dict(label="5Y5Y Forward Inflation Expectation", axis="inflation", fred="T5YIFR", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["TIP", "GLD"],
        rising="Fed가 가장 중시하는 장기 기대인플레 지표. 상승은 장기 인플레 기대가 들썩인다는 신호로 Fed가 민감하게 반응.",
        falling="장기 기대인플레 안정/하락은 Fed의 신뢰도(인플레 억제 능력)가 시장에서 인정받고 있다는 신호."),
    "AHE": dict(label="평균시급 (Average Hourly Earnings, YoY)", axis="inflation", fred="CES0500000003", freq="M", transform="yoy",
        unit="%", change_unit="pt", assets=[],
        rising="임금 상승률 확대는 서비스업 비용압력(임금발 인플레)이 강화되고 있다는 신호.",
        falling="임금 상승률 둔화는 노동시장 과열이 식고 있다는 신호로, 서비스 인플레 완화에 우호적."),

    # ---------------- Policy & Liquidity ----------------
    "FEDFUNDS": dict(label="Effective Fed Funds Rate", axis="policy", fred="DFF", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["BIL"],
        rising="정책금리 인상은 긴축 기조 강화. 단기금리 연동 자산(BIL 등) 수익률이 즉각 높아짐.",
        falling="정책금리 인하는 완화 기조 전환. 단기 재투자 수익률 하락."),
    "UST_2Y": dict(label="2Y Treasury Yield", axis="policy", fred="DGS2", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["IEF", "TLT"],
        rising="2년물은 향후 1~2년 정책금리 경로에 대한 시장 기대를 가장 민감하게 반영. 상승은 긴축 장기화/인하 지연 기대.",
        falling="하락은 인하 시점이 앞당겨지거나 폭이 커질 것이라는 시장 기대 반영."),
    "REAL_YIELD_10Y": dict(label="10Y Real Yield (TIPS)", axis="policy", fred="DFII10", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["GLD", "QQQ", "TIP", "TLT"],
        rising="무위험 실질수익률 상승 — 금의 보유 기회비용이 높아지고, 장기 성장주(QQQ)의 미래이익 할인율 부담이 커짐.",
        falling="실질금리 하락 — 금의 상대적 매력도 상승, 장기 성장주 밸류에이션에 우호적으로 작용할 수 있음."),
    "SOFR": dict(label="SOFR (익일물 담보금리)", axis="policy", fred="SOFR", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["BIL"],
        rising="단기 자금조달 비용 상승. 레포시장 등 단기 유동성이 타이트해지고 있다는 신호일 수 있음.",
        falling="단기 자금조달 비용 완화. 단기 유동성 여건이 느슨해지고 있다는 신호."),
    "M2_US": dict(label="미국 M2 통화량 (YoY)", axis="policy", fred="M2SL", freq="M", transform="yoy",
        unit="%", change_unit="pt", assets=[],
        rising="유동성 공급 확대 — 광의의 유동성 환경이 완화적으로 바뀌고 있다는 신호(위험자산에 우호적인 경우가 많음).",
        falling="유동성 증가세 둔화/위축 — 유동성 환경이 긴축적으로 바뀌고 있다는 신호.",
        data_note="미국 M2 기준이며, 전세계 유동성을 합산한 '글로벌 M2' 단일 공식 시리즈는 FRED에 없음."),

    # ---------------- Credit & Financial Stress ----------------
    "HY_OAS": dict(label="US High Yield OAS", axis="credit", fred="BAMLH0A0HYM2", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["HYG", "LQD", "SPY"],
        rising="하이일드 채권의 신용위험 프리미엄 확대 — 시장이 신용위험에 대해 더 많은 보상을 요구하는, 위험회피 강화 신호.",
        falling="신용 스프레드 축소 — 신용위험 프리미엄이 줄고 위험선호가 회복되고 있다는 신호."),
    "IG_OAS": dict(label="US Investment Grade OAS", axis="credit", fred="BAMLC0A0CM", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["LQD", "IEF"],
        rising="우량채 스프레드 확대는 HY보다는 약하지만 전반적 신용 여건 경색의 초기 신호일 수 있음.",
        falling="우량채 스프레드 축소는 신용시장 여건이 완화되고 있다는 신호."),
    "VIX": dict(label="VIX (S&P500 내재변동성)", axis="credit", fred="VIXCLS", freq="D", transform="level",
        unit="pt", change_unit="pct", assets=["SPY", "QQQ"],
        rising="주식시장의 단기 불확실성·공포 심리 확대. 우리 위기오버레이의 핵심 트리거 중 하나.",
        falling="단기 불확실성 완화, 시장 안정화 신호."),
    "MOVE_PROXY": dict(label="채권 변동성 대용지표 (TLT 20일 실현변동성, 연율화)", axis="credit", fred=None, freq="D",
        transform="realized_vol", unit="%", change_unit="pt", assets=["IEF", "TLT"],
        rising="채권시장 변동성 확대 — 금리 경로에 대한 불확실성이 커지고 있다는 신호(실제 ICE BofA MOVE지수와는 다른 자체 대용치).",
        falling="채권시장 변동성 축소 — 금리 경로에 대한 시장의 확신이 커지고 있다는 신호.",
        data_note="실제 MOVE Index(ICE BofA)는 유료·비공개라 FRED에 없음. 대신 보유 중인 TLT 가격으로 20일 실현변동성을 직접 계산한 대용지표."),
    "NFCI": dict(label="Chicago Fed 금융여건지수 (NFCI)", axis="credit", fred="NFCI", freq="W", transform="level",
        unit="pt", change_unit="pt", assets=["SPY", "HYG"],
        rising="0 기준 양(+)이면 평균보다 긴축적인 금융여건. 상승은 신용·유동성 여건이 더 타이트해지고 있다는 신호.",
        falling="0 기준 음(-)이면 평균보다 완화적인 금융여건. 하락은 여건이 느슨해지고 있다는 신호."),

    # ---------------- Sentiment & Positioning (대부분 무료 API 없음) ----------------
    "AAII": dict(label="AAII 개인투자자 심리", axis="sentiment", fred=None, freq="W", transform="level",
        unit="%", change_unit="pt", assets=["SPY"],
        rising="강세(Bullish) 응답비율 상승 — 극단적으로 높으면 역발상 매도신호로 해석되기도 함.",
        falling="약세(Bearish) 응답비율 상승 — 극단적으로 높으면 역발상 매수신호로 해석되기도 함.",
        data_note="AAII는 유료 구독 기반이라 무료 공개 API가 없음."),
    "COT": dict(label="CFTC 선물 포지셔닝 (COT)", axis="sentiment", fred=None, freq="W", transform="level",
        unit="계약수", change_unit="pct", assets=["GLD", "DBC"],
        rising="비상업적(투기) 순매수 포지션 증가 — 해당 자산에 대한 추세추종 수요 확대.",
        falling="순매수 포지션 감소/순매도 전환 — 포지션 청산 또는 추세 반전 베팅.",
        data_note="CFTC가 원시 데이터를 무료 공개하지만 구조화된 API가 아니라 주간 리포트 파싱이 필요 — 추후 확장 가능."),
    "PUTCALL": dict(label="CBOE Put/Call Ratio", axis="sentiment", fred=None, freq="D", transform="level",
        unit="x", change_unit="pct", assets=["SPY"],
        rising="풋/콜 비율 상승은 헤지·약세 베팅 증가(역발상 매수신호로 쓰이기도 함).",
        falling="풋/콜 비율 하락은 콜 쏠림(낙관/투기) 증가(역발상 매도신호로 쓰이기도 함).",
        data_note="CBOE가 실시간 무료 API를 제공하지 않음."),
    "BOFA_FMS": dict(label="BofA 글로벌 펀드매니저 서베이", axis="sentiment", fred=None, freq="M", transform="level",
        unit="%", change_unit="pt", assets=["SPY"],
        rising="현금비중 상승/낙관 응답 감소 — 기관 포지셔닝의 방어적 전환.",
        falling="현금비중 하락/낙관 응답 증가 — 기관의 위험선호 확대.",
        data_note="BofA 내부 서베이로 비공개, 월간 요약만 언론을 통해 간접 확인 가능."),

    # ---------------- 자산별 전용 (매크로 축에는 안 걸리고 자산 패널에만 등장) ----------------
    "DXY_BROAD": dict(label="Broad Dollar Index (DTWEXBGS)", axis=None, fred="DTWEXBGS", freq="D", transform="level",
        unit="index", change_unit="pct", assets=["DBC", "GLD", "069500.KS"],
        rising="달러 강세 — 달러표시 원자재·금에 부담, 신흥국(한국 포함) 금융여건 긴축 압력.",
        falling="달러 약세 — 원자재·금에 상대적으로 우호적, 신흥국 금융여건 완화.",
        data_note="좁은 의미의 DXY(ICE 선물 인덱스)가 아니라 Fed가 발표하는 Broad Dollar Index(교역가중, 더 넓은 통화바스켓)."),
    "WTI": dict(label="WTI 유가", axis=None, fred="DCOILWTICO", freq="D", transform="level",
        unit="$", change_unit="pct", assets=["DBC"],
        rising="에너지 가격 상승은 DBC 내 에너지 비중에 직접 긍정적이며, 헤드라인 인플레 상방 압력으로 연결.",
        falling="에너지 가격 하락은 DBC에 부담이며, 헤드라인 인플레 하방 압력."),
    "USDKRW": dict(label="원/달러 환율", axis=None, fred="DEXKOUS", freq="D", transform="level",
        unit="₩", change_unit="pct", assets=["069500.KS"],
        rising="원화 약세 — 외국인 입장에서 원화자산 환헤지 비용·환손실 우려 확대, 외국인 수급에 부담 요인이 될 수 있음.",
        falling="원화 강세 — 외국인 입장에서 원화자산 매력도 상승 요인."),
    "UST_5Y": dict(label="5Y Treasury Yield", axis=None, fred="DGS5", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["IEF"],
        rising="중기금리 상승은 IEF 가격에 하방압력.",
        falling="중기금리 하락은 IEF 가격에 상방요인."),
    "UST_10Y": dict(label="10Y Treasury Yield (명목)", axis=None, fred="DGS10", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["IEF", "TLT", "LQD", "TIP"],
        rising="장기 명목금리 상승 — 성장기대/인플레우려/기간프리미엄 중 무엇이 원인인지 구분 필요. 채권가격엔 하방압력.",
        falling="장기 명목금리 하락 — 경기침체 우려에 의한 하락인지 정책완화 기대에 의한 하락인지 구분 필요."),
    "UST_30Y": dict(label="30Y Treasury Yield", axis=None, fred="DGS30", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["TLT"],
        rising="초장기금리 상승은 TLT(20년+) 듀레이션 특성상 가격에 가장 민감하게(크게) 반영됨.",
        falling="초장기금리 하락은 TLT에 가장 크게 우호적으로 작용."),
    "UST_1M": dict(label="1M T-bill Yield", axis=None, fred="DGS1MO", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["BIL"],
        rising="초단기 재투자 수익률 상승 — BIL 캐리(이자수익) 개선.",
        falling="초단기 재투자 수익률 하락 — BIL 캐리 둔화."),
    "UST_3M": dict(label="3M T-bill Yield", axis=None, fred="DGS3MO", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["BIL"],
        rising="3개월물 상승 — 단기 정책금리 기대 상향.",
        falling="3개월물 하락 — 단기 정책금리 기대 하향(인하 임박 기대 반영 가능)."),
    "SPREAD_2S10S": dict(label="2s10s 스프레드 (10Y-2Y)", axis=None, fred="T10Y2Y", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["IEF", "TLT"],
        rising="커브 가팔라짐(스티프닝) — 경기회복 기대 또는 장기 기간프리미엄 확대. 역전 상태에서의 스티프닝은 침체 임박 신호로 해석되기도 함.",
        falling="커브 평탄화/역전 심화 — 단기긴축 지속 또는 경기둔화 우려 반영."),
    "SPREAD_3M10Y": dict(label="3m10y 스프레드 (10Y-3M)", axis=None, fred="T10Y3M", freq="D", transform="level",
        unit="%", change_unit="bp", assets=["IEF", "TLT"],
        rising="Fed가 침체예측에 가장 신뢰하는 커브 중 하나. 역전에서 플러스로 전환(스티프닝)되는 과정 자체가 과거 침체 임박과 겹친 적이 많음.",
        falling="역전 심화는 전통적인 침체 선행신호로 해석되어 옴(단, 최근 사이클에서는 선행시차가 들쑥날쑥)."),
    "QQQ_SPY_RS": dict(label="QQQ/SPY 상대강도", axis=None, fred=None, freq="D", transform="price_ratio",
        unit="ratio", change_unit="pct", assets=["QQQ", "SPY"],
        rising="나스닥(성장주)이 S&P500 대비 아웃퍼폼 — growth/tech 로테이션 강화 국면.",
        falling="나스닥이 S&P500 대비 언더퍼폼 — value/대형주로의 로테이션 또는 성장주 밸류에이션 조정 국면.",
        data_note="자체 보유 중인 QQQ·SPY 가격으로 직접 계산한 비율(외부 소스 아님)."),
    "SOX": dict(label="필라델피아 반도체지수 (SOX)", axis=None, fred=None, freq="D", transform="level",
        unit="pt", change_unit="pct", assets=["QQQ"],
        rising="반도체 업황 개선 기대 반영 — QQQ 내 비중이 큰 반도체주에 직접적 호재.",
        falling="반도체 업황 둔화 우려 반영 — QQQ에 부담.",
        data_note="필라델피아거래소 독자 지수라 FRED에 없음. 야후파이낸스 등 별도 연동 필요(추후 확장 가능)."),
    "FORWARD_PE": dict(label="S&P500 Forward P/E", axis=None, fred=None, freq="D", transform="level",
        unit="x", change_unit="pct", assets=["SPY"],
        rising="밸류에이션 부담 확대 — 향후 이익 기대 대비 주가가 비싸지고 있다는 의미.",
        falling="밸류에이션 부담 완화 — 이익 기대 대비 주가가 싸지고 있다는 의미.",
        data_note="S&P 공식 forward EPS 컨센서스(IBES/FactSet)가 필요해 무료 공개 API 없음."),
    "ERP": dict(label="Equity Risk Premium (1/Fwd PE − 10Y 실질금리)", axis=None, fred=None, freq="D", transform="level",
        unit="%", change_unit="bp", assets=["SPY"],
        rising="주식이 채권 대비 상대적으로 저평가 — 주식의 상대 매력도 상승.",
        falling="주식이 채권 대비 상대적으로 고평가 — 채권 대비 주식 매력도 하락.",
        data_note="Forward PE 데이터가 없어 계산 불가 (Forward PE 확보 시 연동 가능)."),
    "VIX_TERM": dict(label="VIX 기간구조 (VIX9D/VIX/VIX3M)", axis=None, fred=None, freq="D", transform="level",
        unit="ratio", change_unit="pct", assets=["SPY"],
        rising="단기물이 장기물보다 급등(백워데이션 전환) — 임박한 이벤트/공포에 대한 단기 헤지 수요 급증 신호.",
        falling="정상적인 콘탱고(단기<장기) 복귀 — 단기 공포 완화.",
        data_note="VIX9D·VIX3M은 FRED 미제공, CBOE 직접 연동 필요(추후 확장 가능)."),
    "EPS_REV": dict(label="EPS 전망치 수정비율 (상향/하향)", axis=None, fred=None, freq="M", transform="level",
        unit="ratio", change_unit="pct", assets=["SPY"],
        rising="상향 조정이 하향 조정보다 많아짐 — 실적 모멘텀 개선.",
        falling="하향 조정이 많아짐 — 실적 모멘텀 악화.",
        data_note="IBES/FactSet 컨센서스 데이터 필요, 무료 API 없음."),
    "BREADTH": dict(label="시장 폭 (200일선 상회 비율)", axis=None, fred=None, freq="D", transform="level",
        unit="%", change_unit="pt", assets=["SPY"],
        rising="상승 종목 비율 확대 — 소수 대형주가 아닌 시장 전반의 강세(건강한 랠리).",
        falling="상승 종목 비율 축소 — 소수 종목에 의존하는 취약한 랠리일 가능성.",
        data_note="S&P500 전 종목 데이터가 필요해 현재 미연동(추후 확장 가능)."),
    "FOREIGN_FLOW": dict(label="외국인 순매수 (코스피, 현물/선물)", axis=None, fred=None, freq="D", transform="level",
        unit="원", change_unit="pct", assets=["069500.KS"],
        rising="외국인 순매수 유입 — 한국 증시 수급 개선, 통상 원화 강세와 동반.",
        falling="외국인 순매도 — 수급 악화, 통상 원화 약세와 동반.",
        data_note="KRX 공공데이터 API로 확보 가능하나 현재 미연동(추후 확장 가능 — 이미 보유한 KRX 인증키 활용 가능)."),
    "DRAM_NAND": dict(label="DRAM/NAND 가격", axis=None, fred=None, freq="M", transform="level",
        unit="$", change_unit="pct", assets=["069500.KS"],
        rising="메모리 반도체 가격 상승 — 코스피 비중 1위 삼성전자/SK하이닉스 실적에 직접 호재.",
        falling="메모리 가격 하락 — 반도체 다운사이클 우려.",
        data_note="DRAMeXchange 등 유료 데이터, 무료 공개 API 없음."),
    "CHINA_PMI": dict(label="중국 제조업 PMI", axis=None, fred=None, freq="M", transform="level",
        unit="pt", change_unit="pt", assets=["DBC", "069500.KS"],
        rising="중국 수요 회복 기대 — 원자재 및 한국 수출(대중 의존도 높음)에 우호적.",
        falling="중국 수요 둔화 우려 — 원자재 및 한국 수출에 부담.",
        data_note="중국 국가통계국 공식수치를 FRED가 실시간 재배포하지 않음."),
    "GLOBAL_PMI": dict(label="Global Composite PMI", axis=None, fred=None, freq="M", transform="level",
        unit="pt", change_unit="pt", assets=["DBC"],
        rising="글로벌 경기 확장 국면 — 원자재 수요 기대 개선.",
        falling="글로벌 경기 수축 국면 — 원자재 수요 위축 우려.",
        data_note="J.P.Morgan/S&P Global 공동 발표, 유료 라이선스라 무료 API 없음."),
    "FUTURES_CURVE": dict(label="원자재 선물 기간구조 (백워데이션/콘탱고)", axis=None, fred=None, freq="D", transform="level",
        unit="%", change_unit="pt", assets=["DBC"],
        rising="백워데이션 심화(근월물>원월물) — 현물 공급 타이트, 롤오버 수익에 우호적.",
        falling="콘탱고 심화(근월물<원월물) — 공급 여유, 롤오버 비용 발생.",
        data_note="선물 체인 데이터(CME/ICE)가 필요해 현재 미연동(추후 확장 가능)."),
    "EIA_INV": dict(label="EIA 원유 재고", axis=None, fred=None, freq="W", transform="level",
        unit="bbl", change_unit="pct", assets=["DBC"],
        rising="재고 증가 — 공급 과잉/수요 둔화 신호, 유가에 하방 압력.",
        falling="재고 감소 — 공급 타이트/수요 견조 신호, 유가에 상방 압력.",
        data_note="EIA 주간 재고 시리즈가 현재 FRED에서 유효한 ID로 확인되지 않아 미연동(추후 EIA 직접 API로 확장 가능)."),
    "CB_GOLD": dict(label="중앙은행 금 순매입", axis=None, fred=None, freq="Q", transform="level",
        unit="톤", change_unit="pct", assets=["GLD"],
        rising="각국 중앙은행의 금 매입 확대 — 구조적 수요 기반 강화.",
        falling="중앙은행 매입 둔화 — 구조적 수요 약화.",
        data_note="World Gold Council 분기 리포트, 공개 API 없음."),
    "GLD_HOLDINGS": dict(label="GLD/IAU ETF 보유량", axis=None, fred=None, freq="D", transform="level",
        unit="톤", change_unit="pct", assets=["GLD"],
        rising="ETF 보유량 증가 — 금 실물 수요(특히 서구권 투자수요) 유입.",
        falling="ETF 보유량 감소 — 금 실물 수요 유출.",
        data_note="State Street/BlackRock 일일 공시 파일 연동 필요, 현재 미연동(추후 확장 가능)."),
    "FED_FUTURES": dict(label="Fed Funds Futures 내재 정책경로", axis=None, fred=None, freq="D", transform="level",
        unit="%", change_unit="bp", assets=["IEF", "TLT"],
        rising="향후 금리인하 기대 축소/인상 기대 확대.",
        falling="향후 금리인하 기대 확대/인상 기대 축소.",
        data_note="CME FedWatch 등 선물시장 데이터, 무료 공개 API 없음(CME 데이터 라이선스 필요)."),
    "QRA": dict(label="미 재무부 발행계획 (QRA)", axis=None, fred=None, freq="Q", transform="level",
        unit="$", change_unit="pct", assets=["IEF", "TLT"],
        rising="국채 발행 규모 확대 — 수급 측면에서 채권가격에 하방압력 요인.",
        falling="발행 규모 축소 — 수급 측면에서 채권가격에 상방압력 요인.",
        data_note="재무부가 PDF 형태로만 공시, 구조화 API 없음."),
    "CDX_IG": dict(label="CDX IG 지수", axis=None, fred=None, freq="D", transform="level",
        unit="bp", change_unit="bp", assets=["LQD"],
        rising="IG 신용파생 스프레드 확대 — 현물(OAS)보다 선행하는 경우가 많은 신용스트레스 신호.",
        falling="IG 신용파생 스프레드 축소 — 신용여건 개선 선행신호.",
        data_note="IHS Markit/ICE 지수사용료 필요, 무료 API 없음."),
    "CDX_HY": dict(label="CDX HY 지수", axis=None, fred=None, freq="D", transform="level",
        unit="bp", change_unit="bp", assets=["HYG"],
        rising="HY 신용파생 스프레드 확대 — 현물시장보다 빠르게 신용스트레스를 반영하는 경향.",
        falling="HY 신용파생 스프레드 축소 — 위험선호 회복 선행신호.",
        data_note="CDX_IG와 동일 사유로 미연동."),
    "HY_ISSUANCE": dict(label="하이일드 회사채 발행량", axis=None, fred=None, freq="M", transform="level",
        unit="$", change_unit="pct", assets=["HYG"],
        rising="발행 증가 — 신용시장 접근성 양호(위험선호 회복 반영).",
        falling="발행 위축 — 신용시장 경색 신호일 수 있음.",
        data_note="SIFMA/LSEG 집계 데이터, 무료 API 없음."),
    "CORP_ISSUANCE": dict(label="투자등급 회사채 발행량", axis=None, fred=None, freq="M", transform="level",
        unit="$", change_unit="pct", assets=["LQD"],
        rising="발행 증가 — 기업들의 자금조달 여건 양호.",
        falling="발행 위축 — 자금조달 비용 부담 또는 수요 위축.",
        data_note="SIFMA 집계, 무료 API 없음."),
    "RATING_RATIO": dict(label="신용등급 상향/하향 비율", axis=None, fred=None, freq="Q", transform="level",
        unit="ratio", change_unit="pct", assets=["HYG", "LQD"],
        rising="상향 비율 확대 — 기업 신용 펀더멘털 개선 추세.",
        falling="하향 비율 확대 — 기업 신용 펀더멘털 악화 추세.",
        data_note="Moody's/S&P 집계, 무료 API 없음."),
    "AI_CAPEX": dict(label="AI 관련 설비투자(Capex) 가이던스", axis=None, fred=None, freq="Q", transform="level",
        unit="$", change_unit="pct", assets=["QQQ"],
        rising="빅테크 AI capex 확대 가이던스 — 반도체·인프라 수요 기대 강화(QQQ 우호적).",
        falling="capex 가이던스 하향 — AI 투자 사이클 둔화 우려.",
        data_note="개별 기업 실적발표(정성적 가이던스)라 단일 수치 API가 없음 — 정성 모니터링 영역으로 남겨둠."),
}

AXIS_LABELS = {
    "growth": "① Growth",
    "inflation": "② Inflation",
    "policy": "③ Policy & Liquidity",
    "credit": "④ Credit & Financial Stress",
    "sentiment": "⑤ Positioning & Sentiment",
}

AXIS_ORDER = ["growth", "inflation", "policy", "credit", "sentiment"]

ASSET_LABELS = {
    "SPY": "SPY — US Large Cap Equity",
    "QQQ": "QQQ — US Growth / Technology",
    "069500.KS": "KODEX200 — Korean Equity",
    "DBC": "DBC — Commodities",
    "GLD": "GLD — Gold",
    "IEF_TLT": "IEF / TLT — US Treasury",
    "LQD": "LQD — Investment Grade Credit",
    "TIP": "TIP — Inflation-Linked Treasury",
    "BIL": "BIL — Cash / Short-Term Treasury",
    "HYG": "HYG — High Yield Credit",
}

ASSET_PANEL_KEYS = {
    "SPY": ["FORWARD_PE", "ERP", "VIX", "VIX_TERM", "EPS_REV", "BREADTH"],
    "QQQ": ["REAL_YIELD_10Y", "SOX", "QQQ_SPY_RS", "AI_CAPEX"],
    "069500.KS": ["FOREIGN_FLOW", "USDKRW", "DRAM_NAND", "CHINA_PMI"],
    "DBC": ["DXY_BROAD", "CHINA_PMI", "GLOBAL_PMI", "FUTURES_CURVE", "WTI", "EIA_INV"],
    "GLD": ["REAL_YIELD_10Y", "DXY_BROAD", "CB_GOLD", "GLD_HOLDINGS"],
    "IEF_TLT": ["UST_2Y", "UST_5Y", "UST_10Y", "UST_30Y", "SPREAD_2S10S", "SPREAD_3M10Y", "FED_FUTURES", "QRA", "MOVE_PROXY"],
    "LQD": ["IG_OAS", "CDX_IG", "UST_10Y", "CORP_ISSUANCE"],
    "TIP": ["REAL_YIELD_10Y", "BREAKEVEN_10Y", "FORWARD_5Y5Y", "PCE_CORE"],
    "BIL": ["UST_1M", "UST_3M", "SOFR", "FEDFUNDS"],
    "HYG": ["HY_OAS", "CDX_HY", "HY_ISSUANCE", "RATING_RATIO"],
}


# ------------------------------------------------------------------
# 데이터 로딩 + 트렌드 계산
# ------------------------------------------------------------------
def _fetch_raw_series(fred_id, start="1990-01-01", end=None):
    end = end or date.today().isoformat()
    s = strat.try_fetch_fred(fred_id, start, end)
    return s


def _build_series(ind_key, ind, market_data, raw_cache):
    transform = ind["transform"]
    if transform == "price_ratio":
        px = market_data["px"]
        if "QQQ" not in px.columns or "SPY" not in px.columns:
            return None
        return (px["QQQ"] / px["SPY"]).dropna()
    if transform == "realized_vol":
        px = market_data["px"]
        if "TLT" not in px.columns:
            return None
        ret = px["TLT"].pct_change()
        return (ret.rolling(20).std() * np.sqrt(252) * 100).dropna()
    fred_id = ind.get("fred")
    if not fred_id:
        return None
    if fred_id not in raw_cache:
        raw_cache[fred_id] = _fetch_raw_series(fred_id)
    raw = raw_cache[fred_id]
    if raw is None or len(raw) < 3:
        return None
    if transform == "level":
        return raw
    if transform == "yoy":
        monthly = raw.resample("ME").last()
        return (monthly.pct_change(12) * 100).dropna()
    return raw


def classify_trend(chg_1m, chg_3m, chg_6m, eps):
    """1/3/6개월 변화로 Rising/Falling/Neutral/Accelerating/Reversing 분류."""
    if pd.isna(chg_1m):
        return "Neutral"
    pace_3m = chg_3m / 3 if pd.notna(chg_3m) else np.nan
    if abs(chg_1m) < eps and (pd.isna(pace_3m) or abs(pace_3m) < eps):
        return "Neutral"
    if pd.notna(pace_3m) and abs(pace_3m) >= eps and np.sign(chg_1m) != np.sign(pace_3m) and abs(chg_1m) >= eps:
        return "Reversing"
    if pd.notna(pace_3m) and abs(pace_3m) >= eps and np.sign(chg_1m) == np.sign(pace_3m) and abs(chg_1m) > abs(pace_3m) * 1.4:
        return "Accelerating"
    return "Rising" if chg_1m > 0 else "Falling"


TREND_KO = {
    "Rising": "상승", "Falling": "하락", "Neutral": "횡보",
    "Accelerating": "가속", "Reversing": "반전조짐",
}

EPS_BY_UNIT = {"bp": 3.0, "pt": 0.15, "pct": 0.3}


def compute_indicator(ind_key, market_data, raw_cache):
    ind = IND[ind_key]
    series = _build_series(ind_key, ind, market_data, raw_cache)
    if series is None or len(series) < 3:
        return {"key": ind_key, **ind, "available": False}

    series = series.dropna()
    latest = series.iloc[-1]
    data_date = series.index[-1]
    prev = series.iloc[-2] if len(series) >= 2 else np.nan

    def _at_offset(months):
        target = data_date - pd.DateOffset(months=months)
        sub = series.loc[:target]
        return sub.iloc[-1] if len(sub) else np.nan

    v1m, v3m, v6m = _at_offset(1), _at_offset(3), _at_offset(6)
    change_unit = ind["change_unit"]

    def _chg(a, b):
        if pd.isna(a) or pd.isna(b):
            return np.nan
        if change_unit == "bp":
            return (a - b) * 100
        if change_unit == "pt":
            return a - b
        if b == 0:
            return np.nan
        return (a / b - 1) * 100

    chg_1m, chg_3m, chg_6m = _chg(latest, v1m), _chg(latest, v3m), _chg(latest, v6m)
    eps = EPS_BY_UNIT.get(change_unit, 0.3)
    trend = classify_trend(chg_1m, chg_3m, chg_6m, eps)

    return {
        "key": ind_key, **ind, "available": True,
        "series": series, "latest": latest, "prev": prev, "data_date": data_date,
        "chg_1m": chg_1m, "chg_3m": chg_3m, "chg_6m": chg_6m, "trend": trend,
    }


def compute_all(market_data):
    raw_cache = {}
    return {k: compute_indicator(k, market_data, raw_cache) for k in IND}


# ------------------------------------------------------------------
# 축별 요약 문장 (실제 계산된 트렌드로부터 템플릿 선택 — 임의 생성 아님)
# ------------------------------------------------------------------
def summarize_growth(res):
    ip, cl = res.get("INDPRO"), res.get("ICSA")
    if not (ip and ip["available"]) or not (cl and cl["available"]):
        return "핵심 성장 지표 데이터를 아직 충분히 확보하지 못해 요약을 생성할 수 없습니다."
    ip_t, cl_t = ip["trend"], cl["trend"]
    softening = ip_t in ("Falling", "Reversing") and cl_t in ("Rising", "Accelerating")
    resilient = ip_t in ("Rising", "Accelerating") and cl_t in ("Falling",)
    base = f"산업생산 YoY {ip['latest']:+.1f}%({TREND_KO[ip_t]}), 신규실업수당청구 {cl['latest']:,.0f}건({TREND_KO[cl_t]})."
    if softening:
        return base + " 생산 모멘텀 둔화와 청구건수 증가가 겹쳐 경기 둔화 신호가 강화되고 있으나, 아직 침체로 단정할 단계는 아닙니다."
    if resilient:
        return base + " 생산 모멘텀과 고용 모두 양호해 성장세가 비교적 견고한 국면으로 보입니다."
    return base + " 두 지표가 엇갈린 신호를 보이고 있어 방향을 단정하기 어려운 상황입니다."


def summarize_inflation(res):
    cpi, pce, be = res.get("CPI_CORE"), res.get("PCE_CORE"), res.get("BREAKEVEN_10Y")
    parts = []
    if cpi and cpi["available"]:
        parts.append(f"Core CPI {cpi['latest']:+.1f}%({TREND_KO[cpi['trend']]})")
    if pce and pce["available"]:
        parts.append(f"Core PCE {pce['latest']:+.1f}%({TREND_KO[pce['trend']]})")
    if not parts:
        return "근원물가 지표 데이터를 아직 확보하지 못했습니다."
    base = ", ".join(parts) + "."
    if be and be["available"]:
        be_t = be["trend"]
        stable_expect = be_t in ("Neutral", "Falling")
        cpi_hot = bool(cpi and cpi["available"] and cpi["trend"] in ("Rising", "Accelerating"))
        if stable_expect and cpi_hot:
            return base + f" 10Y 기대인플레이션({be['latest']:.2f}%)은 {TREND_KO[be_t]} 흐름이라 기대인플레는 비교적 안정적이지만, 실제 근원물가 상승 압력은 남아있는 상황."
        return base + f" 10Y 기대인플레이션은 {be['latest']:.2f}%로 {TREND_KO[be_t]} 흐름."
    return base


def summarize_policy(res):
    ff, uy2, ry = res.get("FEDFUNDS"), res.get("UST_2Y"), res.get("REAL_YIELD_10Y")
    parts = []
    if ff and ff["available"]:
        parts.append(f"Fed Funds {ff['latest']:.2f}%({TREND_KO[ff['trend']]})")
    if uy2 and uy2["available"]:
        parts.append(f"2Y {uy2['latest']:.2f}%({TREND_KO[uy2['trend']]})")
    if ry and ry["available"]:
        parts.append(f"10Y 실질금리 {ry['latest']:.2f}%({TREND_KO[ry['trend']]})")
    if not parts:
        return "정책금리/유동성 지표 데이터를 아직 확보하지 못했습니다."
    return ", ".join(parts) + ". 2년물과 실질금리 흐름을 함께 보면 시장이 반영 중인 긴축/완화 기대 방향을 가늠할 수 있습니다."


def summarize_credit(res):
    hy, ig, vix = res.get("HY_OAS"), res.get("IG_OAS"), res.get("VIX")
    if not (hy and hy["available"]):
        return "신용스프레드 데이터를 아직 확보하지 못했습니다."
    hy_t = hy["trend"]
    vix_t = vix["trend"] if vix and vix["available"] else None
    base = f"HY OAS {hy['latest']:.2f}%({TREND_KO[hy_t]})"
    if ig and ig["available"]:
        base += f", IG OAS {ig['latest']:.2f}%({TREND_KO[ig['trend']]})"
    if vix_t:
        base += f", VIX {vix['latest']:.1f}({TREND_KO[vix_t]})"
    base += "."
    if hy_t in ("Rising", "Accelerating") and vix_t in ("Rising", "Accelerating"):
        return base + " 신용과 변동성이 동시에 확대되고 있어 시장의 위험회피 심리가 강화되는 국면으로 해석됩니다."
    if hy_t in ("Falling",) and (vix_t in ("Falling", "Neutral") if vix_t else True):
        return base + " 신용스프레드가 축소되며 위험선호가 유지되고 있는 국면입니다."
    return base + " 신용과 변동성 신호가 뚜렷한 한 방향으로 정렬되어 있지는 않습니다."


def summarize_sentiment(res):
    available = [k for k in ("AAII", "COT", "PUTCALL", "BOFA_FMS") if res.get(k, {}).get("available")]
    if not available:
        return "포지셔닝·센티먼트 지표는 대부분 유료/비공개 데이터원이라 현재 집계 가능한 지표가 없습니다 (추후 확장 가능 영역)."
    return "일부 센티먼트 지표가 확보되었습니다: " + ", ".join(available)


AXIS_SUMMARY_FN = {
    "growth": summarize_growth,
    "inflation": summarize_inflation,
    "policy": summarize_policy,
    "credit": summarize_credit,
    "sentiment": summarize_sentiment,
}
