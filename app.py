# app.py
# Streamlit Cultural Cartography — Reddit Audience Analysis
# Uses Streamlit Secrets for Reddit API keys.

import os
import json
from collections import Counter
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import praw

# -----------------------------------
# CONFIG
# -----------------------------------
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASELINE_FILE = os.path.join(OUTPUT_DIR, "baseline.csv")
SAMPLE_FREQ_FILE = os.path.join(OUTPUT_DIR, "sample_freq.csv")
UNIQUENESS_FILE = os.path.join(OUTPUT_DIR, "uniqueness.csv")
RAW_POSTS_JSON = os.path.join(OUTPUT_DIR, "posts.json")
REPORT_HTML_FILE = os.path.join(OUTPUT_DIR, "report.html")

# -----------------------------------
# REDDIT CLIENT FROM STREAMLIT SECRETS
# -----------------------------------
def get_reddit_client():
    try:
        client_id = st.secrets["REDDIT_CLIENT_ID"]
        client_secret = st.secrets["REDDIT_CLIENT_SECRET"]
        user_agent = st.secrets.get("REDDIT_USER_AGENT", "cultural-app")
    except:
        raise RuntimeError(
            "Missing secrets. Please add REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET in Streamlit → Settings → Secrets."
        )

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        check_for_async=False
    )

# -----------------------------------
# FETCH POSTS
# -----------------------------------
def fetch_posts(query, max_posts=200, progress_cb=None):
    reddit = get_reddit_client()
    posts = []
    c = 0
    for submission in reddit.subreddit("all").search(query, limit=max_posts, sort="new"):
        posts.append({
            "id": submission.id,
            "title": submission.title or "",
            "selftext": submission.selftext or "",
            "subreddit": str(submission.subreddit),
            "author": str(submission.author),
        })
        c += 1
        if progress_cb:
            progress_cb(c / max_posts)
    return posts

# -----------------------------------
# ANALYZE 
# -----------------------------------
def analyze(posts, cap=300):
    user_map = {}

    for p in posts:
        a = p["author"]
        s = p["subreddit"]
        if a.lower() in ["none", "[deleted]"]:
            continue
        user_map.setdefault(a, set()).add(s)

    users = list(user_map.keys())[:cap]

    ctr = Counter()
    for u in users:
        ctr.update(user_map[u])

    df = pd.DataFrame(ctr.most_common(), columns=["subreddit", "count"])
    df["freq_percent"] = df["count"] / len(users) * 100 if len(users) else 0

    # sentiment
    sid = SentimentIntensityAnalyzer()
    texts = [(p["title"] + " " + p["selftext"]).strip() for p in posts]
    scores = [sid.polarity_scores(t)["compound"] for t in texts if t]

    if scores:
        sentiment = {
            "positive_pct": round(sum(s > 0.05 for s in scores) / len(scores) * 100, 2),
            "negative_pct": round(sum(s < -0.05 for s in scores) / len(scores) * 100, 2),
            "neutral_pct": round(sum(-0.05 <= s <= 0.05 for s in scores) / len(scores) * 100, 2),
            "avg": round(sum(scores) / len(scores), 3)
        }
    else:
        sentiment = {"positive_pct":0,"negative_pct":0,"neutral_pct":0,"avg":0}

    return df, sentiment, len(users)

# -----------------------------------
# BASELINE 
# -----------------------------------
def baseline():
    if os.path.exists(BASELINE_FILE):
        return pd.read_csv(BASELINE_FILE)

    # first time
    reddit = get_reddit_client()
    ctr = Counter()
    for s in reddit.subreddit("all").hot(limit=400):
        ctr.update([str(s.subreddit)])

    df = pd.DataFrame(ctr.most_common(), columns=["subreddit", "count"])
    df["freq_percent"] = df["count"] / df["count"].sum() * 100
    df.to_csv(BASELINE_FILE, index=False)
    return df

