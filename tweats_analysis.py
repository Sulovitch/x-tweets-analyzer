# =========================================
#        X Tweets Analyzer (One Page)
#   OAuth2 PKCE + Full Analytics Dashboard
# =========================================

# =========================================
#        X Tweets Analyzer (One Page)
#   OAuth2 PKCE + Full Analytics Dashboard
# =========================================

import os, json, requests, secrets, urllib.parse, base64, hashlib
import numpy as np, pandas as pd, matplotlib.pyplot as plt, streamlit as st
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression
from wordcloud import WordCloud
import arabic_reshaper
from bidi.algorithm import get_display
from collections import Counter
import sqlite3
import re
import matplotlib.pyplot as plt
from matplotlib import rcParams
import json
import time




plt.rcParams['font.family'] = ['Arial', 'Segoe UI Emoji']




def init_db():
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()

    # جدول التغريدات
    c.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            username TEXT,
            text TEXT,
            created_at TEXT,
            like_count INTEGER,
            retweet_count INTEGER,
            reply_count INTEGER,
            impression_count INTEGER,
            media_urls TEXT
        )
    """)

    # تأكد من media_urls لو جدول قديم
    c.execute("PRAGMA table_info(tweets)")
    cols = [col[1] for col in c.fetchall()]
    if "media_urls" not in cols:
        try:
            c.execute("ALTER TABLE tweets ADD COLUMN media_urls TEXT")
        except Exception:
            pass

    # جدول التوكنات (لازم يكون برا الـ if)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_tokens (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            access_token TEXT,
            refresh_token TEXT,
            expires_at TEXT,
            last_fetch TEXT
        )
    """)

    # تأكد من last_fetch لو جدول قديم
    c.execute("PRAGMA table_info(user_tokens)")
    cols = [col[1] for col in c.fetchall()]
    if "last_fetch" not in cols:
        try:
            c.execute("ALTER TABLE user_tokens ADD COLUMN last_fetch TEXT")
        except Exception:
            pass

    # جدول oauth_state (اختياري بس مفيد)
    c.execute("""
        CREATE TABLE IF NOT EXISTS oauth_state (
            state TEXT PRIMARY KEY,
            verifier TEXT
        )
    """)

    conn.commit()
    conn.close()
init_db()




def save_tokens_to_db(user_id, username, tokens):
    """احفظ access/refresh + وقت الانتهاء في SQLite"""
    expires_at = None
    try:
        # بعض الاستجابات ترجع expires_in بالثواني
        if "expires_in" in tokens:
            expires_at = (datetime.now() + timedelta(seconds=int(tokens["expires_in"]))).isoformat()
    except Exception:
        pass

    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO user_tokens (user_id, username, access_token, refresh_token, expires_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        tokens.get("access_token"),
        tokens.get("refresh_token"),
        expires_at
    ))
    conn.commit()
    conn.close()

