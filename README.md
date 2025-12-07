# Pachelarr

A smart caching proxy between Prowlarr and debrid services that dramatically improves torrent search results by prioritizing cached content and enriching metadata.

## What It Does

Pachelarr sits between your media management tools (Radarr/Sonarr) and Prowlarr, intercepting torrent searches to:

1. **Check debrid cache status** - Queries your debrid service (currently Torbox) to identify which torrents are already cached
2. **Boost cached results** - Adds a configurable seeder boost (default: 10,000) to cached torrents, making them appear at the top of search results
3. **Enrich metadata** - Optionally scrapes trackers for real-time seeders/leechers data
4. **Resolve IDs to titles** - Uses TMDB API to convert IMDb/TVDB/TMDB IDs into searchable text queries, fixing compatibility with public indexers that don't support ID-based searches

## The Problem It Solves

### 1. Debrid Service Integration
**Problem:** Radarr/Sonarr can't check if torrents are cached before downloading, often grabbing uncached torrents that take hours to download to your debrid service.

**Solution:** Pachelarr checks cache status in real-time and boosts cached torrents to the top of results. Your media manager will almost always pick instantly-available cached content.

### 2. ID-Only Search Failures
**Problem:** When Radarr/Sonarr search by IMDb/TVDB ID alone (without text), public torrent indexers return wrong results because they don't support native ID-based searches.

**Example:** Searching for "Elf (2003)" with IMDb ID `tt0319343` returns random movies like "Emperor's New Groove" and "Fraggle Rock."

**Solution:** Pachelarr automatically looks up the movie/TV title from the ID using TMDB API and adds it to the search, ensuring accurate results.

### 3. Poor Metadata Quality
**Problem:** Many public indexers don't provide accurate seeder/leecher counts, making it hard to judge torrent health.

**Solution:** Enable optional UDP tracker scraping to get real-time stats directly from trackers.

## Compatibility

### Media Management (Clients)
- ✅ **Radarr** (all versions)
- ✅ **Sonarr** (all versions)
- ✅ Any Torznab-compatible client

### Indexer Aggregators
- ✅ **Prowlarr** (required)

### Debrid Services
- ✅ **Torbox** (fully supported)
- 🔄 **Real-Debrid, AllDebrid, Premiumize** (coming soon)

> **Note:** Pachelarr currently only works with Torbox but will be updated to support other popular debrid providers in future releases.

## How It Works

```
┌─────────┐     ┌───────────┐     ┌──────────┐     ┌─────────┐
│ Radarr/ │────▶│ Pachelarr │────▶│ Prowlarr │────▶│ Public  │
│ Sonarr  │◀────│           │◀────│          │◀────│ Indexers│
└─────────┘     └─────┬─────┘     └──────────┘     └─────────┘
                      │
                      │ Check cache status
                      ▼
                ┌──────────┐
                │  Torbox  │
                │   API    │
                └──────────┘
                      │
                      │ Lookup titles from IDs
                      ▼
                ┌──────────┐
                │   TMDB   │
                │   API    │
                └──────────┘
```

**Request Flow:**
1. Radarr/Sonarr sends search request to Pachelarr (configured as a Torznab indexer)
2. If search contains only IDs, Pachelarr looks up the title via TMDB
3. Pachelarr forwards enriched search to Prowlarr
4. Prowlarr queries all enabled public indexers
5. Pachelarr receives results and extracts info hashes
6. Pachelarr checks which torrents are cached in Torbox
7. Cached torrents get massive seeder boost (10,000+ seeders added)
8. Results returned to Radarr/Sonarr with cached content at the top
9. Radarr/Sonarr picks the "best" torrent (almost always cached)

## Installation

### Prerequisites
- Docker and Docker Compose
- Prowlarr instance with configured indexers
- Torbox account and API key
- TMDB API key (free, required for ID-based searches)


### Using Docker Image Directly

