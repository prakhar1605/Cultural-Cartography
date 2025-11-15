# app.py
# Streamlit app: Cultural Cartography (Reddit-based audience analysis)
# Requirements:
# pip install praw pandas streamlit vaderSentiment python-dotenv
#
# NOTE: This version uses Streamlit Secrets (st.secrets) to read API keys.
# Put the following keys in Streamlit Secrets:
# REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
#
# Run locally:
# streamlit run app.py

import os
import time
import json
from collections import Counter
from datetime import datetime

import pandas as pd
import streamlit as st

# Sentiment
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Reddit client
import praw

# ---------- Config ----------
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASELINE_FILE = os.path.join(OUTPUT_DIR, "baseline_subreddit_freq.csv")
SAMPLE_FREQ_FILE = os.path.join(OUTPUT_DIR, "subreddit_freq_sample.csv")
UNIQUENESS_FILE = os.path.join(OUTPUT_DIR, "uniqueness.csv")
RAW_POSTS_JSON = os.path.join(OUTPUT_DIR, "raw_posts.json")
REPORT_HTML = os.path.join(OUTPUT_DIR, "final_report.html")

# ---------- Helper: Reddit client (using Streamlit secrets) ----------
def get_reddit_client():
    """
    Use Streamlit secrets to read Reddit credentials.
    In Streamlit Cloud: Settings -> Secrets
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
    """
    try:
        client_id = st.secrets["REDDIT_CLIENT_ID"]
        client_secret = st.secrets["REDDIT_CLIENT_SECRET"]
        user_agent = st.secrets.get("REDDIT_USER_AGENT", "cultural-cartography-app")
    except Exception:
        raise RuntimeError(
            "Missing Streamlit secrets: set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET "
            "and optionally REDDIT_USER_AGENT in Streamlit → Settings → Secrets"
        )

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        check_for_async=False
    )

# ---------- Fetch posts (search across r/all) ----------
def fetch_reddit_posts(query, max_posts=200, progress_callback=None):
    reddit = get_reddit_client()
    posts = []
    count = 0
    try:
        # using .search on r/all - rate sensitive
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
        raise RuntimeError(f"Error while fetching from Reddit: {e}")
    return posts

# ---------- Analyze: build subreddit frequencies and sentiment ----------
def analyze_posts(posts, sample_limit_users=300):
    # Map authors -> set of subreddits they appear in (approx audience)
    user_subs = {}
    for p in posts:
        a = p.get("author")
        s = p.get("subreddit")
        if not a or a.lower() in ("none", "[deleted]"):
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
    texts = [(p.get("title", "") + " " + (p.get("selftext") or "")).strip() for p in posts if (p.get("title") or p.get("selftext"))]
    if texts:
        scores = [sid.polarity_scores(t)["compound"] for t in texts]
        pos = sum(1 for s in scores if s > 0.05)
        neg = sum(1 for s in scores if s < -0.05)
        neu = len(scores) - pos - neg
        sentiment = {
            "positive_pct": round(100 * pos / len(scores), 2),
            "negative_pct": round(100 * neg / len(scores), 2),
            "neutral_pct": round(100 * neu / len(scores), 2),
            "average_compound": round(sum(scores) / len(scores), 3)
        }
    else:
        sentiment = {"positive_pct": 0, "negative_pct": 0, "neutral_pct": 0, "average_compound": 0}

    return df, sentiment, len(sample_users)

# ---------- Compute uniqueness vs baseline ----------
def compute_uniqueness(sample_df, baseline_df):
    # baseline_df should have columns: subreddit, freq_percent
    s = sample_df.copy()
    b = baseline_df.copy()
    b = b.rename(columns={"freq_percent": "baseline_freq_percent"})
    merged = s.merge(b[["subreddit", "baseline_freq_percent"]], on="subreddit", how="left")
    merged["baseline_freq_percent"] = merged["baseline_freq_percent"].fillna(0.0001)  # smoothing
    merged["uniqueness"] = merged["freq_percent"] / merged["baseline_freq_percent"]
    merged = merged.sort_values("uniqueness", ascending=False)
    return merged

