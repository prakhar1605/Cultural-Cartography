def generate_report_html(brand, top_subs_df, uniqueness_df, sentiment, sample_size):
    """
    Improved HTML generation that forces readable colors even when Streamlit is in dark mode.
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"{brand} — Cultural analysis of the audience"
    top_subs = top_subs_df.head(20).to_dict(orient="records")
    top_unique = uniqueness_df.head(20).to_dict(orient="records")

    # CSS that forces readable colors (overrides Streamlit dark theme)
    style = """
    <style>
      /* Container */
      .cc-report { 
        background: #ffffff !important; 
        color: #111111 !important; 
        padding: 18px; 
        border-radius: 10px; 
        font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial; 
        box-shadow: 0 6px 18px rgba(15,23,42,0.08);
      }

      /* Headings */
      .cc-report h1 { color: #0f172a !important; margin: 0 0 8px; font-size: 26px; }
      .cc-report h2 { color: #0b1220 !important; margin-top:18px; font-size:18px; }

      /* Paragraphs and small text */
      .cc-report p, .cc-report li, .cc-report td, .cc-report th { color: #111827 !important; }
      .cc-muted { color: #6b7280 !important; font-size:13px; }

      /* Tables */
      .cc-table { border-collapse: collapse; width: 100%; margin-top:12px; }
      .cc-table th { text-align:left; padding:8px; border-bottom:1px solid #e6e9ee; color:#374151 !important; font-weight:600; background:transparent; }
      .cc-table td { padding:8px; border-bottom:1px solid #f3f4f6; color:#111827 !important; }

      /* badges */
      .cc-badge { display:inline-block; padding:4px 8px; border-radius:999px; background:#eef2ff; color:#3730a3; font-weight:600; font-size:13px; }

      /* force links visible */
      .cc-report a { color: #0b69ff !important; }

      /* small screens adjustments */
      @media (max-width:640px) {
        .cc-report { padding:12px; }
        .cc-report h1 { font-size:20px; }
      }
    </style>
    """

    # Build HTML content (same structure, but wrapped in .cc-report container)
    lines = []
    lines.append(f"<div class='cc-report'>")
    lines.append(f"<h1>{title}</h1>")
    lines.append(f"<p class='cc-muted'><em>Report generated: {now} — sample size approx: {sample_size}</em></p>")

    # Executive summary
    lines.append("<h2>Executive summary</h2>")
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
    lines.append("<table class='cc-table'><thead><tr><th>Subreddit</th><th>Count</th><th>Freq %</th></tr></thead><tbody>")
    for _, r in top_subs_df.head(25).iterrows():
        lines.append(f"<tr><td>{r['subreddit']}</td><td>{int(r['count'])}</td><td>{r['freq_percent']:.2f}%</td></tr>")
    lines.append("</tbody></table>")

    # Uniqueness table
    lines.append("<h2>Most unique subreddits (vs baseline)</h2>")
    lines.append("<table class='cc-table'><thead><tr><th>Subreddit</th><th>Freq %</th><th>Uniqueness</th></tr></thead><tbody>")
    for _, r in uniqueness_df.head(25).iterrows():
        lines.append(f"<tr><td>{r['subreddit']}</td><td>{r['freq_percent']:.2f}%</td><td>{r['uniqueness']:.2f}x</td></tr>")
    lines.append("</tbody></table>")

    # Sentiment summary
    lines.append("<h2>Sentiment summary</h2>")
    lines.append("<ul>")
    lines.append(f"<li>Positive: {sentiment.get('positive_pct', 0)}%</li>")
    lines.append(f"<li>Negative: {sentiment.get('negative_pct', 0)}%</li>")
    lines.append(f"<li>Neutral: {sentiment.get('neutral_pct', 0)}%</li>")
    lines.append("</ul>")

    lines.append("<p class='cc-muted'>Notes: Uniqueness = how much more likely the sample is to follow a subreddit compared to a baseline. Treat results as aggregated signals, not personal data.</p>")

    lines.append("</div>")  # end container

    html = style + "\n" + "".join(lines)

    # Save HTML for inspection
    try:
        with open(REPORT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass

    return html