You can also pull and run the pre-built Docker image without cloning the repository:

```bash
# Pull the latest image
docker pull ghcr.io/northernpowerhouse/pachelarr:latest

# Run with docker run
docker run -d \
  --name pachelarr \
  -p 6800:6800 \
  -e PROWLARR_URL=http://your-prowlarr-host:9696 \
  -e PROWLARR_API_KEY=your_prowlarr_api_key_here \
  -e TORBOX_API_KEY=your_torbox_api_key_here \
  -e PACHELARR_API_KEY=your_pachelarr_api_key_here \
  -e TMDB_API_KEY=your_tmdb_api_key_here \
  --restart unless-stopped \
  ghcr.io/northernpowerhouse/pachelarr:latest
```

### Using Docker Compose (Recommended)

1. **Clone or download this repository**

2. **Download the docker-compose.yml**

You can download the compose file directly or copy it from the repository:

```bash
# Download directly
curl -O https://raw.githubusercontent.com/northernpowerhouse/pachelarr/main/docker-compose.yml

# Or if you prefer wget
wget https://raw.githubusercontent.com/northernpowerhouse/pachelarr/main/docker-compose.yml
```

**Or copy this into your docker-compose.yml:**

<details>
<summary>Click to expand docker-compose.yml</summary>

```yaml
services:
  pachelarr:
    image: ghcr.io/northernpowerhouse/pachelarr:latest
    container_name: pachelarr
    ports:
      - "6800:6800"
    environment:
      # === REQUIRED CONFIGURATION ===
      # Prowlarr connection settings
      - PROWLARR_URL=http://your-prowlarr-host:9696
      - PROWLARR_API_KEY=your_prowlarr_api_key_here
      
      # Torbox API key for torrent caching
      - TORBOX_API_KEY=your_torbox_api_key_here
      
      # Pachelarr API key (used by Radarr/Sonarr to authenticate)
      - PACHELARR_API_KEY=your_pachelarr_api_key_here
      
      # === PACHELARR SETTINGS ===
      # Port to listen on (default: 8080)
      - PACHELARR_PORT=6800
      
      # Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
      - PACHELARR_LOG_LEVEL=INFO
      
      # Seeders boost value added to cached torrents (default: 10000)
      - PACHELARR_SEEDERS_BOOST=10000
      
      # Fallback query for category-only requests (improves Sonarr "Test" behavior)
      # Set to empty string to disable (default: "")
      - PACHELARR_TEST_FALLBACK_QUERY=
      
      # === TMDB CONFIGURATION ===
      # TMDB API key for looking up movie/TV titles from IMDb/TVDB/TMDB IDs
      # Get a free key at: https://www.themoviedb.org/settings/api
      # Without this, ID-only searches (common with Radarr/Sonarr) will fail
      - TMDB_API_KEY=your_tmdb_api_key_here
      
      # === TORBOX SETTINGS ===
      # Torbox API endpoint for checking cached torrents
      - TORBOX_CHECK_URL=https://api.torbox.app/v1/api/torrents/checkcached
      
      # Number of hashes to check per Torbox API request (default: 100, max: 100)
      - TORBOX_CHUNK_SIZE=100
      
      # Maximum retry attempts for Torbox API failures (default: 3)
      - TORBOX_MAX_RETRIES=3
      
      # Backoff delay in seconds between retries (default: 0.5)
      - TORBOX_RETRY_BACKOFF=0.5
      
      # === TRACKER SCRAPING SETTINGS ===
      # Enable direct UDP tracker scraping for seeders/leechers (default: false)
      # Warning: Enables direct contact with public trackers
      - TRACKER_SCRAPE_ENABLED=false
      
      # Number of concurrent tracker scrape requests (default: 4)
      - TRACKER_SCRAPE_CONCURRENCY=4
      
      # Timeout in seconds for tracker scrape requests (default: 5.0)
      - TRACKER_SCRAPE_TIMEOUT=5.0
      
      # Number of info hashes to scrape per tracker request (default: 50)
      - TRACKER_SCRAPE_BATCH_SIZE=50
    restart: unless-stopped
```

