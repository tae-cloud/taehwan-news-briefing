(() => {
  const esc = (value = "") => String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  const safeUrl = (value = "") => {
    try {
      const url = new URL(value, location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
    } catch { return "#"; }
  };
  const flattenSources = (sources) => Array.isArray(sources)
    ? sources
    : Object.values(sources || {}).flat();
  const sourceLinks = (sources) => flattenSources(sources)
    .map(s => `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a>`)
    .join(" · ");
  const section = (title, body, extra = "") => body ? `
    <section class="block ${extra}"><h3>${esc(title)}</h3><div class="verbatim">${body}</div></section>` : "";
  const list = (items = []) => items.length
    ? `<ul>${items.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : "";
  const qualityScore = article => {
    const text = article.querySelector(".article")?.innerText || "";
    const sections = article.querySelectorAll(".block").length;
    const sources = article.querySelectorAll(".verbatim a").length;
    return text.length + (sections * 180) + (sources * 80);
  };

  const renderStory = (item) => {
    const article = document.createElement("article");
    const impact = typeof item.btc_impact === "object"
      ? item.btc_impact
      : { direction: item.impact || "양방향", assessment: item.btc_impact || "" };
    const tone = ["up", "down", "warn"].includes(item.tone) ? item.tone : "warn";
    const verification = item.verification || {};
    const separation = verification.trump_separation || {};
    const stars = Math.max(1, Math.min(5, Number(item.importance) || 3));
    article.className = `story ${tone} live-story`;
    article.dataset.tone = tone;
    article.dataset.newsId = item.stable_id || "";
    article.dataset.published = item.source_time || item.published_at || "";
    article.id = `live-${item.stable_id || Math.random().toString(36).slice(2)}`;
    article.innerHTML = `
      <section class="article">
        <div class="page">실시간 업데이트 · ${esc(item.kst || item.published_at_kst || item.published_at)}</div>
        <h2>${esc(item.title)}</h2>
        <div class="metadata">
          <b>중요도: ${"★".repeat(stars)}${"☆".repeat(5 - stars)} · BTC ${esc(impact.direction)}</b>
          <span>원문 시각: ${esc(item.source_time || item.published_at || "확인 중")}</span>
          <span class="importance">${esc(verification.state || item.status || "verified")}</span>
        </div>
        ${section("핵심 내용", esc(item.summary))}
        ${section("왜 중요한가", esc(item.why_it_matters))}
        ${section("BTC 영향", esc(impact.assessment))}
        ${section("시장이 놓치고 있는 포인트", esc(item.missed_point))}
        ${section("추가 확인", list(item.follow_up))}
        ${separation.statement ? section("발언·정책·시장 해석", `
          <p><b>발언</b><br>${esc(separation.statement)}</p>
          <p><b>정책 행동</b><br>${esc(separation.policy_action)}</p>
          <p><b>시장 해석</b><br>${esc(separation.market_interpretation)}</p>`) : ""}
        ${section("검증 메모", esc(verification.notes))}
        ${section("출처", sourceLinks(item.sources))}
      </section>
      <aside class="side">
        <div><div class="eyebrow">LIVE VERIFIED</div><div class="motif">${esc(impact.direction)}</div>
        <div class="track"><i></i><i></i><i></i><span>사건</span><span>시장 변수</span><span>BTC 영향</span></div></div>
        <div class="sidecopy">${esc(verification.independent_sources || flattenSources(item.sources).length)}개 이상 출처와 후속 맥락을 교차 확인한 분석입니다.</div>
      </aside>`;
    return article;
  };

  const applySearch = () => {
    const query = document.getElementById("news-search")?.value.trim().toLowerCase() || "";
    document.querySelectorAll(".story").forEach(story => {
      story.classList.toggle("search-hidden", Boolean(query) && !story.textContent.toLowerCase().includes(query));
    });
  };
  const timestamp = story => {
    const parsed = Date.parse(story.dataset.published || "");
    if (Number.isFinite(parsed)) return parsed;
    const text = `${story.querySelector(".page")?.textContent || ""} ${story.querySelector(".metadata")?.textContent || ""}`;
    const datedTime = text.match(/(20\d{2})[.-](\d{2})[.-](\d{2})(?:\s*(?:약\s*)?(\d{2}):(\d{2}))?/);
    if (!datedTime) return 0;
    const hour = datedTime[4] == null ? 0 : Number(datedTime[4]);
    const minute = datedTime[5] == null ? 0 : Number(datedTime[5]);
    return Date.UTC(
      Number(datedTime[1]),
      Number(datedTime[2]) - 1,
      Number(datedTime[3]),
      hour - 9,
      minute
    );
  };
  const timelineTime = story => {
    const text = `${story.querySelector(".page")?.textContent || ""} ${story.querySelector(".metadata")?.textContent || ""}`;
    const match = text.match(/(20\d{2})[.-](\d{2})[.-](\d{2})(?:\s*(?:약\s*)?(\d{2}):(\d{2}))?/);
    if (!match) return "시간 확인 중";
    const date = `${match[2]}.${match[3]}`;
    return match[4] == null ? `${date} · 시간 미표기` : `${date} ${match[4]}:${match[5]} KST`;
  };
  const sortAndTimeline = () => {
    const main = document.querySelector("main");
    const empty = main?.querySelector(".empty");
    if (!main || !empty) return;
    const stories = [...main.querySelectorAll(":scope > .story")]
      .sort((a, b) => timestamp(b) - timestamp(a));
    stories.forEach(story => main.insertBefore(story, empty));
    const timeline = document.querySelector(".jump");
    if (!timeline) return;
    timeline.replaceChildren(...stories.map((story, index) => {
      if (!story.id) story.id = `news-${index + 1}`;
      const link = document.createElement("a");
      const title = story.querySelector("h2")?.textContent?.trim() || `뉴스 ${index + 1}`;
      link.href = `#${story.id}`;
      link.textContent = `${timelineTime(story)} · ${title.length > 28 ? `${title.slice(0, 28)}…` : title}`;
      return link;
    }));
  };

  document.querySelector(".hero .notice")?.remove();
  document.querySelectorAll(".page").forEach(label => {
    if (/페이지|ORIGINAL TEXT/i.test(label.textContent || "")) label.remove();
  });
  fetch(`/live-news.json?t=${Date.now()}`, { cache: "no-store" })
    .then(response => {
      if (!response.ok) throw new Error("feed unavailable");
      return response.json();
    })
    .then(feed => {
      const main = document.querySelector("main");
      if (!main || !Array.isArray(feed.items)) return;
      document.querySelectorAll(".live-story").forEach(node => node.remove());
      const empty = main.querySelector(".empty");
      const existingStories = new Map([...main.querySelectorAll(".story[data-news-id]")]
        .map(story => [story.dataset.newsId, story]).filter(([id]) => Boolean(id)));
      feed.items.forEach(item => {
        const rendered = renderStory(item);
        const previous = existingStories.get(item.stable_id);
        if (previous && qualityScore(rendered) >= qualityScore(previous)) previous.replaceWith(rendered);
        else if (!previous) main.insertBefore(rendered, empty);
      });
      sortAndTimeline();
      applySearch();
      document.getElementById("news-search")?.addEventListener("input", applySearch);
    }).catch(() => {});
})();
