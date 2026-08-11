from __future__ import annotations

import hashlib, json, os, re, time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "site" / "live-news.json"
QUEUE_PATH = ROOT / "verification-queue.json"
KST = timezone(timedelta(hours=9))
NOW = datetime.now(timezone.utc)
LOOKBACK_DAYS = max(1, min(14, int(os.getenv("NEWS_LOOKBACK_DAYS", "1"))))
TRUSTED = {"Reuters", "Associated Press", "AP", "Bloomberg"}
DIRECT_FEEDS = (
    ("FinancialJuice", "https://www.financialjuice.com/feed.ashx?xy=rss", "financialjuice"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "coindesk"),
    ("AP News", "https://apnews.com/index.rss", "ap"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "federal_reserve"),
    ("SEC", "https://www.sec.gov/news/pressreleases.rss", "sec"),
    ("CFTC", "https://www.cftc.gov/RSS/RSSGP/rssgp.xml", "cftc"),
    ("Strategy SEC 8-K", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1050446&type=8-K&owner=exclude&count=40&output=atom", "strategy_sec"),
)
QUERIES = [
    "bitcoin Reuters", "bitcoin AP", "bitcoin Bloomberg",
    "bitcoin Federal Reserve", "bitcoin regulation United States",
    "oil Iran Hormuz Reuters", "Iran Hormuz AP", "Iran Hormuz Bloomberg",
    "Iran negotiations AP Reuters", "Iran talks Hormuz agreement Reuters AP",
    "US Japan coordinated yen intervention Reuters AP",
    "Japan yen intervention FIMA Repo Reuters AP",
    "Federal Reserve rates inflation Reuters", "Beth Hammack Federal Reserve rate hikes inflation", "CME FedWatch bitcoin",
    "altcoin token burn crypto", "official scheduled token burn crypto",
    "token burn announcement buyback burn schedule", "소각 예정 코인 공식 발표",
    "token unlock crypto",
    "crypto mainnet upgrade governance proposal",
    "crypto exchange listing delisting altcoin",
    "crypto protocol exploit hack", "crypto foundation treasury token transfer",
    "Ethereum Solana XRP BNB Cardano Avalanche Chainlink TON Sui Aptos crypto",
    "site:reuters.com bitcoin crypto Federal Reserve Iran oil tariff",
    "site:apnews.com bitcoin crypto Federal Reserve Iran oil tariff",
    "site:bloomberg.com bitcoin crypto Federal Reserve Iran oil tariff",
    "site:coindesk.com bitcoin crypto regulation treasury onchain",
    "site:lookonchain.com bitcoin BTC whale treasury transfer",
    "Lookonchain bitcoin BTC whale treasury transfer",
    "site:sec.gov crypto bitcoin ETF enforcement filing",
    "site:federalreserve.gov inflation interest rates monetary policy",
    "site:cftc.gov crypto digital assets enforcement",
    "Trump Media DJT bitcoin treasury Crypto.com Lookonchain",
    "site:strategy.com/press Strategy bitcoin sold acquired holdings USD reserve",
    "site:sec.gov/Archives/edgar/data/1050446 Strategy bitcoin sale holdings 8-K",
    "Strategy MSTR bitcoin sold holdings USD reserve preferred dividend",
]
BTC_TERMS = {"bitcoin", "btc", "crypto", "federal reserve", "interest rate",
             "inflation", "oil", "iran", "hormuz", "tariff", "sec", "cftc",
             "비트코인", "암호화폐", "연준", "금리", "인플레이션", "유가",
             "이란", "호르무즈", "관세", "달러", "채권"}
BTC_TERMS.update({
    "fomc", "powell", "williams", "warsh", "hammack", "beth hammack", "해맥", "employment", "unemployment",
    "monetary policy", "rate hike", "rate cut", "treasury yield", "middle east",
    "venezuela", "dollar", "yen", "intervention",
    "strategy", "microstrategy", "mstr", "saylor", "usd reserve", "preferred dividend",
    "altcoin", "token", "burn", "unlock", "airdrop", "mainnet", "governance",
    "listing", "delisting", "exploit", "hack", "staking", "treasury",
    "알트코인", "토큰", "소각", "소각 예정", "언락", "에어드롭", "메인넷", "거버넌스",
    "상장", "상장폐지", "해킹", "스테이킹", "재단", "유통량", "고용", "실업",
    "통화정책", "금리인상", "금리인하", "국채", "중동", "베네수엘라", "엔화", "개입",
    "스트래티지", "마이크로스트래티지", "세일러", "달러 준비금", "우선주 배당",
})
TELEGRAM_CHANNELS = ("goddessTTF",)
SAVETICKER_URL = "https://www.saveticker.com/news"
YOUTUBE_CHANNELS = ("https://www.youtube.com/@새벽에온주호",)
SUPPRESSED_DUPLICATES = {
    "2026-07-26-cd976c2c93c2",
    "2026-07-26-08d1a65d77c4",
}
LOW_SIGNAL_TITLE_PATTERNS = (
    "price holds above",
    "traders brace",
    "price remains above",
    "market awaits",
)


def clean_title(title):
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()

def clean_html(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def collect_telegram():
    rows = []
    for channel in TELEGRAM_CHANNELS:
        try:
            response = requests.get(
                f"https://t.me/s/{channel}",
                headers={"User-Agent": "Mozilla/5.0 (compatible; TaehwanNewsBot/1.0)"},
                timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for message in soup.select(".tgme_widget_message"):
            post_id = message.get("data-post", "")
            text_node = message.select_one(".tgme_widget_message_text")
            time_node = message.select_one("time[datetime]")
            if not post_id or text_node is None or time_node is None:
                continue
            text = clean_html(text_node.get_text(" ", strip=True))
            try:
                when = datetime.fromisoformat(time_node["datetime"].replace("Z", "+00:00")).astimezone(timezone.utc)
            except (KeyError, ValueError):
                continue
            if NOW - when > timedelta(hours=30) or not any(term in text.lower() for term in BTC_TERMS):
                continue
            rows.append({
                "title": text[:220],
                "url": f"https://t.me/{post_id}",
                "source": f"Telegram @{channel}",
                "published_at": when.isoformat().replace("+00:00", "Z"),
                "snippet": text[:1800],
                "discovery_source": "telegram",
            })
    return rows


def relative_kst_time(label):
    label = label.strip()
    now_kst = NOW.astimezone(KST)
    if label == "방금 전":
        return NOW
    match = re.fullmatch(r"(\d+)(분|시간)\s*전", label)
    if match:
        minutes = int(match.group(1)) * (60 if match.group(2) == "시간" else 1)
        return NOW - timedelta(minutes=minutes)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", label)
    if match:
        candidate = now_kst.replace(hour=int(match.group(1)), minute=int(match.group(2)),
                                    second=0, microsecond=0)
        if candidate > now_kst + timedelta(minutes=5):
            candidate -= timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    return None


def collect_saveticker():
    try:
        response = requests.get(
            SAVETICKER_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TaehwanNewsBot/1.0)"},
            timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows, seen = [], set()
    for card in soup.select("div[data-index]"):
        title_node = card.select_one("p[class*='text-large-bold']")
        if title_node is None:
            continue
        title = clean_html(title_node.get_text(" ", strip=True))
        if not title or title in seen or title.startswith("(카더라)"):
            continue
        text = card.get_text("\n", strip=True)
        time_match = re.search(r"(방금 전|\d+\s*(?:분|시간)\s*전|\d{1,2}:\d{2})", text)
        when = relative_kst_time(time_match.group(1).replace(" ", "")) if time_match else None
        if when is None or NOW - when > timedelta(hours=30):
            continue
        if not any(term in title.lower() for term in BTC_TERMS):
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        source = lines[0] if lines else "SaveTicker"
        rows.append({
            "title": title[:220],
            "url": SAVETICKER_URL,
            "source": f"SaveTicker · {source}",
            "published_at": when.isoformat().replace("+00:00", "Z"),
            "snippet": title,
            "discovery_source": "saveticker",
        })
        seen.add(title)
    return rows


def collect_youtube():
    rows = []
    for channel_url in YOUTUBE_CHANNELS:
        try:
            page = requests.get(
                f"{channel_url}/videos",
                headers={"User-Agent": "Mozilla/5.0 (compatible; TaehwanNewsBot/1.0)"},
                timeout=20)
            page.raise_for_status()
        except requests.RequestException:
            continue
        channel_match = re.search(r'"(?:channelId|externalId)":"(UC[^"]+)"', page.text)
        if not channel_match:
            continue
        feed = feedparser.parse(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_match.group(1)}")
        for entry in feed.entries[:15]:
            raw = entry.get("published") or entry.get("updated")
            try:
                when = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
            except (AttributeError, ValueError):
                continue
            title = clean_title(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            combined = f"{title} {summary}".lower()
            if NOW - when > timedelta(days=14) or not any(term in combined for term in BTC_TERMS):
                continue
            rows.append({
                "title": title[:220],
                "url": entry.get("link", channel_url),
                "source": "YouTube @새벽에온주호",
                "published_at": when.isoformat().replace("+00:00", "Z"),
                "snippet": summary[:1800],
                "discovery_source": "youtube",
            })
    return rows


def collect_direct_feeds():
    rows = []
    for source_name, feed_url, discovery_source in DIRECT_FEEDS:
        try:
            feed = feedparser.parse(feed_url,
                request_headers={"User-Agent": "Mozilla/5.0 (compatible; TaehwanNewsBot/1.0)"})
        except Exception:
            continue
        for entry in feed.entries[:80]:
            raw = entry.get("published") or entry.get("updated")
            try:
                when = parsedate_to_datetime(raw).astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
            title = clean_title(entry.get("title", ""))
            summary = clean_html(entry.get("summary", "") or entry.get("description", ""))
            combined = f"{title} {summary}".lower()
            if NOW - when > timedelta(hours=36) or not any(term in combined for term in BTC_TERMS):
                continue
            rows.append({
                "title": title[:220],
                "url": entry.get("link", feed_url),
                "source": source_name,
                "published_at": when.isoformat().replace("+00:00", "Z"),
                "snippet": summary[:1800],
                "discovery_source": discovery_source,
            })
    return rows


def collect():
    rows = []
    youtube_rows = collect_youtube()
    rows.extend(collect_direct_feeds())
    search_jobs = [(query, LOOKBACK_DAYS) for query in QUERIES]
    search_jobs.extend((row["title"], 14) for row in youtube_rows[:12])
    for query, days in search_jobs:
        url = f"https://news.google.com/rss/search?q={quote_plus(query + f' when:{days}d')}&hl=en-US&gl=US&ceid=US:en"
        for entry in feedparser.parse(url).entries[:30]:
            raw = entry.get("published") or entry.get("updated")
            try:
                when = parsedate_to_datetime(raw).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            title = clean_title(entry.get("title", ""))
            if NOW - when > timedelta(days=days, hours=6) or not any(t in title.lower() for t in BTC_TERMS):
                continue
            source = (entry.get("source") or {}).get("title", "Google News").strip()
            rows.append({"title": title, "url": entry.get("link", ""), "source": source,
                         "published_at": when.isoformat().replace("+00:00", "Z"),
                         "snippet": clean_html(entry.get("summary", ""))[:1200]})
    rows.extend(collect_telegram())
    rows.extend(collect_saveticker())
    rows.extend(youtube_rows)
    return rows


def words(title):
    return {w for w in re.findall(r"[a-z0-9가-힣]{3,}", title.lower())
            if w not in {"the", "and", "for", "with", "from", "after"}}


def cluster(rows):
    groups = []
    for row in sorted(rows, key=lambda x: x["published_at"], reverse=True):
        match = next((g for g in groups if len(words(g[0]["title"]) & words(row["title"])) /
                      max(1, len(words(g[0]["title"]) | words(row["title"]))) >= .46), None)
        if match is None:
            groups.append([row])
        elif row["source"] not in {x["source"] for x in match}:
            match.append(row)
    return groups


def stable_id(title, when):
    return f"{when[:10]}-{hashlib.sha256(title.lower().encode()).hexdigest()[:12]}"


def candidates():
    result = []
    for group in cluster(collect()):
        discovery_sources = {x.get("discovery_source") for x in group} - {None}
        discovery_only = bool(discovery_sources)
        if len(group) < 2 and not any(x["source"] in TRUSTED for x in group) and not discovery_only:
            continue
        lead = group[0]
        if any(pattern in lead["title"].lower() for pattern in LOW_SIGNAL_TITLE_PATTERNS):
            continue
        result.append({
            "stable_id": stable_id(lead["title"], lead["published_at"]),
            "original_title": lead["title"], "published_at": lead["published_at"],
            "discovery_source": sorted(discovery_sources)[0] if discovery_sources else "news",
            "evidence": [{"headline": x["title"], "source": x["source"],
                          "snippet": x.get("snippet", ""), "url": x["url"]}
                         for x in group[:5]],
            "sources": [{"name": x["source"], "url": x["url"]} for x in group[:5]]
        })
    return result


def valid(item):
    impact = item.get("btc_impact", {})
    title = item.get("title", "")
    verification = item.get("verification", {})
    independent = verification.get("independent_sources", 0)
    independent_count = len(independent) if isinstance(independent, list) else int(independent or 0)
    sources = item.get("sources", [])
    source_rows = sources if isinstance(sources, list) else [
        source for group in sources.values() for source in group
    ]
    asset_class = item.get("asset_class", "bitcoin")
    event_type = item.get("event_type", "market")
    completed_sensitive_event = (
        event_type not in {"burn", "unlock", "treasury_move"}
        or verification.get("official_or_onchain") is True
    )
    scheduled_burn_verified = (
        event_type != "burn_scheduled"
        or (verification.get("official_source") is True
            and bool(item.get("scheduled_at"))
            and bool(item.get("burn_amount") or item.get("burn_method")))
    )
    altcoin_complete = (asset_class != "altcoin"
                        or (bool(item.get("token_symbol"))
                            and completed_sensitive_event
                            and scheduled_burn_verified))
    discovery_verified = (item.get("discovery_source", "news") == "news"
                          or (independent_count >= 2
                              and any(all(tag not in source.get("name", "").lower()
                                          for tag in ("telegram", "saveticker", "youtube"))
                                      for source in source_rows)))
    return (discovery_verified and altcoin_complete
            and bool(re.search(r"[가-힣]", title))
            and 8 <= len(title) <= 90
            and len(item.get("summary", "")) >= 180
            and len(item.get("why_it_matters", "")) >= 100
            and isinstance(impact, dict) and len(impact.get("assessment", "")) >= 100
            and len(item.get("missed_point", "")) >= 80
            and len(item.get("follow_up", [])) >= 3
            and len(source_rows) >= 1)


def candidate_score(item):
    sources = item.get("sources", [])
    names = {str(source.get("name", "")).lower() for source in sources}
    title = item.get("original_title", "").lower()
    official_tags = ("federal reserve", "sec", "cftc", "strategy sec", "white house", "bank of japan")
    major_tags = ("reuters", "associated press", "ap", "bloomberg", "coindesk")
    urgent_terms = ("bitcoin", "strategy", "iran", "hormuz", "federal reserve", "rate", "inflation",
                    "oil", "tariff", "intervention", "sec", "cftc", "hack", "burn", "unlock")
    score = len(names) * 12
    score += 20 if any(any(tag in name for tag in official_tags) for name in names) else 0
    score += 12 if any(any(tag in name for tag in major_tags) for name in names) else 0
    score += sum(2 for term in urgent_terms if term in title)
    return score


def enrich(items):
    token = os.getenv("GROQ_API_KEY", "").strip()
    if not items:
        return []
    if not token:
        raise RuntimeError("GROQ_API_KEY is unavailable; verified candidates remain queued")
    prompt = """당신은 비트코인 거시경제 뉴스 편집자다. 제공된 헤드라인·기사 스니펫·출처만 사용하고 추측하지 않는다.
각 항목을 한국어로 자세히 분석한다. 정보가 부족하거나 단순 가격 시황이면 results에서 제외한다.
title은 출처명·'[검증 중]'·불필요한 인용문을 빼고 핵심 사실만 한국어 55자 이내로 작성한다.
같은 사건의 반복 보도는 새 카드로 만들지 말고, 실제 정책·시장 반응·공식 발언이 추가된 경우에만 업데이트로 본다.
긍정적 헤드라인과 반대되는 신호, 협상 발언과 실제 정책·군사행동의 차이,
유가→물가→연준→금리·달러→BTC 전달 경로, 후속 발언으로 기존 평가가 바뀌는지를 반드시 검토한다.
FinancialJuice 단독 속보는 공식·독립 출처로 재검증되지 않으면 제외한다.
Strategy·Michael Saylor 관련 비트코인 매수·매도·보유량 변화는 Strategy 공식 발표 또는 SEC 8-K가 있을 때만 확정한다. 개인 지갑 이동과 회사의 실제 매각을 구분하고, 직전 공시 보유량과 최신 공시 보유량의 차이를 계산해 수량 오류를 점검한다.
Telegram 게시물은 속보 탐지용일 뿐이다. Telegram 단독 항목은 절대 반환하지 않는다.
SaveTicker 게시물도 속보 탐지용일 뿐이다. SaveTicker 단독 항목은 절대 반환하지 않는다.
YouTube 영상도 아이디어 탐지용일 뿐이다. 영상의 주장이나 가격 전망을 사실처럼 쓰지 않는다.
YouTube와 Telegram, SaveTicker는 공개 sources 배열에 넣지 말고 검증에 사용한 공식 발표와 독립 언론만 넣는다.
전체 후보의 evidence를 서로 대조해 Reuters·AP·Bloomberg 또는 공식 발표가 같은 사실을 독립적으로
확인한 경우에만 Telegram·SaveTicker·YouTube 후보를 반환하고, 그 독립 출처 링크를 sources 배열에 복사한다.
반환은 JSON 객체 하나이며 results 배열만 포함한다. 각 결과에는 stable_id, title, summary(최소 5문장),
importance(1~5), tone(up/down/warn), btc_impact({direction: 호재/악재/양방향, assessment: 최소 3문장}),
why_it_matters(최소 3문장), missed_point(최소 2문장), follow_up(구체적 확인사항 3개 이상),
sources([{name,url}] 최소 2개),
verification({state, independent_sources, financialjuice_only, rumor_excluded, notes,
official_or_onchain, official_source, trump_separation:{statement, policy_action, market_interpretation}}),
asset_class(bitcoin 또는 altcoin), token_symbol(알트코인이면 필수), event_type
(burn/burn_scheduled/unlock/listing/delisting/upgrade/governance/hack/treasury_move/market)를 넣는다.
중소형 코인도 포함하되 소각·언락·재단 이동은 공식 공지 또는 온체인 근거가 확인된 경우에만 반환한다.
예정된 소각은 event_type을 burn_scheduled로 하고 제목에 '소각 예정'을 명시한다.
이 경우 scheduled_at(공식 예정 일시), burn_amount(확정 수량, 없으면 빈 문자열),
burn_method(자동 소각·바이백 후 소각 등), verification.official_source=true를 반드시 넣는다.
날짜·수량·방식 중 핵심 조건이 공식 출처에서 확인되지 않거나 커뮤니티 투표·제안 단계라면 반환하지 않는다.
출처에 없는 숫자나 사실을 만들지 않는다."""
    patches = {}
    models = ("openai/gpt-oss-120b", "qwen/qwen3.6-27b")
    for start in range(0, len(items), 1):
        batch = items[start:start + 1]
        completed = False
        last_error = None
        for model in models:
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "max_completion_tokens": 1400,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content":
                                json.dumps(batch, ensure_ascii=False)},
                        ],
                    },
                    timeout=90)
                if response.status_code >= 400:
                    detail = response.text.replace("\n", " ")[:240]
                    print(f"::warning::Model {model} HTTP {response.status_code}: {detail}")
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                content = message.get("content") or message.get("reasoning") or ""
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if not match:
                    raise ValueError("model response did not contain a JSON object")
                results = json.loads(match.group(0)).get("results", [])
                patches.update({x["stable_id"]: x for x in results})
                print(f"Enriched batch {start // 3 + 1} with {model}: {len(results)}/{len(batch)} publishable")
                completed = True
                break
            except Exception as exc:
                last_error = exc
        if not completed:
            raise RuntimeError(f"all model retries failed for batch {start // 3 + 1}: {type(last_error).__name__}: {str(last_error)[:180]}")
        if start + 1 < len(items):
            time.sleep(31)
    enriched = []
    for item in items:
        patch = patches.get(item["stable_id"])
        if not patch:
            continue
        item.update(patch)
        if isinstance(item.get("sources"), list):
            item["sources"] = [
                source for source in item["sources"]
                if all(tag not in source.get("name", "").lower()
                       for tag in ("youtube", "새벽에온주호", "telegram", "saveticker"))
            ]
        elif isinstance(item.get("sources"), dict):
            item["sources"] = {
                group: [
                    source for source in sources
                    if all(tag not in source.get("name", "").lower()
                           for tag in ("youtube", "새벽에온주호", "telegram", "saveticker"))
                ]
                for group, sources in item["sources"].items()
            }
        when = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        item["kst"] = when.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        item["status"] = item.get("verification", {}).get("state", "verified")
        item["impact"] = item.get("btc_impact", {}).get("direction", "양방향")
        if valid(item):
            enriched.append(item)
    return enriched


