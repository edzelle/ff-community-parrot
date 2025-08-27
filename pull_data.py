import praw
import requests
import json
from rapidfuzz import fuzz, process
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
analyzer = SentimentIntensityAnalyzer()
from collections import defaultdict, OrderedDict
from textblob import TextBlob
import json
import spacy
from spacy.matcher import PhraseMatcher
import math

# Load secrets from file
with open('secrets.json') as f:
    secrets = json.load(f)

# Access individual secrets
client_secret = secrets['client_secret']
user_agent = secrets['user_agent']
client_id = secrets['client_id']

DECAY_FACTOR = 0.5       # how much context weakens per depth
MIN_THRESHOLD = 0.075     # ignore weak sentiment signals


NEGATIVE_KEYWORDS = ["injured reserve", "IR", "sidelined", "high ankle sprain", "out", "NFI", "PUP"]

position_keywords = {
    "QB": ["qb", "quarterback", "qb1"],
    "RB": ["rb", "running back", "rb1", "rb2", "bellcow"],
    "WR": ["wr", "receiver", "wideout", "wr1", "wr2", "wr3"],
    "TE": ["te", "tight end", "te1"]
}

COMMON_FIRST_NAMES= {"will", "josh", "taylor", "joe", "love", "likely",
                      "brown", "calvin", "aaron", "williams", "smith", "brandon",
                      "chris","sanders", "drake", "anthony", "harris", "james", "jordan", 
                      "allen", "dart", "ford", "mcmillan"}

def fetch_threads(subreddit_name, post_limit=5):
    reddit = praw.Reddit(
        client_id = client_id,
        client_secret = client_secret,
        user_agent = user_agent
    )

    subreddit = reddit.subreddit(subreddit_name)

    submissions = []
    threads = []
    for submission in subreddit.hot(limit=post_limit):
        post_text = submission.title + " " + submission.selftext
        submissions.append({
            "submission_id": submission.id,
            "post_text": post_text
        })

        submission.comments.replace_more(limit=0)
        for comment in submission.comments.list():
            threads.append({
                "comment_id": comment.id,
                "parent_id": comment.parent_id,
                "body": comment.body,
                "created_utc": comment.created_utc,
                "author": str(comment.author),
                "submissionId": submission.id
            })
    
    return submissions, threads

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

def get_sentence_player_matches(sentence, nlp, matcher):
    """Return canonical player names mentioned in the sentence."""
    doc = nlp(sentence)
    matches = matcher(doc)
    matched_players = set()
    for match_id, start, end in matches:
        # match_id maps to full_name string
        canonical_name = nlp.vocab.strings[match_id]
        matched_players.add(canonical_name)
    return matched_players

def compute_weighted_sentiment(sentence):
    """Compute sentiment and apply injury keyword weighting."""
    polarity = TextBlob(sentence).sentiment.polarity
    # Penalize if sentence contains injury keywords
    if any(kw in sentence.lower() for kw in NEGATIVE_KEYWORDS):
        polarity *= 1.5  # increase negative impact
        polarity = min(polarity, 1.0)  # cap max
        polarity = max(polarity, -1.0)
    return polarity

def process_comments_nlp(comments, player_sentiments, nlp, matcher):

    for comment in comments:
        doc = nlp(comment.get("body"))
        for sent in doc.sents:
            sentence_text = sent.text
            matched_players = get_sentence_player_matches(sentence_text, nlp, matcher)
            if not matched_players:
                continue
            sentiment = compute_weighted_sentiment(sentence_text)
            for player in matched_players:
                player_sentiments[player]["sentiment_score"] += sentiment
                player_sentiments[player]["texts"].append(sentence_text)

    return player_sentiments

def process_post_nlp(posts, player_sentiments, nlp, matcher):

    for post in posts:
        doc = nlp(post)
        for sent in doc.sents:
            sentence_text = sent.text
            matched_players = get_sentence_player_matches(sentence_text, nlp, matcher)
            if not matched_players:
                continue
            sentiment = compute_weighted_sentiment(sentence_text)
            for player in matched_players:
                player_sentiments[player]["sentiment_score"] += sentiment
                player_sentiments[player]["texts"].append(sentence_text)

    return player_sentiments

