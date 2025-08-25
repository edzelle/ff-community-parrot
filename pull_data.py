import praw
import requests
import json
from rapidfuzz import fuzz, process
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
analyzer = SentimentIntensityAnalyzer()
from collections import defaultdict, OrderedDict
from textblob import TextBlob
import json

# Load secrets from file
with open('secrets.json') as f:
    secrets = json.load(f)

# Access individual secrets
client_secret = secrets['client_secret']
user_agent = secrets['user_agent']
client_id = secrets['client_id']


position_keywords = {
    "QB": ["qb", "quarterback", "qb1"],
    "RB": ["rb", "running back", "rb1", "rb2", "bellcow"],
    "WR": ["wr", "receiver", "wideout", "wr1", "wr2", "wr3"],
    "TE": ["te", "tight end", "te1"]
}

COMMON_FIRST_NAMES= {"will", "josh", "taylor", "joe", "love", "likely", "brown"}

def fetch_threads(subreddit_name, post_limit=20):
    reddit = praw.Reddit(
        client_id = client_id,
        client_secret = client_secret,
        user_agent = user_agent
    )

    subreddit = reddit.subreddit(subreddit_name)
    threads = []
    post_texts = []
    for submission in subreddit.hot(limit=post_limit):
        post_text = submission.title + " " + submission.selftext
        post_texts.append(post_text)
        submission.comments.replace_more(limit=0)
        for comment in submission.comments.list():
            threads.append({
                "comment_id": comment.id,
                "parent_id":comment.parent_id,
                "body": comment.body,
                "created_utc": comment.created_utc,
                "author": str(comment.author),
                "submissionId": submission.id
            })
    
    return post_texts, threads

def fetch_all_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

def fetch_players_by_position_order_by_adp(pos_key):
    url = f"https://api.sleeper.com/projections/nfl/2025?season_type=regular&position[]={pos_key}&order_by=adp_ppr"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

def get_top_players_by_position(player_data, top_n):
    filtered = []
    for p in player_data:
        filtered.append({
            "player_id": p.get("player_id"), 
            "full_name": str(p.get("player").get("first_name")) + " " + str(p.get("player").get("last_name")),
            "nicknames": [p.get("player").get("first_name"), p.get("player").get("last_name"), str(p.get("player").get("first_name")) + " " + str(p.get("player").get("last_name"))],
            "position": p.get("player").get("position")
        })

    return filtered[:top_n]

def dynamic_cutoff(text_length, base_cutoff=80):
    reduction = max(0, (text_length - 30) // 10)
    return max(60, base_cutoff - reduction)

def detect_position(text, position_keywords):
    found= set()
    for pos, kws in position_keywords:
        for kw in kws:
            if kw in text.lower():
                found.add(pos)
    return found

def smart_score(alias, text):
    partial = fuzz.partial_ratio(alias.lower(), text)
    token_set = fuzz.token_set_ratio(alias.lower(), text)
    return max(
        partial, token_set
    )

def token_overlaps(alias, text):
    alias_tokens = set(alias.lower().split())
    text_tokens = set(text.lower().split())
    return len(alias_tokens & text_tokens) / len(alias_tokens)

def refined_smart_score(alias, text):

    alias_lower = alias.lower()

    if alias_lower in COMMON_FIRST_NAMES and " " not in alias_lower:
        return 0

    base = smart_score(alias, text)

    overlap = token_overlaps(alias, text)
    if overlap < 0.5:
        return 0
    if len(alias) <= 3 and overlap < 1.0:
        base -=30
    
    if " " in alias and alias.lower() in text.lower():
        base += 15
    elif len(alias) > 4 and alias.lower() in text.lower():
        base += 10
    return min(max(base,0),100)

def best_player_match(text, player_names, position_keywords, score_cutoff=80):
    detect_positions = detect_position(text, position_keywords)
    cutoff = dynamic_cutoff(len(text))

    results = []

    for player in player_names:
        best_alias_score = 0
        for alias in player.get("nicknames"):
            score = refined_smart_score(alias, text)

            if " " in alias and alias.lower() in text.lower():
                score += 10
            
            if player.get("position") in detect_positions:
                score += 15

            score = min(score, 100)
            best_alias_score = max(best_alias_score, score)
        if best_alias_score >= cutoff:
            results.append((player.get("full_name"), best_alias_score))
    
    return sorted(results,key=lambda x: x[1], reverse=True)

def get_sentiment(text):
    scores = analyzer.polarity_scores(text)
    return scores["compound"]

def process_text(text, players, position_keywords):
    matches = best_player_match(text, players, position_keywords,dynamic_cutoff(len(text)))
    if not matches:
        return
    sentiment = get_sentiment(text)
    for player, confidence, in matches:
        weighted_score = sentiment * (confidence / 100)
        player_sentiments[player]["sentiment_score"] += weighted_score
        player_sentiments[player]["texts"].append(text)


def pull_data_and_analyize_sentiment():

    post_texts, threads = fetch_threads("fantasyfootball")

    for post in post_texts:
        process_text(post, player_names, position_keywords)
    for comment in threads:
        process_text(comment.get("body"), player_names, position_keywords)



player_sentiments = defaultdict(lambda: {"sentiment_score": 0, "texts": []})

# qbs = fetch_players_by_position_order_by_adp("QB")
# top_qbs = get_top_players_by_position(qbs, 40)

# rbs = fetch_players_by_position_order_by_adp("RB")
# top_rbs = get_top_players_by_position(rbs, 100)

# wrs = fetch_players_by_position_order_by_adp("WR")
# top_wrs = get_top_players_by_position(wrs, 100)

# tes = fetch_players_by_position_order_by_adp("TE")
# top_tes = get_top_players_by_position(tes, 50)

# result = top_qbs + top_rbs + top_wrs + top_tes


# with open('player_names.json', 'w') as f:
#     json.dump(result, f)

with open('player_names.json', 'r') as f:
    player_names = json.load(f)

pull_data_and_analyize_sentiment()

sorted_player_data = OrderedDict(
    sorted(player_sentiments.items(), key=lambda x : x[1]["sentiment_score"], reverse=True)
)

with open('player_sentiment_output.json', 'w') as f:
     json.dump(sorted_player_data, f)