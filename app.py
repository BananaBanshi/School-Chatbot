import os, time, csv, io
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from openai import OpenAI
import requests
from urllib.parse import urlparse

# -----------------------
# Config + setup
# -----------------------
load_dotenv()
app = Flask(__name__, static_folder="static", static_url_path="")

CSV_URL = os.getenv("CSV_URL", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
CACHE_TTL_SECONDS = 300  # 5 min cache

# -----------------------
# CSV Cache helpers
# -----------------------
_csv_cache = {
    "loaded_at": 0.0,
    "en": [],
    "es": []
}

def _now():
    return time.time()

def _csv_cache_expired():
    return (_now() - _csv_cache["loaded_at"]) > CACHE_TTL_SECONDS

def _fetch_csv_text(url: str) -> str:
    u = url.strip().strip('"').strip("'")
    parsed = urlparse(u)

    # Local file (absolute path or file://)
    if parsed.scheme == "file":
        path = parsed.path
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    if parsed.scheme == "":
        path = os.path.expanduser(u)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # Web URL
    if parsed.scheme in ("http", "https"):
        r = requests.get(u, timeout=15)
        r.raise_for_status()
        return r.text

    raise ValueError(f"Unsupported CSV_URL scheme: {parsed.scheme}")

def _load_bilingual_csv(url: str):
    try:
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

        qi_en = pick("question_en", "question")
        ai_en = pick("answer_en", "answer")
        qi_es = pick("question_es", "pregunta")
        ai_es = pick("answer_es", "respuesta")

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

def _format_context_for_model(pairs, lang_tag):
    blocks = []
    for q, a in pairs:
        if lang_tag == "[EN]":
            blocks.append(f"{lang_tag}\nQ: {q}\nA: {a}")
        else:
            blocks.append(f"{lang_tag}\nP: {q}\nR: {a}")
    return "\n\n".join(blocks)

# -----------------------
# Routes
# -----------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.post("/api/chat")
def chat():
    data = request.get_json(force=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "No message"}), 400
    if not OPENAI_API_KEY:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    client = OpenAI(api_key=OPENAI_API_KEY)
    ctx = _get_bilingual_context()

    blocks = []
    if ctx["en"]:
        blocks.append(_format_context_for_model(ctx["en"], "[EN]"))
    if ctx["es"]:
        blocks.append(_format_context_for_model(ctx["es"], "[ES]"))

    context_text = "\n\n".join(blocks)
    system_prompt = (
        "You are a helpful school assistant. Detect user's language (English or Spanish) "
        "and reply in that language. Use matching-language entries from context when available. "
        "If missing, translate the closest available answer."
    )

    if context_text:
        user_prompt = f"Context:\n{context_text}\n\nUser: {user_msg}"
    else:
        user_prompt = f"User: {user_msg}"

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        reply = resp.choices[0].message.content
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/debug/csv")
def debug_csv():
    ctx = _get_bilingual_context()
    return jsonify({
        "csv_url": CSV_URL,
        "en_count": len(ctx["en"]),
        "es_count": len(ctx["es"]),
        "sample_en": ctx["en"][:2],
        "sample_es": ctx["es"][:2]
    })

# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
