# TMDB API Setup for ID-Based Searches

## Problem
When Radarr/Sonarr search through pachelarr using only IDs (IMDb, TVDB, TMDB, etc.) without text queries, public torrent indexers return incorrect results because they don't support native ID-based searches. They require text queries to work properly.

## Solution
Pachelarr now uses TMDB API to lookup movie/TV titles from external IDs, then passes both the ID and the title text to Prowlarr for better results.

## Setup Instructions

### 1. Get a Free TMDB API Key
1. Go to https://www.themoviedb.org/signup and create a free account
2. After logging in, go to https://www.themoviedb.org/settings/api
3. Request an API key (select "Developer" if asked)
4. Copy your API key (v3 auth)

### 2. Configure Pachelarr
Update your `docker-compose.yml` to include your TMDB API key:

```yaml
environment:
  - TMDB_API_KEY=your_actual_api_key_here
```

Replace `YOUR_TMDB_API_KEY_HERE` with your actual key.

### 3. Rebuild and Restart
```bash
docker-compose down
docker-compose build
docker-compose up -d
```

## Supported ID Types

TMDB API supports looking up titles from:

| ID Type | Description | Supported For | Example |
|---------|-------------|---------------|---------|
| **imdbid** | IMDb ID | Movies & TV Shows | tt0319343 |
| **tvdbid** | TVDB ID | TV Shows only | 73739 |
| **rid** | TVRage ID | TV Shows only (deprecated but still works) | 2930 |
| **tmdbid** | TMDB ID | Movies & TV Shows (direct lookup) | 10719 |

**Note:** TMDB does not support tvmaze, traktid, or doubanid. These IDs will be passed to Prowlarr but won't trigger title lookups.

## How It Works

1. **Without TMDB_API_KEY:**
   - Radarr sends: `imdbid=0319343` (no query text)
   - Pachelarr passes to Prowlarr: `imdbid=0319343` (no query text)
   - Public indexers can't search by ID alone → wrong results

2. **With TMDB_API_KEY:**
   - Radarr sends: `imdbid=0319343` (no query text)
   - Pachelarr looks up title from TMDB: "Elf 2003"
   - Pachelarr passes to Prowlarr: `imdbid=0319343&query=Elf 2003`
   - Public indexers search for "Elf 2003" → correct results!

## Testing

Test that it's working:

```bash
# Without title lookup (if TMDB_API_KEY not set), you'd get wrong results
curl "http://localhost:6800/api?t=movie&cat=2000&imdbid=0319343&limit=5"

# With TMDB lookup, you should get "Elf" movie results
```

Check logs for successful lookups:
```
Successfully looked up movie via TMDB (IMDb): Elf 2003
```

## TMDB API Limits

TMDB's free tier includes:
- **40 requests per 10 seconds**
- **Unlimited requests per day**

This is more than enough for typical Radarr/Sonarr usage. Each search only makes 1 TMDB API call if needed.

## Fallback Behavior

If TMDB lookup fails or times out (3 second timeout):
- Pachelarr logs the error but continues
- Search still goes to Prowlarr with original parameters
- Cached torrents (from Torbox) still work fine

## Privacy Note

By using TMDB API, your searches are sent to TMDB's servers. This is necessary to convert IDs to titles. If privacy is a concern:
- Don't set `TMDB_API_KEY` (ID searches won't work as well)
- Use Radarr's "Application" integration with Prowlarr directly (bypasses pachelarr for searches)