</details>

**For Docker Compose GUI users (Portainer, Dockge, etc.):**
- Copy the compose content above
- Paste it into your Docker Compose editor
- Update the environment variables with your API keys
- Deploy the stack

```bash
git clone https://github.com/northernpowerhouse/pachelarr.git
cd pachelarr
```

1. **Clone or download this repository**

2. **Download the docker-compose.yml**

You can download the compose file directly or copy it from the repository:

```bash
# Download directly
curl -O https://raw.githubusercontent.com/northernpowerhouse/pachelarr/main/docker-compose.yml

# Or if you prefer wget
wget https://raw.githubusercontent.com/northernpowerhouse/pachelarr/main/docker-compose.yml
```

**Or copy this into your docker-compose.yml:**

<details>
<summary>Click to expand docker-compose.yml</summary>

```yaml
services:
  pachelarr:
    image: ghcr.io/northernpowerhouse/pachelarr:latest
    container_name: pachelarr
    ports:
      - "6800:6800"
    environment:
      # === REQUIRED CONFIGURATION ===
      # Prowlarr connection settings
      - PROWLARR_URL=http://your-prowlarr-host:9696
      - PROWLARR_API_KEY=your_prowlarr_api_key_here
      
      # Torbox API key for torrent caching
      - TORBOX_API_KEY=your_torbox_api_key_here
      
      # Pachelarr API key (used by Radarr/Sonarr to authenticate)
      - PACHELARR_API_KEY=your_pachelarr_api_key_here
      
      # === PACHELARR SETTINGS ===
      # Port to listen on (default: 8080)
      - PACHELARR_PORT=6800
      
      # Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
      - PACHELARR_LOG_LEVEL=INFO
      
      # Seeders boost value added to cached torrents (default: 10000)
      - PACHELARR_SEEDERS_BOOST=10000
      
      # Fallback query for category-only requests (improves Sonarr "Test" behavior)
      # Set to empty string to disable (default: "")
      - PACHELARR_TEST_FALLBACK_QUERY=
      
      # === TMDB CONFIGURATION ===
      # TMDB API key for looking up movie/TV titles from IMDb/TVDB/TMDB IDs
      # Get a free key at: https://www.themoviedb.org/settings/api
      # Without this, ID-only searches (common with Radarr/Sonarr) will fail
      - TMDB_API_KEY=your_tmdb_api_key_here
      
      # === TORBOX SETTINGS ===
      # Torbox API endpoint for checking cached torrents
      - TORBOX_CHECK_URL=https://api.torbox.app/v1/api/torrents/checkcached
      
      # Number of hashes to check per Torbox API request (default: 100, max: 100)
      - TORBOX_CHUNK_SIZE=100
      
      # Maximum retry attempts for Torbox API failures (default: 3)
      - TORBOX_MAX_RETRIES=3
      
      # Backoff delay in seconds between retries (default: 0.5)
      - TORBOX_RETRY_BACKOFF=0.5
      
      # === TRACKER SCRAPING SETTINGS ===
      # Enable direct UDP tracker scraping for seeders/leechers (default: false)
      # Warning: Enables direct contact with public trackers
      - TRACKER_SCRAPE_ENABLED=false
      
      # Number of concurrent tracker scrape requests (default: 4)
      - TRACKER_SCRAPE_CONCURRENCY=4
      
      # Timeout in seconds for tracker scrape requests (default: 5.0)
      - TRACKER_SCRAPE_TIMEOUT=5.0
      
      # Number of info hashes to scrape per tracker request (default: 50)
      - TRACKER_SCRAPE_BATCH_SIZE=50
    restart: unless-stopped
```

</details>