def process_text(text, players, position_keywords, player_sentiments):
    matches = best_player_match(text, players, position_keywords)
    if not matches:
        return

    sentiment = get_sentiment(text)

    for player, confidence in matches:
        # initialize dict if player not seen before
        if player not in player_sentiments:
            player_sentiments[player] = {"sentiment_score": 0.0, "texts": []}

        # weight sentiment by match confidence
        weighted_score = sentiment * (confidence / 100)
        player_sentiments[player]["sentiment_score"] += weighted_score
        player_sentiments[player]["texts"].append(text)


def pull_data_and_analyize_sentiment(player_sentiments, player_names):
    nlp = spacy.load("en_core_web_sm")
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

    for player in player_names:
        patterns = [nlp.make_doc(alias) for alias in player.get("nicknames") if alias.lower() not in COMMON_FIRST_NAMES]
        matcher.add(player.get("full_name"), patterns)


    post_texts, threads = fetch_threads("fantasyfootball")

    
    process_post_nlp(post_texts, player_sentiments, nlp, matcher)

       # process_text(post, player_names, position_keywords, player_sentiments)
    process_comments_nlp(threads, player_sentiments, nlp, matcher)

       # process_text(comment.get("body"), player_names, position_keywords, player_sentiments)

def build_comment_tree(threads, submission_id):
    comment_map = {
        c["comment_id"]: {**c, "children": []}
        for c in threads if c["submissionId"] == submission_id
    }

    root_comments = []
    for comment in comment_map.values():
        parent_id = comment["parent_id"]
        if parent_id.startswith("t3_"):  # parent is submission
            root_comments.append(comment)
        else:
            parent_key = parent_id.split("_")[1]  # strip t1_ prefix
            if parent_key in comment_map:
                comment_map[parent_key]["children"].append(comment)
    
    return root_comments

def process_thread(node, parent_context, players, position_keywords, player_sentiments):
    matches = best_player_match(node["body"], players, position_keywords)
    sentiment = get_sentiment(node["body"])

    if matches:
        current_context = [m[0] for m in matches]  # matched players
    else:
        current_context = parent_context[:]        # inherit from parent

    for player in current_context:
        player_sentiments[player]["sentiment_score"] += sentiment
        player_sentiments[player]["texts"].append(node["body"])

    for child in node.get("children", []):
        process_thread(child, current_context, players, position_keywords, player_sentiments)


def process_submission(submission, threads, players, position_keywords, player_sentiments):
    matches = best_player_match(submission["post_text"], players, position_keywords)
    root_context = [m[0] for m in matches]

    sentiment = get_sentiment(submission["post_text"])
    for player in root_context:
        player_sentiments[player]["sentiment_score"] += sentiment
        player_sentiments[player]["texts"].append(submission["post_text"])

    comment_tree = build_comment_tree(threads, submission["submission_id"])
    for root_comment in comment_tree:
        process_thread(root_comment, root_context, players, position_keywords, player_sentiments)

def process_submission_nlp(submission, threads, player_sentiments, nlp, matcher):
    # Extract root context from the post itself
    doc = nlp(submission["post_text"])
    root_context = {}  
    for sent in doc.sents:
        sentence_text = sent.text
        players = get_sentence_player_matches(sentence_text, nlp, matcher)
        sentiment = compute_weighted_sentiment(sentence_text)
        if abs(sentiment) < MIN_THRESHOLD:
            continue
        
        if players:
            for player in players:
                # add to root context (with origin depth = 0 for decay math later)
                if player not in root_context:
                    root_context[player] = {"origin_depth": 0}

                # record sentiment at post level
                player_sentiments[player]["sentiment_score"] += sentiment
                add_unique_text(
                    player_sentiments[player]["texts"],
                    {
                        "sentence": sentence_text,
                        "sentiment": sentiment,
                        "players": [player],
                        "depth": 0,
                    }
                )

    # Build comment tree
    comment_tree = build_comment_tree(threads, submission["submission_id"])

    for root_comment in comment_tree:
        process_thread_nlp(root_comment, context=root_context, depth=1,
                           player_sentiments=player_sentiments,
                           nlp=nlp, matcher=matcher)


