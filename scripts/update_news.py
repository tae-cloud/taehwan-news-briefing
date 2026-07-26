from __future__ import annotations

import hashlib
import json
import os
import re
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
MAX_AGE = timedelta(hours=30)
MAX_ITEMS = 40

QUERIES = [
    "bitcoin Reuters",
    "bitcoin AP",
    "bitcoin Federal Reserve",
    "bitcoin regulation United States",
    "oil Iran Hormuz Reuters",
    "Federal Reserve rates inflation Reuters",
]

BTC_TERMS = {
    "bitcoin", "btc", "crypto", "cryptocurrency", "digital asset",
    "federal reserve", "interest rate", "inflation", "cpi", "pce",
    "oil", "iran", "hormuz", "tariff", "sec", "cftc",
}

UP_TERMS = {"ceasefire", "pause", "approval", "inflow", "rate cut", "easing", "deal", "agreement"}
DOWN_TERMS = {"attack", "war", "tariff", "rate hike", "inflation", "ban", "outflow", "sanction"}
TRUSTED = {"Reuters", "Associated Press", "AP", "Bloomberg", "Federal Reserve", "SEC", "CFTC"}


def clean_title(title: str) -> str:
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()


def tokens(title: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9가-힣]{3,}", title.lower())
        if word not in {"the", "and", "for", "with", "from", "after"}
    }


def similarity(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    return len(a & b) / max(1, len(a | b))


def published(entry) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(raw)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def source_name(entry) -> str:
    source = entry.get("source") or {}
    return (source.get("title") or "Google News").strip()


def collect() -> list[dict]:
    rows: list[dict] = []
    for query in QUERIES:
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
        )
        parsed = feedparser.parse(url)
        for entry in parsed.entries[:30]:
            when = published(entry)
            if not when or NOW - when > MAX_AGE:
                continue
            title = clean_title(entry.get("title", ""))
            haystack = f"{title} {entry.get('summary', '')}".lower()
            if not any(term in haystack for term in BTC_TERMS):
                continue
            rows.append({
                "title": title,
                "url": entry.get("link", ""),
                "source": source_name(entry),
                "published_at": when.isoformat().replace("+00:00", "Z"),
            })
    return rows


def cluster(rows: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for row in sorted(rows, key=lambda item: item["published_at"], reverse=True):
        match = next(
            (group for group in groups if similarity(group[0]["title"], row["title"]) >= 0.46),
            None,
        )
        if match is None:
            groups.append([row])
        elif row["source"] not in {item["source"] for item in match}:
            match.append(row)
    return groups


def classify(title: str) -> tuple[str, str]:
    lowered = title.lower()
    up = sum(term in lowered for term in UP_TERMS)
    down = sum(term in lowered for term in DOWN_TERMS)
    if up > down:
        return "up", "호재"
    if down > up:
        return "down", "악재"
    return "warn", "양방향"


def stable_id(title: str, when: str) -> str:
    digest = hashlib.sha256(title.lower().encode("utf-8")).hexdigest()[:12]
    return f"{when[:10]}-{digest}"


def fallback_item(group: list[dict]) -> dict:
    lead = group[0]
    tone, impact = classify(lead["title"])
    cross_verified = len(group) >= 2
    trusted = any(item["source"] in TRUSTED for item in group)
    status = "cross_verified" if cross_verified else "verified" if trusted else "publishable"
    when = datetime.fromisoformat(lead["published_at"].replace("Z", "+00:00"))
    return {
        "stable_id": stable_id(lead["title"], lead["published_at"]),
        "title": lead["title"],
        "published_at": lead["published_at"],
        "kst": when.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "status": status,
        "tone": tone,
        "impact": impact,
        "importance": 5 if cross_verified else 4 if trusted else 3,
        "summary": "복수의 최신 뉴스 피드에서 확인된 주요 사실입니다." if cross_verified else "신뢰 가능한 최신 뉴스 피드에서 확인된 업데이트입니다.",
        "why_it_matters": "유가·금리·규제 및 위험선호 경로를 통해 비트코인 가격 변동성에 영향을 줄 수 있습니다.",
        "btc_impact": f"현재 분류는 BTC {impact}입니다. 원문과 후속 보도를 함께 확인해야 합니다.",
        "sources": [{"name": item["source"], "url": item["url"]} for item in group[:4]],
    }


def enrich_with_openai(items: list[dict]) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not items:
        return items
    prompt = {
        "task": "아래 뉴스 항목을 한국어로 간결하고 정확하게 보강한다. 추측하지 말고 제공된 제목과 출처만 사용한다.",
        "output": "각 stable_id별 summary, why_it_matters, btc_impact, tone(up/down/warn), impact(호재/악재/양방향), importance(1-5)를 JSON 배열로 반환",
        "items": items,
    }
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-5-mini",
                "input": json.dumps(prompt, ensure_ascii=False),
                "text": {"format": {"type": "json_object"}},
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload.get("output_text", "")
        enriched = json.loads(text).get("items", [])
        by_id = {item["stable_id"]: item for item in enriched}
        for item in items:
            patch = by_id.get(item["stable_id"], {})
            for key in ("summary", "why_it_matters", "btc_impact", "tone", "impact", "importance"):
                if key in patch:
                    item[key] = patch[key]
    except Exception:
        pass
    return items


def main() -> None:
    current = json.loads(FEED_PATH.read_text(encoding="utf-8")) if FEED_PATH.exists() else {"items": []}
    existing = {item["stable_id"]: item for item in current.get("items", [])}
    candidates = []
    for group in cluster(collect()):
        item = fallback_item(group)
        if item["status"] in {"verified", "cross_verified"}:
            candidates.append(item)
    new_items = [item for item in candidates if item["stable_id"] not in existing]
    for item in enrich_with_openai(new_items):
        existing[item["stable_id"]] = item
    output = {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "items": sorted(existing.values(), key=lambda item: item["published_at"], reverse=True)[:MAX_ITEMS],
    }
    before = json.dumps(current, ensure_ascii=False, sort_keys=True)
    after = json.dumps(output, ensure_ascii=False, sort_keys=True)
    if before != after:
        FEED_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

