import requests
import pycountry
import json

BASE_URL = "https://api.imdbapi.dev"


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────

def country_to_countryCode(country: str) -> str:
    """
        Converts a country name to its ISO 3166-1 alpha-2 code.

        Example: "United States" --> "US", "United Kingdom" --> "GB"

        Uses exact match first, then fuzzy search as fallback.
    """
    country_entry = pycountry.countries.get(name=country)
    if country_entry is not None:
        code = country_entry.alpha_2
        return code

    try:
        country_fuzzy_entry = pycountry.countries.search_fuzzy(country)
        return country_fuzzy_entry[0].alpha_2
    except LookupError:
        print("country_to_countryCode : Invalid Input!")
        return None


def language_to_languageCode(language: str) -> str:
    """
        Converts a language name to its ISO 639-2 (alpha-3) code.

        Example: "Spanish" --> "spa", "English" --> "eng", "Japanese" --> "jpn"

        Uses exact match only (fuzzy search not available for languages).
        Falls back to case-insensitive match: prefers startswith, then substring.
    """
    language_entry = pycountry.languages.get(name=language)
    if language_entry is not None:
        code = language_entry.alpha_3
        return code

    # Manual fuzzy fallback — prefer startswith, then substring
    query = language.lower()
    for lang in pycountry.languages:
        if lang.name.lower().startswith(query):
            return lang.alpha_3
    for lang in pycountry.languages:
        if query in lang.name.lower():
            return lang.alpha_3

    print("language_to_languageCode : Invalid Input!")
    return None


def _make_request(url: str):
    """
        Internal helper. Sends a GET request and returns (json, url) or None.
    """
    response = requests.get(url)
    if response.status_code == 200:
        return response.json(), url
    else:
        print(f"Request failed with status {response.status_code}: {url}")
        return None


# ──────────────────────────────────────────────
# Title Endpoints
# ──────────────────────────────────────────────

