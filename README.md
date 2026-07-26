# 태환의 뉴스 브리핑

비트코인에 영향을 줄 수 있는 거시경제·정책·지정학 뉴스를 자동으로 수집하고 교차 확인한 뒤 정적 사이트에 게시합니다.

## 자동 실행

- GitHub Actions가 5분마다 최신 뉴스 피드를 확인합니다.
- 서로 다른 출처에서 같은 사건이 확인되거나 Reuters·AP·Bloomberg·공식기관 등 신뢰 가능한 출처인 경우만 게시합니다.
- 새 게시 항목이 있을 때만 `site/live-news.json`을 커밋합니다.
- Netlify가 `main` 브랜치 변경을 감지해 자동 배포합니다.

## 선택적 AI 검토

저장소의 `Settings → Secrets and variables → Actions`에 `OPENAI_API_KEY`를 등록하면 핵심 내용, 중요성, BTC 영향과 호재·악재 분류를 AI가 보강합니다. 키가 없어도 교차검증 및 규칙 기반 분류는 작동합니다.

## 배포

Netlify에서 이 저장소를 연결하고 Publish directory를 `site`로 설정합니다. `netlify.toml`에도 동일한 설정이 포함되어 있습니다.
