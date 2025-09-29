# app.py — all-in-one chatbot + embeddable widget

import os, time, csv, io
from urllib.parse import urlparse

from flask import Flask, request, jsonify, Response, send_from_directory
from dotenv import load_dotenv
from openai import OpenAI
import requests

# -----------------------
# Setup
# -----------------------
load_dotenv()

# Serve static files under /static
app = Flask(__name__, static_folder="static", static_url_path="/static")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
CSV_URL        = os.getenv("CSV_URL", "").strip()
CACHE_TTL      = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # seconds, default 5 min

# (Optional) tighten who can embed your widget via CSP frame-ancestors:
# Example: "self https://school-website.org http://localhost:8080"
FRAME_ANCESTORS = os.getenv("FRAME_ANCESTORS", "self *")

# -----------------------
# CSV caching & helpers
# -----------------------
_csv_cache = {"loaded_at": 0.0, "en": [], "es": []}

def _now(): return time.time()

def _csv_cache_expired() -> bool:
    return (_now() - _csv_cache["loaded_at"]) > CACHE_TTL

def _fetch_csv_text(url: str) -> str:
    """Fetch CSV from http(s), file://, or local path; expand ~ if needed."""
    u = (url or "").strip().strip('"').strip("'")
    parsed = urlparse(u)

    if parsed.scheme in ("http", "https"):
        r = requests.get(u, timeout=20)
        r.raise_for_status()
        return r.text
    if parsed.scheme == "file":
        path = parsed.path
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    if parsed.scheme == "":
        path = os.path.expanduser(u)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    raise ValueError(f"Unsupported CSV_URL scheme: {parsed.scheme}")

def _load_bilingual_csv(url: str) -> None:
    """
    Tolerant header mapping. Accepts:
      question_en, answer_en, question_es, answer_es
    Fallback: if only 'question' & 'answer' exist, treat as English.
    Ignores extra columns (e.g., source_url).
    """
    try:
        # bust simple caches on remote CSV
        bust = f"{url}{'&_ts=' if '?' in url else '?_ts='}{int(time.time())}"
        text = _fetch_csv_text(bust)
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            raise ValueError("Empty CSV")

        header = [h.strip().lower() for h in rows[0]]
        idx = {h: i for i, h in enumerate(header)}

        def pick(*names):
            for n in names:
                if n in idx:
                    return idx[n]
            return None

        qi_en = pick("question_en", "question en", "question", "q_en", "q")
        ai_en = pick("answer_en",   "answer en",   "answer",   "a_en", "a")
        qi_es = pick("question_es", "question es", "pregunta_es", "pregunta es", "pregunta")
        ai_es = pick("answer_es",   "answer es",   "respuesta_es","respuesta es","respuesta")

        en_rows, es_rows = [], []
        for r in rows[1:]:
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            q_en = r[qi_en] if qi_en is not None else ""
            a_en = r[ai_en] if ai_en is not None else ""
            q_es = r[qi_es] if qi_es is not None else ""
            a_es = r[ai_es] if ai_es is not None else ""

            if q_en.strip() and a_en.strip():
                en_rows.append((q_en.strip(), a_en.strip()))
            if q_es.strip() and a_es.strip():
                es_rows.append((q_es.strip(), a_es.strip()))

        _csv_cache["en"] = en_rows
        _csv_cache["es"] = es_rows
        _csv_cache["loaded_at"] = _now()
        print(f"[CSV] Loaded {len(en_rows)} EN rows, {len(es_rows)} ES rows.")

    except Exception as e:
        print("CSV load error:", e)

def _get_bilingual_context():
    if not CSV_URL:
        return {"en": [], "es": []}
    if _csv_cache_expired() or _csv_cache["loaded_at"] == 0.0:
        _load_bilingual_csv(CSV_URL)
    return {"en": _csv_cache["en"], "es": _csv_cache["es"]}

def _format_context_for_model(pairs, lang_tag: str) -> str:
    blocks = []
    for q, a in pairs:
        if lang_tag == "[EN]":
            blocks.append(f"{lang_tag}\nQ: {q}\nA: {a}")
        else:
            blocks.append(f"{lang_tag}\nP: {q}\nR: {a}")
    return "\n\n".join(blocks)

# -----------------------
# Global headers (embedding)
# -----------------------
@app.after_request
def add_embed_headers(resp):
    # Allow embedding in iframes; tighten CSP when you know your allowed parent domains.
    resp.headers["X-Frame-Options"] = "ALLOWALL"
    resp.headers["Content-Security-Policy"] = f"frame-ancestors {FRAME_ANCESTORS};"
    return resp