def get_titles(type="", genres="", countries="", languages="",
               name_ids="", interest_ids="",
               start_year="", end_year="",
               min_vote_count="", max_vote_count="",
               min_agg_rating="", max_agg_rating="",
               sort_by="", sort_order="",
               page_token=""):
    """
        Retrieve a list of titles with optional filters.
        Endpoint: GET /titles

        type (str):
            The type of title to filter by. Comma-separated for multiple.

            MOVIE              - A movie title
            TV_SERIES          - A TV series title
            TV_MINI_SERIES     - A TV mini-series title
            TV_SPECIAL         - A TV special title
            TV_MOVIE           - A TV movie title
            SHORT              - A short title
            VIDEO              - A video title
            VIDEO_GAME         - A video game title

            Example: "MOVIE"
            Example: "MOVIE,TV_SERIES"

        genres (str):
            Filter by genre(s). Comma-separated for multiple.

            Action | Adult | Adventure | Animation | Biography | Comedy | Crime |
            Documentary | Drama | Family | Fantasy | Film Noir | Game Show | History |
            Horror | Musical | Music | Mystery | News | Reality-TV | Romance | Sci-Fi |
            Short | Sport | Talk-Show | Thriller | War | Western

            Example: "Action"
            Example: "Action,Drama"

        countries (str):
            Filter by country name(s). Comma-separated for multiple.
            Automatically converted to ISO 3166-1 alpha-2 codes.

            Example: "United States"
            Example: "United States,Germany"

            NOTE: This filter may not work as expected (known API issue).
                  Results may include titles distributed in the country,
                  not necessarily produced there. Use originCountries in
                  the response data for client-side filtering if needed.

        languages (str):
            Filter by language name(s). Comma-separated for multiple.
            Automatically converted to ISO 639-2 codes.

            Example: "English"
            Example: "English,Spanish"

            NOTE: Same caveat as countries — may filter by association
                  rather than primary spoken language.

        name_ids (str):
            Filter by IMDb name ID(s). Comma-separated for multiple.

            Example: "nm0000138"
            Example: "nm0000138,nm0000354"

        interest_ids (str):
            Filter by interest ID(s). Comma-separated for multiple.

            Example: "action"
            Example: "action,comedy"

        start_year (int|str):
            Filter by starting year (inclusive).
            Example: 2008

        end_year (int|str):
            Filter by ending year (inclusive).
            Example: 2026

        min_vote_count (int|str):
            Minimum number of votes a title must have.
            Range: 0 to 1,000,000,000. Default: 0.
            Example: 100

        max_vote_count (int|str):
            Maximum number of votes a title can have.
            Range: 0 to 1,000,000,000.
            Example: 100000

        min_agg_rating (float|str):
            Minimum aggregate rating (0.0 to 10.0).
            Example: 7.3

        max_agg_rating (float|str):
            Maximum aggregate rating (0.0 to 10.0).
            Example: 8.1

        sort_by (str):
            Sorting field. Default: sorted by popularity.

            SORT_BY_POPULARITY         - Sort by popularity
            SORT_BY_RELEASE_DATE       - Sort by release date
            SORT_BY_USER_RATING        - Sort by user rating
            SORT_BY_USER_RATING_COUNT  - Sort by number of user ratings
            SORT_BY_YEAR               - Sort by year

        sort_order (str):
            Sorting direction. Default: ascending.

            ASC  - Ascending order
            DESC - Descending order

        page_token (str):
            Token for pagination. Obtained from nextPageToken in a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            titles         - List of title objects
            totalCount     - Total number of matching titles
            nextPageToken  - Token for next page (if more results exist)
    """
    url = f"{BASE_URL}/titles?"

    if type:
        url += f"types={type}&"
    if genres:
        url += f"genres={genres}&"
    if countries:
        codes = ",".join(
            code for c in countries.split(",")
            if (code := country_to_countryCode(c.strip())) is not None
        )
        if codes:
            url += f"countryCodes={codes}&"
    if languages:
        codes = ",".join(
            code for l in languages.split(",")
            if (code := language_to_languageCode(l.strip())) is not None
        )
        if codes:
            url += f"languageCodes={codes}&"
    if name_ids:
        url += f"nameIds={name_ids}&"
    if interest_ids:
        url += f"interestIds={interest_ids}&"
    if start_year:
        url += f"startYear={start_year}&"
    if end_year:
        url += f"endYear={end_year}&"
    if min_vote_count:
        url += f"minVoteCount={min_vote_count}&"
    if max_vote_count:
        url += f"maxVoteCount={max_vote_count}&"
    if min_agg_rating:
        url += f"minAggregateRating={min_agg_rating}&"
    if max_agg_rating:
        url += f"maxAggregateRating={max_agg_rating}&"
    if sort_by:
        url += f"sortBy={sort_by}&"
    if sort_order:
        url += f"sortOrder={sort_order}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&")
    return _make_request(url)


def get_title(title_id: str):
    """
        Retrieve a single title's full details by its IMDb ID.
        Endpoint: GET /titles/{titleId}

        title_id (str):
            Required. The IMDb title ID.
            Format: "tt" followed by digits.

            Example: "tt0111161"  (The Shawshank Redemption)
            Example: "tt1375666"  (Inception)

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            id               - IMDb ID (e.g. "tt0111161")
            type             - Title type (e.g. "movie", "tvSeries")
            isAdult          - Whether the title is for adult audiences
            primaryTitle     - Most recognized title name
            originalTitle    - Title as originally released
            primaryImage     - Poster image (url, width, height)
            startYear        - Release year (or series start year)
            endYear          - Series end year (if applicable)
            runtimeSeconds   - Runtime in seconds
            genres           - List of genre strings
            rating           - { aggregateRating, voteCount }
            metacritic       - { url, score, reviewCount }
            plot             - Plot summary
            directors        - List of director name objects
            writers          - List of writer name objects
            stars            - List of star name objects
            originCountries  - List of { code, name } country objects
            spokenLanguages  - List of { code, name } language objects
            interests        - List of interest objects
    """
    url = f"{BASE_URL}/titles/{title_id}"
    return _make_request(url)


