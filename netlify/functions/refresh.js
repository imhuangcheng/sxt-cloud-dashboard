const WATCHLIST_PATH = "config/watchlist.json";
const SXT_API = "https://sxt-dual-period-dashboard.netlify.app/.netlify/functions/sxt";
const EASTMONEY_QUOTE_API = "https://push2.eastmoney.com/api/qt/stock/get";

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
    body: JSON.stringify(body),
  };
}

function githubConfig() {
  const token = process.env.GITHUB_TOKEN;
  const owner = process.env.GITHUB_OWNER;
  const repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || "main";
  const missing = [];
  if (!token) missing.push("GITHUB_TOKEN");
  if (!owner) missing.push("GITHUB_OWNER");
  if (!repo) missing.push("GITHUB_REPO");
  return { token, owner, repo, branch, missing };
}

async function githubRequest(path, options = {}) {
  const { token, owner, repo, branch, missing } = githubConfig();
  if (missing.length > 0) {
    return {
      ok: false,
      status: 500,
      payload: { error: `Missing Netlify environment variables: ${missing.join(", ")}` },
    };
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/contents/${path}`;
  const requestUrl = options.method === "PUT" ? url : `${url}?ref=${encodeURIComponent(branch)}`;
  const response = await fetch(requestUrl, {
    ...options,
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      "x-github-api-version": "2022-11-28",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, payload, branch };
}

function decodeJsonContent(content) {
  return JSON.parse(Buffer.from(content || "", "base64").toString("utf8"));
}

function normalizeWatchlist(payload) {
  const values = Array.isArray(payload?.watchlist) ? payload.watchlist : payload;
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map((item) => {
    if (typeof item === "string") return item.trim();
    return String(item?.code || item?.symbol || item?.stock_code || "").trim();
  }).filter((code) => /^\d{6}$/.test(code)))].sort();
}

function statusFor(dailySxt, minute15Sxt) {
  if (dailySxt === null || dailySxt === undefined || minute15Sxt === null || minute15Sxt === undefined) return "NO_DATA";
  return Number(dailySxt) === 2 && Number(minute15Sxt) === 2 ? "ALERT" : "WATCH";
}

function secidForCode(code) {
  return /^(6|9)/.test(code) ? `1.${code}` : `0.${code}`;
}

async function loadWatchlist() {
  const response = await githubRequest(WATCHLIST_PATH);
  if (!response.ok) {
    throw new Error(response.payload.error || response.payload.message || "watchlist read failed");
  }
  return normalizeWatchlist(decodeJsonContent(response.payload.content));
}

async function fetchStockName(code) {
  try {
    const url = new URL(EASTMONEY_QUOTE_API);
    url.searchParams.set("secid", secidForCode(code));
    url.searchParams.set("fields", "f58");
    const response = await fetch(url, {
      cache: "no-store",
      headers: {
        "user-agent": "Mozilla/5.0",
        "referer": "https://quote.eastmoney.com/",
      },
    });
    const payload = await response.json().catch(() => ({}));
    const name = String(payload?.data?.f58 || "").trim();
    return name === "-" ? "" : name;
  } catch {
    return "";
  }
}

async function querySxt(code) {
  const url = `${SXT_API}?code=${encodeURIComponent(code)}`;
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  const dailySxt = payload.daily_sxt ?? null;
  const minute15Sxt = payload.m15_sxt ?? payload.minute15_sxt ?? null;
  const name = payload.name || await fetchStockName(code);
  return {
    code,
    name,
    market: /^(6|9)/.test(code) ? "sh" : "sz",
    daily_sxt: dailySxt,
    minute15_sxt: minute15Sxt,
    status: statusFor(dailySxt, minute15Sxt),
    last_daily_time: payload.daily_last_bar || "",
    last_15m_time: payload.m15_last_bar || "",
    error: [payload.daily_error, payload.m15_error].filter(Boolean).join("; "),
    daily_signal: payload.daily_status || "",
    minute15_signal: payload.m15_status || "",
  };
}

async function scanWatchlist() {
  const watchlist = await loadWatchlist();
  const results = await Promise.allSettled(watchlist.map((code) => querySxt(code)));
  return Promise.all(watchlist.map(async (code, index) => {
    const result = results[index];
    if (result.status === "fulfilled") return result.value;
    const name = await fetchStockName(code);
    return {
      code,
      name,
      market: /^(6|9)/.test(code) ? "sh" : "sz",
      daily_sxt: null,
      minute15_sxt: null,
      status: "ERROR",
      last_daily_time: "",
      last_15m_time: "",
      error: result.reason?.message || "查询失败",
      daily_signal: "",
      minute15_signal: "",
    };
  }));
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return json(405, { error: "Method not allowed" });
  }

  const { missing } = githubConfig();
  if (missing.length > 0) {
    return json(500, { error: `Missing Netlify environment variables: ${missing.join(", ")}` });
  }

  try {
    const now = new Date();
    const updatedAt = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(now).replaceAll("/", "-");
    const items = await scanWatchlist();

    return json(202, {
      ok: true,
      mode: "live",
      message: "实时刷新完成。",
      updated_at: updatedAt,
      items,
    });
  } catch (error) {
    return json(400, { error: error.message || "Invalid request" });
  }
};
