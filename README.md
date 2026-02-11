<img width="874" height="605" alt="Capture" src="https://github.com/user-attachments/assets/da2e980a-2346-4188-9428-1038b7016606" />

Build custom lists for Radarr, using filters (actors, genres, ratings, studios, years).  
  
### Scans exclude:
 - Adult content  
 - Stand-up comedy  
 - Videos under 45 minutes  
 - Animation, Documentary, Music, TV Movie (can be overridden)  
 - All languages not specified in the compose file  


### Prerequisites  
- TMDB API key [HERE](https://www.themoviedb.org/settings/api)

## docker-compose
```
TMDB_API_KEY=       Set you API Key
DEFAULT_LANGUAGES=  Search for only movies in these languages
TZ=                 Your time zone. Used in the GUI for last upated time.
user:               ID # of your non-root user.  *Make sure user has permissions to access data dir.
```

Web Page: `http://localhost:5000`  
<br />  
  
🚨  Do NOT connect this to your WAN. Designed for local access only. You will have problems.  
  
## Radarr Setup  
1. Create and configure your lists in the web interface at `http://localhost:5000`
2. Copy the Master List URL from the main screen
3. In Radarr, go to **Settings → Import Lists → Add List (+) → Custom Lists**
4. Configure:
   - **Name**: Flickarr
   - **Enable**: ✓
   - **Search on Add**: ✓
   - **Minimum Availability**: Released
   - **Radarr Tags**: flickarr
   - **List URL**: `http://your-server:5000/api/master-list`
5. **Save**

## Data Files  
- `lists.json`       - Your lists
- `cache.json`       - Cached movie results
- `update_time.json` - Last update timestamp

## Credits
- Claude AI
- Movie data provided by [The Movie Database (TMDB)](https://www.themoviedb.org/)
- Built for [Radarr](https://github.com/Radarr/Radarr)
- Inspired by [listrr.pro](https://listrr.pro). *Listrr is far more advanced.