**For Docker Compose GUI users (Portainer, Dockge, etc.):**
- Copy the compose content above
- Paste it into your Docker Compose editor
- Update the environment variables with your API keys
- Deploy the stack

```bash
git clone https://github.com/northernpowerhouse/pachelarr.git
cd pachelarr
```

3. **Get your API keys**
   - **Torbox API Key:** https://torbox.app/settings (under API section)
   - **Prowlarr API Key:** Prowlarr → Settings → General → API Key
   - **TMDB API Key:** https://www.themoviedb.org/settings/api (free account required)

4. **Configure environment variables**

Edit `docker-compose.yml` and update these required values:
```yaml
- PROWLARR_URL=http://your-prowlarr-host:9696
- PROWLARR_API_KEY=your_prowlarr_api_key_here
- TORBOX_API_KEY=your_torbox_api_key_here
- TMDB_API_KEY=your_tmdb_api_key_here
- PACHELARR_API_KEY=your_pachelarr_api_key_here  # Any random string
```

5. **Start the service**
```bash
docker compose up -d
```

6. **Configure Radarr/Sonarr**

Add Pachelarr as a Torznab indexer:
- **URL:** `http://pachelarr-host:6800/api`
- **API Key:** Whatever you set for `PACHELARR_API_KEY`
- **Categories:** 
  - Movies: 2000,2010,2020,2030,2040,2045,2050,2060,2070,2080
  - TV: 5000,5010,5020,5030,5040,5045,5050,5060,5070,5080

## Configuration

All configuration is done via environment variables in `docker-compose.yml`.

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `PROWLARR_URL` | Prowlarr instance URL | `http://192.168.1.100:9696` |
| `PROWLARR_API_KEY` | Prowlarr API key | `abc123...` |
| `TORBOX_API_KEY` | Torbox API key | `xyz789...` |
| `PACHELARR_API_KEY` | API key for Radarr/Sonarr to authenticate | Any string |
| `TMDB_API_KEY` | TMDB API key for ID lookups | Get at themoviedb.org |

### Optional Settings

#### Pachelarr Settings
| Variable | Default | Description |
|----------|---------|-------------|
| `PACHELARR_PORT` | `8080` | Port to listen on |
| `PACHELARR_LOG_LEVEL` | `INFO` | Log verbosity: DEBUG, INFO, WARNING, ERROR |
| `PACHELARR_SEEDERS_BOOST` | `10000` | Seeders added to cached torrents |
| `PACHELARR_TEST_FALLBACK_QUERY` | `""` | Fallback query for category-only searches (improves Sonarr "Test" button) |

#### Torbox Settings
| Variable | Default | Description |
|----------|---------|-------------|
| `TORBOX_CHECK_URL` | `https://api.torbox.app/v1/api/torrents/checkcached` | Torbox cache check endpoint |
| `TORBOX_CHUNK_SIZE` | `100` | Hashes per API request (max: 100) |
| `TORBOX_MAX_RETRIES` | `3` | Retry attempts on failure |
| `TORBOX_RETRY_BACKOFF` | `0.5` | Seconds between retries |

#### Tracker Scraping Settings
| Variable | Default | Description |
|----------|---------|-------------|
| `TRACKER_SCRAPE_ENABLED` | `false` | Enable UDP tracker scraping for real seeders/leechers |
| `TRACKER_SCRAPE_CONCURRENCY` | `4` | Concurrent scrape requests |
| `TRACKER_SCRAPE_TIMEOUT` | `5.0` | Timeout per scrape request (seconds) |
| `TRACKER_SCRAPE_BATCH_SIZE` | `50` | Info hashes per scrape request |

⚠️ **Warning:** Enabling tracker scraping makes direct UDP connections to public trackers. Use at your own discretion.

## Features

### 🚀 Cache-First Results
Automatically prioritizes torrents that are already cached on your debrid service, giving you instant downloads instead of waiting hours for uncached content.

