# app.py
# Single-file Streamlit app that runs full Cultural Cartography pipeline on button click.
# Requirements (in your .venv): praw, pandas, streamlit, vaderSentiment, python-dotenv
# Put your reddit credentials in a .env file or set as environment vars:
# REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
#
# Usage:
#   source .venv/bin/activate
#   streamlit run app.py

import os
import time
import json
from collections import Counter
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Use vaderSentiment to avoid NLTK download issues
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Reddit client (import inside functions to avoid top-level failures in deploy)
import praw

# ---------- Config ----------
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# For baseline we use this filename (app will attempt to load cached baseline or fetch a small one)
BASELINE_FILE = os.path.join(OUTPUT_DIR, "baseline_subreddit_freq.csv")
SAMPLE_FREQ_FILE = os.path.join(OUTPUT_DIR, "subreddit_freq_sample.csv")
UNIQUENESS_FILE = os.path.join(OUTPUT_DIR, "uniqueness.csv")
RAW_POSTS_JSON = os.path.join(OUTPUT_DIR, "raw_posts.json")
REPORT_HTML = os.path.join(OUTPUT_DIR, "final_report.html")

# Load .env (if present) so Streamlit and local run can use env vars
load_dotenv()

# ---------- Helper: Reddit client ----------
def get_reddit_client():
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT", "cultural-cartography-app")

    if not client_id or not client_secret:
        raise RuntimeError("Missing Reddit API credentials. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in environment or .env.")

    return praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent, check_for_async=False)

# ---------- Fetch posts (search 'all' subreddits) ----------
def fetch_reddit_posts(query, max_posts=200, progress_callback=None):
    reddit = get_reddit_client()
    posts = []
    count = 0
    try:
        # Using reddit.subreddit("all").search is rate-sensitive. limit param caps results.
        for submission in reddit.subreddit("all").search(query, limit=max_posts, sort="new"):
            posts.append({
                "id": submission.id,
                "title": submission.title or "",
                "selftext": submission.selftext or "",
                "subreddit": str(submission.subreddit),
                "author": str(submission.author),
                "score": int(getattr(submission, "score", 0)),
                "num_comments": int(getattr(submission, "num_comments", 0))
            })
            count += 1
            if progress_callback and max_posts:
                progress_callback(count / max_posts)
    except Exception as e:
        # Surface helpful error
        raise RuntimeError(f"Error while fetching from Reddit: {e}")
    return posts

# ---------- Analyze: build subreddit frequencies and sentiment ----------
def analyze_posts(posts, sample_limit_users=300):
    # Map authors -> set of subreddits they appear in (approx audience)
    user_subs = {}
    for p in posts:
        a = p.get("author")
        s = p.get("subreddit")
        if not a or a.lower() in ("none","[deleted]"): 
            continue
        user_subs.setdefault(a, set()).add(s)

    # sample users (cap)
    sample_users = list(user_subs.keys())[:sample_limit_users]
    ctr = Counter()
    for u in sample_users:
        ctr.update(user_subs[u])

    df = pd.DataFrame(ctr.most_common(), columns=["subreddit", "count"])
    if len(sample_users) > 0:
        df["freq_percent"] = df["count"] / len(sample_users) * 100
    else:
        df["freq_percent"] = 0.0

    # sentiment on titles + selftext
    sid = SentimentIntensityAnalyzer()
    texts = [(p.get("title","") + " " + (p.get("selftext") or "")).strip() for p in posts if (p.get("title") or p.get("selftext"))]
    if texts:
        scores = [sid.polarity_scores(t)["compound"] for t in texts]
        pos = sum(1 for s in scores if s > 0.05)
        neg = sum(1 for s in scores if s < -0.05)
        neu = len(scores) - pos - neg
        sentiment = {
            "positive_pct": round(100 * pos / len(scores), 2),
            "negative_pct": round(100 * neg / len(scores), 2),
            "neutral_pct": round(100 * neu / len(scores), 2),
            "average_compound": round(sum(scores)/len(scores), 3)
        }
    else:
        sentiment = {"positive_pct":0,"negative_pct":0,"neutral_pct":0,"average_compound":0}

    return df, sentiment, len(sample_users)

