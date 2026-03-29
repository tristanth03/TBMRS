"""
    Nitrate Recommendation Engine
    
    Generates movie recommendations based on a user's lists and collection.
    
    Usage:
        from recommender import Recommender
        
        rec = Recommender(user_movies, user_lists)
        
        # Get recommendations based on a specific list
        recs = rec.recommend_for_list("list_123", n=10)
        
        # Get general recommendations based on entire collection
        recs = rec.recommend_general(n=10)
        
        # Get "because you liked X" style recommendations
        recs = rec.recommend_because(title_id="tt0111161", n=5)

    Each recommendation returns:
        [
            {
                "titleId": "tt1234567",
                "reason": "Because you liked Inception (Sci-Fi, Thriller)",
                "score": 0.87,
                "query_params": { ... }   # params used to find this
            },
            ...
        ]
    
    Note: This module builds the query parameters. 
          You still need to call the API yourself with these params.
          See recommend_and_fetch() for an all-in-one version.
"""

import requests
import json
import math
from collections import Counter, defaultdict
from typing import Optional
from datetime import datetime, timezone

API_BASE = "https://api.imdbapi.dev"


# ──────────────────────────────────────────────
# Corpus Statistics (lightweight IDF)
# ──────────────────────────────────────────────

# Approximate document-frequency of IMDb genres across all titles.
# Derived from genre distribution on IMDb's ~600k qualifying titles.
# Used as IDF prior so "Drama" (appears in ~40% of titles) gets
# downweighted vs "Film-Noir" (appears in <0.3%).
_GENRE_DOC_FREQ = {
    "Drama": 0.40, "Comedy": 0.22, "Action": 0.12, "Romance": 0.10,
    "Thriller": 0.09, "Crime": 0.08, "Horror": 0.07, "Adventure": 0.07,
    "Sci-Fi": 0.05, "Mystery": 0.05, "Fantasy": 0.04, "Documentary": 0.10,
    "Animation": 0.04, "Family": 0.04, "Biography": 0.03, "History": 0.03,
    "Music": 0.03, "War": 0.02, "Musical": 0.015, "Sport": 0.015,
    "Western": 0.01, "Film Noir": 0.003, "News": 0.005, "Reality-TV": 0.005,
    "Game Show": 0.003, "Talk-Show": 0.003, "Adult": 0.02, "Short": 0.08,
}

def _idf(genre: str) -> float:
    """Inverse document frequency: rarer genres → higher weight."""
    df = _GENRE_DOC_FREQ.get(genre, 0.01)
    return math.log(1.0 / df)


# ──────────────────────────────────────────────
# Preference Profile
# ──────────────────────────────────────────────

