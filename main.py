from flask import Flask, render_template, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)

TMDB_API_KEY = os.getenv('TMDB_API_KEY', '')
if not TMDB_API_KEY:
    print("WARNING: TMDB_API_KEY not set")

DEFAULT_LANGUAGES_STR = os.getenv('DEFAULT_LANGUAGES', 'en')
DEFAULT_LANGUAGES = [lang.strip() for lang in DEFAULT_LANGUAGES_STR.split(',') if lang.strip()]
print(f"Default languages: {', '.join(DEFAULT_LANGUAGES)}")

TMDB_BASE_URL = 'https://api.themoviedb.org/3'

DATA_DIR = os.getenv('DATA_DIR', './data')
os.makedirs(DATA_DIR, exist_ok=True)

LISTS_FILE = os.path.join(DATA_DIR, 'lists.json')
CACHE_FILE = os.path.join(DATA_DIR, 'cache.json')
METADATA_FILE = os.path.join(DATA_DIR, 'update_time.json')

def load_lists():
    if os.path.exists(LISTS_FILE):
        with open(LISTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_lists(lists):
    with open(LISTS_FILE, 'w') as f:
        json.dump(lists, f, indent=2)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def load_metadata():
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {'lastUpdated': None}

def save_metadata(metadata):
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)

movie_lists = load_lists()
movie_cache = load_cache()
metadata = load_metadata()

def refresh_cache_on_startup():
    if should_update_cache():
        refresh_all_lists_parallel()

def refresh_all_lists_parallel():
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    enabled_lists = [(list_id, list_config) for list_id, list_config in movie_lists.items() 
                     if list_config.get('enabled', True)]

    if not enabled_lists:
        print("No lists enabled to refresh")
        return

    print(f"Updating lists...")

    def fetch_list(list_id, list_config):
        try:
            movies = get_movies_from_tmdb(list_config)
            print(f" ✓ {len(movies)} movies - {list_config['name']}")
            return list_id, movies
        except Exception as e:
            print(f"  ✗ Error fetching {list_config['name']}: {e}")
            return list_id, []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_list, list_id, list_config): list_id 
                   for list_id, list_config in enabled_lists}
        
        for future in as_completed(futures):
            list_id, movies = future.result()
            movie_cache[list_id] = movies
    
    metadata['lastUpdated'] = datetime.now().isoformat()
    save_cache(movie_cache)
    save_metadata(metadata)
    print("Cache refresh done!")