def batch_get_titles(title_ids: str):
    """
        Retrieve details of multiple titles at once by their IMDb IDs.
        Endpoint: GET /titles:batchGet

        title_ids (str):
            Required. Comma-separated IMDb title IDs. Maximum 5 IDs.

            Example: "tt0111161"
            Example: "tt0111161,tt1375666,tt0068646"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            titles  - List of title objects (same structure as get_title)
    """
    url = f"{BASE_URL}/titles:batchGet?"

    ids = [t.strip() for t in title_ids.split(",")]
    url += "&".join(f"titleIds={tid}" for tid in ids)

    return _make_request(url)


def search_titles(query: str, limit=""):
    """
        Search for titles using a query string.
        Endpoint: GET /search/titles

        query (str):
            Required. The search query.

            Example: "Inception"
            Example: "Breaking Bad"
            Example: "Tarantino"

        limit (int|str):
            Optional. Max number of results to return.
            Maximum: 50.

            Example: 10

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            titles  - List of matching title objects
    """
    url = f"{BASE_URL}/search/titles?query={query}"

    if limit:
        url += f"&limit={limit}"

    return _make_request(url)


def get_title_credits(title_id: str, categories="", page_size="", page_token=""):
    """
        Retrieve the credits (cast & crew) for a specific title.
        Endpoint: GET /titles/{titleId}/credits

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        categories (str):
            Optional. Comma-separated credit categories to filter by.

            Example: "actor"
            Example: "actor,director,writer"

        page_size (int|str):
            Optional. Number of credits per page. Range: 1-50. Default: 20.
            Example: 50

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            credits        - List of credit objects, each containing:
                             title      - The associated title
                             name       - The credited person { id, displayName, ... }
                             category   - Credit category (e.g. "actor", "director")
                             characters - List of character names played
                             episodeCount - Number of episodes (for series)
            totalCount     - Total number of credits
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/credits?"

    if categories:
        url += f"categories={categories}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_release_dates(title_id: str, page_size="", page_token=""):
    """
        Retrieve the release dates for a specific title across countries.
        Endpoint: GET /titles/{titleId}/releaseDates

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        page_size (int|str):
            Optional. Number of results per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            releaseDates   - List of release date objects, each containing:
                             country     - { code, name }
                             releaseDate - { year, month, day }
                             attributes  - e.g. ["Theatrical"], ["DVD"], ["Blu-ray"]
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/releaseDates?"

    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_akas(title_id: str):
    """
        Retrieve the alternative titles (AKAs) for a specific title.
        Endpoint: GET /titles/{titleId}/akas

        These are the localized titles used in different countries and languages.

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            akas  - List of AKA objects, each containing:
                    text       - The localized title text
                    country    - { code, name }
                    language   - { code, name }
                    attributes - e.g. ["original title"], ["working title"]
    """
    url = f"{BASE_URL}/titles/{title_id}/akas"
    return _make_request(url)


def get_title_seasons(title_id: str):
    """
        Retrieve the seasons for a TV series title.
        Endpoint: GET /titles/{titleId}/seasons

        title_id (str):
            Required. IMDb title ID of a TV series.
            Example: "tt0903747"  (Breaking Bad)

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            seasons  - List of season objects, each containing:
                       season       - Season number (as string)
                       episodeCount - Number of episodes in that season
    """
    url = f"{BASE_URL}/titles/{title_id}/seasons"
    return _make_request(url)