def save_state_to_db(state, verifier):
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS oauth_state (
        state TEXT PRIMARY KEY,
        verifier TEXT
    )
    """)
    c.execute("INSERT OR REPLACE INTO oauth_state (state, verifier) VALUES (?, ?)", (state, verifier))
    conn.commit()
    conn.close()

def load_state_from_db(state):
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    c.execute("SELECT verifier FROM oauth_state WHERE state=?", (state,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def load_tokens_from_db_by_user(user_id):
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    c.execute("SELECT access_token, refresh_token, expires_at, username FROM user_tokens WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "expires_at": row[2],
        "username": row[3]
    }


def load_any_tokens():
    """للتطبيق الشخصي (مستخدم واحد): رجّع أول صف محفوظ لاستخدامه بعد Refresh الصفحة."""
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    c.execute("SELECT user_id, username, access_token, refresh_token, expires_at FROM user_tokens LIMIT 1")
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0],
        "username": row[1],
        "access_token": row[2],
        "refresh_token": row[3],
        "expires_at": row[4]
    }


def refresh_access_token(refresh_token):
    token_url = "https://api.twitter.com/2/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(token_url, data=data, headers=headers, timeout=30)
    return r


def ensure_valid_token():
    """
    - إذا ما فيه access_token بالجلسة → خله فاضي وخلي المستخدم يسجل دخول.
    - إذا فيه expires_at + refresh_token → يحدثه عادي زي أول.
    """
    # لا تحمل أي حساب محفوظ تلقائياً
    if "access_token" not in st.session_state:
        return  

    # تحقق من انتهاء الصلاحية (تقريبي) ثم حدّث
    exp = st.session_state.get("expires_at")
    ref = st.session_state.get("refresh_token")
    if exp and ref:
        try:
            if datetime.fromisoformat(exp) <= datetime.now():
                rr = refresh_access_token(ref)
                if rr.status_code == 200:
                    new_tokens = rr.json()
                    st.session_state["access_token"] = new_tokens["access_token"]

                    # حدث expires_at
                    if "expires_in" in new_tokens:
                        st.session_state["expires_at"] = (
                            datetime.now() + timedelta(seconds=int(new_tokens["expires_in"]))
                        ).isoformat()

                    # خزّن بالداتابيس (إذا فيه user_id/username)
                    if st.session_state.get("user_id") and st.session_state.get("username"):
                        save_tokens_to_db(
                            st.session_state["user_id"],
                            st.session_state["username"],
                            {
                                "access_token": new_tokens["access_token"],
                                "refresh_token": new_tokens.get("refresh_token", ref),
                                "expires_in": new_tokens.get("expires_in"),
                            },
                        )
                else:
                    st.warning("انتهت صلاحية التوكن وتعذّر تحديثه. الرجاء تسجيل الدخول من جديد.")
                    for k in ["access_token", "refresh_token", "expires_at", "user_id", "username"]:
                        st.session_state.pop(k, None)
        except Exception:
            pass


def get_last_fetch(user_id):
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    c.execute("SELECT last_fetch FROM user_tokens WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

def format_last_fetch(last_fetch_date):
    if last_fetch_date and last_fetch_date not in ["— (وضع تجريبي)"]:
        try:
            dt = datetime.fromisoformat(last_fetch_date)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return last_fetch_date
    return last_fetch_date or "—"



# ====== ضبط نمط الرسوم ======
plt.style.use("dark_background")

# ====== أدوات تنسيق عربية ======
def reshape_label(text):
    try:
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return str(text)

def beautify_axes(ax):
    ax.set_facecolor("#0E1117")
    ax.tick_params(colors="white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    ax.title.set_color("#FFD700")

# ====== إعدادات تويتر OAuth ======
CLIENT_ID = st.secrets["CLIENT_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
SCOPE = "tweet.read users.read offline.access"
AUTH_URL = "https://twitter.com/i/oauth2/authorize"

# ====== مخزن لحفظ state/verifier ======
@st.cache_resource
def get_state_store():
    return {}

state_store = get_state_store()

# ====== توليد PKCE ======
def gen_pkce_pair():
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return code_verifier, code_challenge

# ====== ستايل زر الدخول ======
st.markdown(
    """
    <style>
    div.stButton > button {
        background-color: #1DA1F2;
        color: white;
        font-size: 22px;
        font-weight: bold;
        padding: 15px 40px;
        border-radius: 10px;
        border: none;
        cursor: pointer;
        transition: 0.3s;
    }
    div.stButton > button:hover { 
        background-color: #0d8ddb; 
    }
    .center-button {
        display: flex;
        justify-content: center;   /* وسط أفقياً */
        align-items: center;       /* وسط عمودياً */
                    
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ====== شاشة تسجيل الدخول + وضع التجربة (مع وسائط وهمية) ======
if "access_token" not in st.session_state:
    with st.container():
        st.markdown('<div class="center-button">', unsafe_allow_html=True)

        # زر تسجيل الدخول العادي
        if st.button("🔑 سجل الدخول بحساب تويتر"):
            state = secrets.token_urlsafe(16)
            code_verifier, code_challenge = gen_pkce_pair()
            save_state_to_db(state, code_verifier)

            params = {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPE,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "prompt": "consent",
            }
            login_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
            st.markdown(
                f"""<meta http-equiv="refresh" content="0; url={login_url}">""",
                unsafe_allow_html=True,
            )

       # زر وضع التجربة (demo mode) تحت زر تسجيل الدخول
    if st.button("👀 وضع التجربة (عرض تجريبي)"):
        import random
        

        now = datetime.now()

        # جمل متنوعة للتغريدات الوهمية
        samples = [
            "تحديث بسيط عن المشروع: الأمور تتقدم خطوة بخطوة 🛠️",
            "اولاً: شكرًا للفريق على الجهد اليوم 🙏",
            "معلومة سريعة: التقنية تغير شكل العمل بسرعة ⚡",
            "فكرة: ماذا لو ربطنا الخدمة مع API آخر؟ 🤔",
            "لحظة رياضية: مبروك للفريق على الفوز 🏆",
            "نصيحة: ابدأ يومك بخطة صغيرة وسريعة التنفيذ ✅",
            "لقطة من الرحلة اليوم كانت مدهشة ✨",
            "حدث مهم تقني — قريبًا تغطية كاملة.",
            "هل أحد جرب الأداة الجديدة؟ شاركونا رأيكم 👇",
            "اقتباس اليوم: العمل الجماعي يصنع المعجزات."
        ]

        # توزيع على 7 أيام (كل تغريدة تُعطى يوم مختلف تقريباً)
        days_back = list(range(7))  # 0 = اليوم, 6 = قبل أسبوع

        fake_tweets = []
        for i in range(10):
            # اختر يوم عشوائي من الأسبوع وساعة عشوائية
            day_offset = random.choice(days_back)
            created = now - timedelta(days=day_offset, hours=random.randint(0, 23))

            # أضف صورة لبعض التغريدات
            media = []
            if i % 3 == 0:
                media.append(f"https://picsum.photos/seed/demo{i}/800/450")

            fake_tweets.append({
                "id": f"fake_{i+1}",
                "text": samples[i % len(samples)],
                "created_at": created.isoformat(),
                "public_metrics": {
                    "like_count": random.randint(5, 500),
                    "retweet_count": random.randint(0, 120),
                    "reply_count": random.randint(0, 80),
                    "impression_count": random.randint(200, 3000),
                },
                "media_urls": media
            })

        # خزّن وضع التجربة في الجلسة
        st.session_state["tweets_demo"] = fake_tweets
        st.session_state["username"] = "demo_user"
        st.session_state["user_id"] = "demo_id"
        st.session_state["access_token"] = "demo_token"  # لتجاوز شرط التوكن
        st.success("✅ تم تفعيل وضع التجربة")

    st.markdown('</div>', unsafe_allow_html=True)


    # ====== بعد الرجوع من تويتر (OAuth callback) ======
    q = st.query_params
    code, state = q.get("code"), q.get("state")
    if isinstance(code, list): code = code[0]
    if isinstance(state, list): state = state[0]

    if code and state and "access_token" not in st.session_state:
        code_verifier = load_state_from_db(state)
        if not code_verifier:
            st.error("⚠️ state غير معروف. أعد المحاولة.")
            st.stop()

        token_url = "https://api.twitter.com/2/oauth2/token"
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "code_verifier": code_verifier,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        r = requests.post(token_url, data=data, headers=headers, timeout=30)
        tokens = r.json()

        if "access_token" in tokens:
            st.session_state["access_token"] = tokens["access_token"]

            me = requests.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=30
            )
            user_data = me.json().get("data", {})
            st.session_state["user_id"] = user_data.get("id")
            st.session_state["username"] = user_data.get("username")

            # خزّن expires_at/refresh_token في الجلسة والداتابيس
            if "expires_in" in tokens:
                st.session_state["expires_at"] = (datetime.now() + timedelta(seconds=int(tokens["expires_in"]))).isoformat()
            if "refresh_token" in tokens:
                st.session_state["refresh_token"] = tokens["refresh_token"]

            save_tokens_to_db(
                st.session_state["user_id"],
                st.session_state["username"],
                {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens.get("refresh_token"),
                    "expires_in": tokens.get("expires_in")
                }
            )

            # تنظيف الرابط (إزالة query params)
            st.markdown(
                """
                <script>
                if (window.location.search.length > 0) {
                    window.history.replaceState({}, document.title, window.location.pathname);
                }
                </script>
                """,
                unsafe_allow_html=True
            )
        else:
            st.warning(" حاول تسجيل الدخول مرة أخرى")


ensure_valid_token()

# ====== بعد تسجيل الدخول ======
USERNAME = st.session_state.get("username")
BEARER_TOKEN = st.session_state.get("access_token")

if not BEARER_TOKEN:
    st.stop()

#if not USERNAME:
#    st.error("🚨 لم نستطع جلب بيانات المستخدم. قد يكون السبب تجاوز الحد المسموح (429 Too Many Requests).")
 #   st.info("⏳ جرّب بعد فترة أو بعد شهر")
 #   st.stop()









# ====== دوال API ======
def auth_header():
    return {"Authorization": f"Bearer {st.session_state.get('access_token')}"}


def get_user_id(username: str):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    r = requests.get(url, headers=auth_header(), timeout=30)
    if r.status_code == 401 and st.session_state.get("refresh_token"):
        rr = refresh_access_token(st.session_state["refresh_token"])
        if rr.status_code == 200:
            new_tokens = rr.json()
            st.session_state["access_token"] = new_tokens["access_token"]
            if "expires_in" in new_tokens:
                st.session_state["expires_at"] = (datetime.now() + timedelta(seconds=int(new_tokens["expires_in"]))).isoformat()
            # خزّن
            if st.session_state.get("user_id") and st.session_state.get("username"):
                save_tokens_to_db(st.session_state["user_id"], st.session_state["username"], {
                    "access_token": new_tokens["access_token"],
                    "refresh_token": new_tokens.get("refresh_token", st.session_state.get("refresh_token")),
                    "expires_in": new_tokens.get("expires_in")
                })
            # أعد الطلب
            r = requests.get(url, headers=auth_header(), timeout=30)
    r.raise_for_status()
    return r.json()["data"]["id"]


