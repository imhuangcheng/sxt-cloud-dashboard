const WORKFLOW_ID = "monitor.yml";
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, OPTIONS",
  "access-control-allow-headers": "Content-Type",
};

function json(statusCode, body) {
  return {
    statusCode,
    headers: JSON_HEADERS,
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

  const url = `https://api.github.com/repos/${owner}/${repo}${path}`;
  const response = await fetch(url, {
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

async function dispatchMonitorWorkflow() {
  const { branch } = githubConfig();
  return githubRequest(`/actions/workflows/${WORKFLOW_ID}/dispatches`, {
    method: "POST",
    body: JSON.stringify({
      ref: branch,
      inputs: { force_scan: "true" },
    }),
  });
}

async function triggerByRefreshCommit() {
  const { branch } = githubConfig();
  const current = await githubRequest(`/contents/config/refresh.json?ref=${encodeURIComponent(branch)}`);
  if (!current.ok) return current;
  const currentContent = String(current.payload.content || "").replace(/\s/g, "");
  let payload;
  try {
    payload = JSON.parse(Buffer.from(currentContent, "base64").toString("utf8"));
  } catch (error) {
    return { ok: false, status: 500, payload: { message: `无法解析 config/refresh.json：${error.message}` }, branch };
  }
  payload.requested_at = new Date().toISOString();
  payload.force_scan = true;
  payload.reason = "Dashboard requested scan";
  return githubRequest("/contents/config/refresh.json", {
    method: "PUT",
    body: JSON.stringify({
      message: "chore: trigger cloud monitor scan",
      content: Buffer.from(`${JSON.stringify(payload, null, 2)}\n`, "utf8").toString("base64"),
      sha: current.payload.sha,
      branch,
    }),
  });
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers: JSON_HEADERS, body: "" };
  }

  if (event.httpMethod !== "POST") {
    return json(405, { error: "Method not allowed" });
  }

  const { missing } = githubConfig();
  if (missing.length > 0) {
    return json(500, { error: `Missing Netlify environment variables: ${missing.join(", ")}` });
  }

  try {
    const response = await dispatchMonitorWorkflow();
    if (!response.ok) {
      const fallback = await triggerByRefreshCommit();
      if (fallback.ok) {
        return json(202, {
          ok: true,
          mode: "github_contents_push",
          message: "已通过 GitHub 配置提交触发云端强制扫描，完成后会更新数据。",
        });
      }
      if (response.status === 401 || response.status === 403) {
        const detail = response.payload.message ? `（GitHub：${response.payload.message}）` : "";
        const fallbackDetail = fallback.payload?.message ? `；回退提交也失败：${fallback.payload.message}` : "";
        throw new Error(`Netlify 的 GITHUB_TOKEN 无法触发 GitHub Actions，请检查仓库权限${detail}${fallbackDetail}`);
      }
      throw new Error(response.payload.message || response.payload.error || `GitHub API ${response.status}`);
    }

    return json(202, {
      ok: true,
      mode: "github_actions",
      message: "已触发云端强制扫描，GitHub Actions 完成后会更新数据。",
    });
  } catch (error) {
    return json(400, { error: error.message || "Invalid request" });
  }
};
