// 门缝：所有人共用的一个投递口
//
//   GET  /door              → 最近一条留话 {"line":"...","ts":123}
//   POST /door {"line":"..."} → 塞进去一条
//
// 只存一个键 door:latest：门缝只读最近一张，不需要历史。
// 部署后在 Worker 设置里绑定 KV namespace，变量名必须是 DOOR。

const KEY = "door:latest";

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
      const v = await env.DOOR.get(KEY, "json");
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
      await env.DOOR.put(KEY, JSON.stringify({ line, ts }));
      return json({ ok: true, ts }, cors);
    }

    return new Response("method not allowed", { status: 405, headers: cors });
  },
};

function json(obj, cors, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
  });
}
