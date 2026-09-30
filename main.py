from flask import Flask, render_template, request, jsonify
import requests
import json
import os
import re
import html
import threading
import uuid
import socket
import time
import logging
from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

app = Flask(__name__)

# Trim Werkzeug's console output: drop the "development server" and
# "Running on all addresses" startup lines and the access-log line for successful requests (status < 400).
# Errors (4xx/5xx), malformed requests, and the startup addresses still print.
_HIDDEN_STARTUP_LINES = ('This is a development server', 'Running on all addresses')

class _QuietRequestLog(logging.Filter):
    def filter(self, record):
        # The warning shares one log record with the "Running on ..." address
        # lines, so remove just that line rather than dropping the record.
        message = record.getMessage()
        if any(text in message for text in _HIDDEN_STARTUP_LINES):
            lines = [line for line in message.split('\n')
                     if not any(text in line for text in _HIDDEN_STARTUP_LINES)]
            record.msg = '\n'.join(lines)
            record.args = ()
            return bool(lines)
        # Access-log records carry (request line, status code, size)
        args = record.args
        if isinstance(args, tuple) and len(args) == 3 and str(args[1]).isdigit():
            return int(args[1]) >= 400
        return True

logging.getLogger('werkzeug').addFilter(_QuietRequestLog())

# --- DNS cache ---
# Every TMDB/Radarr call re-resolves the same handful of hostnames.
# socket.getaddrinfo isn't cached by Python/urllib3, so a brief resolver
# hiccup fails a request that a cached answer from moments ago would have
# served fine. This wraps it with a short TTL cache, storing successes only
# so real, sustained DNS outages still surface (not silently swallowed).
_dns_cache = {}
_dns_cache_lock = threading.Lock()
DNS_CACHE_TTL_SECONDS = 300
_original_getaddrinfo = socket.getaddrinfo

def _cached_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    cache_key = (host, port, family, type, proto, flags)
    now = time.time()
    with _dns_cache_lock:
        cached = _dns_cache.get(cache_key)
        if cached and now - cached[1] < DNS_CACHE_TTL_SECONDS:
            return cached[0]

    result = _original_getaddrinfo(host, port, family, type, proto, flags)

    with _dns_cache_lock:
        _dns_cache[cache_key] = (result, now)
    return result

socket.getaddrinfo = _cached_getaddrinfo

TMDB_API_KEY = os.getenv('TMDB_API_KEY', '')
if not TMDB_API_KEY:
    print("WARNING: TMDB_API_KEY not set")

DEFAULT_LANGUAGES_STR = os.getenv('DEFAULT_LANGUAGES', 'en')
DEFAULT_LANGUAGES = [lang.strip() for lang in DEFAULT_LANGUAGES_STR.split(',') if lang.strip()]

# Optional. When both are set, "Import from Radarr" needs no input in the web UI.
RADARR_URL = os.getenv('RADARR_URL', '').strip().rstrip('/')
RADARR_API_KEY = os.getenv('RADARR_API_KEY', '').strip()

TMDB_BASE_URL = 'https://api.themoviedb.org/3'
MAX_PAGES = 25

def safe_error(e):
    """Stringifies an exception with API key values stripped, since
    requests embeds the full request URL (including the query string)
    in connection-error messages. Matches both TMDB's api_key= and
    Radarr's apikey= query params."""
    return re.sub(r'api_?key=[^&\s\']+', 'api_key=REDACTED', str(e), flags=re.IGNORECASE)

DATA_DIR = os.getenv('DATA_DIR', './data')
os.makedirs(DATA_DIR, exist_ok=True)

LISTS_FILE = os.path.join(DATA_DIR, 'lists.json')
CACHE_FILE = os.path.join(DATA_DIR, 'cache.json')
METADATA_FILE = os.path.join(DATA_DIR, 'update_time.json')
IGNORE_FILE = os.path.join(DATA_DIR, 'ignore.json')

# The cache only needs these fields (master list, list counts, list view).
# Everything else TMDB returns is dropped before storing.
CACHED_MOVIE_FIELDS = ('id', 'title', 'release_date', 'vote_average', 'vote_count')

def slim_movie(movie):
    return {key: movie[key] for key in CACHED_MOVIE_FIELDS if key in movie}