def search_person(name):
    url = f"{TMDB_BASE_URL}/search/person"
    params = {
        'api_key': TMDB_API_KEY,
        'query': name.strip()
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            results = response.json().get('results', [])
            return [{'id': p['id'], 'name': p['name']} for p in results[:10]]
    except Exception as e:
        print(f"Error searching person: {e}")
    return []

def search_company_id(company_name):
    url = f"{TMDB_BASE_URL}/search/company"
    params = {
        'api_key': TMDB_API_KEY,
        'query': company_name.strip()
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                for i, company in enumerate(results[:5]):
                    print(f"  Option {i+1}: '{company['name']}' (ID: {company['id']})")
                selected = results[0]
                print(f"Using: '{selected['name']}' (ID: {selected['id']})")
                return selected['id']
    except Exception as e:
        print(f"Error searching company: {e}")
    return None

def get_movies_from_tmdb(list_config):
    movies = []
    page = 1
    max_pages = 25
    
    title_terms = list_config.get('titleTerms', '').strip()
    
    if title_terms:
        return search_movies_by_title(list_config, title_terms)
    
    title_exclude = list_config.get('titleExclude', '').strip()
    exclude_terms = []
    if title_exclude:
        exclude_terms = [term.strip().lower() for term in title_exclude.split(',') if term.strip()]
    
    params = {
        'api_key': TMDB_API_KEY,
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
    
    if list_config.get('includeGenres'):
        params['with_genres'] = ','.join(list_config['includeGenres'])
    
    excluded_genres = list(list_config.get('excludeGenres', []))
    if excluded_genres:
        params['without_genres'] = ','.join(excluded_genres)
    
    if list_config.get('actors'):
        people_ids = [str(actor['id']) for actor in list_config['actors']]
        params['with_people'] = ','.join(people_ids)
    
    if list_config.get('studios'):
        company_ids = [str(studio['id']) for studio in list_config['studios']]
        if company_ids:
            params['with_companies'] = '|'.join(company_ids)
    
    max_results = list_config.get('maxResults') or 500
    
    excluded_actor_ids = [actor['id'] for actor in list_config.get('excludeActors', [])]
    
    while len(movies) < max_results and page <= max_pages:
        params['page'] = page
        try:
            response = requests.get(f"{TMDB_BASE_URL}/discover/movie", params=params)
            
            if response.status_code == 200:
                results = response.json().get('results', [])
                if not results:
                    break
                
                for movie in results:
                    if movie.get('adult', False):
                        continue

                    if exclude_terms:
                        movie_title_lower = movie.get('title', '').lower()
                        excluded = False
                        for term in exclude_terms:
                            if term in movie_title_lower:
                                excluded = True
                                break
                        if excluded:
                            continue
                    
                    if excluded_actor_ids:
                        has_excluded = False
                        try:
                            credits_response = requests.get(
                                f"{TMDB_BASE_URL}/movie/{movie['id']}/credits",
                                params={'api_key': TMDB_API_KEY}
                            )
                            if credits_response.status_code == 200:
                                credits = credits_response.json()
                                cast_ids = [person['id'] for person in credits.get('cast', [])]
                                crew_ids = [person['id'] for person in credits.get('crew', [])]
                                all_people_ids = set(cast_ids + crew_ids)
                                
                                if any(ex_id in all_people_ids for ex_id in excluded_actor_ids):
                                    has_excluded = True
                        except Exception as e:
                            print(f"Error checking credits: {e}")
                        
                        if has_excluded:
                            continue
                    
                    movies.append(movie)
                    if len(movies) >= max_results:
                        break
                
                page += 1
            else:
                print(f"TMDB API Error: Status {response.status_code}")
                break
        except Exception as e:
            print(f"Error fetching movies: {e}")
            break
    
    return movies[:max_results]

def search_movies_by_title(list_config, title_query):
    movies = []
    page = 1
    max_pages = 25
    max_results = list_config.get('maxResults') or 500
    
    excluded_actor_ids = [actor['id'] for actor in list_config.get('excludeActors', [])]
    
    title_exclude = list_config.get('titleExclude', '').strip()
    exclude_terms = []
    if title_exclude:
        exclude_terms = [term.strip().lower() for term in title_exclude.split(',') if term.strip()]
    
    while len(movies) < max_results and page <= max_pages:
        try:
            response = requests.get(
                f"{TMDB_BASE_URL}/search/movie",
                params={
                    'api_key': TMDB_API_KEY,
                    'query': title_query,
                    'page': page
                }
            )
            
            if response.status_code == 200:
                results = response.json().get('results', [])
                if not results:
                    break
                
                for movie in results:
                    if movie.get('adult', False):
                        continue
                    
                    movie_title_lower = movie.get('title', '').lower()
                    
                    if exclude_terms:
                        excluded = False
                        for term in exclude_terms:
                            if term in movie_title_lower:
                                excluded = True
                                break
                        if excluded:
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
                    if list_config.get('includeGenres'):
                        required_genres = set(list_config['includeGenres'])
                        if not required_genres.intersection(movie_genres):
                            continue
                    if list_config.get('excludeGenres'):
                        excluded_genres = set(list_config['excludeGenres'])
                        if excluded_genres.intersection(movie_genres):
                            continue
                    
                    if excluded_actor_ids:
                        has_excluded = False
                        try:
                            credits_response = requests.get(
                                f"{TMDB_BASE_URL}/movie/{movie['id']}/credits",
                                params={'api_key': TMDB_API_KEY}
                            )
                            if credits_response.status_code == 200:
                                credits = credits_response.json()
                                cast_ids = [person['id'] for person in credits.get('cast', [])]
                                crew_ids = [person['id'] for person in credits.get('crew', [])]
                                all_people_ids = set(cast_ids + crew_ids)
                                
                                if any(ex_id in all_people_ids for ex_id in excluded_actor_ids):
                                    has_excluded = True
                        except Exception as e:
                            print(f"Error checking credits: {e}")
                        
                        if has_excluded:
                            continue
                    
                    movies.append(movie)
                    if len(movies) >= max_results:
                        break
                
                page += 1
            else:
                break
        except Exception as e:
            print(f"Error searching movies: {e}")
            break

    print(f" ✓ {len(movies)} Movies - Title Search")
    return movies[:max_results]

def should_update_cache():
    last_updated = metadata.get('lastUpdated')
    if not last_updated:
        return True
    
    last_update_time = datetime.fromisoformat(last_updated)
    return datetime.now() - last_update_time > timedelta(hours=3)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/metadata')
def get_metadata():
    all_movie_ids = set()
    for list_id, list_config in movie_lists.items():
        if list_config.get('enabled', True):
            movies = movie_cache.get(list_id, [])
            for movie in movies:
                all_movie_ids.add(movie['id'])
    
    metadata['totalMovies'] = len(all_movie_ids)
    return jsonify(metadata)

@app.route('/api/test-api')
def test_api():
    try:
        response = requests.get(
            f"{TMDB_BASE_URL}/movie/550",
            params={'api_key': TMDB_API_KEY},
            timeout=5
        )
        if response.status_code == 200:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': f'API returned status {response.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/search-person')
def api_search_person():
    query = request.args.get('q', '')
    results = search_person(query)
    return jsonify(results)

@app.route('/api/search-company')
def api_search_company():
    query = request.args.get('q', '')
    url = f"{TMDB_BASE_URL}/search/company"
    params = {
        'api_key': TMDB_API_KEY,
        'query': query.strip()
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            results = response.json().get('results', [])
            return jsonify([{'id': c['id'], 'name': c['name']} for c in results[:10]])
    except Exception as e:
        print(f"Error searching company: {e}")
    return jsonify([])

@app.route('/api/preview-list', methods=['POST'])
def preview_list():
    data = request.json
    print(f"Preview request data: {data}")
    movies = get_movies_from_tmdb(data)
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
    
    return jsonify({'movies': preview, 'totalCount': total_count})

@app.route('/api/create-list', methods=['POST'])
def create_list():
    data = request.json

    new_name = data['name']
    for existing_id, existing_list in movie_lists.items():
        if existing_list['name'].lower() == new_name.lower():
            return jsonify({'success': False, 'error': 'A list with this name already exists'}), 400
    
    list_id = data['name'].lower().replace(' ', '-').replace('/', '-') + '-' + str(len(movie_lists))
    
    list_config = {
        'name': data['name'],
        'minRating': data.get('minRating'),
        'minVotes': data.get('minVotes'),
        'yearFrom': data.get('yearFrom'),
        'yearTo': data.get('yearTo'),
        'maxResults': data.get('maxResults'),
        'languages': data.get('languages', DEFAULT_LANGUAGES),
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
    if list_id not in movie_lists:
        return jsonify({'success': False, 'error': 'List not found'}), 404
    
    data = request.json

    new_name = data['name']
    for existing_id, existing_list in movie_lists.items():
        if existing_id != list_id and existing_list['name'].lower() == new_name.lower():
            return jsonify({'success': False, 'error': 'A list with this name already exists'}), 400

    movie_lists[list_id].update({
        'name': data['name'],
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
    })
    
    save_lists(movie_lists)
    return jsonify({'success': True})

@app.route('/api/toggle-list/<list_id>', methods=['POST'])
def toggle_list(list_id):
    if list_id in movie_lists:
        movie_lists[list_id]['enabled'] = not movie_lists[list_id].get('enabled', True)
        save_lists(movie_lists)
    return jsonify({'success': True})

@app.route('/api/delete-list/<list_id>', methods=['DELETE'])
def delete_list(list_id):
    if list_id in movie_lists:
        del movie_lists[list_id]
        if list_id in movie_cache:
            del movie_cache[list_id]
        save_lists(movie_lists)
        save_cache(movie_cache)
    return jsonify({'success': True})

@app.route('/api/lists')
def get_lists():
    return jsonify(movie_lists)

@app.route('/api/list-count/<list_id>')
def get_list_count(list_id):
    count = len(movie_cache.get(list_id, []))
    return jsonify({'count': count})

@app.route('/view/<list_id>')
def view_list(list_id):
    if list_id not in movie_lists:
        return "List not found", 404
    
    list_config = movie_lists[list_id]
    movies = movie_cache.get(list_id, [])
    
    sorted_movies = sorted(movies, key=lambda m: m.get('release_date', ''))
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{list_config['name']} - Movie List</title>
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
            <h1>{list_config['name']}</h1>
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
        html += f"""
                    <tr>
                        <td>{movie['title']}</td>
                        <td>{year}</td>
                        <td>{rating}/10</td>
                        <td>{votes:,}</td>
                    </tr>
        """
    
    html += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/api/refresh-cache', methods=['POST'])
def force_refresh_cache():
    try:
        print("=" * 60)
        print("Manual cache refresh requested")
        print("-" * 30)
        refresh_all_lists_parallel()
        print("=" * 60)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error refreshing cache: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/master-list')
def get_master_list():
    all_movies = {}
    
    print("=" * 28)
    print(" Master list requested")
    print("=" * 28)
    
    if should_update_cache():
        print("Update triggered. Updating lists")
        refresh_all_lists_parallel()
    
    for list_id, list_config in movie_lists.items():
        if list_config.get('enabled', True):
            movies = movie_cache.get(list_id, [])
            print(f" {len(movies)} movies - {list_config['name']}")
            for movie in movies:
                all_movies[movie['id']] = movie
    
    radarr_list = []
    for movie in all_movies.values():
        radarr_list.append({
            'id': movie['id']
        })

    print("=" * 28)
    print(f" {len(radarr_list)} Total")
    print("=" * 60)
    return jsonify(radarr_list)

if __name__ == '__main__':
    print("=" * 60)
    print("TMDB Movie List Generator for Radarr")
    print(" - Feed updates every 3 hours")
    print(" - Adult content ignored")
    print(" - Stand-up comedy ignored")
    print(" - Minimum of 45 minutes")
    print("=" * 60)
    
    if not TMDB_API_KEY:
        print("\n⚠️  WARNING: TMDB_API_KEY not set!")
        print("Set it using environment variable or .env file")
        print("=" * 60 + "\n")
    
    import threading
    def delayed_cache_check():
        import time
        time.sleep(5)
        refresh_cache_on_startup()
    
    threading.Thread(target=delayed_cache_check, daemon=True).start()
    
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
