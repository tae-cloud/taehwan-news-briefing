from __future__ import annotations

import hashlib, json, os, re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "site" / "live-news.json"
KST = timezone(timedelta(hours=9))
NOW = datetime.now(timezone.utc)
TRUSTED = {"Reuters", "Associated Press", "AP", "Bloomberg"}
QUERIES = ["bitcoin Reuters", "bitcoin AP", "bitcoin Federal Reserve",
           "bitcoin regulation United States", "oil Iran Hormuz Reuters",
           "Federal Reserve rates inflation Reuters"]
BTC_TERMS = {"bitcoin", "btc", "crypto", "federal reserve", "interest rate",
             "inflation", "oil", "iran", "hormuz", "tariff", "sec", "cftc"}


def clean_title(title):
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()


def collect():
    rows = []
    for query in QUERIES:
        url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
        for entry in feedparser.parse(url).entries[:30]:
            raw = entry.get("published") or entry.get("updated")
            try:
                when = parsedate_to_datetime(raw).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            title = clean_title(entry.get("title", ""))
            if NOW - when > timedelta(hours=30) or not any(t in title.lower() for t in BTC_TERMS):
                continue
            source = (entry.get("source") or {}).get("title", "Google News").strip()
            rows.append({"title": title, "url": entry.get("link", ""), "source": source,
                         "published_at": when.isoformat().replace("+00:00", "Z")})
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
        if len(group) < 2 and not any(x["source"] in TRUSTED for x in group):
            continue
        lead = group[0]
        result.append({
            "stable_id": stable_id(lead["title"], lead["published_at"]),
            "original_title": lead["title"], "published_at": lead["published_at"],
            "sources": [{"name": x["source"], "url": x["url"]} for x in group[:5]]
        })
    return result


def valid(item):
    impact = item.get("btc_impact", {})
    return (len(item.get("summary", "")) >= 180
            and len(item.get("why_it_matters", "")) >= 100
            and isinstance(impact, dict) and len(impact.get("assessment", "")) >= 100
            and len(item.get("missed_point", "")) >= 80
            and len(item.get("follow_up", [])) >= 3
            and len(item.get("sources", [])) >= 1)


def enrich(items):
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token or not items:
        return []
    prompt = """당신은 비트코인 거시경제 뉴스 편집자다. 제공된 기사 제목과 출처만 사용하고 추측하지 않는다.
각 항목을 한국어로 자세히 분석한다. 정보가 부족하면 해당 항목을 results에서 제외한다.
반환은 JSON 객체 하나이며 results 배열만 포함한다. 각 결과에는 stable_id, title, summary(최소 5문장),
importance(1~5), tone(up/down/warn), btc_impact({direction: 호재/악재/양방향, assessment: 최소 3문장}),
why_it_matters(최소 3문장), missed_point(최소 2문장), follow_up(구체적 확인사항 3개 이상),
verification({state, independent_sources, notes})를 넣는다. 출처에 없는 숫자나 사실을 만들지 않는다."""
    response = requests.post(
        "https://models.github.ai/inference/chat/completions",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"model": "openai/gpt-4.1", "temperature": 0.2,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": prompt},
                           {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]},
        timeout=90)
    response.raise_for_status()
    patches = {x["stable_id"]: x for x in json.loads(response.json()["choices"][0]["message"]["content"]).get("results", [])}
    enriched = []
    for item in items:
        patch = patches.get(item["stable_id"])
        if not patch:
            continue
        item.update(patch)
        when = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        item["kst"] = when.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        item["status"] = item.get("verification", {}).get("state", "verified")
        item["impact"] = item.get("btc_impact", {}).get("direction", "양방향")
        if valid(item):
            enriched.append(item)
    return enriched


def main():
    current = json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.exists() else {"items": []}
    existing = {x["stable_id"]: x for x in current.get("items", []) if valid(x)}
    new = [x for x in candidates() if x["stable_id"] not in existing]
    try:
        for item in enrich(new):
            existing[item["stable_id"]] = item
    except Exception as exc:
        print(f"Enrichment unavailable; publishing nothing new: {type(exc).__name__}")
    output = {"generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
              "items": sorted(existing.values(), key=lambda x: x.get("source_time") or x.get("published_at", ""), reverse=True)[:40]}
    if json.dumps(current, ensure_ascii=False, sort_keys=True) != json.dumps(output, ensure_ascii=False, sort_keys=True):
        FEED_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