def write_json_atomic(path, obj, compact=False):
    """Writes to a temp file in the same directory, then swaps it in with
    os.replace, so a crash mid-write can't leave a truncated JSON file."""
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, 'w') as f:
            if compact:
                json.dump(obj, f, separators=(',', ':'))
            else:
                json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def load_lists():
    if os.path.exists(LISTS_FILE):
        with open(LISTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_lists(lists):
    write_json_atomic(LISTS_FILE, lists)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
        # Older caches hold full TMDB objects; slim them on load
        return {list_id: [slim_movie(m) for m in movies] for list_id, movies in cache.items()}
    return {}

def save_cache(cache):
    write_json_atomic(CACHE_FILE, cache, compact=True)

def load_metadata():
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {'lastUpdated': None}

def save_metadata(metadata):
    write_json_atomic(METADATA_FILE, metadata)

def load_ignore_list():
    # Keyed by TMDB id (string) -> {'title': ..., 'year': ...}
    if os.path.exists(IGNORE_FILE):
        with open(IGNORE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_ignore_list(ignored):
    write_json_atomic(IGNORE_FILE, ignored)

movie_lists = load_lists()
movie_cache = load_cache()
metadata = load_metadata()
ignore_list = load_ignore_list()
state_lock = threading.Lock()

# Held for the duration of a refresh. Lets callers start one without
# blocking (and without two running at once).
_refresh_lock = threading.Lock()

def refresh_cache_on_startup():
    if should_update_cache():
        refresh_all_lists_parallel()

def start_background_refresh():
    """Starts a refresh on a daemon thread. No-op if one is already running."""
    if _refresh_lock.locked():
        return

    def run():
        try:
            refresh_all_lists_parallel()
        except Exception as e:
            print(f"Background refresh failed: {safe_error(e)}")

    threading.Thread(target=run, daemon=True).start()

def refresh_all_lists_parallel(wait=False):
    """Refreshes every enabled list. Returns True if this call ran the refresh.
    If one is already running, returns False - after waiting for it to finish
    when wait=True."""
    if not _refresh_lock.acquire(blocking=False):
        if wait:
            with _refresh_lock:
                pass
        return False

    try:
        with state_lock:
            enabled_lists = [(list_id, list_config) for list_id, list_config in movie_lists.items()
                             if list_config.get('enabled', True)]

        if not enabled_lists:
            print("No lists enabled to refresh")
            return True

        print("Updating lists...")

        def fetch_list(list_id, list_config):
            """Returns (list_id, movies), or (list_id, None) to keep the
            list's existing cache untouched."""
            try:
                movies = get_movies_from_tmdb(list_config)
                print(f" \u2713 {len(movies)} movies - {list_config['name']}")
                return list_id, movies
            except FetchIncomplete as e:
                with state_lock:
                    previous = len(movie_cache.get(list_id, []))
                if previous:
                    print(f"  ! {list_config['name']}: TMDB error ({e.reason}) - kept previous {previous} movies")
                    return list_id, None
                print(f"  ! {list_config['name']}: TMDB error ({e.reason}) - saved {len(e.movies)} partial results")
                return list_id, e.movies
            except Exception as e:
                print(f"  \u2717 Error fetching {list_config['name']}: {safe_error(e)} - kept previous data")
                return list_id, None

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fetch_list, list_id, list_config): list_id
                       for list_id, list_config in enabled_lists}

            for future in as_completed(futures):
                list_id, movies = future.result()
                with state_lock:
                    # Skip lists deleted while the refresh was running, and
                    # lists whose fetch failed (movies is None)
                    if movies is not None and list_id in movie_lists:
                        movie_cache[list_id] = movies

        with state_lock:
            metadata['lastUpdated'] = datetime.now().isoformat()
            save_cache(movie_cache)
            save_metadata(metadata)
        print("Cache refresh done!")
        return True
    finally:
        _refresh_lock.release()

class TMDBError(Exception):
    """A TMDB request failed: retries exhausted (rate limit, server or network
    error), the request was rejected (e.g. bad API key), or the response was
    unusable."""

class FetchIncomplete(Exception):
    """A list fetch hit a TMDB error part-way. .movies holds whatever was
    collected before the failure."""
    def __init__(self, movies, reason):
        super().__init__(reason)
        self.movies = movies
        self.reason = reason

def tmdb_get(path, params=None, retries=3):
    """GET a TMDB endpoint and return the parsed JSON dict.
    Returns None only for 404 (the resource doesn't exist). Any other failure
    raises TMDBError. Retries 429 (honouring Retry-After, capped at 10s), 5xx
    and network errors. Pass retries=1 for interactive calls that shouldn't sleep."""
    query = {'api_key': TMDB_API_KEY}
    query.update(params or {})
    reason = 'unknown error'

    for attempt in range(retries):
        last_attempt = attempt == retries - 1
        delay = 1 + attempt
        try:
            response = requests.get(f"{TMDB_BASE_URL}{path}", params=query, timeout=10)
        except requests.exceptions.RequestException as e:
            reason = 'network error'
            print(f"TMDB request error ({path}): {safe_error(e)}")
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    print(f"TMDB returned invalid JSON ({path})")
                    raise TMDBError('invalid JSON from TMDB')
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                reason = 'rate limited'
                try:
                    delay = min(int(response.headers.get('Retry-After', 2)), 10)
                except ValueError:
                    delay = 2
                print(f"TMDB rate limit hit ({path})" + ("" if last_attempt else f" - retrying in {delay}s"))
            elif response.status_code >= 500:
                reason = f'server error {response.status_code}'
                print(f"TMDB server error {response.status_code} ({path})")
            else:
                print(f"TMDB API Error: Status {response.status_code} ({path})")
                raise TMDBError(f'TMDB rejected the request (status {response.status_code})')
        if not last_attempt:
            time.sleep(delay)
    raise TMDBError(reason)