# -----------------------
# Routes
# -----------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

    # Minimal home that loads your static UI
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>School Chatbot</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;padding:40px;background:#f6f7fb;color:#111}
    .wrap{max-width:860px;margin:0 auto}
    h1{margin:0 0 6px}
    .card{background:#fff;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.08);padding:20px}
    iframe{width:100%;height:70vh;border:0;border-radius:10px}
    .meta{font-size:14px;color:#555;margin:10px 0 20px}
    code{background:#eef2ff;padding:.1rem .35rem;border-radius:6px}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>School Chatbot</h1>
    <div class="meta">Bilingual (EN/ES). Content managed via Google Sheets CSV.</div>
    <div class="card">
      <iframe src="/" onload="this.src='/static/index.html'"></iframe>
    </div>
    <p class="meta">
      Embed anywhere with: <code>&lt;script src=&quot;{origin}/widget.js&quot; data-chatbot-src=&quot;{origin}&quot;&gt;&lt;/script&gt;</code>
    </p>
    <p class="meta">
      Debug CSV: <a href="/debug/csv">/debug/csv</a> • Health: <a href="/health">/health</a>
    </p>
  </div>
</body>
</html>
""".replace("{origin}", request.host_url.rstrip("/"))

@app.get("/health")
def health():
    return "ok", 200



@app.get("/debug/csv")
def debug_csv():
    ctx = _get_bilingual_context()
    return jsonify({
        "csv_url": CSV_URL,
        "en_count": len(ctx.get("en", [])),
        "es_count": len(ctx.get("es", [])),
        "ja_count": len(ctx.get("ja", [])),
        "sample_en": ctx.get("en", [])[:2],
        "sample_es": ctx.get("es", [])[:2],
        "sample_ja": ctx.get("ja", [])[:2], 
    })



# --- Simple admin (optional token) ---
from datetime import datetime

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

def _admin_allowed() -> bool:
    if not ADMIN_TOKEN:
        return True
    token = (request.args.get("token") or "").strip()
    return token == ADMIN_TOKEN

def _fmt_ts(ts: float) -> str:
    if not ts: return "never"
    try:
        return datetime.utcfromtimestamp(ts).isoformat() + "Z"
    except Exception:
        return str(ts)




@app.get("/routes")
def routes():
    return "<pre>" + "\n".join(sorted(str(r) for r in app.url_map.iter_rules())) + "</pre>"



# --- Floating widget JS (💬 bubble) ---
@app.get("/widget.js")
def widget_js():
    js = r"""
(() => {
  const currentScript = document.currentScript;
  const CHAT_SRC = currentScript?.dataset?.chatbotSrc || (location.origin);
  const BTN_COLOR = currentScript?.dataset?.primaryColor || "#2563eb";
  const CORNER    = currentScript?.dataset?.position || "right";
  const TITLE     = currentScript?.dataset?.title || "Ask the School";

  const style = document.createElement("style");
  style.textContent = `
    .scb-btn { position:fixed; ${CORNER}:20px; bottom:20px; width:56px; height:56px;
      border-radius:9999px; background:${BTN_COLOR}; color:#fff; border:0; cursor:pointer;
      display:flex; align-items:center; justify-content:center; box-shadow:0 10px 24px rgba(0,0,0,.2);
      z-index:2147483646; font:600 16px/1 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif; }
    .scb-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.2); display:none; z-index:2147483645; }
    .scb-panel { position:fixed; bottom:90px; ${CORNER}:20px; width:min(420px,95vw); height:min(70vh,700px);
      background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 20px 40px rgba(0,0,0,.25);
      display:none; z-index:2147483647; }
    .scb-header { height:44px; background:#111827; color:#fff; display:flex; align-items:center; justify-content:space-between; padding:0 12px;
      font:600 14px/1 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif; }
    .scb-close { background:transparent; border:0; color:#fff; font-size:18px; cursor:pointer; }
    .scb-iframe { width:100%; height:calc(100% - 44px); border:0; }
    @media (max-width:640px){ .scb-panel{ bottom:0; ${CORNER}:0; width:100vw; height:85vh; border-radius:12px 12px 0 0; } }
  `;
  document.head.appendChild(style);

  const btn = document.createElement("button");
  btn.className = "scb-btn"; btn.setAttribute("aria-label","Open chat"); btn.innerHTML = "💬";

  const backdrop = document.createElement("div"); backdrop.className = "scb-backdrop";
  const panel    = document.createElement("div"); panel.className = "scb-panel";

  const header = document.createElement("div"); header.className = "scb-header";
  header.innerHTML = `<span>${TITLE}</span>`;
  const close = document.createElement("button"); close.className = "scb-close"; close.innerHTML = "×";
  close.addEventListener("click", () => { panel.style.display="none"; backdrop.style.display="none"; });
  header.appendChild(close);

  const iframe = document.createElement("iframe"); iframe.className = "scb-iframe"; iframe.src = CHAT_SRC;

  panel.appendChild(header); panel.appendChild(iframe);
  document.body.appendChild(backdrop); document.body.appendChild(panel); document.body.appendChild(btn);

  btn.addEventListener("click", () => { panel.style.display="block"; backdrop.style.display="block"; });
  backdrop.addEventListener("click", () => { panel.style.display="none";  backdrop.style.display="none"; });
  window.addEventListener("keydown", (e)=>{ if(e.key==="Escape"){ panel.style.display="none"; backdrop.style.display="none"; }});
})();
    """.strip()
    return Response(js, mimetype="application/javascript")



# --- Fuzzy matching helper ---
import difflib

def top_match(user_q: str, pairs, cutoff=0.55):
    """
    Return the (question, answer) pair whose question best matches user_q.
    pairs: list of (q, a)
    cutoff: 0..1 (higher = stricter)
    """
    if not user_q or not pairs:
        return None
    questions = [q for q, _ in pairs]
    best = difflib.get_close_matches(user_q, questions, n=1, cutoff=cutoff)
    if not best:
        return None
    qbest = best[0]
    for q, a in pairs:
        if q == qbest:
            return (q, a)
    return None



# --- Chat API using OpenAI ---
@app.post("/api/chat")
def chat():
    try:
        data = request.get_json(silent=True) or {}
        user_msg = (data.get("message") or "").strip()
        forced_lang = (data.get("lang") or "").lower()

        if not user_msg:
            return jsonify({"error": "Empty message"}), 400

        # Load context (EN/ES/JA if present)
        ctx = _get_bilingual_context()
        blocks = []
        if ctx.get("en"):
            blocks.append(_format_context_for_model(ctx["en"], "[EN]"))
        if ctx.get("es"):
            blocks.append(_format_context_for_model(ctx["es"], "[ES]"))
        if ctx.get("ja"):
            blocks.append(_format_context_for_model(ctx["ja"], "[JA]"))
        context_text = "\n\n".join(blocks) if blocks else ""

        # Fuzzy hint across all languages
        all_pairs = []
        if ctx.get("ja"): all_pairs.extend(ctx["ja"])
        if ctx.get("es"): all_pairs.extend(ctx["es"])
        if ctx.get("en"): all_pairs.extend(ctx["en"])
        best = top_match(user_msg, all_pairs, cutoff=0.55)
        best_hint = ""
        if best:
            qh, ah = best
            best_hint = f"\n\nLikely match:\nQ: {qh}\nA: {ah}"

        # System prompt
        system_prompt = (
            "You are a helpful school assistant. Detect if the user writes in English, Spanish, or Japanese "
            "and reply in that language. Prefer matching-language entries from the provided context. "
            "If no direct match exists, translate the best available answer. Keep responses concise."
        )
        if forced_lang in ("en","es","ja"):
            system_prompt += f" The user requested replies in {forced_lang.upper()} regardless of input."

        # User prompt
        if context_text:
            user_prompt = f"Context:\n{context_text}\n{best_hint}\n\nUser: {user_msg}"
        else:
            user_prompt = f"{best_hint}\n\nUser: {user_msg}"

        # Call OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.2,
        )
        reply = resp.choices[0].message.content.strip()
        return jsonify({"reply": reply})

    except Exception:
        app.logger.exception("Chat error")
        return jsonify({"error":"Server error processing your request."}), 500




# --- Simple admin (optional token) ---
from datetime import datetime

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

def _admin_allowed() -> bool:
    if not ADMIN_TOKEN:
        return True
    token = (request.args.get("token") or "").strip()
    return token == ADMIN_TOKEN

def _fmt_ts(ts: float) -> str:
    if not ts: return "never"
    try:
        return datetime.utcfromtimestamp(ts).isoformat() + "Z"
    except Exception:
        return str(ts)


@app.get("/admin")
def admin():
    if not _admin_allowed():
        return ("forbidden", 403)
    ctx = _get_bilingual_context()
    en = len(ctx.get("en", []))
    es = len(ctx.get("es", []))
    ja = len(ctx.get("ja", []))
    last = _fmt_ts(_csv_cache.get("loaded_at", 0.0))
    hint = f"&token={ADMIN_TOKEN}" if ADMIN_TOKEN else ""
    html = f"""
<!doctype html>
<meta charset="utf-8">
<title>Admin</title>
<style>
body{{font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:820px;margin:40px auto;padding:0 16px}}
pre,code{{background:#f6f7fb;padding:.25rem .5rem;border-radius:6px}}
.card{{background:#fff;border-radius:10px;box-shadow:0 10px 24px rgba(0,0,0,.08);padding:16px;margin-bottom:16px}}
button{{padding:.45rem .8rem;border-radius:8px;border:1px solid #e5e7eb;background:#111827;color:#fff;cursor:pointer}}
a{{color:#2563eb}}
</style>
<h1>Admin</h1>
<div class="card">
  <div><b>CSV URL</b>: <code>{CSV_URL or '(not set)'}</code></div>
  <div>Counts → EN: <b>{en}</b> · ES: <b>{es}</b> · JA: <b>{ja}</b></div>
  <div>Last load: <code>{last}</code> (TTL: {CACHE_TTL}s)</div>
</div>
<div class="card">
  <form method="post" action="/admin/flush{hint}">
    <button>Flush CSV Cache</button>
  </form>
</div>
<p><a href="/debug/csv">debug/csv</a> · <a href="/">home</a></p>
"""
    return html

@app.post("/admin/flush")
def admin_flush():
    if not _admin_allowed():
        return ("forbidden", 403)
    _csv_cache.update({"loaded_at": 0.0, "en": [], "es": [], "ja": _csv_cache.get("ja", [])})
    return 'Cache flushed. <a href="/admin">Back</a>'






# --- serve /static if you have a frontend ---
@app.get("/static/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)

# --- Run locally ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)