### 🎯 Smart ID Resolution
Converts IMDb/TVDB/TMDB IDs to searchable titles using TMDB API, fixing broken ID-only searches that plague public indexers.

**Supported ID types:**
- IMDb IDs (movies & TV)
- TVDB IDs (TV shows)
- TMDB IDs (movies & TV)
- TVRage IDs (TV shows, legacy)

### 📊 Real-Time Metadata
Optional UDP tracker scraping provides accurate, real-time seeder and leecher counts directly from BitTorrent trackers.

### 🔄 Transparent Proxy
Works seamlessly with Radarr/Sonarr - no modifications needed to existing workflows. Just add as a Torznab indexer.

### ⚡ Performance Optimized
- Bulk hash checking (up to 100 hashes per API call)
- Concurrent tracker scraping
- Configurable timeouts and retry logic
- Request caching for faster repeated searches

## Usage Examples

### Typical Radarr Search
1. User adds "Elf (2003)" to Radarr
2. Radarr searches Pachelarr with `imdbid=0319343`
3. Pachelarr looks up "Elf (2003)" from TMDB
4. Pachelarr searches Prowlarr with "Elf 2003" + IMDb ID
5. Prowlarr returns 200+ torrents from public indexers
6. Pachelarr checks which are cached in Torbox (e.g., 25 cached)
7. Cached torrents get +10,000 seeders
8. Radarr sees cached 4K REMUX with 10,500 seeders at top
9. Radarr grabs cached torrent → instant download from Torbox

### Manual Testing
Test the cache checking:
```bash
curl "http://localhost:6800/api?t=movie&cat=2000&imdbid=0319343&apikey=your_api_key"
```

Look for `[CACHED]` prefix in results - these torrents are instantly available.

## Troubleshooting

### No cached results appearing
- Verify `TORBOX_API_KEY` is correct
- Check logs: `docker logs pachelarr-pachelarr-1`
- Ensure torrents exist in Torbox cache (check Torbox directly)

### Wrong search results
- Ensure `TMDB_API_KEY` is set and valid
- Check logs for "Successfully looked up movie via TMDB"
- Verify Prowlarr has working indexers

### Radarr/Sonarr can't connect
- Confirm `PACHELARR_API_KEY` matches in both places
- Check port 6800 is accessible
- Verify container is running: `docker ps`

### Enable debug logging
```yaml
- PACHELARR_LOG_LEVEL=DEBUG
```
Then restart: `docker compose restart`

## Performance Considerations

### TMDB API Rate Limits
- **Free tier:** 40 requests per 10 seconds
- **Pachelarr usage:** 1 request per ID-only search
- More than sufficient for typical Radarr/Sonarr usage

### Torbox API Limits
- Check up to 100 hashes per request
- Typical search checks 50-200 torrents (1-2 API calls)
- No known rate limits for personal use

### Tracker Scraping
- Adds 1-3 seconds latency per search when enabled
- Recommended for users who need accurate seeder counts
- Disable if speed is more important than metadata accuracy

## Privacy & Security

- All API keys stored in environment variables (not in code)
- No telemetry or analytics
- TMDB lookups expose searched titles to TMDB servers
- Tracker scraping exposes your IP to public BitTorrent trackers
- Use with VPN if privacy is a concern

## Contributing

Contributions welcome! Areas for improvement:
- Add support for Real-Debrid, AllDebrid, Premiumize
- Implement proper caching layer (Redis/SQLite)
- Add web UI for configuration and stats
- Support for more ID types (Trakt, TVmaze, etc.)
- Better error handling and retry logic

## License

[Add your license here]

## Credits

Built to solve the debrid + public indexer problem that plagued Radarr/Sonarr users who don't want to pay for private trackers.

## Support

- **Issues:** [Create an issue](link-to-issues)
- **Discussions:** [GitHub Discussions](link-to-discussions)
