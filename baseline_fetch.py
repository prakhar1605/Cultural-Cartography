import os, json
from dotenv import load_dotenv
import praw

load_dotenv()
CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
USER_AGENT = os.getenv('REDDIT_USER_AGENT')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

reddit = praw.Reddit(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, user_agent=USER_AGENT)

posts = []
for submission in reddit.subreddit('all').hot(limit=1000):
    posts.append({'id': submission.id, 'subreddit': submission.subreddit.display_name, 'author': str(submission.author)})

with open(os.path.join(OUTPUT_DIR, 'baseline_posts.json'), 'w') as f:
    json.dump(posts, f, indent=2)
print("Saved baseline_posts.json")