class PreferenceProfile:
    """
        Captures a user's taste from a set of movies.
        
        Built from either a list's movies or the full collection.
        
        Signals extracted:
          - TF-IDF weighted genre scores (rare genre affinity amplified)
          - Genre co-occurrence pairs (captures "Crime + Thriller" as a unit)
          - Rating surprise (user_rating - imdb_rating → personal taste signal)
          - Temporal decay (recent watches weigh more)
          - Bayesian rating threshold (derived, not hardcoded)
          - Taste entropy (narrow vs broad → auto-tunes strategy)
    """

    def __init__(self, movies: list[dict]):
        self.movies = movies

        # Raw accumulators
        self.genre_scores = Counter()       # TF-IDF weighted
        self.pair_scores = Counter()        # co-occurrence pairs
        self.decade_scores = Counter()
        self.type_scores = Counter()
        self.avg_user_rating = 0.0
        self.avg_imdb_rating = 0.0
        self.rating_std = 0.0              # how varied the user's ratings are
        self.preferred_year_range = (1900, 2030)
        self._genre_entropy = 0.0          # Shannon entropy of genre dist

        self._analyze()

    def _analyze(self):
        if not self.movies:
            return

        now_ts = datetime.now(timezone.utc).timestamp()
        user_ratings = []
        imdb_ratings = []
        years = []

        for m in self.movies:
            # ── Temporal decay ──
            # Half-life ~365 days: movies watched a year ago get ~0.5× weight
            decay = 1.0
            watched = m.get("watchedDate") or m.get("addedAt")
            if watched:
                try:
                    if isinstance(watched, str):
                        wt = datetime.fromisoformat(watched.replace("Z", "+00:00")).timestamp()
                    elif hasattr(watched, "timestamp"):
                        wt = watched.timestamp()
                    else:
                        wt = now_ts
                    age_days = max(0, (now_ts - wt) / 86400)
                    decay = math.exp(-0.0019 * age_days)   # λ = ln2/365 ≈ 0.0019
                except (ValueError, TypeError, OSError):
                    decay = 1.0

            # ── Rating surprise ──
            # If user rates 9 but IMDb says 6.5 → surprise = +2.5 → strong taste signal
            ur = m.get("userRating") or 0
            ir = m.get("imdbRating") or 0
            surprise = max(0, ur - ir) if (ur and ir) else 0
            base_weight = (ur or 5) / 5.0
            weight = base_weight * decay * (1.0 + 0.3 * surprise)

            # ── Genre scoring with IDF ──
            genres = m.get("genres") or []
            for g in genres:
                self.genre_scores[g] += weight * _idf(g)

            # ── Co-occurrence pairs ──
            # Sorted pairs so (Crime, Drama) == (Drama, Crime)
            if len(genres) >= 2:
                sorted_g = sorted(genres)
                for i in range(len(sorted_g)):
                    for j in range(i + 1, len(sorted_g)):
                        self.pair_scores[(sorted_g[i], sorted_g[j])] += weight

            # ── Decade scoring ──
            year = m.get("startYear")
            if year:
                decade = (year // 10) * 10
                self.decade_scores[decade] += weight
                years.append(year)

            # ── Type scoring ──
            self.type_scores[m.get("type", "movie")] += weight

            # ── Rating collection ──
            if ur and ur > 0:
                user_ratings.append(ur)
            if ir and ir > 0:
                imdb_ratings.append(ir)

        # ── Aggregate stats ──
        if user_ratings:
            self.avg_user_rating = sum(user_ratings) / len(user_ratings)
            if len(user_ratings) > 1:
                mean = self.avg_user_rating
                self.rating_std = math.sqrt(
                    sum((r - mean) ** 2 for r in user_ratings) / (len(user_ratings) - 1)
                )
        if imdb_ratings:
            self.avg_imdb_rating = sum(imdb_ratings) / len(imdb_ratings)

        # ── Year range (10th percentile → max) ──
        if years:
            years.sort()
            low_idx = max(0, len(years) // 10)
            self.preferred_year_range = (years[low_idx], years[-1])

        # ── Genre entropy (Shannon) ──
        # Low entropy = narrow taste → system should explore more
        # High entropy = broad taste → safe to exploit
        total = sum(self.genre_scores.values())
        if total > 0:
            probs = [v / total for v in self.genre_scores.values()]
            self._genre_entropy = -sum(p * math.log2(p) for p in probs if p > 0)

    # ── Properties ──

    @property
    def top_genres(self) -> list[str]:
        """Top 3 genres by TF-IDF-weighted score."""
        return [g for g, _ in self.genre_scores.most_common(3)]

    @property
    def top_pairs(self) -> list[tuple[str, str]]:
        """Top 2 genre co-occurrence pairs."""
        return [p for p, _ in self.pair_scores.most_common(2)]

    @property
    def top_type(self) -> str:
        if self.type_scores:
            return self.type_scores.most_common(1)[0][0]
        return "movie"

    @property
    def top_decades(self) -> list[int]:
        return [d for d, _ in self.decade_scores.most_common(2)]

    @property
    def genre_entropy(self) -> float:
        """Shannon entropy of genre distribution. Higher = broader taste."""
        return self._genre_entropy

    @property
    def min_rating_threshold(self) -> float:
        """
            Bayesian-style threshold.
            Blends the user's average with a prior of 6.5,
            pulled toward the prior when we have few data points.
        """
        prior = 6.5
        k = 5  # strength of prior (equivalent to 5 "phantom" movies at 6.5)
        n = len([m for m in self.movies if m.get("userRating")])
        if n == 0:
            return prior - 1.0  # lenient default
        blended = (prior * k + self.avg_user_rating * n) / (k + n)
        # Threshold = blended average minus one standard deviation (be generous)
        return max(4.0, round(blended - max(self.rating_std, 0.5), 1))

    @property
    def suggested_strategy(self) -> str:
        """
            Auto-select strategy from genre entropy.
            Narrow taste → explore.  Broad taste → similar.  Middle → balanced.
        """
        if self._genre_entropy < 2.0:
            return "explore"
        elif self._genre_entropy > 3.5:
            return "similar"
        return "balanced"

    def genre_adjacency(self) -> dict[str, str]:
        """
            Learn adjacent genres from co-occurrence data instead of a hardcoded map.
            For each top genre, find its strongest co-occurring partner
            that ISN'T also a top genre → that's the "adjacent" genre for exploration.
        """
        top_set = set(self.top_genres)
        adjacency = {}
        for g in self.top_genres:
            best, best_score = "Drama", 0  # fallback
            for (a, b), score in self.pair_scores.most_common():
                partner = b if a == g else (a if b == g else None)
                if partner and partner not in top_set and score > best_score:
                    best, best_score = partner, score
            adjacency[g] = best
        return adjacency

    def summary(self) -> dict:
        return {
            "top_genres": self.top_genres,
            "top_pairs": [list(p) for p in self.top_pairs],
            "top_type": self.top_type,
            "top_decades": self.top_decades,
            "avg_user_rating": round(self.avg_user_rating, 1),
            "avg_imdb_rating": round(self.avg_imdb_rating, 1),
            "rating_std": round(self.rating_std, 2),
            "preferred_years": self.preferred_year_range,
            "min_rating_threshold": self.min_rating_threshold,
            "genre_entropy": round(self._genre_entropy, 2),
            "suggested_strategy": self.suggested_strategy,
            "movie_count": len(self.movies),
        }

    def __repr__(self):
        return f"PreferenceProfile({json.dumps(self.summary(), indent=2)})"


# ──────────────────────────────────────────────
# Recommendation Strategies
# ──────────────────────────────────────────────

def _norm_type(t: str) -> str:
    """Normalize type string for the API."""
    return t.upper().replace("TVSERIES", "TV_SERIES").replace("TVMINISERIES", "TV_MINI_SERIES")


def _build_api_params(profile: PreferenceProfile, strategy: str = "balanced") -> list[dict]:
    """
        Builds a list of API query parameter sets from a profile.
        
        Multiple param sets = multiple queries to increase diversity.
        
        Strategies:
            "balanced"   — mix of genre combos and year ranges
            "similar"    — tight match to existing taste
            "explore"    — push outside comfort zone slightly
            "auto"       — let entropy decide
        
        Uses co-occurrence pairs for tighter genre combos,
        and learned adjacency for exploration.
    """
    if strategy == "auto":
        strategy = profile.suggested_strategy

    queries = []
    genres = profile.top_genres
    pairs = profile.top_pairs
    min_rating = profile.min_rating_threshold
    adjacency = profile.genre_adjacency()

    if strategy == "similar":
        # ── Tight match: best co-occurring pair, same era, high rating ──
        if pairs:
            queries.append({
                "types": _norm_type(profile.top_type),
                "genres": ",".join(pairs[0]),
                "startYear": profile.preferred_year_range[0],
                "endYear": profile.preferred_year_range[1],
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })
        elif genres:
            queries.append({
                "types": _norm_type(profile.top_type),
                "genres": ",".join(genres[:2]),
                "startYear": profile.preferred_year_range[0],
                "endYear": profile.preferred_year_range[1],
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })
        # Second query: the other pair or solo top genre in a different sort
        if len(pairs) >= 2:
            queries.append({
                "genres": ",".join(pairs[1]),
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })

    elif strategy == "explore":
        # ── Learned adjacency instead of hardcoded map ──
        if genres and adjacency:
            # Adjacent genre in the user's era
            adj = adjacency.get(genres[0], "Drama")
            queries.append({
                "genres": adj,
                "startYear": profile.preferred_year_range[0],
                "endYear": profile.preferred_year_range[1],
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })
        if genres:
            # Same top genre but a different era (earlier classics)
            queries.append({
                "genres": genres[0],
                "endYear": max(1960, profile.preferred_year_range[0] - 1),
                "minAggregateRating": max(min_rating, 7.0),
                "minVoteCount": 10000,
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })
        # Third query: second-ranked pair flipped into explore territory
        if len(genres) >= 2 and adjacency:
            adj2 = adjacency.get(genres[1], "Drama")
            if adj2 != adjacency.get(genres[0], ""):
                queries.append({
                    "genres": f"{genres[1]},{adj2}",
                    "minAggregateRating": max(min_rating, 6.5),
                    "minVoteCount": 5000,
                    "sortBy": "SORT_BY_USER_RATING",
                    "sortOrder": "DESC",
                })

    else:  # balanced (default)
        # ── Query 1: Best co-occurring pair, popularity sorted ──
        if pairs:
            queries.append({
                "genres": ",".join(pairs[0]),
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })
        elif len(genres) >= 2:
            queries.append({
                "genres": ",".join(genres[:2]),
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })

        # ── Query 2: Third genre (the "wild card"), high rating ──
        if len(genres) >= 3:
            queries.append({
                "genres": genres[2],
                "minAggregateRating": max(min_rating, 7.0),
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })

        # ── Query 3: Top genre + preferred decade ──
        if genres and profile.top_decades:
            decade = profile.top_decades[0]
            queries.append({
                "genres": genres[0],
                "startYear": decade,
                "endYear": decade + 9,
                "minAggregateRating": min_rating,
                "minVoteCount": 5000,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })

        # ── Query 4 (bonus): Adjacent genre for serendipity ──
        if genres and adjacency and len(queries) < 4:
            adj = adjacency.get(genres[0])
            if adj:
                queries.append({
                    "genres": adj,
                    "minAggregateRating": max(min_rating, 6.5),
                    "minVoteCount": 10000,
                    "sortBy": "SORT_BY_USER_RATING",
                    "sortOrder": "DESC",
                })

    # Fallback
    if not queries:
        queries.append({
            "minAggregateRating": 7.0,
            "minVoteCount": 10000,
            "sortBy": "SORT_BY_POPULARITY",
            "sortOrder": "DESC",
        })

    return queries


# ──────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────

def _score_title(title: dict, profile: PreferenceProfile, owned_ids: set) -> float:
    """
        Scores a title (0.0 - 1.0) based on profile match.
        Returns -1 if excluded (already owned).
        
        Scoring breakdown:
          0.35  Genre overlap (TF-IDF weighted, includes pair bonus)
          0.20  IMDb rating quality
          0.15  Year proximity (Gaussian kernel, not linear)
          0.10  Type match
          0.10  Vote credibility (log-scale, smooth)
          0.10  Co-occurrence pair bonus
    """
    tid = title.get("id", "")
    if tid in owned_ids:
        return -1.0

    score = 0.0
    title_genres = set(title.get("genres") or [])

    # ── Genre overlap with IDF weighting (0 – 0.35) ──
    if profile.genre_scores:
        # Weighted overlap: how much IDF-weight does the candidate share?
        profile_total = sum(profile.genre_scores[g] for g in profile.top_genres) or 1
        overlap_weight = sum(profile.genre_scores.get(g, 0) for g in title_genres)
        score += min(overlap_weight / profile_total, 1.0) * 0.35

    # ── Co-occurrence pair bonus (0 – 0.10) ──
    if profile.pair_scores:
        pair_total = sum(v for _, v in profile.pair_scores.most_common(3)) or 1
        pair_hit = 0
        sorted_tg = sorted(title_genres)
        for i in range(len(sorted_tg)):
            for j in range(i + 1, len(sorted_tg)):
                pair_hit += profile.pair_scores.get((sorted_tg[i], sorted_tg[j]), 0)
        score += min(pair_hit / pair_total, 1.0) * 0.10

    # ── IMDb rating quality (0 – 0.20) ──
    rating = (
        title.get("rating", {}).get("aggregateRating", 0)
        if isinstance(title.get("rating"), dict) else 0
    )
    if rating:
        # Sigmoid-ish curve: ratings below 5 contribute almost nothing,
        # ratings above 8 get near-full credit
        score += (1 / (1 + math.exp(-1.5 * (rating - 6.5)))) * 0.20

    # ── Year proximity with Gaussian kernel (0 – 0.15) ──
    year = title.get("startYear", 0)
    if year and profile.preferred_year_range:
        low, high = profile.preferred_year_range
        mid = (low + high) / 2
        sigma = max((high - low) / 2, 10)  # adaptive spread
        proximity = math.exp(-0.5 * ((year - mid) / sigma) ** 2)
        score += proximity * 0.15

    # ── Type match (0 – 0.10) ──
    title_type = (title.get("type") or "").lower().replace(" ", "")
    if title_type == profile.top_type.lower().replace(" ", ""):
        score += 0.10

    # ── Vote credibility — log scale (0 – 0.10) ──
    votes = (
        title.get("rating", {}).get("voteCount", 0)
        if isinstance(title.get("rating"), dict) else 0
    )
    if votes > 0:
        # log10(1000)=3, log10(100000)=5, log10(1M)=6. Normalize to [0, 1].
        score += min(math.log10(votes) / 6.0, 1.0) * 0.10

    return round(score, 4)


def _mmr_rerank(scored: list[dict], n: int, lam: float = 0.7) -> list[dict]:
    """
        Maximal Marginal Relevance re-ranking.
        
        Balances relevance (rec_score) with diversity (genre dissimilarity
        to already-selected items). λ=1 → pure relevance, λ=0 → pure diversity.
        
        This is O(n·k) where k = items to select — trivial for n≤50.
    """
    if len(scored) <= n:
        return scored

    selected = []
    remaining = list(scored)

    # Pick the best one first
    remaining.sort(key=lambda t: t["rec_score"], reverse=True)
    selected.append(remaining.pop(0))

    while len(selected) < n and remaining:
        best_idx, best_mmr = -1, -float("inf")
        sel_genres = [set(t.get("genres") or []) for t in selected]

        for i, cand in enumerate(remaining):
            relevance = cand["rec_score"]

            # Max similarity to any already-selected item (Jaccard)
            cand_genres = set(cand.get("genres") or [])
            max_sim = 0
            for sg in sel_genres:
                union = len(cand_genres | sg) or 1
                max_sim = max(max_sim, len(cand_genres & sg) / union)

            mmr = lam * relevance - (1 - lam) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i

        selected.append(remaining.pop(best_idx))

    return selected


# ──────────────────────────────────────────────
# Main Recommender Class
# ──────────────────────────────────────────────

class Recommender:
    """
        Generates recommendations based on a user's movie collection and lists.
        
        user_movies: dict of { titleId: movieData }
        user_lists:  dict of { listId: listData } where listData has 'name', 'emoji'
        
        Movies should have a 'lists' field (list of listId strings) to associate
        them with lists.
    """

    def __init__(self, user_movies: dict, user_lists: dict):
        self.user_movies = user_movies
        self.user_lists = user_lists
        self.owned_ids = set(user_movies.keys())

    def _movies_in_list(self, list_id: str) -> list[dict]:
        return [
            m for m in self.user_movies.values()
            if list_id in (m.get("lists") or [])
        ]

    def profile_for_list(self, list_id: str) -> PreferenceProfile:
        return PreferenceProfile(self._movies_in_list(list_id))

    def profile_general(self) -> PreferenceProfile:
        return PreferenceProfile(list(self.user_movies.values()))

    def recommend_for_list(self, list_id: str, n: int = 10, strategy: str = "balanced") -> dict:
        """
            Generate recommendations based on a specific list.
            
            Returns:
                {
                    "list_name": "Comfort Movies",
                    "list_emoji": "🛋️",
                    "profile": { ... },
                    "queries": [ { api params }, ... ],
                    "reason": "Based on your 'Comfort Movies' list (Comedy, Romance)"
                }
        """
        list_data = self.user_lists.get(list_id, {})
        profile = self.profile_for_list(list_id)

        if not profile.movies:
            return {
                "list_name": list_data.get("name", "Unknown"),
                "list_emoji": list_data.get("emoji", "🎬"),
                "profile": profile.summary(),
                "queries": [],
                "reason": f"Add movies to '{list_data.get('name', 'this list')}' to get recommendations."
            }

        queries = _build_api_params(profile, strategy)
        genres_str = " & ".join(profile.top_genres[:2]) if profile.top_genres else "your favorites"

        return {
            "list_name": list_data.get("name", "Unknown"),
            "list_emoji": list_data.get("emoji", "🎬"),
            "profile": profile.summary(),
            "queries": queries,
            "reason": f"Based on your '{list_data.get('name', '')}' list ({genres_str})"
        }

    def recommend_general(self, n: int = 10, strategy: str = "balanced") -> dict:
        """
            Generate recommendations based on the entire collection.
            
            Returns same structure as recommend_for_list but for overall taste.
        """
        profile = self.profile_general()

        if not profile.movies:
            return {
                "profile": profile.summary(),
                "queries": [],
                "reason": "Add movies to your collection to get recommendations."
            }

        queries = _build_api_params(profile, strategy)
        genres_str = " & ".join(profile.top_genres[:2]) if profile.top_genres else "movies"

        return {
            "profile": profile.summary(),
            "queries": queries,
            "reason": f"Based on your love of {genres_str}"
        }

    def recommend_because(self, title_id: str, n: int = 5) -> dict:
        """
            "Because you liked X" style recommendations.
            
            Builds a mini-profile from just that one movie and finds similar ones.
        """
        movie = self.user_movies.get(title_id)
        if not movie:
            return {"queries": [], "reason": "Movie not found in collection."}

        profile = PreferenceProfile([movie])
        queries = _build_api_params(profile, "similar")

        return {
            "source_title": movie.get("primaryTitle", "Unknown"),
            "profile": profile.summary(),
            "queries": queries,
            "reason": f"Because you liked {movie.get('primaryTitle', 'this movie')}"
        }

    def recommend_all_lists(self) -> list[dict]:
        """
            Generate recommendations for every list that has 2+ movies.
            
            Returns a list of recommendation objects, one per qualifying list.
        """
        results = []
        for list_id, list_data in self.user_lists.items():
            movies = self._movies_in_list(list_id)
            if len(movies) >= 2:
                rec = self.recommend_for_list(list_id)
                rec["list_id"] = list_id
                results.append(rec)
        return results

    def recommend_and_fetch(self, list_id: Optional[str] = None, n: int = 10, strategy: str = "balanced") -> list[dict]:
        """
            All-in-one: generate recommendations AND fetch from API.
            
            Returns a scored, deduplicated, MMR-diversified list of title dicts.
            Each title gets an extra 'rec_score' and 'rec_reason' field.
        """
        if list_id:
            rec = self.recommend_for_list(list_id, n, strategy)
            profile = self.profile_for_list(list_id)
        else:
            rec = self.recommend_general(n, strategy)
            profile = self.profile_general()

        if not rec["queries"]:
            return []

        # Fetch from API
        all_titles = {}
        for params in rec["queries"]:
            url = f"{API_BASE}/titles?"
            url += "&".join(f"{k}={v}" for k, v in params.items())
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    data = response.json()
                    for t in data.get("titles", []):
                        if t["id"] not in all_titles:
                            all_titles[t["id"]] = t
            except Exception as e:
                print(f"Fetch failed: {e}")
                continue

        # Score
        scored = []
        for title in all_titles.values():
            s = _score_title(title, profile, self.owned_ids)
            if s >= 0:
                title["rec_score"] = s
                title["rec_reason"] = rec["reason"]
                scored.append(title)

        # MMR-diversified re-ranking
        scored.sort(key=lambda t: t["rec_score"], reverse=True)
        diversified = _mmr_rerank(scored, n)

        return diversified[:n]


# ──────────────────────────────────────────────
# CLI Demo
# ──────────────────────────────────────────────

if __name__ == "__main__":
    user_movies = {
        "tt0111161": {
            "titleId": "tt0111161",
            "primaryTitle": "The Shawshank Redemption",
            "genres": ["Drama"],
            "startYear": 1994,
            "type": "movie",
            "userRating": 10,
            "imdbRating": 9.3,
            "lists": ["list_1"]
        },
        "tt0068646": {
            "titleId": "tt0068646",
            "primaryTitle": "The Godfather",
            "genres": ["Crime", "Drama"],
            "startYear": 1972,
            "type": "movie",
            "userRating": 9,
            "imdbRating": 9.2,
            "lists": ["list_1"]
        },
        "tt0816692": {
            "titleId": "tt0816692",
            "primaryTitle": "Interstellar",
            "genres": ["Adventure", "Drama", "Sci-Fi"],
            "startYear": 2014,
            "type": "movie",
            "userRating": 9,
            "imdbRating": 8.7,
            "lists": ["list_2"]
        },
        "tt1375666": {
            "titleId": "tt1375666",
            "primaryTitle": "Inception",
            "genres": ["Action", "Adventure", "Sci-Fi"],
            "startYear": 2010,
            "type": "movie",
            "userRating": 8,
            "imdbRating": 8.8,
            "lists": ["list_2"]
        },
    }

    user_lists = {
        "list_1": {"name": "All-Time Greats", "emoji": "🏆"},
        "list_2": {"name": "Mind-Benders", "emoji": "🌀"},
    }

    rec = Recommender(user_movies, user_lists)

    # Show profiles
    print("=== General Profile ===")
    print(rec.profile_general())

    print("\n=== All-Time Greats Profile ===")
    print(rec.profile_for_list("list_1"))

    print("\n=== Mind-Benders Profile ===")
    print(rec.profile_for_list("list_2"))

    # Generate recommendations (queries only, no fetch)
    print("\n=== Recommendations for 'All-Time Greats' ===")
    r = rec.recommend_for_list("list_1")
    print(f"Reason: {r['reason']}")
    print(f"Queries: {json.dumps(r['queries'], indent=2)}")

    print("\n=== Recommendations for 'Mind-Benders' ===")
    r = rec.recommend_for_list("list_2")
    print(f"Reason: {r['reason']}")
    print(f"Queries: {json.dumps(r['queries'], indent=2)}")

    print("\n=== 'Because you liked Inception' ===")
    r = rec.recommend_because("tt1375666")
    print(f"Reason: {r['reason']}")
    print(f"Queries: {json.dumps(r['queries'], indent=2)}")

    # Fetch actual recommendations
    print("\n=== Fetching recommendations for 'Mind-Benders'... ===")
    results = rec.recommend_and_fetch("list_2", n=5)
    for t in results:
        print(f"  [{t['rec_score']:.2f}] {t.get('primaryTitle', '?')} ({t.get('startYear', '?')}) — {', '.join(t.get('genres', []))}")