import streamlit as st, secrets, urllib.parse, requests, base64, hashlib

CLIENT_ID = st.secrets["CLIENT_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
SCOPE = "tweet.read users.read offline.access"
AUTH_URL = "https://twitter.com/i/oauth2/authorize"

@st.cache_resource
def get_state_store():
    return {}

state_store = get_state_store()

def gen_pkce_pair():
    import secrets, hashlib, base64
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return code_verifier, code_challenge

if "access_token" not in st.session_state:
    if st.button("🔑 سجل الدخول"):
        state = secrets.token_urlsafe(16)
        code_verifier, code_challenge = gen_pkce_pair()
        state_store[state] = code_verifier

        params = {
            "response_type": "code", "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI, "scope": SCOPE,
            "state": state, "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        st.markdown(f"""<meta http-equiv="refresh" content="0; url={AUTH_URL}?{urllib.parse.urlencode(params)}">""", unsafe_allow_html=True)

q = st.query_params
code, state = q.get("code"), q.get("state")
if isinstance(code, list): code = code[0]
if isinstance(state, list): state = state[0]

if code and state:
    if state not in state_store:
        st.error("⚠️ state غير معروف.")
        st.stop()
    st.success("✅ state مطابق!")