def main():
    current = json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.exists() else {"items": []}
    queued = json.loads(QUEUE_PATH.read_text(encoding="utf-8")) if QUEUE_PATH.exists() else {"items": []}
    existing = {x["stable_id"]: x for x in current.get("items", [])
                if x.get("status") != "verification_pending"
                and valid(x) and x["stable_id"] not in SUPPRESSED_DUPLICATES}
    waiting = {x["stable_id"]: x for x in queued.get("items", [])
               if x.get("stable_id") and x.get("original_title")}
    waiting.update({x["stable_id"]: x for x in candidates()})
    new = [x for x in waiting.values()
           if x["stable_id"] not in existing and x["stable_id"] not in SUPPRESSED_DUPLICATES]
    new.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    selected = sorted(new, key=lambda item: (candidate_score(item), item.get("published_at", "")),
                      reverse=True)[:9]
    queue_items = new[:100]
    try:
        published = enrich(selected)
        for item in published:
            existing[item["stable_id"]] = item
        published_ids = {item["stable_id"] for item in published}
        queue_items = [item for item in new if item["stable_id"] not in published_ids][:100]
    except Exception as exc:
        print(f"::warning::Enrichment unavailable; keeping candidates off-site for retry: {type(exc).__name__}")
    output = {"generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
              "items": sorted(existing.values(), key=lambda x: x.get("published_at_kst") or x.get("published_at") or x.get("source_time", ""), reverse=True)[:40]}
    queue_output = {"updated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
                    "items": queue_items}
    if json.dumps(current, ensure_ascii=False, sort_keys=True) != json.dumps(output, ensure_ascii=False, sort_keys=True):
        FEED_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.dumps(queued, ensure_ascii=False, sort_keys=True) != json.dumps(queue_output, ensure_ascii=False, sort_keys=True):
        QUEUE_PATH.write_text(json.dumps(queue_output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
