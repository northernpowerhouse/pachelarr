import os
import asyncio
from datetime import datetime, timezone
import logging
from fastapi import FastAPI, Request, Response
import aiohttp
from lxml import etree as ET
from urllib.parse import urljoin, parse_qs, unquote

app = FastAPI()
PACHELARR_LOG_LEVEL = os.getenv("PACHELARR_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, PACHELARR_LOG_LEVEL, logging.INFO))
logger = logging.getLogger("pachelarr")

PROWLARR_URL = os.getenv("PROWLARR_URL")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY")
TORBOX_API_KEY = os.getenv("TORBOX_API_KEY")
PACHELARR_API_KEY = os.getenv("PACHELARR_API_KEY")
# Seed count used to boost cached items (default: 10000)
PACHELARR_SEEDERS_BOOST = int(os.getenv("PACHELARR_SEEDERS_BOOST", "10000"))

TORBOX_CHECK_URL = os.getenv("TORBOX_CHECK_URL", "https://api.torbox.app/v1/api/torrents/checkcached")
_configured_chunk = int(os.getenv("TORBOX_CHUNK_SIZE", "100"))
# Torbox supports up to 100 per request; enforce a cap.
TORBOX_CHUNK_SIZE = min(_configured_chunk, 100)
TORBOX_MAX_RETRIES = int(os.getenv("TORBOX_MAX_RETRIES", "3"))
TORBOX_RETRY_BACKOFF = float(os.getenv("TORBOX_RETRY_BACKOFF", "0.5"))
TRACKER_SCRAPE_ENABLED = os.getenv("TRACKER_SCRAPE_ENABLED", "false").lower() in ("1", "true", "yes")
TRACKER_SCRAPE_CONCURRENCY = int(os.getenv("TRACKER_SCRAPE_CONCURRENCY", "4"))
TRACKER_SCRAPE_TIMEOUT = float(os.getenv("TRACKER_SCRAPE_TIMEOUT", "5.0"))
TRACKER_SCRAPE_BATCH_SIZE = int(os.getenv("TRACKER_SCRAPE_BATCH_SIZE", "50"))
# Optional query fallback used when an incoming search contains categories but no
# query. Useful to improve Sonarr's "Test" indexer behavior where Sonarr sends a
# 0-query category-only search to verify indexer connectivity.
PACHELARR_TEST_FALLBACK_QUERY = os.getenv("PACHELARR_TEST_FALLBACK_QUERY", "")
# TMDB API key for looking up movie/TV titles from IMDb/TVDB/TMDB IDs
# Get a free key at: https://www.themoviedb.org/settings/api
# This is REQUIRED for ID-based searches to work with indexers that don't support IDs
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

async def lookup_title_from_id(session, imdbid=None, tmdbid=None, tvdbid=None, rid=None, search_type='movie'):
    """Look up movie/TV title from external IDs using TMDB API.
    
    TMDB supports:
    - IMDb IDs (movies and TV shows)
    - TVDB IDs (TV shows)
    - TVRage IDs (TV shows, deprecated)
    - Direct TMDB IDs (movies and TV shows)
    
    Requires TMDB_API_KEY environment variable.
    Get a free API key at: https://www.themoviedb.org/settings/api
    """
    if not TMDB_API_KEY:
        logger.debug("TMDB_API_KEY not configured, skipping title lookup. Set TMDB_API_KEY env var to enable ID-based search support.")
        return None
    
    try:
        # Try IMDb ID lookup (works for both movies and TV)
        if imdbid:
            url = f"https://api.themoviedb.org/3/find/tt{imdbid}?api_key={TMDB_API_KEY}&external_source=imdb_id"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                if response.status == 200:
                    data = await response.json()
                    # Check movie results first
                    if data.get('movie_results') and len(data['movie_results']) > 0:
                        movie = data['movie_results'][0]
                        title = movie.get('title', '')
                        release_date = movie.get('release_date', '')
                        year = release_date.split('-')[0] if release_date else ''
                        if title and year:
                            logger.info(f"Successfully looked up movie via TMDB (IMDb): {title} ({year})")
                            return f"{title} {year}"
                        elif title:
                            logger.info(f"Successfully looked up movie via TMDB (IMDb): {title}")
                            return title
                    # Check TV results
                    if data.get('tv_results') and len(data['tv_results']) > 0:
                        show = data['tv_results'][0]
                        title = show.get('name', '')
                        first_air = show.get('first_air_date', '')
                        year = first_air.split('-')[0] if first_air else ''
                        if title and year:
                            logger.info(f"Successfully looked up TV show via TMDB (IMDb): {title} ({year})")
                            return f"{title} {year}"
                        elif title:
                            logger.info(f"Successfully looked up TV show via TMDB (IMDb): {title}")
                            return title
        
        # Try TVDB ID lookup (TV shows only)
        if tvdbid:
            url = f"https://api.themoviedb.org/3/find/{tvdbid}?api_key={TMDB_API_KEY}&external_source=tvdb_id"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('tv_results') and len(data['tv_results']) > 0:
                        show = data['tv_results'][0]
                        title = show.get('name', '')
                        first_air = show.get('first_air_date', '')
                        year = first_air.split('-')[0] if first_air else ''
                        if title and year:
                            logger.info(f"Successfully looked up TV show via TMDB (TVDB): {title} ({year})")
                            return f"{title} {year}"
                        elif title:
                            logger.info(f"Successfully looked up TV show via TMDB (TVDB): {title}")
                            return title
        
        # Try TVRage ID lookup (deprecated but still supported by TMDB)
        if rid:
            url = f"https://api.themoviedb.org/3/find/{rid}?api_key={TMDB_API_KEY}&external_source=tvrage_id"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('tv_results') and len(data['tv_results']) > 0:
                        show = data['tv_results'][0]
                        title = show.get('name', '')
                        first_air = show.get('first_air_date', '')
                        year = first_air.split('-')[0] if first_air else ''
                        if title and year:
                            logger.info(f"Successfully looked up TV show via TMDB (TVRage): {title} ({year})")
                            return f"{title} {year}"
                        elif title:
                            logger.info(f"Successfully looked up TV show via TMDB (TVRage): {title}")
                            return title
        
        # Direct TMDB ID lookup
        if tmdbid:
            # Determine if it's a movie or TV show based on search type
            if search_type in ('movie', 'search'):
                url = f"https://api.themoviedb.org/3/movie/{tmdbid}?api_key={TMDB_API_KEY}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                    if response.status == 200:
                        data = await response.json()
                        title = data.get('title', '')
                        release_date = data.get('release_date', '')
                        year = release_date.split('-')[0] if release_date else ''
                        if title and year:
                            logger.info(f"Successfully looked up movie via TMDB (TMDB ID): {title} ({year})")
                            return f"{title} {year}"
                        elif title:
                            logger.info(f"Successfully looked up movie via TMDB (TMDB ID): {title}")
                            return title
            else:
                # Try as TV show
                url = f"https://api.themoviedb.org/3/tv/{tmdbid}?api_key={TMDB_API_KEY}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                    if response.status == 200:
                        data = await response.json()
                        title = data.get('name', '')
                        first_air = data.get('first_air_date', '')
                        year = first_air.split('-')[0] if first_air else ''
                        if title and year:
                            logger.info(f"Successfully looked up TV show via TMDB (TMDB ID): {title} ({year})")
                            return f"{title} {year}"
                        elif title:
                            logger.info(f"Successfully looked up TV show via TMDB (TMDB ID): {title}")
                            return title
        
        logger.debug(f"Could not lookup title for imdbid={imdbid} tmdbid={tmdbid} tvdbid={tvdbid} rid={rid}")
        return None
    except Exception as e:
        logger.warning(f"Error looking up title from ID: {e}")
        return None

async def get_all_prowlarr_indexers(session):
    """Fetches all enabled indexer IDs from Prowlarr."""
    try:
        url = urljoin(PROWLARR_URL, "/api/v1/indexer")
        headers = {"X-Api-Key": PROWLARR_API_KEY}
        # Mask the API key for safe debug logging
        def _mask_key(k):
            if not k:
                return None
            if len(k) <= 8:
                return "****"
            return k[:4] + "*" * (len(k) - 8) + k[-4:]
        logger.debug(
            f"Prowlarr indexers request: GET {url} headers={{'X-Api-Key': '{_mask_key(PROWLARR_API_KEY)}'}}"
        )
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            raw = await response.json()
            # Prowlarr can return lists or dicts; normalize to list
            indexers = []
            if isinstance(raw, list):
                indexers = raw
            elif isinstance(raw, dict):
                # Common variations
                for key in ('records', 'results', 'indexers', 'items', 'data'):
                    if key in raw and isinstance(raw[key], list):
                        indexers = raw[key]
                        break
                # Fall back to top-level list-like content
                if not indexers:
                    # If keys are numeric or it's a single indexer dict, try aggregating
                    if all(isinstance(v, dict) for v in raw.values()):
                        indexers = [v for v in raw.values()]
                    else:
                        # If it's a single indexer returned as dict
                        indexers = [raw]

        ids = []
        for idx in indexers:
            # ID field may be 'id' or 'indexerId'.
            idx_id = idx.get('id') or idx.get('indexerId') or idx.get('IndexerId')
            # Check for enabled flags in possible names
            enabled = True
            for key in ('enabled', 'isEnabled', 'enabledByDefault', 'disabled'):
                if key in idx:
                    val = idx.get(key)
                    # Disabled may be a boolean but reversed (disabled True means disabled)
                    if key == 'disabled':
                        enabled = not bool(val)
                    else:
                        enabled = bool(val)
                    break
            if idx_id and enabled:
                ids.append(idx_id)
        logger.info(f'Prowlarr: found {len(ids)} enabled indexers: {ids}')
        return ids
    except aiohttp.ClientError as e:
        logger.exception("Error fetching Prowlarr indexers")
        return []


def dedupe_hashes_preserve_order(hashes):
    """Return list of unique hashes in the original order, normalized to lowercase.

    This ensures we don't make redundant calls to Torbox while keeping
    a stable ordering of values (useful for predictable chunking).
    """
    seen = set()
    out = []
    for h in (hashes or []):
        if not h:
            continue
        hl = h.lower()
        if hl not in seen:
            seen.add(hl)
            out.append(hl)
    return out

@app.get("/api")
async def torznab_proxy(request: Request):
    """Handles Torznab requests from Sonarr/Radarr."""
    params = request.query_params
    logger.info(f"Incoming request: {dict(params)} from {request.client}")

    if params.get('t') == 'caps':
        return Response(content=get_caps_xml(), media_type="application/xml")

    if params.get('t') in ['search', 'tvsearch', 'movie']:
        try:
            return await handle_search(params)
        except Exception:
            logger.exception("Unhandled error in search handler")
            return Response(status_code=500, content="Internal Server Error")
    
    return Response(status_code=400, content="Invalid request type")

async def handle_search(params):
    """Performs search, checks cache, and returns enriched results."""
    query = params.get('q', '')
    # Check if there are any valid identifier parameters (these are valid searches without q)
    has_identifier = any(params.get(k) for k in ('rid', 'tvdbid', 'imdbid', 'tmdbid', 'tvmaze', 'traktid', 'doubanid'))
    # If query is missing but categories/indexerIds are present and a fallback is configured,
    # substitute it early so downstream logic picks it up. Don't apply fallback if identifiers are present.
    if not query and not has_identifier and (params.get('cat') or params.get('indexerIds') or params.get('indexerId')) and PACHELARR_TEST_FALLBACK_QUERY:
        logger.info(f"Incoming category-only request detected; applying fallback query '{PACHELARR_TEST_FALLBACK_QUERY}'")
        query = PACHELARR_TEST_FALLBACK_QUERY
    categories = [cat for cat in params.get('cat', '').split(',') if cat]

    async with aiohttp.ClientSession() as session:
        # We used to fetch all indexer ids and pass them to the search endpoint.
        # Prowlarr searches all enabled indexers by default when `indexerIds` is omitted.
        # To avoid unnecessarily large URLs and to comply with the Prowlarr API behavior,
        # only pass indexer IDs if the caller explicitly requested them via query params
        # (e.g., Sonarr/Radarr can send indexerIds to restrict the search).
        indexer_ids = None

        # Build search parameters for Prowlarr; include tvdbid, season, ep, rid, imdbid when present
        search_kwargs = {
            'query': query,
            'categories': categories,
            'type': params.get('t', 'search')
        }
        logger.info(f"Initial search_kwargs: {search_kwargs}")
        # Pull in optional identifiers from parameters
        for key in ('rid', 'tvdbid', 'season', 'ep', 'imdbid', 'tmdbid', 'tvmaze', 'traktid', 'doubanid'):
            if params.get(key):
                search_kwargs[key] = params.get(key)
        
        # If we have an ID but no query text, try to look up the title
        # This helps Prowlarr work with indexers that don't support ID-based searches
        if not query and has_identifier:
            logger.info(f"Attempting title lookup for ID-based search: imdbid={params.get('imdbid')} tmdbid={params.get('tmdbid')} tvdbid={params.get('tvdbid')} rid={params.get('rid')}")
            title = await lookup_title_from_id(
                session,
                imdbid=params.get('imdbid'),
                tmdbid=params.get('tmdbid'),
                tvdbid=params.get('tvdbid'),
                rid=params.get('rid'),
                search_type=params.get('t', 'search')
            )
            if title:
                logger.info(f"Looked up title '{title}' from ID parameters")
                query = title
                search_kwargs['query'] = title
            else:
                logger.info("Title lookup failed or returned no results")
        
        # Include offset/limit to forward client paging requests to Prowlarr
        if params.get('offset'):
            search_kwargs['offset'] = params.get('offset')
        if params.get('limit'):
            search_kwargs['limit'] = params.get('limit')
        # If caller included indexerIds (or indexerId), honor it and pass it through
        if params.get('indexerIds'):
            search_kwargs['indexerIds'] = params.get('indexerIds').split(',')
        elif params.get('indexerId'):
            search_kwargs['indexerIds'] = [params.get('indexerId')]

        # If we don't have a query nor identifier, avoid calling Prowlarr which can return 400
        # However, Sonarr often performs a 'test' search only with categories (no query string).
        # Allow category-only or indexerIds-only searches to be forwarded to Prowlarr so tools like
        # Sonarr can test the indexer and receive results (or an explicit empty result set from
        # Prowlarr). Additionally, if an optional fallback query is configured via
        # `PACHELARR_TEST_FALLBACK_QUERY`, use it for category-only requests so Sonarr's test
        # returns sample results.
        if not query and not (search_kwargs.get('categories') or search_kwargs.get('indexerIds')) and not has_identifier:
            logger.info('No query nor identifier nor categories/indexerIds present for search; returning empty feed to avoid Prowlarr 400')
            return Response(content=create_empty_rss(), media_type="application/xml")
        # If we don't have a query but categories or indexerIds were provided,
        # this is likely a category-only call (Sonarr test). If a fallback is
        # configured, substitute it as the query and log the behavior.
        # Don't apply fallback if we have identifiers (imdbid, tvdbid, etc.)
        if not query and not has_identifier and ((params.get('cat') or search_kwargs.get('categories')) or (params.get('indexerIds') or search_kwargs.get('indexerId'))) and PACHELARR_TEST_FALLBACK_QUERY:
            logger.info(f"Category-only search detected via raw params; substituting fallback query '{PACHELARR_TEST_FALLBACK_QUERY}' for test behavior")
            # Replace the query on the parameters we will pass to Prowlarr
            search_kwargs['query'] = PACHELARR_TEST_FALLBACK_QUERY
            query = PACHELARR_TEST_FALLBACK_QUERY
        # Debugging: log fallback / query state for incoming search verification
        logger.info(f"Search debug: query={query!r} categories={search_kwargs.get('categories')!r} indexerIds={search_kwargs.get('indexerIds')!r} fallback={PACHELARR_TEST_FALLBACK_QUERY!r}")
        logger.debug(f"search_kwargs full: {search_kwargs}")

        prowlarr_results = await search_prowlarr(session, search_kwargs)
        if not prowlarr_results:
            return Response(content=create_empty_rss(), media_type="application/xml")
        
        info_hashes = extract_info_hashes(prowlarr_results)
        if not info_hashes:
             return Response(content=generate_torznab_xml(prowlarr_results, {}), media_type="application/xml")

        cached_status = await check_torbox_cache(session, info_hashes)
        
        # Consolidate duplicates for all items (cached & uncached) and optionally scrape trackers
        consolidated_results = consolidate_all_items(prowlarr_results, cached_status)
        # Log consolidation counts for debug/verification
        try:
            total_items = len(prowlarr_results)
            consolidated_count = len(consolidated_results)
            dup_removed = total_items - consolidated_count
            if dup_removed:
                logger.debug(f"Consolidated results: total_items={total_items} consolidated_count={consolidated_count} dedupe_removed={dup_removed}")
        except Exception:
            pass
        uncached_seeders = {}
        if TRACKER_SCRAPE_ENABLED:
            # Build tracker->hash list mapping
            tracker_map = {}
            for item in consolidated_results:
                # only uncached
                info_hash = item.get('infoHash')
                ih = info_hash.lower() if info_hash else None
                if not info_hash:
                    # attempt magnet parse from magnetUri, guid or enclosure
                    try:
                        mag = _get_magnet_uri_for_item(item)
                        if not mag:
                            continue
                        parsed_magnet = parse_qs(unquote(mag.split('?')[1]))
                        if 'xt' in parsed_magnet:
                            info_hash = parsed_magnet['xt'][0].split(':')[-1]
                            ih = info_hash.lower() if info_hash else None
                    except Exception:
                        continue
                if not info_hash or cached_status.get(info_hash.lower()):
                    continue
                # parse trackers
                mag = _get_magnet_uri_for_item(item)
                for tr in parse_trackers_from_magnet(mag):
                    tracker_map.setdefault(tr, []).append(info_hash.lower())
            if tracker_map:
                uncached_seeders = await scrape_trackers_inverted(tracker_map)
        xml_response = generate_torznab_xml(consolidated_results, cached_status, uncached_seeders)
        return Response(content=xml_response, media_type="application/xml")

async def search_prowlarr(session, search_kwargs):
    """Searches Prowlarr for the given query."""
    try:
        url = urljoin(PROWLARR_URL, "/api/v1/search")
        headers = {"X-Api-Key": PROWLARR_API_KEY}
        # helper to mask API keys
        def _mask_key(k):
            if not k:
                return None
            if len(k) <= 8:
                return "****"
            return k[:4] + "*" * (len(k) - 8) + k[-4:]
        params = {}
        # map our search kwargs to Prowlarr params
        if 'query' in search_kwargs and search_kwargs['query']:
            params['query'] = search_kwargs['query']
        if 'categories' in search_kwargs and search_kwargs['categories']:
            # Pass categories as a repeated query param (list) to Prowlarr to avoid validation errors
            # e.g., categories=5030&categories=5040
            params['categories'] = list(search_kwargs['categories'])
        if 'indexerIds' in search_kwargs and search_kwargs['indexerIds']:
            idxs = list(search_kwargs['indexerIds'])
            # If there are many indexers, don't pass the indexerIds param (Prowlarr will search all enabled)
            if len(idxs) <= 20:
                params['indexerIds'] = ','.join(map(str, idxs))
            else:
                logger.debug(f"Skipping indexerIds param for Prowlarr search (total {len(idxs)}) to avoid URL/size issues")
        if 'type' in search_kwargs:
            params['type'] = search_kwargs['type']
        # Include all supported identifier parameters from Torznab spec
        for k in ('rid', 'tvdbid', 'season', 'ep', 'imdbid', 'tmdbid', 'tvmaze', 'traktid', 'doubanid'):
            if k in search_kwargs and search_kwargs[k]:
                params[k] = search_kwargs[k]
        # Check if we have any identifiers in the params we're sending to Prowlarr
        has_identifier = any(params.get(k) for k in ('rid', 'tvdbid', 'imdbid', 'tmdbid', 'tvmaze', 'traktid', 'doubanid'))
        # If outgoing params don't include a query but categories/indexerIds are present
        # then this is likely a category-only call from a client like Sonarr. If the
        # caller enabled a fallback query via env var, use it to avoid a 400 from
        # Prowlarr and provide Sonarr with a testable response.
        # Don't apply fallback if we have identifiers (they're valid searches on their own)
        if not params.get('query') and not has_identifier and (params.get('categories') or params.get('indexerIds')) and PACHELARR_TEST_FALLBACK_QUERY:
            logger.info(f"Prowlarr request missing query; adding fallback query '{PACHELARR_TEST_FALLBACK_QUERY}'")
            params['query'] = PACHELARR_TEST_FALLBACK_QUERY
        # Pass paging params to Prowlarr when present (limit/offset)
        if 'limit' in search_kwargs and search_kwargs['limit']:
            try:
                # Only forward a numeric limit > 0; some clients send limit=0 for tests
                if int(search_kwargs['limit']) > 0:
                    params['limit'] = str(int(search_kwargs['limit']))
            except Exception:
                # if non-numeric, forward as-is (Prowlarr will validate)
                params['limit'] = search_kwargs['limit']
        if 'offset' in search_kwargs and search_kwargs['offset']:
            params['offset'] = search_kwargs['offset']
        logger.debug(
            f"Prowlarr search request: GET {url} params={params} headers={{'X-Api-Key':'{_mask_key(PROWLARR_API_KEY)}'}}"
        )
        async with session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            # Normalize returned search results to a list of items
            if isinstance(data, list):
                logger.debug(f"Prowlarr returned {len(data)} items (list)")
                return data
            if isinstance(data, dict):
                for key in ('records', 'results', 'items', 'data'):
                    if key in data and isinstance(data[key], list):
                        logger.debug(f"Prowlarr returned {len(data[key])} items (key={key})")
                        return data[key]
                # If results are under 'result' and it's an object with items
                if 'result' in data and isinstance(data['result'], list):
                    logger.debug(f"Prowlarr returned {len(data['result'])} items (result)")
                    return data['result']
            # If unknown structure, return empty list and log
            print('Unknown Prowlarr search response structure:', type(data), data)
            return []
    except aiohttp.ClientError as e:
        logger.exception(f"Error searching Prowlarr: {e}")
        return []

def extract_info_hashes(prowlarr_results):
    """Extracts info hashes from Prowlarr search results."""
    hashes = []
    raw_hashes = []
    for item in prowlarr_results:
        # Normalize infohashes to lowercase for consistent mapping
        if item.get('infoHash'):
            raw_hashes.append(item['infoHash'])
        else:
            mag = _get_magnet_uri_for_item(item)
            if mag:
                try:
                    # Attempt to parse from magnet link
                    parsed_magnet = parse_qs(unquote(mag.split('?')[1]))
                    if 'xt' in parsed_magnet:
                        hash_val = parsed_magnet['xt'][0].split(':')[-1]
                        raw_hashes.append(hash_val)
                except (IndexError, KeyError) as e:
                    print(f"Could not parse infohash from magnet link: {mag}, error: {e}")

    # Preserve ordering but dedupe and normalize when returning
    return dedupe_hashes_preserve_order(raw_hashes)


def parse_trackers_from_magnet(magnet_uri):
    """Extract tracker URLs from a magnet URI (tr= parameters)."""
    if not magnet_uri:
        return []
    try:
        query = magnet_uri.split('?')[1]
    except Exception:
        return []
    # split by & and look for tr= entries
    trackers = []
    for part in query.split('&'):
        if part.startswith('tr='):
            val = part.split('=', 1)[1]
            trackers.append(unquote(val))
    # normalize and dedupe while preserving order
    out = []
    seen = set()
    for t in trackers:
        t_str = t.strip()
        if not t_str:
            continue
        if t_str not in seen:
            out.append(t_str)
            seen.add(t_str)
    return out


def _get_magnet_uri_for_item(item):
    """Return a magnet URI string from item, trying 'magnetUri' then 'guid'.

    This ensures we parse trackers even when Prowlarr returns magnet in 'guid'.
    """
    if not item:
        return None
    if item.get('magnetUri'):
        return item.get('magnetUri')
    g = item.get('guid')
    if isinstance(g, str) and 'magnet:?' in g:
        return g
    # `enclosure` may be a dict with 'url' or a string; handle both
    enc = item.get('enclosure')
    if isinstance(enc, dict) and isinstance(enc.get('url'), str) and 'magnet:?' in enc.get('url'):
        return enc.get('url')
    if isinstance(enc, str) and 'magnet:?' in enc:
        return enc
    return None


def consolidate_uncached_items(prowlarr_results, cached_status):
    """Consolidate duplicate uncached items per infohash, merge trackers.

    Returns: consolidated list of items (one per unique infohash) where uncached
    items have merged 'magnetUri' containing combined trackers and other metadata
    taken from the first item.
    """
    # Group items by infohash (lowercased)
    groups = {}
    for item in prowlarr_results:
        info = item.get('infoHash')
        if not info:
            mag = _get_magnet_uri_for_item(item)
            if mag:
                try:
                    parsed_magnet = parse_qs(unquote(mag.split('?')[1]))
                    if 'xt' in parsed_magnet:
                        info = parsed_magnet['xt'][0].split(':')[-1]
                except Exception:
                    info = None
        if info:
            try:
                info = info.strip()
            except Exception:
                pass

        if not info:
            # keep them in a bucket keyed by None to preserve them
            key = None
        else:
            key = info.lower()
        groups.setdefault(key, []).append(item)

    consolidated = []
    for key, items in groups.items():
        if key and cached_status.get(key):
            # keep cached items as they are (we don't dedupe cached ones)
            consolidated.extend(items)
            continue
        # For uncached or None (non-hash) group, consolidate
        first = items[0]
        if key:
            # merge trackers from magnetUri across all items
            trackers = []
            tracker_seen = set()
            for it in items:
                mag = _get_magnet_uri_for_item(it)
                for t in parse_trackers_from_magnet(mag):
                    if t not in tracker_seen:
                        trackers.append(t)
                        tracker_seen.add(t)
            # Rebuild magnetUri with the combined trackers
            magnet_base = None
            # Try to use canonical magnet from 'magnetUri' or 'guid'
            base_mag = _get_magnet_uri_for_item(first)
            if base_mag and 'magnet:?' in base_mag:
                try:
                    parsed = parse_qs(unquote(base_mag.split('?', 1)[1]))
                    if 'xt' in parsed:
                        magnet_base = f"magnet:?xt={parsed['xt'][0]}"
                except Exception:
                    magnet_base = None
            # Ensure magnetUri is set even if the first item had no existing magnet
            if not magnet_base:
                magnet_base = f"magnet:?xt=urn:btih:{key}"
            tr_parts = '&'.join('tr=' + t for t in trackers)
            # If the base already contains a query ('?'), append trackers with '&', otherwise use '?'
            if tr_parts:
                connector = '&' if '?' in magnet_base else '?'
                first['magnetUri'] = f"{magnet_base}{connector}{tr_parts}"
            else:
                first['magnetUri'] = magnet_base
            # Ensure GUID always reflects the constructed magnetUri
            first['guid'] = first.get('magnetUri')
        consolidated.append(first)
    return consolidated


def consolidate_all_items(prowlarr_results, cached_status, uncached_seeders=None):
    """Consolidate all duplicate items (cached or uncached) to one per unique infohash.

    - Merge trackers for the hash from all magnet URIs
    - Choose a canonical item (highest original seeders) for metadata
    - For cached items apply PACHELARR_SEEDERS_BOOST; for uncached use uncached_seeders mapping
    - Returns a list of consolidated items
    """
    from copy import deepcopy
    groups = {}
    non_hash_items = []
    for item in prowlarr_results:
        info = item.get('infoHash')
        if not info:
            mag = _get_magnet_uri_for_item(item)
            if mag:
                try:
                    parsed_magnet = parse_qs(unquote(mag.split('?')[1]))
                    if 'xt' in parsed_magnet:
                        info = parsed_magnet['xt'][0].split(':')[-1]
                except Exception:
                    info = None
        if not info:
            non_hash_items.append(item)
            continue
        key = info.lower() if info else None
        groups.setdefault(key, []).append(item)

    consolidated = []
    for key, items in groups.items():
        # choose the item with highest original seeders as canonical
        def parse_seeders(it):
            try:
                return int(it.get('seeders', 0) or 0)
            except Exception:
                return 0
        items_sorted = sorted(items, key=parse_seeders, reverse=True)
        canonical = deepcopy(items_sorted[0])
        # merge trackers from all items
        trackers = []
        seen = set()
        for it in items:
            for tr in parse_trackers_from_magnet(_get_magnet_uri_for_item(it)):
                if tr not in seen:
                    seen.add(tr)
                    trackers.append(tr)
        # compute base magnet from canonical's 'magnetUri' or 'guid'
        base_mag = _get_magnet_uri_for_item(canonical)
        # Ensure base retains xt=urn:btih:<hash> so trackers can be appended properly.
        base = None
        if base_mag and 'magnet:?' in base_mag:
            try:
                parsed = parse_qs(unquote(base_mag.split('?', 1)[1]))
                if 'xt' in parsed:
                    base = f"magnet:?xt={parsed['xt'][0]}"
            except Exception:
                base = None
        if not base:
            # create a base magnet if none present (ensures canonical magnetUri includes xt)
            base = f"magnet:?xt=urn:btih:{key}"
        tr_parts = '&'.join('tr=' + t for t in trackers)
        if tr_parts:
            connector = '&' if '?' in base else '?'
            canonical['magnetUri'] = f"{base}{connector}{tr_parts}"
        else:
            canonical['magnetUri'] = base
        # Ensure canonical GUID always reflects the constructed canonical magnet URI
        canonical['guid'] = canonical.get('magnetUri')
        # set seeders based on cached_status or uncached_seeders
        if key in (cached_status or {}):
            # cached -> apply boost
            try:
                s = int(canonical.get('seeders', 0) or 0)
            except Exception:
                s = 0
            canonical['seeders'] = max(s, PACHELARR_SEEDERS_BOOST)
        else:
            # uncached -> use uncached_seeders if present
            if uncached_seeders and key in uncached_seeders:
                canonical['seeders'] = max(int(canonical.get('seeders', 0) or 0), int(uncached_seeders.get(key) or 0))
        logger.debug(f'Consolidated canonical infohash={key} trackers={len(trackers)} magnet={canonical.get("magnetUri")}')
        consolidated.append(canonical)

    # include non-hash items unchanged
    consolidated.extend(non_hash_items)
    return consolidated


def _parse_tracker_host_port(tracker_url):
    """Return (host, port) for a tracker URL. Only supports udp:// and returns default ports if missing."""
    try:
        from urllib.parse import urlparse
        p = urlparse(tracker_url)
        scheme = p.scheme
        hostname = p.hostname
        port = p.port
        if not hostname:
            return None
        if not port:
            if scheme == 'udp':
                port = 80
            else:
                port = 80
        return hostname, port
    except Exception:
        return None


async def _udp_scrape_one(host, port, hashes, timeout=5.0):
    """Execute a UDP scrape to the given host:port for the list of hashes.

    Returns mapping {hash_hex: seeders}
    """
    import random
    import struct
    loop = asyncio.get_event_loop()
    try:
        logger.debug(f"_udp_scrape_one: host={host} port={port} hashes={len(hashes)} timeout={timeout}")
        # Connect: action 0
        # create socket.
        reader = None
        fut = loop.create_future()

        class Proto(asyncio.DatagramProtocol):
            def __init__(self, fut):
                self.fut = fut
                self.transport = None
            def connection_made(self, transport):
                self.transport = transport
            def datagram_received(self, data, addr):
                if not self.fut.done():
                    self.fut.set_result(data)
            def error_received(self, exc):
                if not self.fut.done():
                    self.fut.set_exception(exc)
            def connection_lost(self, exc):
                pass

        transport, proto = await loop.create_datagram_endpoint(lambda: Proto(fut), remote_addr=(host, port))
        try:
            # Send connect
            trans_id = random.randrange(0, 1 << 31)
            conn_req = struct.pack('!QLL', 0x41727101980, 0, trans_id)[:-4]
            # struct here must be 16 bytes: 64-bit connection_id (magic), 32-bit action, 32-bit transaction
            conn_req = struct.pack('!QII', 0x41727101980, 0, trans_id)
            transport.sendto(conn_req)
            try:
                data = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                return {}
            if len(data) < 16:
                return {}
            action, trans, conn_id = struct.unpack('!IIQ', data[:16])
            if action != 0 or trans != trans_id:
                return {}
            # Now send scrape
            # build request: conn_id (8), action (4=2), transaction (4), followed by hashes
            # hashes as 20-byte binary values
            trans_id2 = random.randrange(0, 1 << 31)
            payload = struct.pack('!QII', conn_id, 2, trans_id2)
            for h in hashes:
                try:
                    payload += bytes.fromhex(h)
                except Exception:
                    # invalid hash length
                    continue
            # clear future and re-use
            fut = loop.create_future()
            proto.fut = fut
            transport.sendto(payload)
            try:
                data = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                return {}
            # response: action (4), trans(4), then for each hash: 3x4 bytes (seeders, leechers, downloads)
            if len(data) < 8:
                return {}
            action, trans = struct.unpack('!II', data[:8])
            if action != 2:
                return {}
            data_body = data[8:]
            out = {}
            # each record is 12 bytes
            for i in range(0, len(data_body), 12):
                rec = data_body[i:i+12]
                if len(rec) < 12:
                    break
                seeders, leechers, downloads = struct.unpack('!III', rec)
                # map positionally to requested hashes
                idx = i // 12
                if idx < len(hashes):
                    out[hashes[idx]] = seeders
            logger.debug(f"_udp_scrape_one: host={host} port={port} result.count={len(out)}")
            return out
        finally:
            transport.close()
    except Exception:
        return {}


async def scrape_trackers_inverted(tracker_to_hashes):
    """Given mapping tracker_url -> list of infohash hex strings, perform inverted scraping and
    return mapping infohash -> max_seeders across trackers.
    """
    # Only implement UDP scrape for 'udp://' trackers, ignore others for now
    sem = asyncio.Semaphore(TRACKER_SCRAPE_CONCURRENCY)
    logger.debug(f"scrape_trackers_inverted: trackers={len(tracker_to_hashes)} concurrency={TRACKER_SCRAPE_CONCURRENCY} batch_size={TRACKER_SCRAPE_BATCH_SIZE} timeout={TRACKER_SCRAPE_TIMEOUT}")
    results_per_hash = {}

    async def _process_tracker(url, hashes):
        hostport = _parse_tracker_host_port(url)
        if not hostport:
            return
        host, port = hostport
        # chunk hashes per TRACKER_SCRAPE_BATCH_SIZE
        for i in range(0, len(hashes), TRACKER_SCRAPE_BATCH_SIZE):
            chunk = hashes[i:i+TRACKER_SCRAPE_BATCH_SIZE]
            async with sem:
                if not url.lower().startswith('udp://'):
                    # skip non-udp in this iteration
                    continue
                try:
                    res = await _udp_scrape_one(host, port, chunk, TRACKER_SCRAPE_TIMEOUT)
                except Exception:
                    res = {}
                for h, s in res.items():
                    cur = results_per_hash.get(h, 0)
                    if s > cur:
                        results_per_hash[h] = s

    tasks = [asyncio.create_task(_process_tracker(url, hashes)) for url, hashes in tracker_to_hashes.items()]
    if tasks:
        await asyncio.gather(*tasks)
    return results_per_hash


async def check_torbox_cache(session, hashes):
    """Checks Torbox cache for a list of info hashes."""
    try:
        headers = {
            "Content-Type": "application/json",
            # Torbox expects Bearer token authentication
            "Authorization": f"Bearer {TORBOX_API_KEY}"
        }
        # Mask Torbox API key for debug logging
        def _mask_key(k):
            if not k:
                return None
            if len(k) <= 8:
                return "****"
            return k[:4] + "*" * (len(k) - 8) + k[-4:]
        # if no hashes, skip the call
        if not hashes:
            return {}

        total_hashes = len(hashes)
        # dedupe hashes (case-insensitively) while preserving ordering
        unique_hashes = dedupe_hashes_preserve_order(hashes)
        dedupe_removed_count = total_hashes - len(unique_hashes)
        if dedupe_removed_count:
            logger.debug(f"Torbox cache check: dedupe_removed={dedupe_removed_count}")
        logger.debug(
            f"Torbox cache check: POST {TORBOX_CHECK_URL} total.hashes={total_hashes} unique.hashes={len(unique_hashes)} dedupe_removed={dedupe_removed_count} Authorization=Bearer {_mask_key(TORBOX_API_KEY)}"
        )

        # Helper to combine and normalize results to lowercase keys
        combined = {}
        total_hits = 0

        async def _call_chunk(chunk):
            """Call Torbox for given chunk, return mapping or raise.
            Handles 401 specially by returning None to indicate bail-out.
            """
            attempt = 1
            backoff = TORBOX_RETRY_BACKOFF
            while attempt <= TORBOX_MAX_RETRIES:
                try:
                    async with session.post(TORBOX_CHECK_URL, json={'hashes': chunk}, headers=headers) as response:
                        if response.status == 401:
                            logger.warning("Torbox returned 401 Unauthorized. Check TORBOX_API_KEY. Aborting cache checks.")
                            return None
                        if response.status >= 500:
                            logger.warning(f"Torbox server error (status {response.status}); attempt {attempt}/{TORBOX_MAX_RETRIES}")
                            # fall through to retry logic
                        else:
                            response.raise_for_status()
                            data = await response.json()
                            return data
                except aiohttp.ClientError as e:
                    logger.warning(f"Torbox request error: {e}; attempt {attempt}/{TORBOX_MAX_RETRIES}")
                # If not returned, sleep then retry
                await asyncio.sleep(backoff)
                backoff *= 2
                attempt += 1
            # After retries exhausted
            logger.warning("Torbox cache check failed after retries for chunk")
            return {}

        # Batch hashes and query Torbox for each chunk
        # use unique_hashes for chunking
        for i in range(0, len(unique_hashes), TORBOX_CHUNK_SIZE):
            chunk = unique_hashes[i:i+TORBOX_CHUNK_SIZE]
            logger.debug(f"Torbox cache chunk: POST {TORBOX_CHECK_URL} chunk.len={len(chunk)} Authorization=Bearer {_mask_key(TORBOX_API_KEY)}")
            try:
                result = await _call_chunk(chunk)
                if result is None:
                    # 401 or non-retriable error; abort and return empty map
                    return {}
                if isinstance(result, dict):
                    # First, try the common {'data': {...}} mapping
                    if 'data' in result:
                        data_map = result['data']
                        if isinstance(data_map, dict):
                            hits = len(data_map)
                            logger.debug(f"Torbox chunk response: hits={hits}")
                            total_hits += hits
                            for k, v in data_map.items():
                                combined[k.lower()] = v
                        elif isinstance(data_map, list):
                            hits = len(data_map)
                            logger.debug(f"Torbox chunk response list: hits={hits}")
                            total_hits += hits
                            for obj in data_map:
                                if isinstance(obj, dict) and obj.get('hash'):
                                    combined[obj['hash'].lower()] = obj
                    else:
                        # result may be directly a mapping
                        hits = len(result)
                        logger.debug(f"Torbox chunk response (mapping): hits={hits}")
                        total_hits += hits
                        for k, v in result.items():
                            combined[k.lower()] = v
                elif isinstance(result, list):
                    # Torbox may return a list of objects [{hash:..., ...}, ...]
                    hits = len(result)
                    logger.debug(f"Torbox chunk response list (top-level): hits={hits}")
                    total_hits += hits
                    for obj in result:
                        if isinstance(obj, dict) and obj.get('hash'):
                            combined[obj['hash'].lower()] = obj
                else:
                    logger.debug(f"Unexpected Torbox chunk response data type: {type(result)}")
            except Exception as e:
                logger.exception(f"Error processing Torbox chunk: {e}")
                # continue to next chunk
                continue
        logger.info(f"Torbox cache check: total cached hits={total_hits}")
        return combined
    except aiohttp.ClientError as e:
        logger.exception(f"Error checking Torbox cache: {e}")
        return {}


def generate_torznab_xml(prowlarr_results, cached_status, uncached_seeders=None):
    """Generates Torznab XML response from enriched data."""
    rss = ET.Element("rss", version="2.0", nsmap={'torznab': "http://torznab.com/schemas/2015/feed"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Torbox Cached Indexer"

    # Cache normalized statuses to lowercase keys to match extract_info_hashes
    cached_status = {k.lower(): v for k, v in (cached_status or {}).items()}

    # Consolidate uncached duplicates into single items with merged trackers
    # Full consolidation should already be performed in handle_search, but fallback here
    prowlarr_results = consolidate_all_items(prowlarr_results, cached_status, uncached_seeders)
    # Map canonical magnetUri per infoHash for diagnostic logging
    canonical_map = {}
    for it in prowlarr_results:
        info = it.get('infoHash')
        if info:
            canonical_map[info.lower()] = it.get('magnetUri') or it.get('guid') or ''
    logger.debug(f"Canonical map size: {len(canonical_map)}")
    # Track infohashes we've emitted to avoid duplicate items in the final feed
    emitted = set()

    for item in prowlarr_results:
        info_hash = item.get('infoHash')
        if not info_hash:
            mag = _get_magnet_uri_for_item(item)
            if mag:
                try:
                    parsed_magnet = parse_qs(unquote(mag.split('?')[1]))
                    if 'xt' in parsed_magnet:
                        info_hash = parsed_magnet['xt'][0].split(':')[-1]
                except (IndexError, KeyError):
                    info_hash = None


        is_cached = cached_status.get(info_hash.lower() if info_hash else None, False)

        title = item.get('title', 'Unknown')
        if info_hash:
            if info_hash.lower() in emitted:
                # Skip duplicate item for the same infohash (full dedupe)
                continue
            emitted.add(info_hash.lower())
        xml_item = ET.SubElement(channel, "item")

        if is_cached:
            title = f"[CACHED] {title}"
        ET.SubElement(xml_item, "title").text = title

        # prefer authoritative magnetUri as GUID so the GUID contains unioned trackers
        # Prefer canonical magnetUri when available so emitted GUIDs contain
        # the union of trackers for the infohash.
        guid_text = item.get('magnetUri') or item.get('guid', '')
        if info_hash:
            can = canonical_map.get(info_hash.lower())
            if can:
                guid_text = can
                # Ensure we update the item.guid so any later code sees the
                # canonical magnet as the truth
                item['guid'] = can
        # Debug log the GUID and magnetUri we are about to emit
        try:
            parsed_tr = parse_trackers_from_magnet(guid_text)
            can_mag = canonical_map.get(info_hash.lower()) if info_hash else None
            logger.debug(f"Emitting item: infohash={info_hash} is_cached={is_cached} guid_len={len(guid_text or '')} trackers_count={len(parsed_tr)} canonical_len={len(can_mag or '')} same_as_canonical={guid_text==can_mag}")
        except Exception:
            can_mag = canonical_map.get(info_hash.lower()) if info_hash else None
            logger.debug(f"Emitting item: infohash={info_hash} is_cached={is_cached} guid_len={len(guid_text or '')} trackers_count=0 canonical_len={len(can_mag or '')} same_as_canonical={guid_text==can_mag}")
        ET.SubElement(xml_item, "guid").text = guid_text
        # also ensure item.guid reflects magnetUri we used
        if item.get('magnetUri') and not item.get('guid'):
            item['guid'] = item.get('magnetUri')
        # Ensure <link> is populated with a sensible URL; prefer an http download link,
        # otherwise fall back to the GUID we will emit (canonical magnet/guid).
        link_text = item.get('link') or item.get('magnetUrl') or item.get('magnetUri') or guid_text
        logger.debug(f"Emitting link: infohash={info_hash} link_len={len(link_text or '')} link_sample={link_text[:60] if link_text else None}")
        ET.SubElement(xml_item, "link").text = link_text

        # pubDate: Sonarr requires a valid publish date for Torznab feeds
        raw_pub_date = item.get('publishDate') or item.get('pubDate') or item.get('date')
        if raw_pub_date:
            try:
                # Prowlarr typically uses ISO8601 like: 2025-05-10T16:57:09Z
                # Parse naive Z-terminated UTC timestamps
                dt = datetime.strptime(raw_pub_date, "%Y-%m-%dT%H:%M:%SZ")
                dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                try:
                    # Fall back to fromisoformat for other ISO variants
                    dt = datetime.fromisoformat(raw_pub_date)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
        # RFC 1123 format (Sonarr expects a valid pubDate)
        ET.SubElement(xml_item, "pubDate").text = dt.strftime('%a, %d %b %Y %H:%M:%S GMT')
        # For enclosure use the same link preference as above. Use magnet or download URL
        # instead of leaving it empty (Sonarr expects an enclosure URL for many torznab feeds).
        enclosure_url = item.get('link') or item.get('magnetUrl') or item.get('magnetUri') or guid_text
        logger.debug(f"Emitting enclosure: infohash={info_hash} enclosure_len={len(enclosure_url or '')} enclosure_sample={enclosure_url[:60] if enclosure_url else None}")
        ET.SubElement(xml_item, "enclosure", url=enclosure_url, type="application/x-bittorrent")

        _seeders = item.get('seeders', 0)
        try:
            seeders = int(_seeders)
        except Exception:
            seeders = 0
        if is_cached:
            # Apply configured boost but don't reduce seeders if original is higher
            seeders = max(seeders, PACHELARR_SEEDERS_BOOST)
            logger.debug(f"Boosting seeders for cached item {info_hash}: {seeders}")
        else:
            # If we have a computed uncached seed count, apply max
            if uncached_seeders and info_hash and info_hash.lower() in uncached_seeders:
                seed_from_trackers = int(uncached_seeders.get(info_hash.lower(), 0) or 0)
                seeders = max(seeders, seed_from_trackers)
                logger.debug(f"Setting seeders for uncached item {info_hash} to {seeders} from trackers")
        
        ET.SubElement(xml_item, "{http://torznab.com/schemas/2015/feed}attr", name="seeders", value=str(seeders))
        ET.SubElement(xml_item, "{http://torznab.com/schemas/2015/feed}attr", name="peers", value=str(item.get('leechers', 0)))
        if info_hash:
            ET.SubElement(xml_item, "{http://torznab.com/schemas/2015/feed}attr", name="infohash", value=info_hash)
        ET.SubElement(xml_item, "{http://torznab.com/schemas/2015/feed}attr", name="size", value=str(item.get('size', 0)))


    return ET.tostring(rss, pretty_print=True, xml_declaration=True, encoding='UTF-8')


def get_caps_xml():
    """Returns the static capabilities XML for Torznab."""
    return """
<caps>
  <searching>
    <search available="yes" supportedParams="q"/>
    <tv-search available="yes" supportedParams="q,season,ep"/>
    <movie-search available="yes" supportedParams="q,imdbid"/>
  </searching>
  <categories>
    <category id="2000" name="Movies"/>
    <category id="5000" name="TV"/>
  </categories>
</caps>
""".strip()

def create_empty_rss():
    """Creates an empty RSS feed for when there are no results."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Torbox Cached Indexer"
    return ET.tostring(rss, pretty_print=True, xml_declaration=True, encoding='UTF-8')

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PACHELARR_PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)