# ---------- Compute uniqueness vs baseline ----------
def compute_uniqueness(sample_df, baseline_df):
    # baseline_df should have columns: subreddit, freq_percent
    # Merge on subreddit and compute uniqueness = sample_freq / baseline_freq (with smoothing)
    s = sample_df.copy()
    b = baseline_df.copy()
    b = b.rename(columns={"freq_percent":"baseline_freq_percent"})
    merged = s.merge(b[["subreddit","baseline_freq_percent"]], on="subreddit", how="left")
    # smoothing for zero baseline: set baseline 0 -> tiny value
    merged["baseline_freq_percent"] = merged["baseline_freq_percent"].fillna(0.0001)
    merged["uniqueness"] = merged["freq_percent"] / merged["baseline_freq_percent"]
    merged = merged.sort_values("uniqueness", ascending=False)
    return merged

# ---------- Simple baseline fetch (only if baseline file missing) ----------
def ensure_baseline(baseline_file=BASELINE_FILE):
    if os.path.exists(baseline_file):
        df = pd.read_csv(baseline_file)
        return df
    # else fetch a small baseline sample for comparison
    reddit = get_reddit_client()
    ctr = Counter()
    fetched = 0
    max_posts = 500
    try:
        for submission in reddit.subreddit("all").hot(limit=max_posts):
            ctr.update([str(submission.subreddit)])
            fetched += 1
    except Exception:
        # fallback to empty baseline
        return pd.DataFrame(columns=["subreddit","count","freq_percent"])
    baseline_df = pd.DataFrame(ctr.most_common(), columns=["subreddit","count"])
    # Estimate freq_percent by normalizing counts by a notional user/sample size
    baseline_df["freq_percent"] = baseline_df["count"] / max(1, baseline_df["count"].sum()) * 100
    baseline_df.to_csv(baseline_file, index=False)
    return baseline_df

# ---------- Report generation (simple HTML snippet + in-app display) ----------
def generate_report_html(brand, top_subs_df, uniqueness_df, sentiment, sample_size):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"# {brand} - cultural analysis of the audience"
    # Build top-10 lists for narrative
    top_subs = top_subs_df.head(20).to_dict(orient="records")
    top_unique = uniqueness_df.head(20).to_dict(orient="records")

    # Compose a friendly narrative (short)
    lines = []
    lines.append(f"<h1>{title}</h1>")
    lines.append(f"<p><em>Report generated: {now} — sample size approx: {sample_size}</em></p>")
    lines.append("<h2>Community overview/characteristics</h2>")
    lines.append("<ol>")
    lines.append("<li><strong>United by a love for communities around:</strong> " +
                 ", ".join([r["subreddit"] for r in top_subs[:5]]) + ".</li>")
    avg_sent = sentiment.get("average_compound",0)
    if avg_sent > 0.05:
        tone = "generally positive"
    elif avg_sent < -0.05:
        tone = "generally negative"
    else:
        tone = "mostly neutral"
    lines.append(f"<li><strong>Tone:</strong> The conversation is {tone} (avg sentiment {avg_sent}).</li>")
    lines.append(f"<li><strong>Top interests:</strong> Top subreddits include {', '.join([r['subreddit'] for r in top_subs[:8]])}.</li>")
    lines.append("</ol>")

    # Key interests snippet + tables
    lines.append("<h2>Key Interests — Top subreddits</h2>")
    lines.append("<table><thead><tr><th>Subreddit</th><th>Count</th><th>Freq %</th></tr></thead><tbody>")
    for _, r in top_subs_df.head(25).iterrows():
        lines.append(f"<tr><td>{r['subreddit']}</td><td>{int(r['count'])}</td><td>{r['freq_percent']:.2f}%</td></tr>")
    lines.append("</tbody></table>")

    lines.append("<h2>Most unique subreddits (vs baseline)</h2>")
    lines.append("<table><thead><tr><th>Subreddit</th><th>Freq %</th><th>Uniqueness</th></tr></thead><tbody>")
    for _, r in uniqueness_df.head(25).iterrows():
        lines.append(f"<tr><td>{r['subreddit']}</td><td>{r['freq_percent']:.2f}%</td><td>{r['uniqueness']:.2f}x</td></tr>")
    lines.append("</tbody></table>")

    lines.append("<h2>Sentiment summary</h2>")
    lines.append("<ul>")
    lines.append(f"<li>Positive: {sentiment.get('positive_pct',0)}%</li>")
    lines.append(f"<li>Negative: {sentiment.get('negative_pct',0)}%</li>")
    lines.append(f"<li>Neutral: {sentiment.get('neutral_pct',0)}%</li>")
    lines.append("</ul>")

    html = "<div style='font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto;'>"
    html += "".join(lines)
    html += "</div>"

    # Save HTML for inspection
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    return html

