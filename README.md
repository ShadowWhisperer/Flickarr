🚨  This is in BETA. I do not recommend to try it yet  
🚨  This way made with help from AI  


### Flickarr  
Use filters to generates custom movie lists from The Movie Database (TMDB) API, for use with Radarr. Filtere lists based on genres, ratings, release years, actors, studios, languages.  

Project was inspired by [listrr.pro](https://listrr.pro). *Listrr is far more advanced.  


### Prerequisites  
- TMDB API key [HERE](https://www.themoviedb.org/settings/api)

### Installation  
1. Clone the repository:
```bash
git clone https://github.com/ShadowWhisperer/flickarr.git
cd flickarr
nano docker-compose.yml
```

2. docker-compose.yml settings
```
TMDB_API_KEY=       Set you API Key
DEFAULT_LANGUAGES=  Search for only movies in these languages
user:               ID # of your non-root user

```

3. Start the container:
```bash
docker-compose up -d
```

Web Page: `http://localhost:5000`

## Radarr Setup  
1. Create and configure your lists in the web interface at `http://localhost:5000`
2. Copy the Master List URL from the main screen
3. In Radarr, go to **Settings → Import Lists → Add List (+) → Custom Lists**
4. Configure:
   - **Name**: Flickarr
   - **Enable**: ✓
   - **Search on Add**: ✓
   - **Minimum Availability**: Released
   - **Radarr Tags**: Flickarr
   - **List URL**: `http://your-server:5000/api/master-list`
5. **Save**


## Default Exclusions
The application automatically excludes:
- Adult content
- Stand-up comedy
- Videos under 45 minutes
- Animation, Documentary, Music, TV Movie (can be overridden)

## Data Files
- `lists.json`       - Your lists
- `cache.json`       - Cached movie results
- `update_time.json` - Last update timestamp

## Credits
- Claude AI
- Movie data provided by [The Movie Database (TMDB)](https://www.themoviedb.org/)
- Built for [Radarr](https://radarr.video/)
