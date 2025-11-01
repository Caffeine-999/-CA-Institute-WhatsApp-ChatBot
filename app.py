"""
Paras Institute WhatsApp Bot (Cloud API) — BOT + ADMIN + CHAT LOG
-----------------------------------------------------------------
- Flow:
  • Know about our Institute  (list: Social/Features/Results/Contacts)
  • CA Coaching (course -> attempt -> group (if needed) -> mode -> features -> thanks)

- Admin:
  • /admin (login) : recent conversations list + pause/resume
  • /admin/chat/<wa_id> : full chat transcript + reply box

- Storage:
  • leads.csv (same as before)
  • chat.db (SQLite) — table 'messages' to log inbound/outbound

Notes:
- Button titles ≤ 20 chars; ≤ 3 buttons
- List row titles ≤ 24 chars
"""

import os
import csv
import json
import sqlite3
import requests
from datetime import datetime
from flask import (
    Flask, request, session, redirect, url_for,
    render_template_string, jsonify
)
from dotenv import load_dotenv

# ----------------- Load env & fail fast -----------------
load_dotenv()
def env(name, required=True, default=None):
    v = os.getenv(name, default)
    if required and (not v or v == "None"):
        raise SystemExit(f"[ENV] {name} is missing. Put it in your .env")
    return v

VERIFY_TOKEN    = env("VERIFY_TOKEN")
WHATSAPP_TOKEN  = env("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = env("PHONE_NUMBER_ID")
GRAPH_API_VER   = os.getenv("GRAPH_API_VERSION", "v22.0")
DEBUG           = os.getenv("DEBUG", "0") == "1"

ADMIN_USER      = env("ADMIN_USER")
ADMIN_PASS      = env("ADMIN_PASS")
SECRET_KEY      = env("SECRET_KEY")

GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VER}/{PHONE_NUMBER_ID}/messages"
LEADS_CSV = "leads.csv"
DB_FILE = "chat.db"
OVERRIDES_JSON = "overrides.json"   # {"paused": {"<wa_id>": true/false}}

app = Flask(__name__)
app.secret_key = SECRET_KEY

print("GRAPH_URL ->", GRAPH_URL)