# ---------- STREAMLIT UI ----------
st.set_page_config(page_title="Cultural Cartography", layout="wide")
st.title("🌍 Cultural Cartography — On-demand Brand Analysis")

st.markdown("""
Enter a brand or keyword and click **Run Analysis**. The app will fetch Reddit posts, analyze audience subreddits, compute uniqueness vs a baseline, and generate a narrative report — all inside this page.
""")

col1, col2 = st.columns([3,1])
with col1:
    brand = st.text_input("Brand / Keyword", placeholder="e.g. Redbull, Coca Cola, Nike")
with col2:
    max_posts = st.number_input("Max posts", value=150, min_value=20, max_value=1000, step=10)
    sample_users = st.number_input("Sample users cap", value=320, min_value=50, max_value=1000, step=10)

run = st.button("Run Analysis")

# show cached baseline size
if os.path.exists(BASELINE_FILE):
    bsize = os.path.getsize(BASELINE_FILE)
    st.caption(f"Baseline cache exists: {BASELINE_FILE}")

if run:
    if not brand or brand.strip()=="":
        st.error("Please enter a brand/keyword to analyze.")
    else:
        brand = brand.strip()
        st.info(f"🔎 Fetching up to {max_posts} Reddit posts for: **{brand}**")

        # progress UI
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        try:
            def progress_cb(frac):
                progress_bar.progress(min(1.0, max(0.0, frac)))
            # Fetch
            posts = fetch_reddit_posts(brand, max_posts=max_posts, progress_callback=progress_cb)
            # Save raw posts
            with open(RAW_POSTS_JSON, "w", encoding="utf-8") as f:
                json.dump(posts, f, indent=2)

            status_text.text("Analyzing posts...")
            progress_bar.progress(0.0)
            top_subs_df, sentiment, actual_sample_users = analyze_posts(posts, sample_limit_users=sample_users)
            top_subs_df.to_csv(SAMPLE_FREQ_FILE, index=False)

            status_text.text("Ensuring baseline for uniqueness...")
            progress_bar.progress(0.2)
            baseline_df = ensure_baseline()

            status_text.text("Computing uniqueness...")
            progress_bar.progress(0.4)
            uniq_df = compute_uniqueness(top_subs_df, baseline_df)
            uniq_df.to_csv(UNIQUENESS_FILE, index=False)

            status_text.text("Generating report...")
            progress_bar.progress(0.7)
            html = generate_report_html(brand, top_subs_df, uniq_df, sentiment, actual_sample_users)

            progress_bar.progress(1.0)
            status_text.success("Done — report generated and saved.")

            # Display results in tabs
            tab1, tab2, tab3 = st.tabs(["📊 Top Subreddits", "📈 Sentiment", "📑 Narrative Report"])
            with tab1:
                st.dataframe(top_subs_df.head(50))
            with tab2:
                st.metric("Positive %", f"{sentiment.get('positive_pct',0)}%")
                st.metric("Negative %", f"{sentiment.get('negative_pct',0)}%")
                st.metric("Neutral %", f"{sentiment.get('neutral_pct',0)}%")
                st.write("Average compound score:", sentiment.get("average_compound",0))
            with tab3:
                st.markdown(html, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Analysis failed: {e}")
            raise

# Footer: helpful notes
st.markdown("---")
st.markdown("**Notes:**\n- This app uses Reddit API — ensure `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, and `REDDIT_USER_AGENT` are set. \n- First-time runs may be slower due to Reddit requests. \n- Keep `Max posts` low (50–200) for quick results in demo/demo deployments.")
