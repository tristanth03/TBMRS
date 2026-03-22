"""
    Tests for imdbapi.py

    Run: python test_imdbapi.py

    These are live API tests — they hit the real imdbapi.dev endpoint.
    No mocking, no faking. If they pass, the wrapper works.
"""

from api_wrapper__v00 import *

SHAWSHANK = "tt0111161"
BREAKING_BAD = "tt0903747"
DICAPRIO = "nm0000138"

passed = 0
failed = 0


import time

def test(name, func):
    global passed, failed
    time.sleep(0.3)  # avoid 429 rate limiting
    try:
        result = func()
        if result:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name} — returned None")
            failed += 1
    except Exception as e:
        print(f"  ✗ {name} — {e}")
        failed += 1


# ──────────────────────────────────────────────
# Helper Tests
# ──────────────────────────────────────────────

print("\n── Helpers ──")

def test_country_exact():
    code = country_to_countryCode("Iceland")
    assert code == "IS", f"Expected 'IS', got '{code}'"
    return True
test("country_to_countryCode exact match", test_country_exact)

def test_country_fuzzy():
    code = country_to_countryCode("german")
    assert code == "DE", f"Expected 'DE', got '{code}'"
    return True
test("country_to_countryCode fuzzy match", test_country_fuzzy)

def test_country_invalid():
    code = country_to_countryCode("Atlantis")
    assert code is None, f"Expected None, got '{code}'"
    return True
test("country_to_countryCode invalid input", test_country_invalid)

def test_language_exact():
    code = language_to_languageCode("English")
    assert code == "eng", f"Expected 'eng', got '{code}'"
    return True
test("language_to_languageCode exact match", test_language_exact)

def test_language_fuzzy():
    code = language_to_languageCode("portug")
    assert code == "por", f"Expected 'por', got '{code}'"
    return True
test("language_to_languageCode fuzzy fallback", test_language_fuzzy)

def test_language_invalid():
    code = language_to_languageCode("Zzxywqq")
    assert code is None, f"Expected None, got '{code}'"
    return True
test("language_to_languageCode invalid input", test_language_invalid)


# ──────────────────────────────────────────────
# Title Endpoint Tests
# ──────────────────────────────────────────────

print("\n── Titles ──")

def test_get_titles_basic():
    data, url = get_titles(type="MOVIE", sort_by="SORT_BY_POPULARITY", sort_order="DESC")
    titles = data.get("titles", [])
    assert len(titles) > 0, "No titles returned"
    assert "primaryTitle" in titles[0], "Missing primaryTitle field"
    return True
test("get_titles — movies by popularity", test_get_titles_basic)

def test_get_titles_filtered():
    data, url = get_titles(
        type="MOVIE",
        genres="Action",
        start_year=2020,
        end_year=2025,
        min_agg_rating=7.0,
        sort_by="SORT_BY_USER_RATING",
        sort_order="DESC"
    )
    titles = data.get("titles", [])
    assert len(titles) > 0, "No titles returned"
    for t in titles:
        rating = t.get("rating", {}).get("aggregateRating", 0)
        assert rating >= 7.0, f"Title '{t['primaryTitle']}' has rating {rating} < 7.0"
    return True
test("get_titles — action movies 2020-2025 rated 7+", test_get_titles_filtered)

def test_get_title_by_id():
    data, url = get_title(SHAWSHANK)
    assert data["id"] == SHAWSHANK, f"Wrong ID: {data['id']}"
    assert data["primaryTitle"] == "The Shawshank Redemption"
    assert data["startYear"] == 1994
    assert "Drama" in data.get("genres", [])
    return True
test("get_title — The Shawshank Redemption", test_get_title_by_id)

def test_batch_get_titles():
    data, url = batch_get_titles(f"{SHAWSHANK},tt1375666")
    titles = data.get("titles", [])
    assert len(titles) == 2, f"Expected 2 titles, got {len(titles)}"
    ids = [t["id"] for t in titles]
    assert SHAWSHANK in ids, "Shawshank not in results"
    assert "tt1375666" in ids, "Inception not in results"
    return True
test("batch_get_titles — Shawshank + Inception", test_batch_get_titles)

def test_search_titles():
    data, url = search_titles("Inception", limit=5)
    titles = data.get("titles", [])
    assert len(titles) > 0, "No search results"
    assert len(titles) <= 5, f"Got {len(titles)} results, expected max 5"
    found = any("Inception" in t.get("primaryTitle", "") for t in titles)
    assert found, "Inception not found in search results"
    return True