def search_person(name):
    try:
        data = tmdb_get('/search/person', {'query': name.strip()}, retries=1)
    except TMDBError:
        return []
    if data is None:
        return []
    return [{'id': p['id'], 'name': p['name']} for p in data.get('results', [])[:10]]

def parse_exclude_terms(list_config):
    raw = (list_config.get('titleExclude') or '').strip()
    return [term.strip().lower() for term in raw.split(',') if term.strip()]

# --- Per-movie details cache (title search only) ---
# search/movie can't filter on runtime or people, so those need one details
# request per candidate. Results are cached so the periodic refresh doesn't
# repeat them. Credits are stored as compact int arrays to stay within the
# container's memory limit.
DETAILS_TTL_SECONDS = 24 * 3600
DETAILS_CACHE_MAX = 5000
_details_cache = {}
_details_lock = threading.Lock()

def get_movie_details(movie_id, need_people):
    """Returns {'runtime': int, 'people': array|None}, or None if the movie no
    longer exists on TMDB (404). Other failures raise TMDBError. One request per movie: credits ride along via
    append_to_response instead of a second call."""
    now = time.time()
    with _details_lock:
        entry = _details_cache.get(movie_id)
    if entry and now - entry['ts'] < DETAILS_TTL_SECONDS and (entry['people'] is not None or not need_people):
        return entry

    data = tmdb_get(f"/movie/{movie_id}", {'append_to_response': 'credits'} if need_people else None)
    if data is None:
        return None

    people = None
    if need_people:
        credits = data.get('credits') or {}
        people = array('I', {p['id'] for p in credits.get('cast', []) + credits.get('crew', []) if 'id' in p})

    entry = {'runtime': data.get('runtime') or 0, 'people': people, 'ts': now}
    with _details_lock:
        if len(_details_cache) >= DETAILS_CACHE_MAX:
            _details_cache.clear()
        _details_cache[movie_id] = entry
    return entry

def get_movies_from_tmdb(list_config):
    """Returns the matching movies. If TMDB fails part-way, raises
    FetchIncomplete carrying the partial results, so callers can keep their
    previous data instead of replacing it with a truncated list."""
    max_results = list_config.get('maxResults') or 500
    title_terms = (list_config.get('titleTerms') or '').strip()
    movies = []
    try:
        if title_terms:
            search_movies_by_title(list_config, title_terms, movies)
        else:
            discover_movies(list_config, movies)
    except TMDBError as e:
        raise FetchIncomplete([slim_movie(m) for m in movies[:max_results]], str(e))
    return [slim_movie(m) for m in movies[:max_results]]

