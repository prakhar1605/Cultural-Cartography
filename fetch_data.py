import os, json, time
from dotenv import load_dotenv
import praw

load_dotenv()
CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
USER_AGENT = os.getenv('REDDIT_USER_AGENT')
QUERY = os.getenv('SEARCH_QUERY', 'redbull')
MAX_POSTS = int(os.getenv('MAX_POSTS', 2000))
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

reddit = praw.Reddit(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, user_agent=USER_AGENT)

posts, count = [], 0
for submission in reddit.subreddit('all').search(QUERY, limit=None, sort='new'):
    if count >= MAX_POSTS: break
    try:
        submission.comments.replace_more(limit=0)
        comments = [c.body for c in submission.comments.list()]
    except: comments = []
    posts.append({
        'id': submission.id,
        'title': submission.title,
        'selftext': submission.selftext,
        'subreddit': submission.subreddit.display_name,
        'author': str(submission.author),
        'comments': comments
    })
    count += 1
    time.sleep(0.1)

with open(os.path.join(OUTPUT_DIR, 'raw_posts.json'), 'w') as f:
    json.dump(posts, f, indent=2)
print("Saved raw_posts.json")