def add_unique_text(text_list, entry):
    for e in text_list:
        if (e.get("sentence") == entry.get("sentence")
            and e.get("depth") == entry.get("depth")
            and set(e.get("players", [])) == set(entry.get("players", []))
            and abs(e.get("sentiment", 0) - entry.get("sentiment", 0)) < 1e-9):
            return
    text_list.append(entry)

def _normalize_context(context, depth):
    """Accepts None | list[str] | dict[str, {origin_depth:int}] and returns dict form."""
    if context is None:
        return {}
    if isinstance(context, dict):
        return context
    if isinstance(context, list):
        # list of player names → dict with current depth as origin
        return {p: {"origin_depth": depth} for p in context}
    # Fallback
    return {}

def process_thread_nlp(node, nlp, matcher, player_sentiments, context=None, depth=0):
    context = _normalize_context(context, depth)

    doc = nlp(node["body"])
    for sent in doc.sents:
        sentence_text = sent.text
        matched_players = get_sentence_player_matches(sentence_text, nlp, matcher)

        if not matched_players and not context:
            continue

        sentiment = compute_weighted_sentiment(sentence_text)
        if abs(sentiment) < MIN_THRESHOLD:
            continue

        # 1. Apply sentiment to players from context with decay
        
        for player, info in context.items():
            weight = DECAY_FACTOR ** (depth - info["origin_depth"])
            weighted_sentiment = sentiment * weight
            player_sentiments[player]["sentiment_score"] += weighted_sentiment

            entry = {
                "sentence": sentence_text,
                "sentiment": weighted_sentiment,
                "players": [player],
                "depth": depth,
            }
            add_unique_text(player_sentiments[player]["texts"], entry)

        # 2. Apply sentiment to explicitly mentioned players
        for player in matched_players:
            if player not in context:
                context[player] = {"origin_depth": depth}
            else:
                # reset decay if re-mentioned
                context[player]["origin_depth"] = depth

            player_sentiments[player]["sentiment_score"] += sentiment
            entry = {
                "sentence": sentence_text,
                "sentiment": sentiment,
                "players": [player],
                "depth": depth,
            }
            add_unique_text(player_sentiments[player]["texts"], entry)

    # Recurse into children
    for child in node.get("children", []):
        process_thread_nlp(child, nlp, matcher, player_sentiments, context.copy(), depth + 1)

    return player_sentiments


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

def get_data():
    player_sentiments = defaultdict(lambda: {"sentiment_score": 0, "texts": []})
    with open('player_names.json', 'r') as f:
        player_names = json.load(f)

    # Load NLP + matcher
    nlp = spacy.load("en_core_web_sm")
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

    for player in player_names:
        patterns = [nlp.make_doc(alias) for alias in player.get("nicknames") if alias.lower() not in COMMON_FIRST_NAMES]
        matcher.add(player.get("full_name"), patterns)

    # Pull reddit data
    submissions, threads = fetch_threads("fantasyfootball")

    # Process each submission with context-aware tree logic
    for submission in submissions:
        process_submission_nlp(submission, threads, player_sentiments, nlp, matcher)

    for player, data in player_sentiments.items():
        if not data["texts"]:
            data["avg_sentiment"] = 0
            data["num_comments"] = 0
            data["normalized_score"] = 0
            continue

        total_sentiment = sum(entry["sentiment"] for entry in data["texts"])
        num_comments = len(data["texts"])
        avg_sentiment = total_sentiment / num_comments

        data["avg_sentiment"] = avg_sentiment
        data["num_comments"] = num_comments
        data["normalized_score"] = avg_sentiment * math.log1p(num_comments)

    # Sort by normalized score
    sorted_players = OrderedDict(
        sorted(player_sentiments.items(),
               key=lambda x: x[1]["normalized_score"],
               reverse=True)
    )
    return sorted_players


# with open('player_names.json', 'r') as f:
#     player_names = json.load(f)

# pull_data_and_analyize_sentiment()

# sorted_player_data = OrderedDict(
#     sorted(player_sentiments.items(), key=lambda x : x[1]["sentiment_score"], reverse=True)
# )

# with open('player_sentiment_output.json', 'w') as f:
#      json.dump(sorted_player_data, f)


sorted_player_data = get_data()
with open('player_sentiment_output.json', 'w') as f:
      json.dump(sorted_player_data, f)