def discover_movies(list_config, movies):
    page = 1
    exclude_terms = parse_exclude_terms(list_config)

    params = {
        'sort_by': 'vote_average.desc',
        'with_runtime.gte': 45,      # Min 45 minutes (Exclude shorts)
        'without_keywords': '9716',  # Exclude stand-ups
    }

    if list_config.get('minRating'):
        params['vote_average.gte'] = list_config['minRating']
    if list_config.get('minVotes'):
        params['vote_count.gte'] = list_config['minVotes']
    if list_config.get('yearFrom'):
        params['primary_release_date.gte'] = f"{list_config['yearFrom']}-01-01"
    if list_config.get('yearTo'):
        params['primary_release_date.lte'] = f"{list_config['yearTo']}-12-31"

    if list_config.get('languages'):
        params['with_original_language'] = '|'.join(list_config['languages'])

    # Comma = AND: a movie must have every selected genre. search_movies_by_title
    # applies the same rule.
    if list_config.get('includeGenres'):
        params['with_genres'] = ','.join(map(str, list_config['includeGenres']))

    excluded_genres = list(list_config.get('excludeGenres', []))
    if excluded_genres:
        params['without_genres'] = ','.join(map(str, excluded_genres))

    if list_config.get('actors'):
        params['with_people'] = ','.join(str(actor['id']) for actor in list_config['actors'])

    if list_config.get('studios'):
        company_ids = [str(studio['id']) for studio in list_config['studios']]
        if company_ids:
            params['with_companies'] = '|'.join(company_ids)

    # Excluded people are checked against each movie's cast and crew
    # (discover's without_people did not exclude reliably).
    excluded_actor_ids = [actor['id'] for actor in list_config.get('excludeActors', [])]
    need_people = bool(excluded_actor_ids)
    unverified = 0

    max_results = list_config.get('maxResults') or 500

    while len(movies) < max_results and page <= MAX_PAGES:
        params['page'] = page
        data = tmdb_get('/discover/movie', params)
        if data is None:
            raise TMDBError('discover endpoint not found')

        results = data.get('results', [])
        if not results:
            break

        candidates = []
        for movie in results:
            if movie.get('adult', False):
                continue

            if str(movie['id']) in ignore_list:
                continue

            if exclude_terms:
                movie_title_lower = movie.get('title', '').lower()
                if any(term in movie_title_lower for term in exclude_terms):
                    continue

            candidates.append(movie)

        # One details request per candidate (credits included), concurrent and
        # cached. Only done when excluded people are set.
        if need_people and candidates:
            with ThreadPoolExecutor(max_workers=5) as executor:
                details_list = list(executor.map(
                    lambda m: get_movie_details(m['id'], True), candidates))
        else:
            details_list = [True] * len(candidates)

        for movie, details in zip(candidates, details_list):
            if need_people:
                if details is None:
                    # Movie no longer exists on TMDB (404)
                    unverified += 1
                    continue
                if any(ex_id in details['people'] for ex_id in excluded_actor_ids):
                    continue

            movies.append(movie)
            if len(movies) >= max_results:
                break

        page += 1

    if unverified:
        print(f" ! {unverified} movies skipped - not found on TMDB")

def search_movies_by_title(list_config, title_query, movies=None):
    if movies is None:
        movies = []
    page = 1
    max_results = list_config.get('maxResults') or 500
    unverified = 0

    excluded_actor_ids = [actor['id'] for actor in list_config.get('excludeActors', [])]
    exclude_terms = parse_exclude_terms(list_config)
    required_genres = set(map(str, list_config.get('includeGenres') or []))
    excluded_genres = set(map(str, list_config.get('excludeGenres') or []))

    while len(movies) < max_results and page <= MAX_PAGES:
        data = tmdb_get('/search/movie', {'query': title_query, 'page': page})
        if data is None:
            raise TMDBError('search endpoint not found')

        results = data.get('results', [])
        if not results:
            break

        # Cheap, local filters first so details are only fetched for real candidates
        candidates = []
        for movie in results:
            if movie.get('adult', False):
                continue

            if str(movie['id']) in ignore_list:
                continue

            movie_title_lower = movie.get('title', '').lower()
            if exclude_terms and any(term in movie_title_lower for term in exclude_terms):
                continue

            if list_config.get('minRating') and movie.get('vote_average', 0) < list_config['minRating']:
                continue
            if list_config.get('minVotes') and movie.get('vote_count', 0) < list_config['minVotes']:
                continue

            release_date = movie.get('release_date', '')
            if release_date:
                year = int(release_date[:4]) if len(release_date) >= 4 else 0
                if list_config.get('yearFrom') and year < list_config['yearFrom']:
                    continue
                if list_config.get('yearTo') and year > list_config['yearTo']:
                    continue

            movie_genres = set(map(str, movie.get('genre_ids', [])))
            # Same rule as discover: every included genre is required (AND)
            if required_genres and not required_genres.issubset(movie_genres):
                continue
            if excluded_genres and excluded_genres.intersection(movie_genres):
                continue

            candidates.append(movie)

        # One details request per candidate (runtime + credits together), run
        # concurrently. Order is preserved.
        need_people = bool(excluded_actor_ids)
        if candidates:
            with ThreadPoolExecutor(max_workers=5) as executor:
                details_list = list(executor.map(
                    lambda m: get_movie_details(m['id'], need_people), candidates))
        else:
            details_list = []

        for movie, details in zip(candidates, details_list):
            if details is None:
                # Movie no longer exists on TMDB (404)
                unverified += 1
                continue

            if details['runtime'] and details['runtime'] < 45:
                continue

            if need_people and any(ex_id in details['people'] for ex_id in excluded_actor_ids):
                continue

            movies.append(movie)
            if len(movies) >= max_results:
                break

        page += 1

    if unverified:
        print(f" ! {unverified} movies skipped - not found on TMDB")
    print(f" \u2713 {len(movies)} Movies - Title Search")
    return movies[:max_results]

CACHE_REFRESH_HOURS = 6

