# dividend-dashboard
배당금 현황 관리 웹 서비스

## Configuration

- **Secrets**  
  민감한 키(`ADMIN_PASSWORD`, `KIS_*`, `DART_API_KEY` 등)는 `.streamlit/secrets.toml` 또는 동일한 환경 변수에 설정해 주세요. `dart_api_key` 파일은 더 이상 사용하지 않습니다.
- **Database**  
  리포지토리에는 스냅샷 역할을 하는 `dividends-seed.sqlite3` 가 포함되어 있습니다. 앱을 실행하면 기본적으로 `var/dividends.sqlite3` 로 복사해 사용하며, 해당 경로에 쓰기 권한이 없을 경우 자동으로 `~/.dividend-dashboard/dividends.sqlite3` 로 백업해 사용합니다. 필요하다면 `.streamlit/secrets.toml` 또는 환경 변수에 `DIVIDENDS_DB_PATH`(파일 경로)나 `DIVIDENDS_DB_URL`(SQLAlchemy URL) 을 지정해 별도의 DB 를 바라보게 할 수 있습니다.
