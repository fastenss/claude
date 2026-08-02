/* ===== Twitter / X home layout — data + interactivity ===== */
(function () {
  "use strict";

  /* ---------- Helpers ---------- */
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const el = (tag, cls) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  };

  // Colored initial avatar as an inline SVG data URI
  const AVATAR_COLORS = ["#1d9bf0", "#f91880", "#00ba7c", "#ffd400", "#7856ff", "#ff7a00"];
  function avatar(name) {
    const initial = (name || "?").trim().charAt(0).toUpperCase();
    const color = AVATAR_COLORS[initial.charCodeAt(0) % AVATAR_COLORS.length];
    const svg =
      `<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>` +
      `<rect width='40' height='40' rx='20' fill='${color}'/>` +
      `<text x='50%' y='55%' font-size='18' fill='white' text-anchor='middle' ` +
      `dominant-baseline='middle' font-family='sans-serif'>${initial}</text></svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  }

  // Abbreviate counts: 1200 -> 1.2K, 3400000 -> 3.4M
  function abbr(n) {
    if (n < 1000) return String(n);
    if (n < 1e6) return (n / 1e3).toFixed(n % 1e3 >= 100 ? 1 : 0).replace(/\.0$/, "") + "K";
    return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  }

  // Escape user text, then linkify @mentions and #hashtags
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }
  function linkify(text) {
    // Escape first, then linkify only #tags / @mentions that follow whitespace
    // or start of string — this avoids matching the digits inside HTML entities
    // such as &#39; (which would otherwise become a bogus "#39" link).
    return escapeHtml(text).replace(
      /(^|\s)([#@]\w+)/g,
      '$1<a href="#">$2</a>'
    );
  }

  /* ---------- Seed data ---------- */
  const now = Date.now();
  const m = (min) => now - min * 60 * 1000;

  let tweets = [
    {
      id: 1, name: "The Verge", handle: "verge", verified: true, time: m(12),
      text: "Breaking: the new open-source browser engine ships today. Faster page loads, better battery life, and a privacy mode that's on by default. 🚀\n\nEarly benchmarks look wild.",
      replies: 342, retweets: 1280, likes: 8400, views: 210000, liked: false, retweeted: false,
    },
    {
      id: 2, name: "Sara Dev", handle: "saradev", verified: false, time: m(38),
      text: "Hot take: your CSS grid is the layout. Stop reaching for a framework for a 3-column page. #webdev #css",
      replies: 88, retweets: 210, likes: 2100, views: 45000, liked: true, retweeted: false,
    },
    {
      id: 3, name: "NASA", handle: "NASA", verified: true, time: m(95),
      text: "We just received new images from the outer solar system. The detail is unlike anything we've seen before. More data incoming this week. 🪐✨",
      replies: 1200, retweets: 15000, likes: 92000, views: 3400000, liked: false, retweeted: true,
    },
    {
      id: 4, name: "Indie Hacker", handle: "buildinpublic", verified: false, time: m(140),
      text: "Day 214 of building in public.\n\nMRR: $4,120 (+8% this week)\nUsers: 1,930\nBiggest lesson: ship the boring feature people actually asked for. 📈",
      replies: 45, retweets: 96, likes: 1400, views: 61000, liked: false, retweeted: false,
    },
    {
      id: 5, name: "Chef Mateo", handle: "chefmateo", verified: false, time: m(220),
      text: "The secret to a good weeknight pasta is salting the water like the sea and finishing the noodles IN the sauce. That's the whole tweet. 🍝",
      replies: 210, retweets: 640, likes: 12000, views: 320000, liked: true, retweeted: false,
    },
  ];

  const trends = [
    { category: "Technology · Trending", title: "#WebDev", count: 84200 },
    { category: "Trending in United States", title: "JavaScript", count: 125000 },
    { category: "Science · Trending", title: "Outer Solar System", count: 19800 },
    { category: "Sports · Trending", title: "#MatchDay", count: 231000 },
    { category: "Only on X · Trending", title: "Building in Public", count: 12400 },
  ];

  const follows = [
    { name: "Open Source", handle: "opensource", verified: true },
    { name: "Design Weekly", handle: "designweekly", verified: false },
    { name: "Astro Nomy", handle: "astronomy", verified: true },
  ];

  const ME = { name: "James", handle: "james_v" };

  /* ---------- Render: tweets ---------- */
  const feed = $("#feed");

  function tweetNode(t) {
    const node = el("article", "tweet");
    node.dataset.id = t.id;
    node.innerHTML = `
      <img class="avatar" src="${avatar(t.name)}" alt="${escapeHtml(t.name)}" />
      <div class="tweet__body">
        <div class="tweet__head">
          <span class="tweet__name">${escapeHtml(t.name)}</span>
          ${t.verified ? '<span class="tweet__verified" title="Verified">✔️</span>' : ""}
          <span class="tweet__handle">@${escapeHtml(t.handle)}</span>
          <span class="tweet__dot">·</span>
          <span class="tweet__time">${relTime(t.time)}</span>
          <span class="tweet__more">⋯</span>
        </div>
        <div class="tweet__text">${linkify(t.text)}</div>
        <div class="tweet__actions">
          <button class="action action--reply" data-act="reply">
            <span class="action__icon">💬</span><span class="action__count">${abbr(t.replies)}</span>
          </button>
          <button class="action action--rt ${t.retweeted ? "active" : ""}" data-act="rt">
            <span class="action__icon">🔁</span><span class="action__count">${abbr(t.retweets)}</span>
          </button>
          <button class="action action--like ${t.liked ? "active" : ""}" data-act="like">
            <span class="action__icon">${t.liked ? "❤️" : "🤍"}</span><span class="action__count">${abbr(t.likes)}</span>
          </button>
          <button class="action action--view" data-act="view">
            <span class="action__icon">📊</span><span class="action__count">${abbr(t.views)}</span>
          </button>
          <button class="action action--share" data-act="share">
            <span class="action__icon">🔗</span>
          </button>
        </div>
      </div>`;
    return node;
  }

  function renderFeed() {
    feed.innerHTML = "";
    const frag = document.createDocumentFragment();
    tweets.forEach((t) => frag.appendChild(tweetNode(t)));
    feed.appendChild(frag);
  }

  // Relative time formatting (Twitter-style): 12s, 5m, 3h, then date
  function relTime(ts) {
    const diff = Math.max(0, Date.now() - ts);
    const s = Math.floor(diff / 1000);
    if (s < 60) return s + "s";
    const min = Math.floor(s / 60);
    if (min < 60) return min + "m";
    const h = Math.floor(min / 60);
    if (h < 24) return h + "h";
    const d = new Date(ts);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  /* ---------- Tweet interactions (event delegation) ---------- */
  feed.addEventListener("click", (e) => {
    const btn = e.target.closest(".action");
    if (!btn) return;
    e.stopPropagation();
    const article = e.target.closest(".tweet");
    const t = tweets.find((x) => x.id === Number(article.dataset.id));
    if (!t) return;

    const act = btn.dataset.act;
    if (act === "like") {
      t.liked = !t.liked;
      t.likes += t.liked ? 1 : -1;
      btn.classList.toggle("active", t.liked);
      $(".action__icon", btn).textContent = t.liked ? "❤️" : "🤍";
      $(".action__count", btn).textContent = abbr(t.likes);
    } else if (act === "rt") {
      t.retweeted = !t.retweeted;
      t.retweets += t.retweeted ? 1 : -1;
      btn.classList.toggle("active", t.retweeted);
      $(".action__count", btn).textContent = abbr(t.retweets);
    } else if (act === "reply") {
      t.replies += 1;
      $(".action__count", btn).textContent = abbr(t.replies);
    } else if (act === "share") {
      const dummy = `https://x.com/${t.handle}/status/${t.id}`;
      if (navigator.clipboard) navigator.clipboard.writeText(dummy).catch(() => {});
      flash(btn, "Copied!");
    }
  });

  function flash(target, msg) {
    const tip = el("span");
    tip.textContent = msg;
    tip.style.cssText =
      "position:absolute;background:var(--accent);color:#fff;font-size:12px;" +
      "padding:2px 8px;border-radius:6px;transform:translate(-50%,-28px);white-space:nowrap;";
    target.style.position = "relative";
    target.appendChild(tip);
    setTimeout(() => tip.remove(), 1000);
  }

  /* ---------- Compose ---------- */
  const input = $("#compose-input");
  const count = $("#compose-count");
  const postBtn = $("#compose-post");
  const LIMIT = 280;

  function syncCompose() {
    // auto-grow textarea
    input.style.height = "auto";
    input.style.height = input.scrollHeight + "px";

    const remaining = LIMIT - input.value.length;
    count.textContent = remaining;
    count.classList.toggle("compose__count--warn", remaining <= 20 && remaining >= 0);
    count.classList.toggle("compose__count--over", remaining < 0);

    const trimmed = input.value.trim();
    postBtn.disabled = trimmed.length === 0 || remaining < 0;
  }

  function publish() {
    const text = input.value.trim();
    if (!text || text.length > LIMIT) return;
    tweets.unshift({
      id: Date.now(),
      name: ME.name, handle: ME.handle, verified: false, time: Date.now(),
      text, replies: 0, retweets: 0, likes: 0, views: 1, liked: false, retweeted: false,
    });
    renderFeed();
    input.value = "";
    syncCompose();
    feed.firstElementChild.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  input.addEventListener("input", syncCompose);
  input.addEventListener("keydown", (e) => {
    // Cmd/Ctrl + Enter to post
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") publish();
  });
  postBtn.addEventListener("click", publish);
  $("#sidebar-post").addEventListener("click", () => input.focus());

  /* ---------- Tabs ---------- */
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("tab--active"));
      tab.classList.add("tab--active");
    });
  });

  /* ---------- Trends ---------- */
  const trendsBox = $("#trends");
  trends.forEach((tr) => {
    const node = el("div", "trend");
    node.innerHTML = `
      <div class="trend__meta"><span>${escapeHtml(tr.category)}</span><span>⋯</span></div>
      <div class="trend__title">${escapeHtml(tr.title)}</div>
      <div class="trend__count">${abbr(tr.count)} posts</div>`;
    trendsBox.appendChild(node);
  });

  /* ---------- Who to follow ---------- */
  const followsBox = $("#follows");
  follows.forEach((f) => {
    const node = el("div", "follow");
    node.innerHTML = `
      <img class="avatar" src="${avatar(f.name)}" alt="${escapeHtml(f.name)}" />
      <div class="follow__meta">
        <div class="follow__name">${escapeHtml(f.name)} ${f.verified ? '<span class="tweet__verified">✔️</span>' : ""}</div>
        <div class="follow__handle">@${escapeHtml(f.handle)}</div>
      </div>
      <button class="follow__btn">Follow</button>`;
    const btn = $(".follow__btn", node);
    btn.addEventListener("click", () => {
      const following = btn.classList.toggle("following");
      btn.textContent = following ? "Following" : "Follow";
    });
    followsBox.appendChild(node);
  });

  /* ---------- Init ---------- */
  renderFeed();
  syncCompose();

  // Keep relative timestamps fresh
  setInterval(() => {
    document.querySelectorAll(".tweet").forEach((node) => {
      const t = tweets.find((x) => x.id === Number(node.dataset.id));
      if (t) $(".tweet__time", node).textContent = relTime(t.time);
    });
  }, 30000);
})();
