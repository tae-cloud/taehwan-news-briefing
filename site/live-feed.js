(() => {
  const escapeHtml = (value = "") =>
    String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);

  const safeUrl = (value = "") => {
    try {
      const url = new URL(value, location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
    } catch {
      return "#";
    }
  };

  const renderSources = (sources = []) => sources
    .map((source) => `<a href="${escapeHtml(safeUrl(source.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.name)} ↗</a>`)
    .join(" · ");

  const renderStory = (item) => {
    const article = document.createElement("article");
    const tone = ["up", "down", "warn"].includes(item.tone) ? item.tone : "warn";
    article.className = `story ${tone} live-story`;
    article.dataset.tone = tone;
    article.dataset.newsId = item.stable_id || "";
    article.dataset.published = item.published_at || "";
    article.innerHTML = `
      <section class="article">
        <div class="page">실시간 업데이트 · ${escapeHtml(item.kst || item.published_at)}</div>
        <h2>${escapeHtml(item.title)}</h2>
        <div class="metadata">
          <b>중요도: ${"★".repeat(Math.max(1, Math.min(5, item.importance || 3)))}${"☆".repeat(Math.max(0, 5 - (item.importance || 3)))} · BTC ${escapeHtml(item.impact || "검증 중")}</b>
          <span>원문 시각: ${escapeHtml(item.published_at || "확인 중")}</span>
          <span class="importance">${escapeHtml(item.status || "verified")}</span>
        </div>
        <section class="block"><h3>핵심 내용</h3><div class="verbatim">${escapeHtml(item.summary || "")}</div></section>
        <section class="block"><h3>왜 중요한가</h3><div class="verbatim">${escapeHtml(item.why_it_matters || "")}</div></section>
        <section class="block"><h3>BTC 영향</h3><div class="verbatim">${escapeHtml(item.btc_impact || "")}</div></section>
        <section class="block"><h3>출처</h3><div class="verbatim">${renderSources(item.sources)}</div></section>
      </section>
      <aside class="side">
        <div><div class="eyebrow">LIVE VERIFIED</div><div class="motif">${escapeHtml(item.impact || "검증")}</div>
        <div class="track"><i></i><i></i><i></i><span>사건</span><span>시장 변수</span><span>BTC 영향</span></div></div>
        <div class="sidecopy">여러 출처를 교차 확인한 뒤 게시된 실시간 업데이트입니다.</div>
      </aside>`;
    return article;
  };

  const applySearch = () => {
    const query = document.getElementById("news-search")?.value.trim().toLowerCase() || "";
    document.querySelectorAll(".story").forEach((story) => {
      story.classList.toggle("search-hidden", Boolean(query) && !story.textContent.toLowerCase().includes(query));
    });
  };

  fetch(`/live-news.json?t=${Date.now()}`, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("feed unavailable");
      return response.json();
    })
    .then((feed) => {
      const main = document.querySelector("main");
      if (!main || !Array.isArray(feed.items)) return;
      document.querySelectorAll(".live-story").forEach((node) => node.remove());
      const empty = main.querySelector(".empty");
      [...feed.items]
        .sort((a, b) => new Date(b.published_at) - new Date(a.published_at))
        .reverse()
        .forEach((item) => main.insertBefore(renderStory(item), main.firstElementChild || empty));
      applySearch();
      document.getElementById("news-search")?.addEventListener("input", applySearch);
    })
    .catch(() => {});
})();

