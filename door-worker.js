// 门缝：所有人共用的一个投递口
//
//   GET  /door              → 最近一条留话 {"line":"...","ts":123}
//   GET  /door?list=N       → 最近 N 条 {"items":[{"line","ts"},...],"count":总数}
//   POST /door {"line":"..."} → 塞进去一条
//
// 每条留话存一个独立 key（door:i:<补零时间戳>:<随机后缀>），
// 同时维护 door:latest 快速取最近一张。KV list 按字典序升序，
// 取末尾 N 个再倒序 = 最新 N 条。
// 部署后在 Worker 设置里绑定 KV namespace，变量名必须是 DOOR。

const LATEST = "door:latest";
const ITEM_PREFIX = "door:i:";

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (req.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }

    const url = new URL(req.url);
    if (url.pathname !== "/door") {
      return new Response("not found", { status: 404, headers: cors });
    }

    if (req.method === "GET") {
      const listN = parseInt(url.searchParams.get("list") || "", 10);
      if (listN > 0) {
        return json(await listRecent(env, listN), cors);
      }
      const v = await env.DOOR.get(LATEST, "json");
      if (!v || !v.line) return json({ line: null, ts: null }, cors);
      return json({ line: v.line, ts: v.ts || null }, cors);
    }

    if (req.method === "POST") {
      let body;
      try {
        body = await req.json();
      } catch {
        return json({ ok: false, error: "bad json" }, cors, 400);
      }
      const line = String(body.line || "")
        .replace(/[\r\n\t]/g, " ")
        .trim()
        .slice(0, 40);
      if (!line) return json({ ok: false, error: "empty" }, cors, 400);

      const ts = Date.now();
      const key = `${ITEM_PREFIX}${String(ts).padStart(16, "0")}:${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      await env.DOOR.put(key, JSON.stringify({ line, ts }));
      await env.DOOR.put(LATEST, JSON.stringify({ line, ts }));
      return json({ ok: true, ts }, cors);
    }

    return new Response("method not allowed", { status: 405, headers: cors });
  },
};

// 取最近 N 条（按时间倒序）+ 总条数
async function listRecent(env, n) {
  const list = await env.DOOR.list({ prefix: ITEM_PREFIX, limit: 1000 });
  const keys = list.keys.map((k) => k.name).sort(); // 字典序 = 时间正序
  const total = keys.length;
  const want = Math.min(n, total);
  const recentKeys = keys.slice(total - want).reverse(); // 最新在前
  const items = [];
  for (const k of recentKeys) {
    const v = await env.DOOR.get(k, "json");
    if (v && v.line) items.push({ line: v.line, ts: v.ts || null });
  }
  return { items, count: total };
}

function json(obj, cors, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
  });
}
