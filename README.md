# Regime Tilt — Growth × Inflation Allocation Strategy

성장×인플레이션 레짐에 따라 자산배분을 조정하는 전략의 Streamlit 대시보드입니다.

- **1) 월별 레짐 배분**: 성장(INDPRO)·인플레이션(CPI) YoY 추세로 4개 레짐(Goldilocks/Reflation/
  Stagflation/Deflation)을 워크포워드로 판정하고, 레짐별 고정 주식비중으로 틸트
- **2) 일별 위기 오버레이**: VIX·SPY·HYG 신호 2/3 투표로 위험회피 상태를 판정, ON이면 위험자산을
  BIL(초단기국채)로 대피
- **3) 간단 Fear & Greed**: VKOSPI + KOSPI 모멘텀 점수로 KODEX200(069500.KS) 포지션만 별도 타이밍

백테스트는 look-ahead 없는 워크포워드 방식이며, 거래비용(턴오버 기반)을 반영한 수치를 기본으로 보여줍니다.
과거 성과이며 투자 조언이 아닙니다.

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# API 키 설정 (아래 두 키는 무료 발급)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# .streamlit/secrets.toml 파일을 열어 FRED_API_KEY, FG_KRX_AUTH_KEY 값을 채워넣기
#   - FRED_API_KEY: https://fred.stlouisfed.org/docs/api/api_key.html
#   - FG_KRX_AUTH_KEY: https://data.krx.co.kr

streamlit run app.py
```

## 배포 (Streamlit Community Cloud)

1. 이 저장소를 [share.streamlit.io](https://share.streamlit.io)에서 "New app"으로 연결, main file은 `app.py`
2. 앱 설정의 **Secrets**에 `.streamlit/secrets.toml.example`과 같은 형식으로
   `FRED_API_KEY`, `FG_KRX_AUTH_KEY` 값을 입력
3. Deploy

## 구성

- `app.py` — Streamlit 대시보드 UI
- `strategy.py` — 데이터 수집 + 백테스트 엔진
- `data/vkospi_daily.csv` — VKOSPI 로컬 캐시 (KRX 공공데이터 API로 자동 증분 갱신)
