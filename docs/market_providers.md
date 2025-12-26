# Market Data Provider Architecture

Streamlit 페이지에서 호출되는 모든 시세/배당 데이터는 `core/market_data.py`에 정의된 `MarketDataProvider` 인터페이스를 통해 라우팅됩니다.  
기본 구성은 다음과 같습니다.

## Registry
- `register_market_provider(market_code, provider)` 로 시장 코드를 등록합니다. (`KR`, `US` 등은 `core.utils.normalize_market_code` 를 거쳐 표준화됩니다.)
- `get_registered_provider(market_code)` 를 호출하면 가장 최근에 등록된 공급자를 돌려줍니다. 등록되지 않은 코드는 `US` 공급자를 fallback 으로 사용합니다.
- 프로젝트 초기화 시 `US`/`KR` 기본 공급자가 자동 등록됩니다. 필요하면 `app.py` 혹은 별도 초기화 코드에서 재등록하여 커스터마이징할 수 있습니다.

## 기본 공급자
- **USProviderYFinance**: yfinance 에서 미국/해외티커 가격과 배당 데이터를 직접 조회합니다.
- **KRDartProvider** *(default KR provider)*:  
  - 배당: OpenDART API(`OpenDartReader`)에서 `배당` 보고서를 읽어 DPS(주당 배당금) 내역을 생성합니다. `dart_api_key` 파일에 인증키가 있어야 하며, `pip install opendartreader` 후 사용할 수 있습니다.  
  - 가격: `KRLocalProvider` 를 통해 `price_cache` → `data/kr_price_snapshot.csv` 순으로만 조회합니다. yfinance/네이버 등 해외 API를 전혀 사용하지 않으므로, 최소 한 번은 스냅샷 파일 또는 price_cache를 수동으로 채워야 합니다.
- **KRLocalProvider**: 로컬 `dividend_events`+스냅샷 가격만 쓰고 싶을 때 직접 등록해서 사용할 수 있는 공급자입니다.
- **KRExperimentalKRXProvider**: KRX 스크래핑 실험용 스켈레톤으로 기본 레지스트리에 포함되지 않습니다.

## DART 연동
- `core/dart_api.DartDividendFetcher` 가 `OpenDartReader` 를 통해 `배당` 보고서를 호출하고, 보통주 항목만 골라 `DividendPoint` 로 변환합니다.
- `dart_api_key` 파일에 인증키를 저장하고(줄바꿈/공백 제거), 가상환경에서 `pip install opendartreader==0.2.3` 같은 명령으로 패키지를 설치한 뒤 Streamlit 앱을 재시작하면 됩니다. (`OpenDartReader`/`opendartreader` 어느 이름으로든 import 가능하도록 처리되어 있습니다.)
- 네트워크나 키 문제로 DART를 호출할 수 없을 경우, 오류 메시지가 그대로 Surface 되며 사용자 조치가 필요합니다.

## 확장 방법 예시
```python
from core.market_data import register_market_provider, MarketDataProvider

class MyCustomProvider(MarketDataProvider):
    name = "my-provider"
    ...

register_market_provider("KR", MyCustomProvider())
```

이 구조 덕분에 KRX 스크래핑/실험용 공급자를 선택적으로 켜거나, DART 기반 공급자를 완전히 교체하는 것이 용이합니다.