# ----------------- DB init -----------------
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            direction TEXT NOT NULL,     -- 'in' or 'out'
            mtype TEXT,                  -- 'text' | 'button' | 'list' | 'system'
            text TEXT,
            ts TEXT NOT NULL,            -- ISO timestamp
            payload TEXT                 -- JSON payload for debugging
        )
        """)
init_db()

# ----------------- Pause map (persisted JSON) -----------------
def load_overrides():
    if not os.path.isfile(OVERRIDES_JSON):
        return {"paused": {}}
    try:
        with open(OVERRIDES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"paused": {}}

def save_overrides(data):
    with open(OVERRIDES_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_paused(wa_id: str) -> bool:
    return bool(load_overrides().get("paused", {}).get(wa_id))

def set_paused(wa_id: str, flag: bool):
    ov = load_overrides()
    ov.setdefault("paused", {})[wa_id] = bool(flag)
    save_overrides(ov)

# ----------------- In-memory state -----------------
STATE = {}

def set_state(wa_id: str, **kwargs):
    cur = STATE.get(wa_id, {})
    cur.update(kwargs)
    STATE[wa_id] = cur

def get_state(wa_id: str):
    return STATE.get(wa_id, {})

def clear_state(wa_id: str):
    STATE.pop(wa_id, None)

# ----------------- Options (YOUR CONTENT) -----------------
COURSES = [
    ("COURSE_FOUNDATION",   "CA Foundation"),
    ("COURSE_INTERMEDIATE", "CA Intermediate"),
    ("COURSE_FINAL_TS",     "Final Test Series"),
]
ATTEMPTS_STD = [("ATTEMPT_SEP", "September"), ("ATTEMPT_MAY", "May"), ("ATTEMPT_JAN", "January")]
GROUPS = [("GROUP_1", "Group 1"), ("GROUP_2", "Group 2"), ("GROUP_BOTH", "Both Groups")]
MODES = [("MODE_FACE", "Face to Face"), ("MODE_ONLINE", "Online"), ("MODE_VIRTUAL", "Virtual")]

SOCIAL_LINKS = {
    "Instagram": "https://www.instagram.com/paras_institute_of_commerce/",
    "YouTube":   "https://www.youtube.com/@ParasInstituteofCommercePvtLtd",
    "Facebook":  "https://www.facebook.com/ParasInstituteIndia",
}
UNIQUE_FEATURES = [
    "Paras Institute Of Commerce Since 1995",
    "Face to Face, Virtual & Online Classes",
    "30+ Years of Experience in teaching",
    "A Core-competent, Efficient & Dedicated Faculty Team",
    "Monthly Progress Report",
    "Regular Doubt-Clearance Classes",
    "Regular Classes Management",
    "Regular co-ordination with parents",
    "CA Foundation : 60 Chapter wise Tests, 12 Unit Tests and 12 Final Mock Test",
    "CA Intermediate : 70 Chapter wise Tests, 12 Unit Tests and 12 Final Mock Test",
    "CA Final : 16 Unit Tests and 12 Final Mock Tests",
    "Timely Test Checking",
]
RESULTS_SUMMARY = [
    "Excellent performance each year",
    "Paras CA Foundation: 80–90% Result",
    "Paras CA Intermediate: 70–80% Result",
    "80+ All India Rank Holders",
]
IMPORTANT_CONTACTS = [
    "Counselor 1 :            +91 9896162844",
    "Counselor 2 :            +91 9896685777",
    "Counselor 3 :            +91 8199996644",
    "Face to Face Management: +91 8950329505",
    "Online Management:       +91 9253076101",
    "Test Dept:               +91 9034510124",
]

FEATURES_TEXT = {
    "Face to Face": (
        "Face to Face Classes – Key Features:\n"
        "• 30+ Years of Experience in teaching\n"
        "• Daily in-class teaching\n"
        "• Doubt counter & peer study rooms\n"
        "• Regular tests & evaluation\n"
        "• Parent coordination & progress reports\n"
        "• Library & discipline-support on campus\n"
        "• CA Foundation : 60 Chapter wise Tests, 12 Unit Tests and 12 Final Mock Test\n"
        "• CA Intermediate : 70 Chapter wise Tests, 12 Unit Tests and 12 Final Mock Test\n"
        "CA Final : 16 Unit Tests and 12 Final Mock Tests\n"
        "• Timely Test Checking\n"
        "• Individual Attention to Each Student"
    ),
    "Online": (
        "Online Classes – Key Features:\n"
        "• Leacture of face to face classes with two way communication between students and teachers.\n"
        "• Unique teaching pattern with concept clarity form basic to advance.\n"
        "• Best study material and updated questions banks covering all type of questions with 100% coverage of syllabus.\n"
        "• Chapter wise, Unit wise and Final Test system for complete syllabus.\n"
        "• Subject wise classes schedule managed by Paras Team on daily basis.\n"
        "• Regular coordination by Paras management Team Members with students & Parents.\n"
        "• Daily Home work PDF checking and revision classes.\n"
        "• Monthly Performance Report and Analysis.\n"
        "• Daily doubt clearance sessions by faculy.\n"
        "• Regular work on physical and mental health."
    ),
    "Virtual": (
        "Virtual Classes – Key Features:\n"
        "• Fixed timetable (live virtual)\n"
        "• Interactive doubt clearing\n"
        "• Regular tests & mentor guidance\n"
        "• Parent updates & performance summary\n"
        "• List of City with Virtual centres of Paras Institute\n"
        "- Bhiwani                  +919429049069\n"
        "- Jind                     +919992757534\n"
        "- Narwana                  +918168188426\n"
        "- Bathinda                 +917888602120\n"
        "- Kaithal                  +919097044004\n"
        "- Rohtak                   +919034869678\n"
        "- Sirsa                    +919416509909\n"
        "- Yamunanagar              +917404909400\n"
        "- Ambala                   +918708824618\n"
        "- Jaipur                   +918802084656\n"
        "- Shahdara, Delhi          +919716692702\n"
        "- Laxmi Nagar, Delhi       +918199996644\n"
        "- Tohana                   +917988476224\n"
        "- Sonipat                  +917015755714\n"
        "- Siliguri                 +919832062876\n"
        "- Rewari                   +919729827454\n"
    ),
}

# ----------------- Logging helpers -----------------
def log_message(wa_id: str, direction: str, mtype: str, text: str, payload: dict | None = None):
    with db() as conn:
        conn.execute(
            "INSERT INTO messages (wa_id, direction, mtype, text, ts, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (wa_id, direction, mtype, text, datetime.now().isoformat(timespec="seconds"),
             json.dumps(payload, ensure_ascii=False) if payload else None)
        )

# ----------------- WhatsApp send helpers (auto-log OUTBOUND) -----------------
def wa_send(payload: dict):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    r = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=30)
    if DEBUG:
        try: print("->", json.dumps(payload, ensure_ascii=False))
        except Exception: print("->", payload)
        print("<-", r.status_code, r.text)
    return r.status_code, r.text

def send_text(to_wa_id: str, text: str):
    payload = {"messaging_product": "whatsapp", "to": to_wa_id, "type": "text", "text": {"body": text}}
    code, resp = wa_send(payload)
    # Log outbound text
    log_message(to_wa_id, "out", "text", text, payload)
    return code, resp

def send_buttons(to_wa_id: str, body_text: str, buttons: list[tuple[str,str]]):
    # max 3 buttons; titles ≤ 20 chars
    b = [{"type": "reply", "reply": {"id": bid, "title": title[:20]}} for bid, title in buttons[:3]]
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body_text}, "action": {"buttons": b}},
    }
    code, resp = wa_send(payload)
    # Log outbound "system" describing the buttons offered
    labels = " | ".join([btn["reply"]["title"] for btn in b])
    log_message(to_wa_id, "out", "button", f"[Buttons] {body_text}  :: {labels}", payload)
    return code, resp

def send_list_menu(to_wa_id: str, header_text: str, body_text: str, rows: list[tuple[str,str]]):
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header_text},
            "body":   {"text": body_text},
            "footer": {"text": "Paras Institute"},
            "action": {
                "button": "Open Menu",
                "sections": [{"title": "Options", "rows": [{"id": rid, "title": title[:24]} for rid, title in rows]}],
            },
        },
    }
    code, resp = wa_send(payload)
    # Log outbound list menu
    labels = " | ".join([title for _, title in rows])
    log_message(to_wa_id, "out", "list", f"[List] {header_text} — {body_text}  :: {labels}", payload)
    return code, resp

# ----------------- Menus -----------------
def send_main_menu(to: str):
    return send_buttons(to,
        "Hi! Thanks for contacting Paras Institute of Commerce.\nHow can we help you?",
        [("KNOW", "Know our Institute"), ("COACH", "CA Coaching")]
    )

def send_know_menu(to: str):
    rows = [
        ("KNOW_SOCIAL",   "Social Media"),
        ("KNOW_FEATURES", "Unique Features"),
        ("KNOW_RESULTS",  "Results"),
        ("KNOW_CONTACTS", "Important Contacts"),
    ]
    return send_list_menu(to, "Know about our Institute", "Choose one:", rows)

def send_course_menu(to: str):
    return send_buttons(to, "Which course are you looking for?", COURSES)

def send_attempt_menu(to: str):
    return send_buttons(to, "Choose your Attempt", ATTEMPTS_STD)

def send_group_menu(to: str):
    return send_buttons(to, "Which Group are you considering?", GROUPS)

def send_mode_menu(to: str):
    return send_buttons(to, "Which mode of classes are you looking for?", MODES)

# ----------------- Leads CSV -----------------
def append_csv(row: dict):
    header = ["timestamp","flow","course","attempt","group","mode","name","city","wa_id","profile_name"]
    file_exists = os.path.isfile(LEADS_CSV)
    with open(LEADS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if not file_exists:
            w.writeheader()
        w.writerow(row)

# ----------------- Webhook endpoints -----------------
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def inbound():
    data = request.get_json()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                if not messages:
                    continue

                msg = messages[0]
                mtype = msg.get("type")
                wa_id = msg.get("from")

                # If paused, do nothing (human takes over via admin)
                if is_paused(wa_id):
                    if DEBUG: print(f"[paused] {wa_id}")
                    return "OK", 200

                contacts = value.get("contacts", [{}])
                profile_name = contacts[0].get("profile", {}).get("name") if contacts else None

                # ===== Interactive =====
                if mtype == "interactive":
                    i = msg.get("interactive", {})

                    if i.get("type") == "button_reply":
                        br = i.get("button_reply", {})
                        bid = (br.get("id") or "").strip()
                        btitle = (br.get("title") or "").strip()
                        # Log inbound button choice
                        log_message(wa_id, "in", "button", f"[User tapped] {btitle} ({bid})", msg)

                        # Top level
                        if bid == "KNOW":
                            set_state(wa_id, stage="KNOW")
                            send_know_menu(wa_id)
                            return "OK", 200
                        elif bid == "COACH":
                            set_state(wa_id, stage="COURSE")
                            send_course_menu(wa_id)
                            return "OK", 200

                        # Course
                        elif bid in {"COURSE_FOUNDATION","COURSE_INTERMEDIATE","COURSE_FINAL_TS"}:
                            set_state(wa_id, stage="ATTEMPT", course=bid.replace("COURSE_",""))
                            send_attempt_menu(wa_id)
                            return "OK", 200

                        # Attempt
                        elif bid in {"ATTEMPT_SEP","ATTEMPT_MAY","ATTEMPT_JAN"}:
                            st = get_state(wa_id)
                            course = st.get("course")
                            attempt = bid.replace("ATTEMPT_","")
                            if course is None:
                                send_text(wa_id, "Please start with *CA Coaching* again.")
                                return "OK", 200

                            if course == "FINAL_TS":
                                info = {
                                    "SEP": "Test series for September attempt are held during July & August months.",
                                    "MAY": "Test series for May attempt are held during March & April months.",
                                    "JAN": "Test series for January attempt are held during November & December months.",
                                }.get(attempt, "")
                                if info: send_text(wa_id, info)
                                set_state(wa_id, stage="GROUP", attempt=attempt)
                                send_group_menu(wa_id)
                                return "OK", 200

                            if course == "FOUNDATION":
                                set_state(wa_id, stage="MODE", attempt=attempt)
                                send_mode_menu(wa_id)
                                return "OK", 200

                            if course == "INTERMEDIATE":
                                set_state(wa_id, stage="GROUP", attempt=attempt)
                                send_group_menu(wa_id)
                                return "OK", 200

                        # Group
                        elif bid in {"GROUP_1","GROUP_2","GROUP_BOTH"}:
                            set_state(wa_id, stage="MODE", group=bid.replace("GROUP_","").replace("_"," "))
                            send_mode_menu(wa_id)
                            return "OK", 200

                        # Mode → features + thanks + log lead
                        elif bid in {"MODE_FACE", "MODE_ONLINE", "MODE_VIRTUAL"}:
                            mode_map = {"MODE_FACE": "Face to Face", "MODE_ONLINE": "Online", "MODE_VIRTUAL": "Virtual"}
                            mode_label = mode_map[bid]
                            st = get_state(wa_id)

                            # Save minimal lead
                            append_csv({
                                "timestamp":    datetime.now().isoformat(timespec="seconds"),
                                "flow":         "COACHING_ENQUIRY",
                                "course":       st.get("course",""),
                                "attempt":      st.get("attempt",""),
                                "group":        st.get("group",""),
                                "mode":         mode_label,
                                "name":         "",
                                "city":         "",
                                "wa_id":        wa_id,
                                "profile_name": profile_name or "",
                            })

                            # Send features + follow-up
                            features = FEATURES_TEXT.get(mode_label, f"{mode_label} – key features will be shared by our team.")
                            send_text(wa_id, features)
                            send_text(wa_id, "Thanks for contacting Paras Institute. We'll soon connect with you via call.")
                            clear_state(wa_id)
                            return "OK", 200

                        # Unknown button id
                        send_text(wa_id, "Thanks! How can we help?")
                        return "OK", 200

                    if i.get("type") == "list_reply":
                        lr = i.get("list_reply", {})
                        lid = (lr.get("id") or "").strip()
                        ltitle = (lr.get("title") or "").strip()
                        # Log inbound list selection
                        log_message(wa_id, "in", "list", f"[User chose] {ltitle} ({lid})", msg)

                        if lid == "KNOW_SOCIAL":
                            lines = [f"• {k}: {v}" for k,v in SOCIAL_LINKS.items()]
                            send_text(wa_id, "Follow us on Social Media:\n" + "\n".join(lines))
                            return "OK", 200
                        if lid == "KNOW_FEATURES":
                            lines = [f"• {x}" for x in UNIQUE_FEATURES]
                            send_text(wa_id, "Unique Features:\n" + "\n".join(lines))
                            return "OK", 200
                        if lid == "KNOW_RESULTS":
                            lines = [f"• {x}" for x in RESULTS_SUMMARY]
                            send_text(wa_id, "Results:\n" + "\n".join(lines))
                            return "OK", 200
                        if lid == "KNOW_CONTACTS":
                            lines = [f"• {x}" for x in IMPORTANT_CONTACTS]
                            send_text(wa_id, "Important Contacts:\n" + "\n".join(lines))
                            return "OK", 200

                        send_text(wa_id, "Thanks! How can we help?")
                        return "OK", 200

                # ===== Free text =====
                if mtype == "text":
                    text_raw = msg.get("text", {}).get("body", "").strip()
                    # Log inbound text
                    log_message(wa_id, "in", "text", text_raw, msg)

                    lower = text_raw.lower()
                    if lower in {"hi","hello","menu","start"}:
                        clear_state(wa_id)
                        send_main_menu(wa_id)
                        return "OK", 200

                    # Nudge if unknown
                    send_text(wa_id, "Please type *Hi* to see options, or share your query directly.")
                    return "OK", 200

        return "EVENT_RECEIVED", 200

    except Exception as e:
        print("Error handling webhook:", e)
        return "OK", 200

# ----------------- Admin UI -----------------
ADMIN_LIST_TMPL = """
<!doctype html><html><head><meta charset="utf-8"/><title>Paras Admin</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;background:#fafafa;color:#222}
a{color:#0a7}
.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin-bottom:20px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
input,button{font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #ccc}
button{background:#0b7;color:#fff;border:none;cursor:pointer}
button.danger{background:#c33}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{border-bottom:1px solid #eee;padding:10px;text-align:left;font-size:14px}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;background:#eee}
.badge.red{background:#fdd}.badge.green{background:#dfd}
.small{font-size:12px;color:#666}
</style></head><body>
<h2>Paras Admin</h2>

<div class="card">
  <h3>Recent Conversations</h3>
  <table>
    <thead><tr><th>Last time</th><th>WA ID</th><th>Preview</th><th>Bot</th><th>Open</th></tr></thead>
    <tbody>
    {% for r in convs %}
      <tr>
        <td>{{ r.last_ts }}</td>
        <td>{{ r.wa_id }}</td>
        <td class="small">{{ r.preview }}</td>
        <td>{% if r.paused %}<span class="badge red">Paused</span>{% else %}<span class="badge green">Running</span>{% endif %}</td>
        <td><a href="{{ url_for('admin_chat', wa_id=r.wa_id) }}">Open chat</a></td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<form method="post" action="{{ url_for('admin_logout') }}"><button class="danger">Logout</button></form>
</body></html>
"""

ADMIN_CHAT_TMPL = """
<!doctype html><html><head><meta charset="utf-8"/><title>Chat {{ wa_id }}</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;background:#fafafa;color:#222}
a{color:#0a7}
.wrap{max-width:900px;margin:auto}
.bubble{max-width:70%;padding:10px 12px;border-radius:14px;margin:8px 0;box-shadow:0 1px 2px rgba(0,0,0,.05)}
.in{background:#fff;border:1px solid #e5e5e5}
.out{background:#e9fff5;border:1px solid #d4f4e5;margin-left:auto}
.meta{font-size:11px;color:#777;margin-top:4px}
.header{display:flex;gap:12px;align-items:center;margin-bottom:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;background:#eee}
.badge.red{background:#fdd}.badge.green{background:#dfd}
input,button{font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #ccc}
button{background:#0b7;color:#fff;border:none;cursor:pointer}
button.danger{background:#c33}
</style></head><body><div class="wrap">
  <div class="header">
    <h3 style="margin:0">Chat: {{ wa_id }}</h3>
    {% if paused %}<span class="badge red">Bot Paused</span>{% else %}<span class="badge green">Bot Running</span>{% endif %}
    <form method="post" action="{{ url_for('admin_toggle') }}">
      <input type="hidden" name="wa_id" value="{{ wa_id }}"/>
      {% if paused %}
        <button class="danger" name="action" value="resume">Resume Bot</button>
      {% else %}
        <button class="danger" name="action" value="pause">Pause Bot</button>
      {% endif %}
      <a href="{{ url_for('admin_home') }}" style="margin-left:12px">← Back</a>
    </form>
  </div>

  {% for m in msgs %}
    <div class="bubble {{ 'in' if m.direction=='in' else 'out' }}">
      <div>{{ m.text|e if m.text else '' }}</div>
      <div class="meta">{{ m.ts }} · {{ m.mtype }}</div>
    </div>
  {% endfor %}

  <form method="post" action="{{ url_for('admin_chat', wa_id=wa_id) }}" style="margin-top:16px">
    <input name="text" placeholder="Type a reply…" style="width:70%" required>
    <button>Send</button>
  </form>
</div></body></html>
"""

LOGIN_TMPL = """
<!doctype html><html><head><meta charset="utf-8"/><title>Login</title>
<style>
body{font-family:system-ui;-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;background:#fafafa}
.card{max-width:420px;background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin:auto;margin-top:60px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
input,button{font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #ccc;width:100%}
button{background:#0b7;color:#fff;border:none;cursor:pointer}
.small{font-size:12px;color:#666}
</style></head><body>
  <div class="card">
    <h3>Paras Admin Login</h3>
    <form method="post">
      <div><input name="user" placeholder="Username" required/></div>
      <div style="margin-top:8px"><input name="pass" type="password" placeholder="Password" required/></div>
      <div style="margin-top:10px"><button type="submit">Log in</button></div>
      {% if error %}<p style="color:#c33">{{ error }}</p>{% endif %}
      <p class="small">Use ADMIN_USER / ADMIN_PASS from your .env</p>
    </form>
  </div>
</body></html>
"""

def authed(): return session.get("admin") is True

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("user") == ADMIN_USER and request.form.get("pass") == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin_home"))
        return render_template_string(LOGIN_TMPL, error="Invalid credentials")
    if authed(): return redirect(url_for("admin_home"))
    return render_template_string(LOGIN_TMPL, error=None)

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin", methods=["GET"])
def admin_home():
    if not authed(): return redirect(url_for("admin_login"))
    # Build recent conversations list
    with db() as conn:
        rows = conn.execute("""
            SELECT wa_id, MAX(ts) AS last_ts
            FROM messages
            GROUP BY wa_id
            ORDER BY last_ts DESC
            LIMIT 200
        """).fetchall()
        convs = []
        for r in rows:
            last = conn.execute(
                "SELECT text FROM messages WHERE wa_id=? ORDER BY ts DESC, id DESC LIMIT 1", (r["wa_id"],)
            ).fetchone()
            convs.append({
                "wa_id": r["wa_id"],
                "last_ts": r["last_ts"],
                "preview": (last["text"] if last and last["text"] else "")[:160],
                "paused": is_paused(r["wa_id"])
            })
    return render_template_string(ADMIN_LIST_TMPL, convs=convs)

@app.route("/admin/chat/<wa_id>", methods=["GET","POST"])
def admin_chat(wa_id):
    if not authed(): return redirect(url_for("admin_login"))
    if request.method == "POST":
        text = (request.form.get("text") or "").strip()
        if text:
            send_text(wa_id, text)  # logged automatically
    with db() as conn:
        msgs = conn.execute(
            "SELECT direction, mtype, text, ts FROM messages WHERE wa_id=? ORDER BY ts ASC, id ASC", (wa_id,)
        ).fetchall()
    return render_template_string(ADMIN_CHAT_TMPL, wa_id=wa_id, msgs=msgs, paused=is_paused(wa_id))

@app.route("/admin/toggle", methods=["POST"])
def admin_toggle():
    if not authed(): return redirect(url_for("admin_login"))
    wa_id = request.form.get("wa_id","").strip()
    action = request.form.get("action","")
    if wa_id:
        set_paused(wa_id, action == "pause")
    # redirect back to chat page if referer contains it
    ref = request.headers.get("Referer","")
    if "/admin/chat/" in ref: return redirect(ref)
    return redirect(url_for("admin_home"))

# ----------------- Run server -----------------
@app.route("/webhook", methods=["GET"])
def verify_webhook_alias():
    # alias to keep the single /webhook route top-most in file
    return verify()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
