import os, json, pandas as pd
from dotenv import load_dotenv
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk; nltk.download('vader_lexicon')

load_dotenv()
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
SAMPLE_SIZE = int(os.getenv('SAMPLE_SIZE', 320))

with open(os.path.join(OUTPUT_DIR, 'raw_posts.json')) as f:
    posts = json.load(f)

user_subs = {}
for p in posts:
    u, s = p.get('author'), p.get('subreddit')
    if not u or u == 'None': continue
    user_subs.setdefault(u, set()).add(s)

sample_users = list(user_subs.keys())[:SAMPLE_SIZE]
pd.Series(sample_users).to_csv(os.path.join(OUTPUT_DIR, 'sample_users.csv'), index=False)

from collections import Counter
ctr = Counter()
for u in sample_users: ctr.update(user_subs[u])
df = pd.DataFrame(ctr.most_common(), columns=['subreddit','count'])
df['freq_percent'] = df['count']/len(sample_users)*100
df.to_csv(os.path.join(OUTPUT_DIR, 'subreddit_freq_sample.csv'), index=False)

sid = SentimentIntensityAnalyzer()
texts = [(p.get('title','') + ' ' + (p.get('selftext') or '')) for p in posts]
vals = [sid.polarity_scores(t)['compound'] for t in texts]
print("Average sentiment:", sum(vals)/len(vals))