def should_update_cache():
    with state_lock:
        last_updated = metadata.get('lastUpdated')
    if not last_updated:
        return True
    
    last_update_time = datetime.fromisoformat(last_updated)
    return datetime.now() - last_update_time > timedelta(hours=CACHE_REFRESH_HOURS)

def get_json_body():
    """Parsed JSON body if it is a JSON object, else None (missing, malformed
    or wrong content type)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None

def bad_body_response():
    return jsonify({'success': False, 'error': 'Request body must be a JSON object'}), 400

def validate_list_fields(data):
    """Checks the types of list-valued fields; returns an error string, or None if OK."""
    for field in ('includeGenres', 'excludeGenres', 'languages'):
        value = data.get(field)
        if value is not None and not (isinstance(value, list) and all(isinstance(v, (str, int)) for v in value)):
            return f"'{field}' must be a list"
    for field in ('studios', 'actors', 'excludeActors'):
        value = data.get(field)
        if value is not None and not (isinstance(value, list) and all(isinstance(v, dict) and 'id' in v for v in value)):
            return f"'{field}' must be a list of objects with an 'id'"
    for field in ('titleTerms', 'titleExclude'):
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            return f"'{field}' must be a string"
    return None

def validate_numeric_fields(data):
    """Validates optional numeric fields; returns an error string, or None if OK."""
    numeric_fields = {
        'minRating': (0, 10),
        'minVotes': (0, None),
        'yearFrom': (1870, 2100),
        'yearTo': (1870, 2100),
        'maxResults': (1, 2000),
    }
    for field, (min_val, max_val) in numeric_fields.items():
        value = data.get(field)
        if value in (None, ''):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f"'{field}' must be a number"
        if min_val is not None and number < min_val:
            return f"'{field}' must be at least {min_val}"
        if max_val is not None and number > max_val:
            return f"'{field}' must be at most {max_val}"
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/metadata')
def get_metadata():
    with state_lock:
        all_movie_ids = set()
        for list_id, list_config in movie_lists.items():
            if list_config.get('enabled', True):
                for movie in movie_cache.get(list_id, []):
                    if str(movie['id']) not in ignore_list:
                        all_movie_ids.add(movie['id'])

        # Computed per request on a copy; the shared metadata dict (which is
        # what gets saved to disk) is never modified here.
        response_data = dict(metadata)
    response_data['totalMovies'] = len(all_movie_ids)
    return jsonify(response_data)

@app.route('/api/search-person')
def api_search_person():
    query = request.args.get('q', '')
    results = search_person(query)
    return jsonify(results)

@app.route('/api/search-company')
def api_search_company():
    query = request.args.get('q', '')
    try:
        data = tmdb_get('/search/company', {'query': query.strip()}, retries=1)
    except TMDBError:
        return jsonify([])
    if data is None:
        return jsonify([])
    return jsonify([{'id': c['id'], 'name': c['name']} for c in data.get('results', [])[:10]])

@app.route('/api/preview-list', methods=['POST'])
def preview_list():
    data = get_json_body()
    if data is None:
        return bad_body_response()
    validation_error = validate_numeric_fields(data) or validate_list_fields(data)
    if validation_error:
        return jsonify({'success': False, 'error': validation_error}), 400
    # Saved lists get DEFAULT_LANGUAGES when none are set; do the same here so
    # the preview matches what the list will contain.
    if data.get('languages') is None:
        data['languages'] = DEFAULT_LANGUAGES
    print(f"Preview request data: {data}")
    incomplete = False
    try:
        movies = get_movies_from_tmdb(data)
    except FetchIncomplete as e:
        movies = e.movies
        incomplete = True
    print(f"Found {len(movies)} movies for preview")
    
    total_count = len(movies)
    preview_movies = movies[:20]
    
    preview = []
    for movie in preview_movies:
        preview.append({
            'title': movie['title'],
            'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
            'rating': movie.get('vote_average', 0)
        })
    
    return jsonify({'movies': preview, 'totalCount': total_count, 'incomplete': incomplete})

@app.route('/api/create-list', methods=['POST'])
def create_list():
    data = get_json_body()
    if data is None:
        return bad_body_response()

    new_name = data.get('name')
    new_name = new_name.strip() if isinstance(new_name, str) else ''
    if not new_name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400

    validation_error = validate_numeric_fields(data) or validate_list_fields(data)
    if validation_error:
        return jsonify({'success': False, 'error': validation_error}), 400

    with state_lock:
        for existing_id, existing_list in movie_lists.items():
            if existing_list['name'].lower() == new_name.lower():
                return jsonify({'success': False, 'error': 'A list with this name already exists'}), 400

        slug = re.sub(r'[^a-z0-9]+', '-', new_name.lower()).strip('-') or 'list'
        list_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        
        list_config = {
            'name': new_name,
            'minRating': data.get('minRating'),
            'minVotes': data.get('minVotes'),
            'yearFrom': data.get('yearFrom'),
            'yearTo': data.get('yearTo'),
            'maxResults': data.get('maxResults'),
            'languages': data['languages'] if data.get('languages') is not None else DEFAULT_LANGUAGES,
            'includeGenres': data.get('includeGenres', []),
            'excludeGenres': data.get('excludeGenres', []),
            'titleTerms': data.get('titleTerms', ''),
            'titleExclude': data.get('titleExclude', ''),
            'studios': data.get('studios', []),
            'actors': data.get('actors', []),
            'excludeActors': data.get('excludeActors', []),
            'enabled': True,
            'created': datetime.now().isoformat()
        }
        
        movie_lists[list_id] = list_config
        movie_cache[list_id] = []
        save_lists(movie_lists)
        save_cache(movie_cache)
    
    return jsonify({'success': True, 'list_id': list_id})

@app.route('/api/update-list/<list_id>', methods=['PUT'])
def update_list(list_id):
    data = get_json_body()
    if data is None:
        return bad_body_response()

    new_name = data.get('name')
    new_name = new_name.strip() if isinstance(new_name, str) else ''
    if not new_name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400

    validation_error = validate_numeric_fields(data) or validate_list_fields(data)
    if validation_error:
        return jsonify({'success': False, 'error': validation_error}), 400

    with state_lock:
        if list_id not in movie_lists:
            return jsonify({'success': False, 'error': 'List not found'}), 404

        for existing_id, existing_list in movie_lists.items():
            if existing_id != list_id and existing_list['name'].lower() == new_name.lower():
                return jsonify({'success': False, 'error': 'A list with this name already exists'}), 400

        updates = {
            'name': new_name,
            'minRating': data.get('minRating'),
            'minVotes': data.get('minVotes'),
            'yearFrom': data.get('yearFrom'),
            'yearTo': data.get('yearTo'),
            'includeGenres': data.get('includeGenres', []),
            'excludeGenres': data.get('excludeGenres', []),
            'titleTerms': data.get('titleTerms', ''),
            'titleExclude': data.get('titleExclude', ''),
            'studios': data.get('studios', []),
            'actors': data.get('actors', []),
            'excludeActors': data.get('excludeActors', []),
        }
        # The web UI has no inputs for these two, so it never sends them.
        # Only touch them when the request includes them, otherwise an edit
        # from the UI would reset them.
        if data.get('languages') is not None:
            updates['languages'] = data['languages']
        if 'maxResults' in data:
            updates['maxResults'] = data['maxResults']

        movie_lists[list_id].update(updates)
        save_lists(movie_lists)
    return jsonify({'success': True})

@app.route('/api/toggle-list/<list_id>', methods=['POST'])
def toggle_list(list_id):
    with state_lock:
        if list_id in movie_lists:
            movie_lists[list_id]['enabled'] = not movie_lists[list_id].get('enabled', True)
            save_lists(movie_lists)
    return jsonify({'success': True})

@app.route('/api/delete-list/<list_id>', methods=['DELETE'])
def delete_list(list_id):
    with state_lock:
        if list_id in movie_lists:
            del movie_lists[list_id]
        if list_id in movie_cache:
            del movie_cache[list_id]
        save_lists(movie_lists)
        save_cache(movie_cache)
    return jsonify({'success': True})

@app.route('/api/lists')
def get_lists():
    with state_lock:
        return jsonify(movie_lists)

@app.route('/api/list-count/<list_id>')
def get_list_count(list_id):
    with state_lock:
        count = sum(1 for movie in movie_cache.get(list_id, []) if str(movie['id']) not in ignore_list)
    return jsonify({'count': count})

@app.route('/view/<list_id>')
def view_list(list_id):
    with state_lock:
        if list_id not in movie_lists:
            return "List not found", 404
        list_name = movie_lists[list_id]['name']
        movies = [m for m in movie_cache.get(list_id, []) if str(m['id']) not in ignore_list]

    sorted_movies = sorted(movies, key=lambda m: m.get('release_date', ''))
    safe_name = html.escape(list_name)

    page = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{safe_name} - Movie List</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 1200px;
                margin: 30px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
                margin-bottom: 10px;
            }}
            .count {{
                color: #666;
                margin-bottom: 20px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                text-align: left;
                padding: 12px;
                border-bottom: 1px solid #ddd;
            }}
            th {{
                background-color: #4CAF50;
                color: white;
            }}
            tr:hover {{
                background-color: #f5f5f5;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{safe_name}</h1>
            <div class="count">Total: {len(movies)} movies</div>
            <table>
                <thead>
                    <tr>
                        <th>Title</th>
                        <th>Year</th>
                        <th>Rating</th>
                        <th>Votes</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for movie in sorted_movies:
        year = movie.get('release_date', '')[:4] if movie.get('release_date') else 'N/A'
        rating = round(movie.get('vote_average', 0), 1)
        votes = movie.get('vote_count', 0)
        safe_title = html.escape(movie.get('title', ''))
        page += f"""
                    <tr>
                        <td>{safe_title}</td>
                        <td>{year}</td>
                        <td>{rating}/10</td>
                        <td>{votes:,}</td>
                    </tr>
        """
    
    page += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    
    return page

@app.route('/api/refresh-cache', methods=['POST'])
def force_refresh_cache():
    try:
        print("=" * 60)
        print("Manual cache refresh requested")
        print("-" * 30)
        if not refresh_all_lists_parallel(wait=True):
            print("A refresh was already running - waited for it to finish")
        print("=" * 60)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error refreshing cache: {safe_error(e)}")
        return jsonify({'success': False, 'error': safe_error(e)}), 500

@app.route('/api/refresh-list/<list_id>', methods=['POST'])
def refresh_single_list(list_id):
    with state_lock:
        list_config = movie_lists.get(list_id)
        list_config = dict(list_config) if list_config else None
    if list_config is None:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    try:
        movies = get_movies_from_tmdb(list_config)
    except FetchIncomplete as e:
        with state_lock:
            has_previous = bool(movie_cache.get(list_id))
        if has_previous:
            print(f" ! {list_config['name']}: TMDB error ({e.reason}) - kept previous data")
            return jsonify({'success': False, 'error': f'TMDB error ({e.reason}); previous data kept'}), 502
        movies = e.movies
    except Exception as e:
        print(f"Error refreshing list {list_config['name']}: {safe_error(e)}")
        return jsonify({'success': False, 'error': 'Refresh failed'}), 500

    with state_lock:
        # Skip if the list was deleted while fetching
        if list_id not in movie_lists:
            return jsonify({'success': False, 'error': 'List not found'}), 404
        movie_cache[list_id] = movies
        save_cache(movie_cache)
        # metadata['lastUpdated'] is left alone: it describes the whole cache,
        # and the other lists have not been refreshed.

    print(f" \u2713 {len(movies)} movies - {list_config['name']} (single list refresh)")
    visible = sum(1 for m in movies if str(m['id']) not in ignore_list)
    return jsonify({'success': True, 'count': visible})

@app.route('/api/master-list')
def get_master_list():
    print("=" * 28)
    print(" Master list requested")
    print("=" * 28)

    # Never block the caller on a refresh (Radarr times out on slow feeds).
    # A stale cache is served immediately while the refresh runs in the background.
    if should_update_cache():
        print("Cache is stale. Refreshing in the background")
        start_background_refresh()

    with state_lock:
        enabled_lists = [(list_id, list_config) for list_id, list_config in movie_lists.items()
                         if list_config.get('enabled', True)]
        has_refreshed = bool(metadata.get('lastUpdated'))
        cached = {list_id: list(movie_cache.get(list_id, [])) for list_id, _ in enabled_lists}

    # Nothing has ever been cached: an empty answer would look like a real,
    # empty list to Radarr. Report "not ready" instead.
    if enabled_lists and not has_refreshed:
        response = jsonify({'error': 'Cache is still being built, retry shortly'})
        response.status_code = 503
        response.headers['Retry-After'] = '60'
        return response

    all_movies = {}
    for list_id, list_config in enabled_lists:
        movies = cached[list_id]
        print(f" {len(movies)} movies - {list_config['name']}")
        for movie in movies:
            all_movies[movie['id']] = movie

    radarr_list = []
    skipped_ignored = 0
    for movie in all_movies.values():
        # Safety net: filters out anything added to the ignore list after
        # this movie was cached, without waiting for the next refresh.
        if str(movie['id']) in ignore_list:
            skipped_ignored += 1
            continue
        radarr_list.append({
            'id': movie['id']
        })

    print("=" * 28)
    print(f" {len(radarr_list)} Total ({skipped_ignored} ignored)")
    print("=" * 60)
    return jsonify(radarr_list)

@app.route('/api/ignore-list')
def get_ignore_list():
    with state_lock:
        return jsonify(ignore_list)

@app.route('/api/ignore-list/<tmdb_id>', methods=['DELETE'])
def remove_ignored(tmdb_id):
    with state_lock:
        if tmdb_id in ignore_list:
            del ignore_list[tmdb_id]
            save_ignore_list(ignore_list)
    return jsonify({'success': True})

@app.route('/api/ignore-list/clear', methods=['POST'])
def clear_ignore_list():
    with state_lock:
        ignore_list.clear()
        save_ignore_list(ignore_list)
    return jsonify({'success': True})

class RadarrImportError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status

def import_radarr_exclusions_from(radarr_url, api_key):
    """Merges Radarr's import list exclusions into the ignore list (existing
    entries are kept). Returns (imported, total). Raises RadarrImportError."""
    try:
        response = requests.get(
            f"{radarr_url}/api/v3/exclusions",
            headers={'X-Api-Key': api_key},
            timeout=15
        )
    except requests.exceptions.RequestException as e:
        raise RadarrImportError(f'Could not reach Radarr: {safe_error(e)}', 502)

    if response.status_code == 401:
        raise RadarrImportError('Radarr rejected the API key', 401)
    if response.status_code != 200:
        raise RadarrImportError(f'Radarr returned status {response.status_code}', 502)

    try:
        exclusions = response.json()
    except ValueError:
        raise RadarrImportError('Radarr response was not valid JSON', 502)

    if not isinstance(exclusions, list):
        raise RadarrImportError('Unexpected response format from Radarr', 502)

    imported = 0
    with state_lock:
        for item in exclusions:
            if not isinstance(item, dict):
                continue
            tmdb_id = item.get('tmdbId')
            if not tmdb_id:
                continue
            ignore_list[str(tmdb_id)] = {
                'title': item.get('movieTitle', ''),
                'year': item.get('movieYear', '')
            }
            imported += 1
        save_ignore_list(ignore_list)
        total = len(ignore_list)
    return imported, total

# Automatic import: runs at startup, then every 12 hours, when both RADARR_URL
# and RADARR_API_KEY are set.
RADARR_IMPORT_INTERVAL_SECONDS = 12 * 3600
RADARR_RETRY_SECONDS = 30 * 60
radarr_sync = {'lastImport': None}

def radarr_auto_import_loop():
    while True:
        try:
            imported, total = import_radarr_exclusions_from(RADARR_URL, RADARR_API_KEY)
            radarr_sync['lastImport'] = datetime.now().isoformat()
            print(f"Radarr exclusions imported: {imported} ({total} total ignored)")
            delay = RADARR_IMPORT_INTERVAL_SECONDS
        except RadarrImportError as e:
            print(f"Radarr auto-import failed: {e.message} - retrying in 30 minutes")
            delay = RADARR_RETRY_SECONDS
        except Exception as e:
            print(f"Radarr auto-import failed: {safe_error(e)} - retrying in 30 minutes")
            delay = RADARR_RETRY_SECONDS
        time.sleep(delay)

@app.route('/api/config')
def get_config():
    # Never includes the API key itself, only whether one is configured.
    return jsonify({'radarrUrl': RADARR_URL, 'radarrKeyConfigured': bool(RADARR_API_KEY),
                    'radarrLastImport': radarr_sync['lastImport']})

@app.route('/api/import-radarr-exclusions', methods=['POST'])
def import_radarr_exclusions():
    data = get_json_body()
    if data is None:
        return bad_body_response()
    body_url = str(data.get('radarr_url') or '').strip().rstrip('/')
    body_key = str(data.get('api_key') or '').strip()

    if body_key:
        # Key typed in the UI: used for this request only, never stored.
        radarr_url = body_url or RADARR_URL
        api_key = body_key
    else:
        # Key from the environment. It is only ever sent to RADARR_URL, never
        # to a URL supplied in the request.
        radarr_url = RADARR_URL
        api_key = RADARR_API_KEY

    if not radarr_url or not api_key:
        return jsonify({'success': False, 'error': 'Radarr URL and API key are required'}), 400

    # The key is never written to disk or logged.
    try:
        imported, total = import_radarr_exclusions_from(radarr_url, api_key)
    except RadarrImportError as e:
        return jsonify({'success': False, 'error': e.message}), e.status

    return jsonify({'success': True, 'imported': imported, 'total': total})

if __name__ == '__main__':
    print("=" * 60)
    print("TMDB Movie List Generator for Radarr")
    print(f" - Feed updates every {CACHE_REFRESH_HOURS} hours")
    print(" - Adult content ignored")
    print(" - Stand-up comedy ignored")
    print(" - Minimum of 45 minutes")
    print("=" * 60)
    
    if not TMDB_API_KEY:
        print("\n⚠️  WARNING: TMDB_API_KEY not set!")
        print("Set it using environment variable or .env file")
        print("=" * 60 + "\n")
    
    def delayed_cache_check():
        time.sleep(5)
        refresh_cache_on_startup()
    
    threading.Thread(target=delayed_cache_check, daemon=True).start()

    if RADARR_URL and RADARR_API_KEY:
        threading.Thread(target=radarr_auto_import_loop, daemon=True).start()
    
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
