<img width="879" height="555" alt="Capture" src="https://github.com/user-attachments/assets/8343fbf6-a8a0-4095-830c-7d2fe1d9a6c5" />

<br /><br />
Build custom lists for Radarr, using filters (actors, genres, ratings, studios, years). Lists refresh every 6 hours.  

🚨  Do NOT connect this to your WAN. Designed for local access only. You will have problems.  

### Scans exclude:
 - Adult content  
 - Stand-up comedy  
 - Videos under 45 minutes  
 - All languages not specified in the .env file  

### Prerequisites  
- TMDB API key [HERE](https://www.themoviedb.org/settings/api)

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
