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
      if (response.status === 401 || response.status === 403) {
        const detail = response.payload.message ? `（GitHub：${response.payload.message}）` : "";
        throw new Error(`Netlify 的 GITHUB_TOKEN 无法触发 GitHub Actions，请检查生产环境变量和 Actions: Read and write 权限${detail}`);
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
