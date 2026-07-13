async function showMediaDetail(payloadId) {
  const payload = state.mediaPayloads.get(payloadId);
  if (!payload) return;
  let detail = {};
  try {
    detail = await api(`/api/tmdb/${payload.media_type}/${payload.tmdb_id}`);
  } catch {
    detail = payload;
  }
  const title = detail.name || detail.title || payload.title;
  const releaseYear = Number.parseInt((detail.first_air_date || detail.release_date || "").slice(0, 4), 10) || payload.release_year || null;
  payload.release_year = releaseYear;
  if (payload.media_type === "tv") {
    payload.tmdb_total_count = detail.number_of_episodes || payload.tmdb_total_count || 0;
  }
  const seasons = payload.media_type === "tv" && detail.number_of_episodes ? `<span>${detail.number_of_episodes} 集</span>` : "";
  const runtime = payload.media_type === "movie" && detail.runtime ? `<span>${detail.runtime} 分钟</span>` : "";
  document.body.insertAdjacentHTML("beforeend", `
    <div class="modal-backdrop" id="mediaModal">
      <section class="detail-panel">
        <button class="detail-close" id="detailClose">×</button>
        <div class="detail-hero" style="background-image: linear-gradient(90deg, rgba(16,47,49,.92), rgba(16,47,49,.52)), url('${backdropUrl(detail)}')">
          <img src="${posterUrl(detail)}" alt="${title}" />
          <div>
            <h2>${title}</h2>
            <div class="detail-facts">
              <span>${payload.media_type === "tv" ? "电视剧" : "电影"}</span>
              <span>${(detail.first_air_date || detail.release_date || "").slice(0, 4) || "未知年份"}</span>
              ${seasons}${runtime}
            </div>
            <p>${detail.overview || payload.overview || "暂无简介"}</p>
            <button id="detailSubscribe">订阅</button>
          </div>
        </div>
      </section>
    </div>
  `);
  $("#detailClose").addEventListener("click", () => $("#mediaModal").remove());
  $("#mediaModal").addEventListener("click", (event) => {
    if (event.target.id === "mediaModal") $("#mediaModal").remove();
  });
  $("#detailSubscribe").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (button.dataset.loading === "true") return;
    button.dataset.loading = "true";
    button.disabled = true;
    button.textContent = "添加中";
    try {
      await subscribeMedia(payload);
      button.textContent = "已订阅";
      $("#mediaModal").remove();
    } catch (error) {
      button.disabled = false;
      button.textContent = "订阅";
      toast(`订阅失败：${error.message}`);
    } finally {
      delete button.dataset.loading;
    }
  });
}
