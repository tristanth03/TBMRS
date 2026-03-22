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
from collections import Counter, defaultdict
from typing import Optional

API_BASE = "https://api.imdbapi.dev"


# ──────────────────────────────────────────────
# Preference Profile
# ──────────────────────────────────────────────

class PreferenceProfile:
    """
        Captures a user's taste from a set of movies.
        
        Built from either a list's movies or the full collection.
        Weights genres, decades, types, and rating patterns.
    """

    def __init__(self, movies: list[dict]):
        """
            movies: list of movie dicts from the user's collection.
                    Each should have: genres, startYear, type, userRating, imdbRating
        """
        self.movies = movies
        self.genre_scores = Counter()
        self.decade_scores = Counter()
        self.type_scores = Counter()
        self.avg_user_rating = 0
        self.avg_imdb_rating = 0
        self.preferred_year_range = (1900, 2030)

        self._analyze()

    def _analyze(self):
        if not self.movies:
            return

        total_user_rating = 0
        total_imdb_rating = 0
        rated_count = 0
        imdb_count = 0
        years = []

        for m in self.movies:
            # Weight = user rating normalized (higher = stronger signal)
            weight = (m.get("userRating") or 5) / 5.0

            # Genre scoring — weighted by how much the user liked it
            for genre in (m.get("genres") or []):
                self.genre_scores[genre] += weight

            # Decade scoring
            year = m.get("startYear")
            if year:
                decade = (year // 10) * 10
                self.decade_scores[decade] += weight
                years.append(year)

            # Type scoring
            mtype = m.get("type", "movie")
            self.type_scores[mtype] += weight

            # Rating aggregation
            ur = m.get("userRating")
            if ur and ur > 0:
                total_user_rating += ur
                rated_count += 1

            ir = m.get("imdbRating")
            if ir and ir > 0:
                total_imdb_rating += ir
                imdb_count += 1

        if rated_count:
            self.avg_user_rating = total_user_rating / rated_count
        if imdb_count:
            self.avg_imdb_rating = total_imdb_rating / imdb_count
        if years:
            # Preferred range: 10th percentile to max (leans toward what they watch most)
            years.sort()
            low_idx = max(0, len(years) // 10)
            self.preferred_year_range = (years[low_idx], years[-1])

    @property
    def top_genres(self) -> list[str]:
        """Top 3 genres by weighted score."""
        return [g for g, _ in self.genre_scores.most_common(3)]

    @property
    def top_type(self) -> str:
        """Most watched type (movie, tvSeries, etc.)."""
        if self.type_scores:
            return self.type_scores.most_common(1)[0][0]
        return "movie"

    @property
    def top_decades(self) -> list[int]:
        """Top 2 decades."""
        return [d for d, _ in self.decade_scores.most_common(2)]

    @property
    def min_rating_threshold(self) -> float:
        """
            Suggest a minimum IMDb rating based on the user's taste.
            Users who rate high tend to prefer higher-rated films.
        """
        if self.avg_user_rating >= 8:
            return 7.0
        elif self.avg_user_rating >= 6:
            return 6.0
        else:
            return 5.0

    def summary(self) -> dict:
        """Human-readable summary of this profile."""
        return {
            "top_genres": self.top_genres,
            "top_type": self.top_type,
            "top_decades": self.top_decades,
            "avg_user_rating": round(self.avg_user_rating, 1),
            "avg_imdb_rating": round(self.avg_imdb_rating, 1),
            "preferred_years": self.preferred_year_range,
            "min_rating_threshold": self.min_rating_threshold,
            "movie_count": len(self.movies),
        }

    def __repr__(self):
        return f"PreferenceProfile({json.dumps(self.summary(), indent=2)})"


# ──────────────────────────────────────────────
# Recommendation Strategies
# ──────────────────────────────────────────────

def _build_api_params(profile: PreferenceProfile, strategy: str = "balanced") -> list[dict]:
    """
        Builds a list of API query parameter sets from a profile.
        
        Multiple param sets = multiple queries to increase diversity.
        
        Strategies:
            "balanced"   — mix of genre combos and year ranges
            "similar"    — tight match to existing taste
            "explore"    — push outside comfort zone slightly
    """
    queries = []
    genres = profile.top_genres
    min_rating = profile.min_rating_threshold

    if strategy == "similar":
        # Tight match: top genres, same era, high rating
        if genres:
            queries.append({
                "types": profile.top_type.upper().replace("TVSERIES", "TV_SERIES").replace("TVMINISERIES", "TV_MINI_SERIES"),
                "genres": ",".join(genres[:2]),
                "startYear": profile.preferred_year_range[0],
                "endYear": profile.preferred_year_range[1],
                "minAggregateRating": min_rating,
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })

    elif strategy == "explore":
        # Same genres but different era
        if genres:
            # Earlier era
            queries.append({
                "genres": genres[0],
                "endYear": profile.preferred_year_range[0] - 1,
                "minAggregateRating": max(min_rating, 7.0),
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })
            # Different genre but same era
            if len(genres) >= 2:
                adjacent_genres = {
                    "Action": "Thriller", "Thriller": "Mystery", "Comedy": "Romance",
                    "Drama": "Biography", "Sci-Fi": "Fantasy", "Horror": "Mystery",
                    "Romance": "Drama", "Adventure": "Fantasy", "Crime": "Thriller",
                    "Animation": "Family", "Documentary": "Biography", "War": "History",
                    "Fantasy": "Adventure", "Mystery": "Crime", "Biography": "History",
                    "Music": "Musical", "Musical": "Music", "Western": "Adventure",
                    "Family": "Animation", "History": "War", "Sport": "Drama",
                }
                adj = adjacent_genres.get(genres[0], "Drama")
                queries.append({
                    "genres": adj,
                    "startYear": profile.preferred_year_range[0],
                    "endYear": profile.preferred_year_range[1],
                    "minAggregateRating": min_rating,
                    "sortBy": "SORT_BY_POPULARITY",
                    "sortOrder": "DESC",
                })

    else:  # balanced (default)
        # Query 1: Primary genre combo, popularity sorted
        if len(genres) >= 2:
            queries.append({
                "genres": ",".join(genres[:2]),
                "minAggregateRating": min_rating,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })
        # Query 2: Third genre + high rating
        if len(genres) >= 3:
            queries.append({
                "genres": genres[2],
                "minAggregateRating": max(min_rating, 7.0),
                "sortBy": "SORT_BY_USER_RATING",
                "sortOrder": "DESC",
            })
        # Query 3: Top genre + preferred decade
        if genres and profile.top_decades:
            decade = profile.top_decades[0]
            queries.append({
                "genres": genres[0],
                "startYear": decade,
                "endYear": decade + 9,
                "minAggregateRating": min_rating,
                "sortBy": "SORT_BY_POPULARITY",
                "sortOrder": "DESC",
            })

    # Fallback: if no queries were generated
    if not queries:
        queries.append({
            "minAggregateRating": 7.0,
            "sortBy": "SORT_BY_POPULARITY",
            "sortOrder": "DESC",
        })

    return queries


# ──────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────

def _score_title(title: dict, profile: PreferenceProfile, owned_ids: set) -> float:
    """
        Scores a title (0.0 - 1.0) based on how well it matches the profile.
        Returns -1 if the title should be excluded (already owned, etc.)
    """
    tid = title.get("id", "")
    if tid in owned_ids:
        return -1.0

    score = 0.0

    # Genre overlap (0 - 0.4)
    title_genres = set(title.get("genres") or [])
    profile_genres = set(profile.top_genres)
    if profile_genres:
        overlap = len(title_genres & profile_genres) / len(profile_genres)
        score += overlap * 0.4

    # IMDb rating bonus (0 - 0.25)
    rating = title.get("rating", {}).get("aggregateRating", 0) if isinstance(title.get("rating"), dict) else 0
    if rating:
        score += min(rating / 10.0, 1.0) * 0.25

    # Year proximity (0 - 0.15)
    year = title.get("startYear", 0)
    if year and profile.preferred_year_range:
        low, high = profile.preferred_year_range
        mid = (low + high) / 2
        dist = abs(year - mid)
        proximity = max(0, 1 - dist / 50)  # within 50 years = some score
        score += proximity * 0.15

    # Type match (0 - 0.1)
    if title.get("type", "").lower().replace(" ", "") == profile.top_type.lower().replace(" ", ""):
        score += 0.1

    # Vote count popularity bonus (0 - 0.1)
    votes = title.get("rating", {}).get("voteCount", 0) if isinstance(title.get("rating"), dict) else 0
    if votes > 50000:
        score += 0.1
    elif votes > 10000:
        score += 0.05

    return round(score, 3)


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
        """Get all movies belonging to a specific list."""
        return [
            m for m in self.user_movies.values()
            if list_id in (m.get("lists") or [])
        ]

    def profile_for_list(self, list_id: str) -> PreferenceProfile:
        """Build a preference profile from a specific list's movies."""
        movies = self._movies_in_list(list_id)
        return PreferenceProfile(movies)

    def profile_general(self) -> PreferenceProfile:
        """Build a preference profile from the entire collection."""
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
            
            Returns a scored, deduplicated, sorted list of title dicts.
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

        # Score and sort
        scored = []
        for title in all_titles.values():
            s = _score_title(title, profile, self.owned_ids)
            if s >= 0:
                title["rec_score"] = s
                title["rec_reason"] = rec["reason"]
                scored.append(title)

        scored.sort(key=lambda t: t["rec_score"], reverse=True)
        return scored[:n]


# ──────────────────────────────────────────────
# CLI Demo
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Example usage with dummy data
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