def get_title_episodes(title_id: str, season="", page_size="", page_token=""):
    """
        Retrieve episodes for a TV series title.
        Endpoint: GET /titles/{titleId}/episodes

        title_id (str):
            Required. IMDb title ID of a TV series.
            Example: "tt0903747"  (Breaking Bad)

        season (str|int):
            Optional. Filter by season number.
            Example: "1"
            Example: 3

        page_size (int|str):
            Optional. Number of episodes per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            episodes       - List of episode objects, each containing:
                             id             - Episode IMDb ID
                             title          - Episode title
                             primaryImage   - Episode image
                             season         - Season number
                             episodeNumber  - Episode number within the season
                             runtimeSeconds - Runtime in seconds
                             plot           - Episode plot summary
                             rating         - { aggregateRating, voteCount }
                             releaseDate    - { year, month, day }
            totalCount     - Total number of episodes
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/episodes?"

    if season:
        url += f"season={season}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_images(title_id: str, types="", page_size="", page_token=""):
    """
        Retrieve images associated with a specific title.
        Endpoint: GET /titles/{titleId}/images

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        types (str):
            Optional. Comma-separated image types to filter by.

            Known types: "poster", "still_frame", "event", etc.

            Example: "poster"
            Example: "poster,still_frame"

        page_size (int|str):
            Optional. Number of images per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            images         - List of image objects, each containing:
                             url    - Image URL
                             width  - Width in pixels
                             height - Height in pixels
                             type   - Image type string
            totalCount     - Total number of images
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/images?"

    if types:
        url += f"types={types}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_videos(title_id: str, types="", page_size="", page_token=""):
    """
        Retrieve videos (trailers, clips, etc.) for a specific title.
        Endpoint: GET /titles/{titleId}/videos

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        types (str):
            Optional. Comma-separated video types to filter by.
            Example: "trailer"

        page_size (int|str):
            Optional. Number of videos per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            videos         - List of video objects, each containing:
                             id             - Video ID
                             type           - Video type (e.g. "trailer")
                             name           - Video name
                             primaryImage   - Thumbnail image
                             description    - Video description
                             width          - Width in pixels
                             height         - Height in pixels
                             runtimeSeconds - Video duration in seconds
            totalCount     - Total number of videos
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/videos?"

    if types:
        url += f"types={types}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_award_nominations(title_id: str, page_size="", page_token=""):
    """
        Retrieve award nominations for a specific title.
        Endpoint: GET /titles/{titleId}/awardNominations

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        page_size (int|str):
            Optional. Number of nominations per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            stats              - { nominationCount, winCount }
            awardNominations   - List of nomination objects, each containing:
                                 titles     - Associated title objects
                                 nominees   - Nominated person objects
                                 event      - { id, name } of the award event
                                 year       - Year of nomination
                                 text       - Description of the nomination
                                 category   - Award category
                                 isWinner   - Whether it won
                                 winnerRank - Rank among winners
            nextPageToken      - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/awardNominations?"

    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_parents_guide(title_id: str):
    """
        Retrieve the parents guide for a specific title.
        Endpoint: GET /titles/{titleId}/parentsGuide

        Content advisory information for parents, broken down by category.

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            parentsGuide  - List of guide entries, each containing:
                            category            - One of:
                                                  SEXUAL_CONTENT
                                                  VIOLENCE
                                                  PROFANITY
                                                  ALCOHOL_DRUGS
                                                  FRIGHTENING_INTENSE_SCENES
                            severityBreakdowns  - List of { severityLevel, voteCount }
                            reviews             - List of { text, isSpoiler }
    """
    url = f"{BASE_URL}/titles/{title_id}/parentsGuide"
    return _make_request(url)


def get_title_certificates(title_id: str):
    """
        Retrieve content rating certificates for a specific title.
        Endpoint: GET /titles/{titleId}/certificates

        These are the age/content ratings assigned by various countries
        (e.g. PG-13, R, 12A, FSK 16).

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            certificates  - List of certificate objects, each containing:
                            rating     - Rating string (e.g. "PG-13", "R", "12A")
                            country    - { code, name }
                            attributes - Additional info list
            totalCount    - Total number of certificates
    """
    url = f"{BASE_URL}/titles/{title_id}/certificates"
    return _make_request(url)