test("search_titles — 'Inception' limit 5", test_search_titles)

def test_get_title_credits():
    data, url = get_title_credits(SHAWSHANK, page_size=5)
    credits = data.get("credits", [])
    assert len(credits) > 0, "No credits returned"
    assert len(credits) <= 5, f"Got {len(credits)} credits, expected max 5"
    assert "category" in credits[0], "Missing category field"
    return True
test("get_title_credits — Shawshank top 5", test_get_title_credits)

def test_get_title_release_dates():
    data, url = get_title_release_dates(SHAWSHANK)
    dates = data.get("releaseDates", [])
    assert len(dates) > 0, "No release dates returned"
    assert "country" in dates[0], "Missing country field"
    assert "releaseDate" in dates[0], "Missing releaseDate field"
    return True
test("get_title_release_dates — Shawshank", test_get_title_release_dates)

def test_get_title_akas():
    data, url = get_title_akas(SHAWSHANK)
    akas = data.get("akas", [])
    assert len(akas) > 0, "No AKAs returned"
    assert "text" in akas[0], "Missing text field"
    return True
test("get_title_akas — Shawshank", test_get_title_akas)

def test_get_title_seasons():
    data, url = get_title_seasons(BREAKING_BAD)
    seasons = data.get("seasons", [])
    assert len(seasons) == 5, f"Expected 5 seasons, got {len(seasons)}"
    return True
test("get_title_seasons — Breaking Bad has 5 seasons", test_get_title_seasons)

def test_get_title_episodes():
    data, url = get_title_episodes(BREAKING_BAD, season=1)
    episodes = data.get("episodes", [])
    assert len(episodes) == 7, f"Expected 7 episodes in S1, got {len(episodes)}"
    assert episodes[0].get("season") == "1"
    return True
test("get_title_episodes — Breaking Bad S1 has 7 episodes", test_get_title_episodes)

def test_get_title_images():
    data, url = get_title_images(SHAWSHANK, page_size=3)
    images = data.get("images", [])
    assert len(images) > 0, "No images returned"
    assert "url" in images[0], "Missing url field"
    return True
test("get_title_images — Shawshank", test_get_title_images)

def test_get_title_videos():
    data, url = get_title_videos(SHAWSHANK, page_size=3)
    videos = data.get("videos", [])
    assert len(videos) > 0, "No videos returned"
    assert "name" in videos[0], "Missing name field"
    return True
test("get_title_videos — Shawshank", test_get_title_videos)

def test_get_title_award_nominations():
    data, url = get_title_award_nominations(SHAWSHANK, page_size=5)
    noms = data.get("awardNominations", [])
    stats = data.get("stats", {})
    assert len(noms) > 0, "No nominations returned"
    assert stats.get("nominationCount", 0) > 0, "No nomination count"
    return True
test("get_title_award_nominations — Shawshank", test_get_title_award_nominations)

def test_get_title_parents_guide():
    data, url = get_title_parents_guide(SHAWSHANK)
    guide = data.get("parentsGuide", [])
    assert len(guide) > 0, "No parents guide returned"
    categories = [g.get("category") for g in guide]
    assert "VIOLENCE" in categories, "Missing VIOLENCE category"
    return True
test("get_title_parents_guide — Shawshank", test_get_title_parents_guide)

def test_get_title_certificates():
    data, url = get_title_certificates(SHAWSHANK)
    certs = data.get("certificates", [])
    assert len(certs) > 0, "No certificates returned"
    assert "rating" in certs[0], "Missing rating field"
    return True
test("get_title_certificates — Shawshank", test_get_title_certificates)

def test_get_title_company_credits():
    data, url = get_title_company_credits(SHAWSHANK, page_size=5)
    credits = data.get("companyCredits", [])
    assert len(credits) > 0, "No company credits returned"
    assert "company" in credits[0], "Missing company field"
    return True
test("get_title_company_credits — Shawshank", test_get_title_company_credits)

def test_get_title_box_office():
    data, url = get_title_box_office(SHAWSHANK)
    assert "worldwideGross" in data or "domesticGross" in data, "No box office data"
    return True
test("get_title_box_office — Shawshank", test_get_title_box_office)


# ──────────────────────────────────────────────
# Name Endpoint Tests
# ──────────────────────────────────────────────

print("\n── Names ──")

