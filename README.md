A web application that generates custom movie lists from The Movie Database (TMDB) API, for use with Radarr.  
Create filtered lists based on genres, ratings, release years, actors, studios, languages.  

Project inspired by [listrr.pro](https://listrr.pro). *Listrr is far more advanced.


### Prerequisites

- TMDB API key [HERE](https://www.themoviedb.org/settings/api)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/flickarr.git
cd flickarr
```

2. Edit `docker-compose.yml`:
   - Replace `your_api_key_here` with your actual TMDB API key
   - (Optional) Change `DEFAULT_LANGUAGES` to your preferred language(s)

3. Start the container:
```bash
docker-compose up -d
```

4. Access the web interface at `http://localhost:5000`


## Manual Docker Build
Build the image:
```bash
docker build -t flickarr .
```

Run the container:
```bash
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e TMDB_API_KEY=your_api_key_here \
  -e DEFAULT_LANGUAGES=en,es \
  --name flickarr \
  flickarr
```


## Radarr Integration
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
All data is stored in the `/app/data` directory (mapped to `./data` on host):
- `lists.json` - Your list configurations
- `cache.json` - Cached movie results
- `update_time.json` - Last update timestamp

## Development
Run locally without Docker:

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export TMDB_API_KEY=your_api_key_here
export DEFAULT_LANGUAGES=en
```

3. Run the application:
```bash
python main.py
```

Access at `http://localhost:5000`


## Credits
- Claude AI
- Movie data provided by [The Movie Database (TMDB)](https://www.themoviedb.org/)
- Built for [Radarr](https://radarr.video/)