def get_title_company_credits(title_id: str, categories="", page_size="", page_token=""):
    """
        Retrieve company credits for a specific title.
        Endpoint: GET /titles/{titleId}/companyCredits

        Lists the companies involved in production, distribution, sales, etc.

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        categories (str):
            Optional. Comma-separated company credit categories to filter by.

            Known categories: "production", "distribution", "sales", etc.

            Example: "production"
            Example: "production,distribution"

        page_size (int|str):
            Optional. Number of results per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            companyCredits  - List of company credit objects, each containing:
                              company       - { id, name }
                              category      - Credit category string
                              countries     - List of { code, name }
                              yearsInvolved - { startYear, endYear }
                              attributes    - Additional info list
            totalCount      - Total number of company credits
            nextPageToken   - Token for next page
    """
    url = f"{BASE_URL}/titles/{title_id}/companyCredits?"

    if categories:
        url += f"categories={categories}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_title_box_office(title_id: str):
    """
        Retrieve box office information for a specific title.
        Endpoint: GET /titles/{titleId}/boxOffice

        title_id (str):
            Required. IMDb title ID.
            Example: "tt0111161"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            domesticGross       - { amount, currency }
            worldwideGross      - { amount, currency }
            openingWeekendGross - { gross: { amount, currency },
                                    weekendEndDate: { year, month, day } }
            productionBudget    - { amount, currency }
    """
    url = f"{BASE_URL}/titles/{title_id}/boxOffice"
    return _make_request(url)


# ──────────────────────────────────────────────
# Name Endpoints
# ──────────────────────────────────────────────

def get_name(name_id: str):
    """
        Retrieve a person's full details by their IMDb name ID.
        Endpoint: GET /names/{nameId}

        name_id (str):
            Required. IMDb name ID.
            Format: "nm" followed by digits.

            Example: "nm0000138"  (Leonardo DiCaprio)
            Example: "nm0000233"  (Quentin Tarantino)

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            id                  - IMDb name ID
            displayName         - Full display name
            alternativeNames    - List of alternative name strings
            primaryImage        - Profile image { url, width, height }
            primaryProfessions  - e.g. ["Actor", "Producer"]
            biography           - Biography text
            heightCm            - Height in centimeters
            birthName           - Birth name
            birthDate           - { year, month, day }
            birthLocation       - Birth location string
            deathDate           - { year, month, day } (empty if alive)
            deathLocation       - Death location string
            deathReason         - Cause of death string
            meterRanking        - { currentRank, changeDirection, difference }
    """
    url = f"{BASE_URL}/names/{name_id}"
    return _make_request(url)


def batch_get_names(name_ids: str):
    """
        Retrieve details of multiple people at once by their IMDb name IDs.
        Endpoint: GET /names:batchGet

        name_ids (str):
            Required. Comma-separated IMDb name IDs. Maximum 5 IDs.

            Example: "nm0000138"
            Example: "nm0000138,nm0000233,nm0000354"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            names  - List of name objects (same structure as get_name)
    """
    url = f"{BASE_URL}/names:batchGet?"

    ids = [n.strip() for n in name_ids.split(",")]
    url += "&".join(f"nameIds={nid}" for nid in ids)

    return _make_request(url)


def get_name_images(name_id: str, types="", page_size="", page_token=""):
    """
        Retrieve images associated with a specific person.
        Endpoint: GET /names/{nameId}/images

        name_id (str):
            Required. IMDb name ID.
            Example: "nm0000138"

        types (str):
            Optional. Comma-separated image types to filter by.
            Example: "event"

        page_size (int|str):
            Optional. Number of images per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            images         - List of image objects { url, width, height, type }
            totalCount     - Total number of images
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/names/{name_id}/images?"

    if types:
        url += f"types={types}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_name_filmography(name_id: str, categories="", page_size="", page_token=""):
    """
        Retrieve the filmography for a specific person.
        Endpoint: GET /names/{nameId}/filmography

        name_id (str):
            Required. IMDb name ID.
            Example: "nm0000138"  (Leonardo DiCaprio)

        categories (str):
            Optional. Comma-separated credit categories to filter by.

            Example: "actor"
            Example: "actor,producer"

        page_size (int|str):
            Optional. Number of credits per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            credits        - List of credit objects, each containing:
                             title        - Associated title object
                             name         - The person
                             category     - Credit category
                             characters   - Characters played
                             episodeCount - Number of episodes (for series)
            totalCount     - Total number of filmography credits
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/names/{name_id}/filmography?"

    if categories:
        url += f"categories={categories}&"
    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


