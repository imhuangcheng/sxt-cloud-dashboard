const WATCHLIST_PATH = "config/watchlist.json";
const COMMIT_MESSAGE = "chore: update watchlist from SXT Cloud";

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

function normalizeWatchlist(value) {
  if (!Array.isArray(value)) {
    throw new Error("watchlist must be an array");
  }

  const codes = [...new Set(value.map((code) => String(code).trim()))]
    .filter(Boolean)
    .sort();

  const invalid = codes.find((code) => !/^\d{6}$/.test(code));
  if (invalid) {
    throw new Error(`invalid stock code: ${invalid}`);
  }
  if (codes.length === 0) {
    throw new Error("watchlist cannot be empty");
  }
  return codes;
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
  return { ok: response.ok, status: response.status, payload, owner, repo, branch, token, url };
}

function decodeContent(content) {
  return JSON.parse(Buffer.from(content || "", "base64").toString("utf8"));
}

exports.handler = async (event) => {
  if (!["GET", "POST"].includes(event.httpMethod)) {
    return json(405, { error: "Method not allowed" });
  }

  try {
    let nextCodes = null;
    if (event.httpMethod === "POST") {
      const body = event.body ? JSON.parse(event.body) : {};
      nextCodes = normalizeWatchlist(body.watchlist);
    }

    const current = await githubRequest(WATCHLIST_PATH);
    if (!current.ok) {
      const message = current.payload.message || "GitHub API read failed";
      return json(current.status, { error: message, details: current.payload });
    }

    const filePayload = decodeContent(current.payload.content);
    const currentCodes = normalizeWatchlist(filePayload.watchlist || filePayload);

    if (event.httpMethod === "GET") {
      return json(200, { watchlist: currentCodes, branch: current.branch });
    }

    const nextContent = `${JSON.stringify({ watchlist: nextCodes }, null, 2)}\n`;

    const update = await githubRequest(WATCHLIST_PATH, {
      method: "PUT",
      body: JSON.stringify({
        message: COMMIT_MESSAGE,
        content: Buffer.from(nextContent, "utf8").toString("base64"),
        sha: current.payload.sha,
        branch: current.branch,
      }),
    });

    if (!update.ok) {
      const message = update.payload.message || "GitHub API update failed";
      return json(update.status, { error: message, details: update.payload });
    }

    return json(200, {
      ok: true,
      message: "保存成功，云端监控将在下一次扫描时自动读取新股票池",
      watchlist: nextCodes,
      commit: update.payload.commit && update.payload.commit.sha,
    });
  } catch (error) {
    return json(400, { error: error.message || "Invalid request" });
  }
};