def test_get_name():
    data, url = get_name(DICAPRIO)
    assert data["id"] == DICAPRIO
    assert "DiCaprio" in data.get("displayName", "")
    assert len(data.get("primaryProfessions", [])) > 0
    return True
test("get_name — Leonardo DiCaprio", test_get_name)

def test_batch_get_names():
    data, url = batch_get_names(f"{DICAPRIO},nm0000233")
    names = data.get("names", [])
    assert len(names) == 2, f"Expected 2 names, got {len(names)}"
    display_names = [n["displayName"] for n in names]
    assert any("DiCaprio" in n for n in display_names)
    assert any("Tarantino" in n for n in display_names)
    return True
test("batch_get_names — DiCaprio + Tarantino", test_batch_get_names)

def test_get_name_images():
    data, url = get_name_images(DICAPRIO, page_size=3)
    images = data.get("images", [])
    assert len(images) > 0, "No images returned"
    return True
test("get_name_images — DiCaprio", test_get_name_images)

def test_get_name_filmography():
    data, url = get_name_filmography(DICAPRIO, categories="actor", page_size=5)
    credits = data.get("credits", [])
    assert len(credits) > 0, "No filmography returned"
    assert credits[0].get("category") == "actor"
    return True
test("get_name_filmography — DiCaprio acting credits", test_get_name_filmography)

def test_get_name_relationships():
    data, url = get_name_relationships(DICAPRIO)
    # Might be empty for some people, just check it doesn't error
    assert "relationships" in data, "Missing relationships key"
    return True
test("get_name_relationships — DiCaprio", test_get_name_relationships)

def test_get_name_trivia():
    data, url = get_name_trivia(DICAPRIO, page_size=3)
    trivia = data.get("triviaEntries", [])
    assert len(trivia) > 0, "No trivia returned"
    assert "text" in trivia[0], "Missing text field"
    return True
test("get_name_trivia — DiCaprio", test_get_name_trivia)


# ──────────────────────────────────────────────
# Chart Endpoint Tests
# ──────────────────────────────────────────────

print("\n── Charts ──")

def test_get_star_meters():
    data, url = get_star_meters()
    names = data.get("names", [])
    assert len(names) > 0, "No star meter results"
    first = names[0]
    assert "meterRanking" in first, "Missing meterRanking"
    assert first["meterRanking"]["currentRank"] == 1, "First result should be rank 1"
    return True
test("get_star_meters — top ranked", test_get_star_meters)


# ──────────────────────────────────────────────
# Interest Endpoint Tests
# ──────────────────────────────────────────────

print("\n── Interests ──")

def test_get_interest_categories():
    data, url = get_interest_categories()
    categories = data.get("categories", [])
    assert len(categories) > 0, "No interest categories returned"
    assert "interests" in categories[0], "Missing interests field"
    return True
test("get_interest_categories", test_get_interest_categories)

def test_get_interest():
    # First grab a valid interest ID from categories
    cats_data, _ = get_interest_categories()
    first_interest = cats_data["categories"][0]["interests"][0]
    interest_id = first_interest["id"]

    data, url = get_interest(interest_id)
    assert data["id"] == interest_id
    assert "name" in data, "Missing name field"
    return True
test("get_interest — first available interest", test_get_interest)


# ──────────────────────────────────────────────
# Pagination Test
# ──────────────────────────────────────────────

print("\n── Pagination ──")

def test_pagination():
    # Get first page
    data1, url1 = get_title_episodes(BREAKING_BAD, page_size=3)
    eps1 = data1.get("episodes", [])
    token = data1.get("nextPageToken")
    assert len(eps1) == 3, f"Expected 3 episodes, got {len(eps1)}"
    assert token is not None, "No nextPageToken returned"

    # Get second page
    data2, url2 = get_title_episodes(BREAKING_BAD, page_size=3, page_token=token)
    eps2 = data2.get("episodes", [])
    assert len(eps2) > 0, "Second page returned no episodes"

    # Make sure pages don't overlap
    ids1 = {e["id"] for e in eps1}
    ids2 = {e["id"] for e in eps2}
    assert ids1.isdisjoint(ids2), "Pages overlap — same episodes on both pages"
    return True
test("pagination — Breaking Bad episodes page 1 → page 2", test_pagination)


# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────

total = passed + failed
print(f"\n{'═' * 40}")
print(f"  {passed}/{total} passed", end="")
if failed:
    print(f"  ·  {failed} failed")
else:
    print(f"  ·  all good! 🎬")
print(f"{'═' * 40}\n")