def get_name_relationships(name_id: str):
    """
        Retrieve personal relationships for a specific person.
        Endpoint: GET /names/{nameId}/relationships

        Includes family, spouses, children, etc.

        name_id (str):
            Required. IMDb name ID.
            Example: "nm0000138"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            relationships  - List of relationship objects, each containing:
                             name         - Related person { id, displayName, ... }
                             relationType - e.g. "spouse", "parent", "child"
                             attributes   - Additional info list
    """
    url = f"{BASE_URL}/names/{name_id}/relationships"
    return _make_request(url)


def get_name_trivia(name_id: str, page_size="", page_token=""):
    """
        Retrieve trivia entries for a specific person.
        Endpoint: GET /names/{nameId}/trivia

        name_id (str):
            Required. IMDb name ID.
            Example: "nm0000138"

        page_size (int|str):
            Optional. Number of trivia entries per page. Range: 1-50. Default: 20.

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            triviaEntries  - List of trivia objects, each containing:
                             id            - Trivia entry ID
                             text          - Trivia text
                             interestCount - Number of interested users
                             voteCount     - Number of votes
            totalCount     - Total number of trivia entries
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/names/{name_id}/trivia?"

    if page_size:
        url += f"pageSize={page_size}&"
    if page_token:
        url += f"pageToken={page_token}&"

    url = url.rstrip("&?")
    return _make_request(url)


# ──────────────────────────────────────────────
# Chart Endpoints
# ──────────────────────────────────────────────

def get_star_meters(page_token=""):
    """
        Retrieve the IMDb Star Meter popularity rankings.
        Endpoint: GET /chart/starmeter

        page_token (str):
            Optional. Pagination token from a previous response.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            names          - List of name objects with meterRanking data:
                             id             - IMDb name ID
                             displayName    - Person's name
                             primaryImage   - Profile image
                             meterRanking   - { currentRank, changeDirection, difference }
            nextPageToken  - Token for next page
    """
    url = f"{BASE_URL}/chart/starmeter"

    if page_token:
        url += f"?pageToken={page_token}"

    return _make_request(url)


# ──────────────────────────────────────────────
# Interest Endpoints
# ──────────────────────────────────────────────

def get_interest_categories():
    """
        Retrieve all available interest categories.
        Endpoint: GET /interests

        Interests are fine-grained genre/topic tags used by IMDb,
        such as "Action Epic", "Adult Animation", "Buddy Comedy", etc.

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            categories  - List of interest category objects, each containing:
                          category  - Category name/ID
                          interests - List of interest objects:
                                     id              - Interest ID
                                     name            - Interest name
                                     primaryImage    - Image for the interest
                                     description     - Description text
                                     isSubgenre      - Whether it's a subgenre
                                     similarInterests - Related interests
    """
    url = f"{BASE_URL}/interests"
    return _make_request(url)


def get_interest(interest_id: str):
    """
        Retrieve details of a specific interest by its ID.
        Endpoint: GET /interests/{interestId}

        interest_id (str):
            Required. The interest ID.

            Example: "action"
            Example: "buddy-comedy"

        Returns:
            tuple: (dict, str) — (JSON response, request URL) on success
            None: on failure

        Response fields:
            id               - Interest ID
            name             - Interest name
            primaryImage     - Image for the interest
            description      - Description text
            isSubgenre       - Whether it's a subgenre
            similarInterests - List of related interest objects
    """
    url = f"{BASE_URL}/interests/{interest_id}"
    return _make_request(url)


# ──────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────

def pretty_print(data):
    """
        Pretty-prints a JSON response.

        data:
            A dict (or the first element of a tuple returned by any function above).

            Example:
                result = get_title("tt0111161")
                pretty_print(result[0])
    """
    print(json.dumps(data, indent=4, ensure_ascii=False))


data,url = get_titles(type="MOVIE",countries="Iceland",languages="Icelandic")
pretty_print(data)