# ---------- Simple baseline fetch (if missing) ----------
def ensure_baseline(baseline_file=BASELINE_FILE):
    if os.path.exists(baseline_file):
        try:
            df = pd.read_csv(baseline_file)
            return df
        except Exception:
            pass

    # fetch small baseline sample from r/all hot posts
    reddit = get_reddit_client()
    ctr = Counter()
    fetched = 0
    max_posts = 500
    try:
        for submission in reddit.subreddit("all").hot(limit=max_posts):
            ctr.update([str(submission.subreddit)])
            fetched += 1
    except Exception:
        # fallback: return empty baseline
        return pd.DataFrame(columns=["subreddit", "count", "freq_percent"])

    baseline_df = pd.DataFrame(ctr.most_common(), columns=["subreddit", "count"])
    baseline_df["freq_percent"] = baseline_df["count"] / max(1, baseline_df["count"].sum()) * 100
    try:
        baseline_df.to_csv(baseline_file, index=False)
    except Exception:
        pass
    return baseline_df

# ---------- Report generation (clean HTML, no markdown '#') ----------
def generate_report_html(brand, top_subs_df, uniqueness_df, sentiment, sample_size):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"{brand} — Cultural analysis of the audience"
    top_subs = top_subs_df.head(20).to_dict(orient="records")
    top_unique = uniqueness_df.head(20).to_dict(orient="records")

    lines = []
    lines.append(f"<h1 style='font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto;'> {title} </h1>")
    lines.append(f"<p style='color:#555'><em>Report generated: {now} — sample size approx: {sample_size}</em></p>")

    # Executive summary
    lines.append("<h2>Executive summary</h2>")
    # a short digest sentence
    if len(top_subs) >= 3:
        lines.append("<p>The sampled audience frequently engages with communities such as <strong>{}</strong>, <strong>{}</strong>, and <strong>{}</strong>. These communities shape the feeds and conversations that this audience sees daily.</p>".format(
            top_subs[0]["subreddit"], top_subs[1]["subreddit"], top_subs[2]["subreddit"]
        ))
    else:
        lines.append("<p>The sample showed diverse interests; top subreddits are shown below.</p>")

    avg_sent = sentiment.get("average_compound", 0)
    if avg_sent > 0.05:
        tone = "generally positive"
    elif avg_sent < -0.05:
        tone = "generally negative"
    else:
        tone = "mostly neutral"
    lines.append(f"<p>The overall discussion tone is <strong>{tone}</strong> (average compound: {avg_sent}).</p>")

    # Top interests table
    lines.append("<h2>Top subreddits — frequency in sample</h2>")
    lines.append("<table style='border-collapse:collapse;width:100%'><thead><tr style='text-align:left'><th style='padding:6px;border-bottom:1px solid #ddd'>Subreddit</th><th style='padding:6px;border-bottom:1px solid #ddd'>Count</th><th style='padding:6px;border-bottom:1px solid #ddd'>Freq %</th></tr></thead><tbody>")
    for _, r in top_subs_df.head(25).iterrows():
        lines.append(f"<tr><td style='padding:6px;border-bottom:1px solid #f1f1f1'>{r['subreddit']}</td><td style='padding:6px;border-bottom:1px solid #f1f1f1'>{int(r['count'])}</td><td style='padding:6px;border-bottom:1px solid #f1f1f1'>{r['freq_percent']:.2f}%</td></tr>")
    lines.append("</tbody></table>")

    # Uniqueness table
    lines.append("<h2>Most unique subreddits (vs baseline)</h2>")
    lines.append("<table style='border-collapse:collapse;width:100%'><thead><tr style='text-align:left'><th style='padding:6px;border-bottom:1px solid #ddd'>Subreddit</th><th style='padding:6px;border-bottom:1px solid #ddd'>Freq %</th><th style='padding:6px;border-bottom:1px solid #ddd'>Uniqueness</th></tr></thead><tbody>")
    for _, r in uniqueness_df.head(25).iterrows():
        lines.append(f"<tr><td style='padding:6px;border-bottom:1px solid #f1f1f1'>{r['subreddit']}</td><td style='padding:6px;border-bottom:1px solid #f1f1f1'>{r['freq_percent']:.2f}%</td><td style='padding:6px;border-bottom:1px solid #f1f1f1'>{r['uniqueness']:.2f}x</td></tr>")
    lines.append("</tbody></table>")

    # Sentiment summary
    lines.append("<h2>Sentiment summary</h2>")
    lines.append("<ul>")
    lines.append(f"<li>Positive: {sentiment.get('positive_pct', 0)}%</li>")
    lines.append(f"<li>Negative: {sentiment.get('negative_pct', 0)}%</li>")
    lines.append(f"<li>Neutral: {sentiment.get('neutral_pct', 0)}%</li>")
    lines.append("</ul>")

    lines.append("<p style='color:#666;font-size:13px'>Notes: Uniqueness = how much more likely the sample is to follow a subreddit compared to a baseline. Treat results as aggregated signals, not personal data.</p>")

    html = "<div style='font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto; padding:14px; background:#fff; border-radius:8px;'>"
    html += "".join(lines)
    html += "</div>"

    try:
        with open(REPORT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass

    return html

# ---------- STREAMLIT UI ----------
st.set_page_config(page_title="Cultural Cartography", layout="wide")
st.title("🌍 Cultural Cartography — On-demand Brand Analysis")

st.markdown("""
Enter a brand or keyword and click **Run Analysis**. The app will fetch Reddit posts, analyze community subreddits, compute uniqueness vs a baseline, and generate a narrative report.
""")

col1, col2 = st.columns([3, 1])
with col1:
    brand = st.text_input("Brand / Keyword", placeholder="e.g. Redbull, Coca Cola, Nike")
with col2:
    max_posts = st.number_input("Max posts", value=150, min_value=20, max_value=1000, step=10)
    sample_users = st.number_input("Sample users cap", value=320, min_value=50, max_value=1000, step=10)

run = st.button("Run Analysis")

# show baseline existence
if os.path.exists(BASELINE_FILE):
    st.caption(f"Baseline cache exists: {BASELINE_FILE}")

if run:
    if not brand or brand.strip() == "":
        st.error("Please enter a brand/keyword to analyze.")
    else:
        brand = brand.strip()
        st.info(f"🔎 Fetching up to {max_posts} Reddit posts for: **{brand}**")

        # progress UI
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        try:
            # Fetch
            def progress_cb(frac):
                progress_bar.progress(min(1.0, max(0.0, frac)))
            posts = fetch_reddit_posts(brand, max_posts=max_posts, progress_callback=progress_cb)

            # Save raw posts
            try:
                with open(RAW_POSTS_JSON, "w", encoding="utf-8") as f:
                    json.dump(posts, f, indent=2)
            except Exception:
                pass

            status_text.text("Analyzing posts...")
            progress_bar.progress(0.0)
            top_subs_df, sentiment, actual_sample_users = analyze_posts(posts, sample_limit_users=sample_users)
            try:
                top_subs_df.to_csv(SAMPLE_FREQ_FILE, index=False)
            except Exception:
                pass

            status_text.text("Ensuring baseline for uniqueness...")
            progress_bar.progress(0.2)
            baseline_df = ensure_baseline()

            status_text.text("Computing uniqueness...")
            progress_bar.progress(0.4)
            uniq_df = compute_uniqueness(top_subs_df, baseline_df)
            try:
                uniq_df.to_csv(UNIQUENESS_FILE, index=False)
            except Exception:
                pass

            status_text.text("Generating report...")
            progress_bar.progress(0.7)
            html = generate_report_html(brand, top_subs_df, uniq_df, sentiment, actual_sample_users)

            progress_bar.progress(1.0)
            status_text.success("Done — report generated and saved.")

            # Display results in tabs
            tab1, tab2, tab3 = st.tabs(["📊 Top Subreddits", "📈 Sentiment", "📑 Narrative Report"])
            with tab1:
                st.dataframe(top_subs_df.head(200))
            with tab2:
                st.metric("Positive %", f"{sentiment.get('positive_pct', 0)}%")
                st.metric("Negative %", f"{sentiment.get('negative_pct', 0)}%")
                st.metric("Neutral %", f"{sentiment.get('neutral_pct', 0)}%")
                st.write("Average compound score:", sentiment.get("average_compound", 0))
            with tab3:
                st.markdown(html, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Analysis failed: {e}")
            # raise for local debug if you want (comment out on Cloud)
            raise

# Footer: helpful notes
st.markdown("---")
st.markdown("**Notes:**\n- This app uses Reddit API via credentials in Streamlit Secrets.\n- Keep `Max posts` low (50–200) for quick results.\n- Use responsibly and respect API rate limits.")
