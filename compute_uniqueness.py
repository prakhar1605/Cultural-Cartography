import os, json, pandas as pd
from dotenv import load_dotenv
from collections import Counter

load_dotenv()
OUTPUT_DIR = os.getenv('OUTPUT_DIR','output')

sample = pd.read_csv(os.path.join(OUTPUT_DIR,'subreddit_freq_sample.csv'))
with open(os.path.join(OUTPUT_DIR,'baseline_posts.json')) as f:
    baseline = json.load(f)

base_ctr = Counter([p['subreddit'] for p in baseline if p.get('subreddit')])
base_df = pd.DataFrame(base_ctr.items(), columns=['subreddit','baseline_count'])
base_df['baseline_freq_percent'] = base_df['baseline_count']/len(baseline)*100

merged = sample.merge(base_df,on='subreddit',how='left').fillna(0)
merged['baseline_freq_percent'].replace(0,0.001,inplace=True)
merged['uniqueness']=merged['freq_percent']/merged['baseline_freq_percent']
merged.sort_values('uniqueness',ascending=False).to_csv(os.path.join(OUTPUT_DIR,'uniqueness.csv'),index=False)
print("Saved uniqueness.csv")