def get_latest_tweets(user_id: str, max_results: int = 80):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets"
    params = {
        "tweet.fields": "public_metrics,created_at,attachments,referenced_tweets,entities",
        "expansions": "attachments.media_keys",
        "media.fields": "url,preview_image_url,type",
        "max_results": min(max_results, 100)
    }
    all_tweets = {}
    next_token = None

    while len(all_tweets) < max_results:
        if next_token:
            params["pagination_token"] = next_token
        elif "pagination_token" in params:
            params.pop("pagination_token")

        r = requests.get(url, headers=auth_header(), params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        tweets = data.get("data", [])
        if not tweets:
            break

        includes_media = {m["media_key"]: m for m in data.get("includes", {}).get("media", [])} if data.get("includes") else {}

        for t in tweets:
            media_urls = []

            # 🟢 الطريقة الرسمية: attachments.media_keys
            atts = t.get("attachments", {})
            if isinstance(atts, dict) and "media_keys" in atts:
                for mk in atts["media_keys"]:
                    m = includes_media.get(mk)
                    if not m:
                        continue
                    if m.get("type") == "photo" and m.get("url"):
                        media_urls.append(m["url"])
                    elif m.get("type") in ["video", "animated_gif"] and m.get("preview_image_url"):
                        media_urls.append(m["preview_image_url"])

            # 🟡 fallback: لو ما فيه media_keys → جرّب entities.urls
            if not media_urls:
                for u in t.get("entities", {}).get("urls", []):
                    expanded = u.get("expanded_url")
                    if expanded and "pbs.twimg.com" in expanded:  # سيرفر صور تويتر
                        media_urls.append(expanded)

            t["media_urls"] = media_urls
            all_tweets[t["id"]] = t

        next_token = data.get("meta", {}).get("next_token")
        if not next_token:
            break

        # 💤 تأخير بسيط قبل الطلب الجاي
        time.sleep(2)

    return sorted(all_tweets.values(), key=lambda t: t.get("created_at", ""), reverse=True)[:max_results]



def save_tweets_to_db(tweets, user_id, username):
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()
    for t in tweets:
        pm = t.get("public_metrics", {}) or {}
        media_json = json.dumps(t.get("media_urls", []), ensure_ascii=False)
        c.execute("""
        INSERT OR REPLACE INTO tweets 
        (id, user_id, username, text, created_at, like_count, retweet_count, reply_count, impression_count, media_urls)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
        t["id"],
        user_id,
        username,
        t.get("text",""),
        t.get("created_at",""),
        pm.get("like_count",0),
        pm.get("retweet_count",0),
        pm.get("reply_count",0),
        pm.get("impression_count",0),
        media_json
    ))

    conn.commit()
    conn.close()


def load_tweets_from_db(username):
    conn = sqlite3.connect("tweets.db")
    c = conn.cursor()

    # تحقق من الأعمدة الموجودة
    c.execute("PRAGMA table_info(tweets)")
    cols = [col[1] for col in c.fetchall()]
    has_media_col = "media_urls" in cols

    if has_media_col:
        c.execute("""
            SELECT id, text, created_at, like_count, retweet_count, reply_count, impression_count, media_urls
            FROM tweets WHERE username=? ORDER BY created_at DESC
        """, (username,))
    else:
        c.execute("""
            SELECT id, text, created_at, like_count, retweet_count, reply_count, impression_count
            FROM tweets WHERE username=? ORDER BY created_at DESC
        """, (username,))

    rows = c.fetchall()
    conn.close()

    tweets = []
    for r in rows:
        if has_media_col:
            media_list = []
            try:
                media_list = json.loads(r[7]) if r[7] else []
            except Exception:
                media_list = []
            tweets.append({
                "id": r[0],
                "text": r[1],
                "created_at": r[2],
                "public_metrics": {
                    "like_count": r[3],
                    "retweet_count": r[4],
                    "reply_count": r[5],
                    "impression_count": r[6],
                },
                "media_urls": media_list
            })
        else:
            tweets.append({
                "id": r[0],
                "text": r[1],
                "created_at": r[2],
                "public_metrics": {
                    "like_count": r[3],
                    "retweet_count": r[4],
                    "reply_count": r[5],
                    "impression_count": r[6],
                },
                "media_urls": []  # ما فيه صور محفوظة في الجدول القديم
            })
    return tweets




# ====== جلب التغريدات ======
if "tweets_demo" in st.session_state:
    # 👀 وضع التجربة
    tweets = st.session_state["tweets_demo"]
    USERNAME = st.session_state.get("username", "demo_user")
    last_fetch_date = "— (وضع تجريبي)"

    st.sidebar.success("✅ أنت تستخدم وضع التجربة (بيانات وهمية)")
else:
    # 👤 الوضع العادي
    tweets = load_tweets_from_db(USERNAME)

    last_fetch_date = None

    current_user_id = st.session_state.get("user_id")
    last_fetch_date = get_last_fetch(current_user_id) if current_user_id else None


    # تحقق من إمكانية التحديث
    can_update = False
    if not last_fetch_date:
        can_update = True
    else:
        try:
            last_dt = datetime.fromisoformat(last_fetch_date)
            if (datetime.now().date() - last_dt.date()).days >= 1:
                can_update = True
        except Exception:
            # لو التاريخ مخرب، اسمح بالتحديث مرة واحدة ثم بيتصلح
            can_update = True


    if can_update:
        if st.sidebar.button("🔄 تحديث البيانات الآن"):
            try:
                user_id = get_user_id(USERNAME)
                new_tweets = get_latest_tweets(user_id, max_results=90)
                save_tweets_to_db(new_tweets, user_id, USERNAME)

                conn = sqlite3.connect("tweets.db")
                c = conn.cursor()
                c.execute("""
                    UPDATE user_tokens
                    SET last_fetch=?
                    WHERE user_id=?
                """, (datetime.now().isoformat(), user_id))
                conn.commit()
                conn.close()

                tweets = load_tweets_from_db(USERNAME)
                st.success(f"✅ تم تحديث البيانات ({len(new_tweets)} تغريدة جديدة) — المجموع الآن {len(tweets)}")
            except Exception as e:
                st.error(f"⚠️ خطأ أثناء التحديث: {e}")
                st.stop()
    else:
        st.sidebar.info("⏳ آخر تحديث محفوظ. 🔔 تقدر تحدث بعد مرور 24 ساعة.")

# ====== تحقق لو مافيه بيانات ======
if not tweets:
    if "tweets_demo" in st.session_state:
        st.warning("⚠️ لا توجد بيانات تجريبية (تأكد من زر 👀 وضع التجربة).")
    else:
        st.warning("⚠️ لا توجد بيانات بعد. جرّب تحديث البيانات أو سجل الدخول.")
    st.stop()

# 🔄 تنسيق التاريخ (مرة وحدة فقط)
formatted = format_last_fetch(last_fetch_date)


# ====== عرض في الـ sidebar ======
st.sidebar.header("🔑 حسابك")
st.sidebar.success(f"✅ متصل كـ @{USERNAME}")

tweets_count = len(tweets) if 'tweets' in locals() else 0

st.sidebar.markdown("### 📊 حالة البيانات")
st.sidebar.info(f"""
- 📝 عدد التغريدات: **{tweets_count}**
- 🗓️ آخر تحديث: **{formatted}**
""")


# ====== تجهيز DataFrame ======
def build_dataframe(raw_tweets):
    rows = []
    for t in raw_tweets:
        pm = t.get("public_metrics", {}) or {}
        created_dt = datetime.fromisoformat(t["created_at"].replace("Z","+00:00")) if t.get("created_at") else None
        created_str = created_dt.strftime("%Y-%m-%d %H:%M") if created_dt else ""
        is_reply = False
        if str(t.get("text","")).strip().startswith("@"):
            is_reply = True
        for ref in t.get("referenced_tweets",[]) or []:
            if ref.get("type")=="replied_to":
                is_reply = True
                break
        media_urls = t.get("media_urls",[]) or []
        rows.append({
            "id": t.get("id",""),
            "النص": t.get("text",""),
            "تاريخ النشر": created_str,
            "DT": created_dt,
            "الإعجابات": pm.get("like_count",0),
            "الريتويت": pm.get("retweet_count",0),
            "الردود": pm.get("reply_count",0),
            "عدد المشاهدات": pm.get("impression_count",0),
            "إجمالي التفاعل": pm.get("like_count",0)+pm.get("retweet_count",0)+pm.get("reply_count",0),
            "نسبة التفاعل (%)": 0.0,
            "has_media": len(media_urls)>0,
            "media_urls": media_urls,
            "is_reply": is_reply
        })
    df_ = pd.DataFrame(rows)
    df_["نسبة التفاعل (%)"] = np.where(
        df_["عدد المشاهدات"]>0,
        (df_["إجمالي التفاعل"]/df_["عدد المشاهدات"]*100).round(2),
        0.0
    )
    return df_

df = build_dataframe(tweets)

# ====== تبويبات الواجهة ======
tab1, tab2 = st.tabs(["📊 تحليل التفاعل", "🔎 تحليل الحساب"])

# =========================================================
#                       لوحة التحليل
# =========================================================
with tab1:
    st.title("📊 لوحة تحكم تحليل التغريدات")

    # --- فلاتر العرض ---
    st.subheader("🔍 فلاتر")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        keyword = st.text_input("ابحث عن كلمة (نص التغريدة)")
    with col_f2:
        date_min = st.date_input("من تاريخ", value=(df["DT"].min().date() if df["DT"].notna().any() else datetime.now().date()))
    with col_f3:
        date_max = st.date_input("إلى تاريخ", value=(df["DT"].max().date() if df["DT"].notna().any() else datetime.now().date()))

    col_f4, col_f5, col_f6 = st.columns(3)
    with col_f4:
        max_eng = int(df["إجمالي التفاعل"].max() or 0)
        if max_eng == 0:
            max_eng = 1  # عشان ما يصير min=max

        min_eng = st.slider(
            "الحد الأدنى لإجمالي التفاعل",
            0,
            max_eng,
            0
        )

    with col_f5:
        kind = st.selectbox("نوع التغريدة", ["الكل", "تغريدات أصلية فقط", "منشن فقط"])
    with col_f6:
        only_media = st.checkbox("📷 عرض التغريدات التي تحتوي وسائط فقط", key="filter_media_checkbox")
        only_charts = st.checkbox(
        "📊 عرض الرسوم فقط",
        value=False,
        help="إذا فعلت هذا الخيار سيتم إخفاء بطاقات التغريدات"
    )
    
    

    # تطبيق الفلاتر
    filtered = df.copy()
    filtered = filtered[(filtered["DT"].dt.date >= date_min) & (filtered["DT"].dt.date <= date_max)]
    if keyword:
        filtered = filtered[filtered["النص"].str.contains(keyword, case=False, na=False)]
    if min_eng > 0:
        filtered = filtered[filtered["إجمالي التفاعل"] >= min_eng]
    if kind == "تغريدات أصلية فقط":
        filtered = filtered[filtered["is_reply"] == False]
    elif kind == "منشن فقط":
        filtered = filtered[filtered["is_reply"] == True]
    if only_media:
        filtered = filtered[filtered["has_media"] == True]

    st.write(f"تم العثور على **{len(filtered)}** تغريدة مطابقة")

    if filtered.empty:
        st.warning("⚠️ لا توجد تغريدات مطابقة بعد تطبيق الفلاتر.")
        st.stop()

    # --- مؤشر التفاعل العام ---
    st.subheader("📈 مؤشر التفاعل العام (Engagement Index)")
    st.caption("مؤشر سريع: إجمالي التفاعل ÷ عدد المشاهدات عبر الفترة المفلترة.")
    total_eng = int(filtered["إجمالي التفاعل"].sum())
    total_impr = int(filtered["عدد المشاهدات"].sum())
    ei = (total_eng / total_impr * 100) if total_impr > 0 else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("إجمالي التفاعل", f"{total_eng:,}")
    c2.metric("إجمالي المشاهدات", f"{total_impr:,}")
    c3.metric("نسبة التفاعل الكلية", f"{ei:.2f}%")

    # --- عرض التغريدات كبطاقات ---
    st.subheader("📝 قائمة التغريدات")
    st.caption("كل بطاقة تعرض أهم أرقام التغريدة مع رابط مباشر وصور إن وجدت.")

    # --- عرض بطاقات التغريدات ---
    if not only_charts:
        for _, row in filtered.iterrows():
            tweet_url = f"https://twitter.com/{USERNAME}/status/{row['id']}"
            st.markdown(
                f"""
                <div style='direction: rtl; text-align: right; border:1px solid #444; border-radius:10px; padding:10px; margin-bottom:8px;'>
                <b>النص:</b> {row['النص']}<br>
                <b>📅 تاريخ النشر:</b> {row['تاريخ النشر']}<br>
                ❤️ <b>{row['الإعجابات']}</b> | 🔁 <b>{row['الريتويت']}</b> | 💬 <b>{row['الردود']}</b> |
                👀 <b>{row['عدد المشاهدات']}</b> | 📊 <b>إجمالي: {row['إجمالي التفاعل']}</b> | % <b>{row['نسبة التفاعل (%)']}</b><br>
                🔗 <a href="{tweet_url}" target="_blank">فتح التغريدة على X</a>
                </div>
                """,
                unsafe_allow_html=True
            )
            if row["has_media"]:
                for m in row["media_urls"]:
                    st.image(m, use_container_width=True)



    else:
        st.info("🗂️ تم إخفاء بطاقات التغريدات لانك مفعل عرض الرسوم فقط")

    # ✅ الرسوم أصبحت دائمًا ظاهرة بغض النظر عن show_cards

    st.subheader("🔥 أكثر التغريدات تفاعلًا")
    st.caption("أفضل 10 تغريدات حسب إجمالي التفاعل.")
    top10 = filtered.sort_values(by="إجمالي التفاعل", ascending=False).head(10)
    if len(top10) > 0:
        fig, ax = plt.subplots()
        ax.barh([reshape_label(str(t)[:50]) for t in top10["النص"]], top10["إجمالي التفاعل"])
        ax.set_xlabel(reshape_label("إجمالي التفاعل")); ax.set_ylabel(reshape_label("النص"))
        beautify_axes(ax)
        st.pyplot(fig)
    else:
        st.info("لا توجد تغريدات كافية للرسم.")

    st.subheader("⏰ أفضل ساعات النشر (متوسط التفاعل)")
    st.caption("متوسط إجمالي التفاعل لكل ساعة نشر.")
    if filtered["DT"].notna().any():
        filtered["ساعة"] = filtered["DT"].dt.hour
        hourly = filtered.groupby("ساعة")["إجمالي التفاعل"].mean()
        fig2, ax2 = plt.subplots()
        hourly.plot(kind="bar", ax=ax2)
        ax2.set_xlabel(reshape_label("ساعة النشر")); ax2.set_ylabel(reshape_label("متوسط التفاعل"))
        beautify_axes(ax2)
        st.pyplot(fig2)
    else:
        st.info("لا توجد تواريخ صالحة.")

    st.subheader("📈 أعلى نسب التفاعل")
    st.caption("أفضل 10 تغريدات حسب نسبة التفاعل (التفاعل ÷ المشاهدات).")
    top_rate = filtered.sort_values(by="نسبة التفاعل (%)", ascending=False).head(10)
    if len(top_rate) > 0:
        fig3, ax3 = plt.subplots()
        ax3.barh([reshape_label(str(t)[:50]) for t in top_rate["النص"]], top_rate["نسبة التفاعل (%)"])
        ax3.set_xlabel(reshape_label("نسبة التفاعل (%)"))
        beautify_axes(ax3)
        st.pyplot(fig3)
    else:
        st.info("لا توجد بيانات كافية.")

    # --- Heatmap ---
    st.subheader("📅 أفضل الأوقات للنشر (Heatmap)")
    st.caption("متوسط التفاعل حسب اليوم والساعة.")
    tmp = filtered.copy()
    if not tmp.empty:
        if "تاريخ النشر_DT" not in tmp.columns:
            tmp["تاريخ النشر_DT"] = pd.to_datetime(tmp["تاريخ النشر"], errors="coerce")
        tmp["اليوم_انجليزي"] = tmp["تاريخ النشر_DT"].dt.day_name()
        tmp["اليوم"] = tmp["اليوم_انجليزي"].map({
            "Sunday": "الأحد", "Monday": "الاثنين", "Tuesday": "الثلاثاء",
            "Wednesday": "الأربعاء", "Thursday": "الخميس", "Friday": "الجمعة", "Saturday": "السبت"
        })
        tmp["الساعة"] = tmp["تاريخ النشر_DT"].dt.hour
        pivot_table = tmp.pivot_table(index="اليوم", columns="الساعة", values="إجمالي التفاعل", aggfunc="mean", fill_value=0)
        if pivot_table.empty:
            st.info("لا توجد بيانات كافية لإنشاء Heatmap.")
        else:
            days_order = ["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"]
            pivot_table = pivot_table.reindex(days_order)
            fig_hm, ax_hm = plt.subplots(figsize=(10, 5))
            cax = ax_hm.imshow(pivot_table, cmap="YlOrRd", aspect="auto")
            ax_hm.set_yticks(range(len(pivot_table.index)))
            ax_hm.set_yticklabels([reshape_label(day) for day in pivot_table.index])
            ax_hm.set_xticks(range(len(pivot_table.columns)))
            ax_hm.set_xticklabels([reshape_label(str(col)) for col in pivot_table.columns], rotation=90)
            ax_hm.set_xlabel(reshape_label("الساعة")); ax_hm.set_ylabel(reshape_label("اليوم"))
            ax_hm.set_title(reshape_label("معدل التفاعل حسب اليوم والساعة"))
            fig_hm.colorbar(cax, ax=ax_hm, label=reshape_label("متوسط التفاعل"))
            beautify_axes(ax_hm)
            st.pyplot(fig_hm)
    else:
        st.info("لا توجد بيانات كافية.")

    # --- توقع الأداء ---
    st.subheader("🔮 توقع الأداء المستقبلي")
    st.caption("علاقة خطية بين المشاهدات والتفاعل لتقدير التفاعل المتوقع.")
    if len(filtered) >= 4 and filtered["عدد المشاهدات"].sum() > 0:
        X = np.array(filtered["عدد المشاهدات"]).reshape(-1, 1)
        y = np.array(filtered["إجمالي التفاعل"])
        try:
            model = LinearRegression().fit(X, y)
            st.info(f"معامل الانحدار: {model.coef_[0]:.4f} | الثابت: {model.intercept_:.2f}")
            future_impr = st.number_input("عدد المشاهدات المتوقعة:", min_value=0, value=500, step=50)
            pred = model.predict([[future_impr]])[0]
            st.success(f"التفاعل المتوقع: {pred:.0f}")

            fig_lr, ax_lr = plt.subplots()
            ax_lr.scatter(X, y, label=reshape_label("التغريدات"))
            x_line = np.linspace(X.min(), X.max(), 100).reshape(-1, 1)
            ax_lr.plot(x_line, model.predict(x_line), label=reshape_label("خط الانحدار"))
            ax_lr.set_xlabel(reshape_label("عدد المشاهدات")); ax_lr.set_ylabel(reshape_label("إجمالي التفاعل"))
            ax_lr.legend()
            beautify_axes(ax_lr)
            st.pyplot(fig_lr)
        except Exception as e:
            st.warning(f"تعذّر تدريب نموذج الانحدار: {e}")
    else:
        st.info("تحتاج على الأقل 4 تغريدات ذات مشاهدات > 0 لتدريب النموذج.")

    # --- سحابة الكلمات ---
    st.subheader("☁️ أكثر الكلمات استخدامًا")
    st.caption("يتم تنظيف الروابط والمنشن والكلمات الوقفية قبل حساب التكرار.")
    word_counts = {}
    if not filtered.empty:
        for _, row in filtered.iterrows():
            text = re.sub(r"http\S+|www\S+|@\S+", "", str(row["النص"]))
            words = text.split()
            for w in words:
                w = w.strip().lower()
                if w.startswith("ال"):
                    w = w[2:]
                if w in {"في","على","من","عن","الى","إلى","و","او","أو","ما","لا","هذا","هذه","ذلك","هذي","هذيك"}:
                    continue
                if w:
                    word_counts[reshape_label(w)] = word_counts.get(reshape_label(w), 0) + 1

    if word_counts:
        try:
            wordcloud = WordCloud(font_path="arial.ttf", width=1200, height=600,
                                background_color="white", max_words=100, min_font_size=14,
                                colormap="plasma").generate_from_frequencies(word_counts)
            fig_wc, ax_wc = plt.subplots(figsize=(12, 6))
            ax_wc.imshow(wordcloud, interpolation="bilinear"); ax_wc.axis("off")
            st.pyplot(fig_wc)
        except Exception:
            st.info("تعذّر توليد سحابة الكلمات (تأكد من وجود خط عربي مثل arial.ttf).")

        st.markdown("### 🏆 الكلمات الأكثر تكراراً")
        top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        top_df = pd.DataFrame(top_words, columns=["الكلمة", "عدد التكرارات"])
        top_df["الكلمة"] = top_df["الكلمة"].apply(reshape_label)
        st.markdown(top_df.to_html(index=False, justify="right"), unsafe_allow_html=True)
    else:
        st.info("لا توجد كلمات كافية بعد التنظيف.")

   

# =========================================================
#                       تحليل الحساب
# =========================================================
with tab2:
    st.title("🔎 تحليل الحساب الشامل")
    st.info("هذه التبويبة تعرض تحليلات معمّقة: أسلوب الكتابة، الهاشتاقات، الروابط، الوسائط، المشاعر، والـ n-grams.")

    # --- تجهيز DF مخصص للتحليل (مبني على الفلاتر من التاب 1) ---
    @st.cache_data
    def prepare_profile_dataframe(tweets_local):
        rows = []
        for t in tweets_local:
            created_dt = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) if t.get("created_at") else None
            created_str = created_dt.strftime("%Y-%m-%d %H:%M") if created_dt else ""
            txt = str(t.get("text", ""))

            rows.append({
                "id": t.get("id", ""),
                "النص": txt,
                "تاريخ النشر": created_str,
                "DT": created_dt,
                "hashtags": re.findall(r"#(\w+)", txt),
                "mentions": re.findall(r"@(\w+)", txt),
                "contains_link": bool(re.search(r"http\S+", txt)),
                "links": re.findall(r"http[s]?://[^\s]+", txt),
                "is_reply": str(txt).strip().startswith("@"),
                "has_media": len(t.get("media_urls", []) or []) > 0,
                "media_urls": t.get("media_urls", []) or []
            })
        return pd.DataFrame(rows)

    # ✅ استخدم فقط التغريدات المفلترة
    filtered_ids = set(filtered["id"].astype(str))
    tweets_filtered_raw = [t for t in tweets if str(t.get("id", "")) in filtered_ids]
    pdf = prepare_profile_dataframe(tweets_filtered_raw)

    # 🔒 أضف فحص هنا قبل أي رسم أو تحليل
    if pdf.empty:
        st.warning("⚠️ لا توجد بيانات مطابقة بعد تطبيق الفلاتر لعرض التحليلات.")
        st.stop()

    
    # =============== تحليل المشاعر =============== 
        
    # --- قاموس مشاعر عربي موسّع مع كلمات عامية ---
    AR_POS = {
        # رسمي + فصيح
        "ممتاز","جميل","رائع","أفضل","مميز","شكرا","سعيد","محبوب","نجاح","حلو","فاخر","قوي","مفيد",
        "مبهج","مفرح","مسرور","مريح","لطيف","مطمئن","مبهر","مذهل","عظيم","سوبر","عبقري","مثالي",
        "محترم","راقي","بطل","مكسب","متفوق","هيبة","فرحة","مرح","مبروك","موفق","رابح","مربح",
        "ساحر","مشرق","مميز","قوي","شجاع","إيجابي","مريح","جميل","متحمس","مسرحي","سلام","حب","خير",
        "واو","مذهوول","فل","خرافي","اسطوري","خورافي","جنان","روعة","تحفة","خيال","قنبلة","فايف_ستار",
        "جامد","كفو","سطوري","فنان","بطل","حماس","فلة","مزيان","جيد","رايق","عالمي","توب","سوبر","قوييي",
        "فلّة","قلب","كويس","زين","طرب","طقطقه حلوه","فنان","ممتازة","مرتب","رهيب","شيك","مهيب","عجبني"
    }

    AR_NEG = {
        # رسمي + فصيح
        "سيء","سئ","رديء","أسوأ","حزين","خسارة","فشل","مزيف","ضعيف","زعج","إزعاج","كارثي","غلط",
        "مزعج","متعب","مقرف","ممل","مؤلم","محبط","بشع","حقد","كراهية","عداء","مأساة","كارثة","سلبية",
        "ضياع","قلة","فوضى","جرح","خوف","مصيبة","كسر","عنف","ظلم","مشكلة","ضعف","هزيمة","كئيب",
        "معاناة","بائس","مقزز","سم","أذى","مرعب","غضب","لعنة","عار","خيبة","فضيحة","مأساوي","مزعجة",
        # عامية + تويتر
        "قهر","طفش","خايس","بايخ","زفت","خايص","شين","تعب","هم","نكد","مقلب","غباء","خراب","تافه",
        "مسخرة","بلاء","نرفزة","قرف","تعبان","طفشان","يا ساتر","بربسة","مغبون","قحط","ملل","ملل","دمار",
        "طيحني","فشلني","مطفوق","قرفان","سمج","كريه","نرفز","خرا","زعلان","منحوس","مخيس","خازوق","شنيع"
    }

    EN_POS = {
    "good","great","awesome","amazing","love","like","nice","happy","perfect","excellent","cool",
    "win","strong","helpful","fantastic","wonderful","brilliant","super","genius","epic","respect",
    "best","top","success","profit","joy","fun","wow","outstanding","positive","cheer","bless","safe",
    "bright","hero","masterpiece","congrats","peace","hope","gift","advantage","benefit","enjoy","smile",
    }

    EN_NEG = {
        "bad","worse","worst","sad","angry","hate","disappoint","fake","weak","annoy","terrible","awful",
        "fail","loss","mess","broken","pain","boring","useless","stupid","lazy","ugly","trouble","risk",
        "fear","danger","negative","cry","problem","miss","chaos","harm","toxic","slow","sucks","hate","mad",
        "angry","depress","scary","nightmare","down","damage","fraud","spam","junk","block","poor",
    }

    def normalize_ar(text: str) -> str:
        s = str(text)

        # إزالة الروابط والمنشن والهاشتاقات
        s = re.sub(r"http\S+|www\S+|@\S+", " ", s)
        s = re.sub(r"#", " ", s)

        # إزالة التشكيل والمدود
        s = re.sub(r"[\u0617-\u061A\u064B-\u0652\u0670\u06D6-\u06ED\u0640]", "", s)

        # توحيد الهمزات
        s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")

        # توحيد الياء والألف المقصورة
        s = s.replace("ى", "ي")

        # توحيد الهاء والتاء المربوطة
        s = s.replace("ة", "ه")

        # إزالة تكرار الحروف أكثر من مرتين (رااااائع → رائع)
        s = re.sub(r"(.)\1{2,}", r"\1", s)

        # مسافات نظيفة
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s


    def simple_sentiment(text: str) -> int:
        """يرجع: 1 إيجابي، -1 سلبي، 0 محايد."""
        t = normalize_ar(text)
        toks = re.findall(r"[a-zA-Z\u0600-\u06FF]+", t)
        score = 0
        for w in toks:
            lw = w.lower()
            if lw in AR_POS or lw in EN_POS: score += 1
            if lw in AR_NEG or lw in EN_NEG: score -= 1
        if score > 0: return 1
        if score < 0: return -1
        return 0


    # =============== تحليل النشاط الزمني ===============
    st.subheader("🕒 النشاط الزمني")
    st.caption("توزيع التغريدات على أيام الأسبوع وساعات اليوم + متوسط التغريد اليومي.")
    if not pdf.empty:
        pdf["اليوم"] = pdf["DT"].dt.day_name()
        day_map = {"Sunday":"الأحد", "Monday":"الاثنين", "Tuesday":"الثلاثاء",
                   "Wednesday":"الأربعاء", "Thursday":"الخميس", "Friday":"الجمعة", "Saturday":"السبت"}
        pdf["اليوم"] = pdf["اليوم"].map(day_map)

        fig_day, ax_day = plt.subplots()
        pdf["اليوم"].value_counts().reindex(day_map.values()).plot(kind="bar", ax=ax_day)
        ax_day.set_xticklabels([reshape_label(lbl.get_text()) for lbl in ax_day.get_xticklabels()])
        ax_day.set_xlabel(reshape_label("اليوم")); ax_day.set_ylabel(reshape_label("عدد التغريدات"))
        ax_day.set_title(reshape_label("توزيع التغريدات على أيام الأسبوع"))
        beautify_axes(ax_day); st.pyplot(fig_day)

        pdf["ساعة"] = pdf["DT"].dt.hour
        fig_hour, ax_hour = plt.subplots()
        pdf["ساعة"].value_counts().sort_index().plot(kind="bar", ax=ax_hour)
        ax_hour.set_xticklabels([reshape_label(lbl.get_text()) for lbl in ax_hour.get_xticklabels()])
        ax_hour.set_xlabel(reshape_label("الساعة")); ax_hour.set_ylabel(reshape_label("عدد التغريدات"))
        ax_hour.set_title(reshape_label("توزيع التغريدات على ساعات اليوم"))
        beautify_axes(ax_hour); st.pyplot(fig_hour)

        tweets_per_day = pdf.groupby(pdf["DT"].dt.date).size()
        st.metric("متوسط التغريد يوميًا", f"{tweets_per_day.mean():.2f} تغريدة/يوم")
    else:
        st.info("لا توجد بيانات بعد تطبيق الفلاتر.")

    # =============== تحليل الأسلوب ===============
    # =============== تحليل الأسلوب (مطور) ===============
    st.subheader("📝 تحليل الأسلوب")
    st.caption("تحليل مفصّل لأسلوب الكتابة: طول النصوص، الكلمات، الجمل، استخدام الرموز، الهاشتاقات، الروابط، تنوع الكلمات، والمشاعر.")

    style_df = filtered.copy()  # ✅ استخدم البيانات المفلترة
    if not style_df.empty:
        # --- حساب مقاييس أساسية ---
        style_df["طول_النص"] = style_df["النص"].astype(str).str.len()
        style_df["عدد_الكلمات"] = style_df["النص"].astype(str).str.split().apply(len)
        style_df["عدد_الجمل"] = style_df["النص"].str.count(r"[.!؟!]")
        style_df["فيه_سؤال"] = style_df["النص"].str.contains(r"\?", regex=True)
        style_df["فيه_تعجب"] = style_df["النص"].str.contains(r"!", regex=True)
        style_df["فيه_نقطتين"] = style_df["النص"].str.contains(":")
        style_df["عدد_الهاشتاقات"] = style_df["النص"].str.count(r"#\w+")
        style_df["عدد_الروابط"] = style_df["النص"].str.count(r"http[s]?://")
        emoji_pattern = r"[\U0001F300-\U0001FAD6\U0001F900-\U0001F9FF\U00002600-\U000026FF]"
        style_df["عدد_الإيموجي"] = style_df["النص"].str.count(emoji_pattern)

        # --- بطاقات المؤشرات ---
        c1, c2, c3 = st.columns(3)
        c1.metric("متوسط طول التغريدة", f"{style_df['طول_النص'].mean():.1f} حرف")
        c2.metric("متوسط عدد الكلمات", f"{style_df['عدد_الكلمات'].mean():.1f}")
        c3.metric("نسبة الردود", f"{style_df['is_reply'].mean()*100:.1f}%")

        c4, c5, c6 = st.columns(3)
        c4.metric("متوسط عدد الجمل", f"{style_df['عدد_الجمل'].mean():.1f} جملة")
        c5.metric("متوسط عدد الهاشتاقات", f"{style_df['عدد_الهاشتاقات'].mean():.2f}")
        c6.metric("متوسط عدد الروابط", f"{style_df['عدد_الروابط'].mean():.2f}")

        c7, c8, c9 = st.columns(3)
        c7.metric("نسبة استخدام التعجب", f"{style_df['فيه_تعجب'].mean()*100:.1f}%")
        c8.metric("نسبة استخدام السؤال", f"{style_df['فيه_سؤال'].mean()*100:.1f}%")
        c9.metric("نسبة استخدام النقطتين", f"{style_df['فيه_نقطتين'].mean()*100:.1f}%")

        # --- مؤشر تنوع الكلمات ---
        all_words = " ".join(style_df["النص"].astype(str)).split()
        unique_words = set(all_words)
        lexical_diversity = len(unique_words) / len(all_words) if len(all_words) > 0 else 0
        st.metric("📊 مؤشر تنوع الكلمات", f"{lexical_diversity*100:.1f}%")

        # --- رسم توزيع طول التغريدات ---
        st.caption("توزيع طول التغريدات (حروف).")
        fig_len, ax_len = plt.subplots()
        style_df["طول_النص"].plot(kind="hist", bins=20, ax=ax_len)
        ax_len.set_xlabel(reshape_label("طول النص")); ax_len.set_ylabel(reshape_label("عدد التغريدات"))
        beautify_axes(ax_len); st.pyplot(fig_len)

        # --- تحليل الإيموجي الأكثر استخداماً ---
        import re
        all_emojis = "".join(re.findall(emoji_pattern, " ".join(style_df["النص"].astype(str))))
        from collections import Counter
        emoji_counts = Counter(all_emojis)
        if emoji_counts:
            st.markdown("### 😍 الإيموجي الأكثر استخداماً")
            top_emoji = pd.DataFrame(emoji_counts.most_common(10), columns=["الإيموجي","التكرار"])
            st.dataframe(top_emoji)
        else:
            st.info("لا توجد إيموجيات كافية لعرضها.")

        # --- ملخص مشاعر سريع داخل تحليل الأسلوب ---
        st.markdown("### 😊 توزيع المشاعر (مبسّط)")
        style_df["sentiment"] = style_df["النص"].apply(simple_sentiment)
        sent_dist = style_df["sentiment"].map({1:"إيجابي",0:"محايد",-1:"سلبي"}).value_counts(normalize=True)
        st.bar_chart(sent_dist)
    else:
        st.info("لا توجد بيانات لتحليل الأسلوب بعد تطبيق الفلاتر.")
    

    # --- عرض الكلمات الإيجابية والسلبية الفعلية من التغريدات ---
    from collections import Counter

    pos_counter = Counter()
    neg_counter = Counter()

    # --- حساب التكرار فقط ---
    for txt in style_df["النص"]:
        normalized = normalize_ar(txt)
        words = re.findall(r"[a-zA-Z\u0600-\u06FF]+", normalized)
        for w in words:
            if w in AR_POS:
                pos_counter[w] += 1
            elif w in AR_NEG:
                neg_counter[w] += 1

    # --- عرض النتائج مرة واحدة فقط ---
    st.subheader("📊 الكلمات الإيجابية والسلبية في التغريدات المفلترة")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### ✅ الكلمات الإيجابية الأكثر تكراراً")
        if pos_counter:
            pos_df = pd.DataFrame(pos_counter.most_common(20), columns=["الكلمة","عدد التكرار"])
            st.dataframe(pos_df)
        else:
            st.info("لا توجد كلمات إيجابية في التغريدات المفلترة.")

    with col2:
        st.markdown("### ❌ الكلمات السلبية الأكثر تكراراً")
        if neg_counter:
            neg_df = pd.DataFrame(neg_counter.most_common(20), columns=["الكلمة","عدد التكرار"])
            st.dataframe(neg_df)
        else:
            st.info("لا توجد كلمات سلبية في التغريدات المفلترة.")




    # =============== تحليل الوسائط ===============
    st.subheader("🎥 تأثير الوسائط")

    media_grp = filtered.groupby("has_media")["إجمالي التفاعل"].mean().rename({False: reshape_label("بدون وسائط"), True: reshape_label("مع وسائط")})

    if not media_grp.empty:
        fig_media, ax_media = plt.subplots()
        media_grp.plot(kind="bar", ax=ax_media)
        ax_media.set_xlabel(reshape_label("الوسائط"))
        ax_media.set_ylabel(reshape_label("متوسط إجمالي التفاعل"))
        beautify_axes(ax_media)
        st.pyplot(fig_media)
    else:
        st.info("لا توجد بيانات كافية لتحليل الوسائط بعد تطبيق الفلاتر.")


    # =============== تحليل الهاشتاقات ===============
    st.subheader("🏷️ أداء الهاشتاقات")
    tag_rows = []
    for _, r in filtered.iterrows():  # ✅ استخدم المفلتر
        tags = re.findall(r"#(\w+)", str(r["النص"]))
        for t in tags:
            tag_rows.append({"hashtag": t.lower(), "eng": r["إجمالي التفاعل"]})
    if tag_rows:
        tag_df = pd.DataFrame(tag_rows)
        top_use = tag_df["hashtag"].value_counts().head(15)
        st.bar_chart(top_use)

        perf = tag_df.groupby("hashtag")["eng"].mean().sort_values(ascending=False).head(15)
        st.markdown("### 🔝 أفضل 15 هاشتاق حسب **متوسط التفاعل**")
        st.dataframe(perf.reset_index().rename(columns={"hashtag":"الهاشتاق","eng":"متوسط التفاعل"}))
    else:
        st.info("لا توجد هاشتاقات كافية للتحليل.")



    # =============== تحليل الروابط ===============
    st.subheader("🔗 تحليل الروابط")
    st.caption("أكثر النطاقات تكرارًا في الروابط داخل تغريداتك.")
    all_links = [l for links in pdf["links"] for l in links]
    if all_links:
        domains = pd.Series([re.sub(r"https?://(www\.)?", "", l).split("/")[0] for l in all_links])
        dom_counts = domains.value_counts().head(15)
        st.bar_chart(dom_counts)
        st.markdown("### جدول النطاقات الأكثر تكرارًا")
        st.dataframe(dom_counts.reset_index().rename(columns={"index":"النطاق", 0:"عدد الروابط"}))
    else:
        st.info("لا توجد روابط كافية.")

    # =============== Bigram / Trigram ===============
    st.subheader("📚 أكثر العبارات تكراراً (Bigram / Trigram)")
    st.caption("نطبّع النص العربي ونزيل الروابط والمنشن والكلمات الوقفية، ثم نعرض أكثر العبارات شيوعاً.")

    from collections import Counter

    AR_STOP = {
        "في","على","من","عن","الى","إلى","و","او","أو","ما","لا","هذا","هذه","ذلك","هذي","هذيك",
        "انا","أنا","انت","أنت","هو","هي","هم","هن","مع","تم","عن","قد","كان","كانت","كيف","ليش","ليه",
        "the","a","an","and","or","to","of","for","in","on","with","is","are","am","it","this","that"
    }

    def normalize_ar(text: str) -> str:
        s = str(text)
        s = re.sub(r"http\S+|www\S+|@\S+", " ", s)
        s = re.sub(r"#", " ", s)
        s = re.sub(r"[\u0617-\u061A\u064B-\u0652\u0670\u06D6-\u06ED\u0640]", "", s)
        s = s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ؤ","و").replace("ئ","ي").replace("ة","ه")
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    def tokenize(text: str):
        s = normalize_ar(text)
        tokens = re.findall(r"[a-zA-Z\u0600-\u06FF]+", s)
        return [t for t in tokens if len(t) >= 2 and t not in AR_STOP]

    def ngrams_from_tokens(tokens, n=2):
        return [" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)] if len(tokens) >= n else []

    def count_ngrams(series_text, n=2) -> Counter:
        c = Counter()
        for txt in series_text:
            toks = tokenize(txt)
            c.update(ngrams_from_tokens(toks, n=n))
        return c

    @st.cache_data
    def count_ngrams_cached(series_text, n=2):
        return count_ngrams(series_text, n)

    def plot_top_counter(counter: Counter, title: str, k: int = 10):
        items = counter.most_common(k)
        if not items:
            st.info("لا توجد عبارات كافية بعد التنظيف.")
            return
        labels = [reshape_label(t) for t, _ in items]
        values = [v for _, v in items]
        fig, ax = plt.subplots()
        ax.barh(labels, values)
        ax.set_xlabel(reshape_label("التكرار"))
        ax.set_title(reshape_label(title))
        beautify_axes(ax)
        st.pyplot(fig)
        st.dataframe(pd.DataFrame(items, columns=["العبارة","التكرار"]))

    # استخدام الدوال
    bigrams = count_ngrams_cached(pdf["النص"], n=2)
    plot_top_counter(bigrams, "أكثر Bigram تكراراً", k=10)

    trigrams = count_ngrams_cached(pdf["النص"], n=3)
    plot_top_counter(trigrams, "أكثر Trigram تكراراً", k=10)






    # =============== شبكة المنشن (اختياري) ===============
    st.subheader("🧩 شبكة المنشن")
    st.caption("تعرض الحسابات التي تم ذكرها بكثرة")
    try:
        from pyvis.network import Network
        import streamlit.components.v1 as components
        import matplotlib.colors as mcolors
        import matplotlib.cm as cm

        mention_rows = []
        for _, row in pdf.iterrows():
            for m in row["mentions"]:
                mention_rows.append({"source": USERNAME, "target": m})

        if not mention_rows:
            st.info("لا توجد منشنات كافية.")
        else:
            mdf = pd.DataFrame(mention_rows)
            mention_counts = mdf["target"].value_counts()
            top_n = st.slider("🔝 عدد الحسابات المعروضة", 5, 50, 15)
            selected_mentions = mention_counts.head(top_n)
            st.write(f"تم العثور على **{len(selected_mentions)}** حساب للعرض")
            st.bar_chart(selected_mentions)

            net = Network(height="750px", width="100%", bgcolor="#0E1117", font_color="white", directed=True)
            net.add_node(USERNAME, label=f"@{USERNAME}", size=50, color="#FFD700", shape="dot")

            max_count = selected_mentions.max() if len(selected_mentions) > 0 else 1
            norm = plt.Normalize(vmin=selected_mentions.min(), vmax=max_count)
            import matplotlib
            cmap = matplotlib.colormaps.get("coolwarm")

            for account, count in selected_mentions.items():
                net.add_node(
                    account,
                    label=account,
                    size=20 + count * 3,
                    color=mcolors.to_hex(cmap(norm(count))),
                    shape="dot",
                    title=f"مرات الذكر: {count}"
                )
                net.add_edge(USERNAME, account, color="#AAAAAA", width=2)

            net.save_graph("mentions_network.html")
            st.success("✅ تم إنشاء الرسم — يمكنك استعراضه أدناه أو تحميله.")
            with open("mentions_network.html", "r", encoding="utf-8") as f:
                components.html(f.read(), height=800)
            with open("mentions_network.html", "rb") as f:
                st.download_button("💾 تحميل الرسم كـ HTML", data=f, file_name="mentions_network.html", mime="text/html")
    except Exception:
        st.warning("⚠️ لتفعيل شبكة المنشن، ثبّت:  `pip install pyvis`")


