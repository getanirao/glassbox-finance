import os, json
from config import *

cache = json.load(open(NEWS_CACHE_FILE)) if os.path.exists(NEWS_CACHE_FILE) else {'headlines': []}
headlines = cache.get('headlines', [])
net = sum(1 for h in headlines if h.get('net_score') is not None)
print(f'Total headlines: {len(headlines)}')
print(f'With net_score: {net}')
if net > 0:
    scores = [h['net_score'] for h in headlines if h.get('net_score') is not None]
    print(f'Score range: {min(scores):.3f} to {max(scores):.3f}, avg={sum(scores)/len(scores):.4f}')
    for h in headlines[:5]:
        print(f'  ticker={h.get("ticker")}, net={h.get("net_score")}, ts={h.get("timestamp","")[:19]}')
    print('...')
    for h in headlines[-3:]:
        print(f'  ticker={h.get("ticker")}, net={h.get("net_score")}, ts={h.get("timestamp","")[:19]}')

from config import DECAY_HALF_LIFE_HOURS, NEWS_CYCLE_HOURS, LONG_WINDOW_HOURS
print(f'DECAY_HALF_LIFE_HOURS = {DECAY_HALF_LIFE_HOURS}')
print(f'NEWS_CYCLE_HOURS = {NEWS_CYCLE_HOURS}')
print(f'LONG_WINDOW_HOURS = {LONG_WINDOW_HOURS}')
