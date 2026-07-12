const GROUPS_PATH = "config/watchlist_groups.json";
const WATCHLIST_PATH = "config/watchlist.json";
const COMMIT_MESSAGE = "chore: update grouped watchlist from SXT Cloud";
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "Content-Type",
};

function json(statusCode, body) { return { statusCode, headers: JSON_HEADERS, body: JSON.stringify(body) }; }
function githubConfig() {
  const token = process.env.GITHUB_TOKEN, owner = process.env.GITHUB_OWNER, repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || "main";
  const missing = []; if (!token) missing.push("GITHUB_TOKEN"); if (!owner) missing.push("GITHUB_OWNER"); if (!repo) missing.push("GITHUB_REPO");
  return { token, owner, repo, branch, missing };
}
function codesFrom(payload) {
  return [...new Set(payload.groups.flatMap((group) => group.symbols))].sort();
}
function normalizeGroups(value) {
  if (!value || !Array.isArray(value.groups)) throw new Error("groups must be an array");
  const ids = new Set(), names = new Set();
  const groups = value.groups.map((raw) => {
    const id = String(raw.id || "").trim(), name = String(raw.name || "").trim();
    if (!id || !name) throw new Error("group id and name are required");
    if (ids.has(id)) throw new Error(`duplicate group id: ${id}`);
    if (names.has(name)) throw new Error(`duplicate group name: ${name}`);
    ids.add(id); names.add(name);
    if (!Array.isArray(raw.symbols)) throw new Error(`symbols must be an array: ${name}`);
    const symbols = [...new Set(raw.symbols.map((code) => String(code).trim()))].sort();
    const invalid = symbols.find((code) => !/^\d{6}$/.test(code));
    if (invalid) throw new Error(`invalid stock code: ${invalid}`);
    return { id, name, symbols };
  });
  return { version: 1, updated_at: new Date().toISOString(), groups };
}
async function githubRequest(path, options = {}) {
  const { token, owner, repo, branch, missing } = githubConfig();
  if (missing.length) return { ok: false, status: 500, payload: { message: `Missing Netlify environment variables: ${missing.join(", ")}` } };
  const url = `https://api.github.com/repos/${owner}/${repo}/contents/${path}`;
  const response = await fetch(options.method === "PUT" ? url : `${url}?ref=${encodeURIComponent(branch)}`, {
    ...options,
    headers: { accept: "application/vnd.github+json", authorization: `Bearer ${token}`, "content-type": "application/json", "x-github-api-version": "2022-11-28", ...(options.headers || {}) },
  });
  return { ok: response.ok, status: response.status, payload: await response.json().catch(() => ({})), branch };
}
function decodeContent(content) { return JSON.parse(Buffer.from(content || "", "base64").toString("utf8")); }
async function readFile(path) {
  const result = await githubRequest(path); if (!result.ok) throw new Error(result.payload.message || `GitHub API read failed: ${path}`);
  return { ...result, data: decodeContent(result.payload.content) };
}
async function updateFile(path, content, current) {
  return githubRequest(path, { method: "PUT", body: JSON.stringify({ message: COMMIT_MESSAGE, content: Buffer.from(`${JSON.stringify(content, null, 2)}\n`).toString("base64"), sha: current.payload.sha, branch: current.branch }) });
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: JSON_HEADERS, body: "" };
  if (!["GET", "POST"].includes(event.httpMethod)) return json(405, { error: "Method not allowed" });
  try {
    const groupsFile = await readFile(GROUPS_PATH);
    const groups = event.httpMethod === "GET" ? normalizeGroups(groupsFile.data) : normalizeGroups(JSON.parse(event.body || "{}"));
    const watchlist = codesFrom(groups);
    if (event.httpMethod === "GET") return json(200, { ...groups, watchlist, branch: groupsFile.branch });
    const legacyFile = await readFile(WATCHLIST_PATH);
    const updateGroups = await updateFile(GROUPS_PATH, groups, groupsFile);
    if (!updateGroups.ok) return json(updateGroups.status, { error: updateGroups.payload.message || "Grouped watchlist update failed" });
    const oldLegacy = legacyFile.data && !Array.isArray(legacyFile.data) ? legacyFile.data : {};
    const updateLegacy = await updateFile(WATCHLIST_PATH, { ...oldLegacy, watchlist }, legacyFile);
    if (!updateLegacy.ok) return json(502, { error: "分组已保存，但兼容 watchlist.json 同步失败，请刷新后重试。", details: updateLegacy.payload });
    return json(200, { ok: true, message: "股票池已更新，下一次扫描将使用新列表", ...groups, watchlist });
  } catch (error) { return json(400, { error: error.message || "Invalid request" }); }
};