# -----------------------------------
# UNIQUENESS
# -----------------------------------
def uniqueness(sample_df, base_df):
    b = base_df.rename(columns={"freq_percent": "baseline"})
    m = sample_df.merge(b[["subreddit", "baseline"]], on="subreddit", how="left")
    m["baseline"] = m["baseline"].fillna(0.0001)
    m["uniqueness"] = m["freq_percent"] / m["baseline"]
    return m.sort_values("uniqueness", ascending=False)

# -----------------------------------
# HTML REPORT GENERATION
# -----------------------------------
def make_html(brand, sample_df, uniq_df, sentiment, size):

    css = """
    <style>
    body { background:white; color:#111; font-family: Inter,Arial; padding:20px; }
    h1 { margin-bottom:5px; }
    table { border-collapse: collapse; width:100%; margin-top: 15px; }
    th, td { padding:8px; border-bottom:1px solid #eee; }
    th { font-weight:600; }
    </style>
    """

    top = sample_df.head(5)["subreddit"].tolist()

    html = f"""
    <html><head>{css}</head><body>
    <h1>{brand} — Cultural Analysis</h1>
    <p><em>Generated: {datetime.utcnow()} — Sample size: {size}</em></p>

    <h2>Executive Summary</h2>
    <p>
    Audience frequently engages with communities like <b>{", ".join(top)}</b>.
    </p>
    <p>
    Tone of discussion is <b>{sentiment["avg"]}</b> (pos {sentiment["positive_pct"]}%, neg {sentiment["negative_pct"]}%).
    </p>

    <h2>Top Subreddits</h2>
    <table>
        <tr><th>Subreddit</th><th>Count</th><th>Freq %</th></tr>
        { "".join(f"<tr><td>{r.subreddit}</td><td>{int(r['count'])}</td><td>{r['freq_percent']:.2f}%</td></tr>" for _, r in sample_df.head(30).iterrows()) }
    </table>

    <h2>Most Unique Subreddits</h2>
    <table>
        <tr><th>Subreddit</th><th>Freq %</th><th>Uniqueness</th></tr>
        { "".join(f"<tr><td>{r.subreddit}</td><td>{r['freq_percent']:.2f}%</td><td>{r['uniqueness']:.2f}x</td></tr>" for _, r in uniq_df.head(30).iterrows()) }
    </table>

    </body></html>
    """

    with open(REPORT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    return html


# -----------------------------------
# STREAMLIT UI
# -----------------------------------
st.set_page_config(page_title="Cultural Cartography", layout="wide")
st.title("🌍 Cultural Cartography — Reddit Audience Analyzer")

brand = st.text_input("Brand / Keyword")
max_posts = st.number_input("Max posts", value=150, min_value=50, max_value=800)
cap = st.number_input("Sample users cap", value=320, min_value=50, max_value=1000)

if st.button("Run Analysis"):
    if brand.strip() == "":
        st.error("Enter brand name.")
    else:
        st.info("Fetching posts...")

        pb = st.progress(0)
        posts = fetch_posts(brand, max_posts=max_posts, progress_cb=lambda x: pb.progress(x))

        with open(RAW_POSTS_JSON, "w") as f:
            json.dump(posts, f, indent=2)

        st.info("Analyzing...")
        sample_df, sentiment, size = analyze(posts, cap)

        st.info("Baseline...")
        base = baseline()

        st.info("Computing uniqueness...")
        uniq_df = uniqueness(sample_df, base)

        st.info("Generating report...")
        html = make_html(brand, sample_df, uniq_df, sentiment, size)

        # Tabs
        tab1, tab2, tab3 = st.tabs(["Top Subreddits", "Sentiment", "Narrative Report"])

        with tab1:
            st.dataframe(sample_df)

        with tab2:
            st.metric("Positive %", sentiment["positive_pct"])
            st.metric("Negative %", sentiment["negative_pct"])
            st.metric("Neutral %", sentiment["neutral_pct"])
            st.write("Avg compound:", sentiment["avg"])

        with tab3:
            st.write("### Full Narrative Report")
            components.html(html, height=1000, scrolling=True)

            st.download_button(
                label="📥 Download Report (HTML)",
                data=html,
                file_name=f"{brand}_report.html",
                mime="text/html"
            )
