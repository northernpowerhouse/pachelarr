import asyncio
import aiohttp
import pytest

from main import check_torbox_cache, TORBOX_CHUNK_SIZE


class FakeCtx:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        # sometimes _data may be callable (to reflect the input chunk)
        if callable(self._data):
            return self._data()
        return self._data

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientError(f"status {self.status}")


class FakeSession:
    def __init__(self, responses):
        # responses: list of tuples (status, data or callable)
        self._responses = responses
        self._idx = 0
        self.last_payload = None
        self.last_headers = None

    def post(self, url, json, headers):
        # Return a context manager for the next response in the list.
        self.last_payload = json
        self.last_headers = headers
        resp = self._responses[self._idx]
        self._idx = min(self._idx + 1, len(self._responses) - 1)
        return FakeCtx(resp[0], resp[1] if len(resp) > 1 else {})


@pytest.mark.asyncio
async def test_check_torbox_cache_single_chunk_success():
    # Setup fake session returning a mapping for a single hash
    mapping = {"ABC123": True}
    session = FakeSession([(200, mapping)])
    out = await check_torbox_cache(session, ["ABC123"])
    assert out == {"abc123": True}
    # verify we posted a json object using 'hashes' and an Authorization header
    assert session.last_payload == {"hashes": ["abc123"]}
    assert session.last_headers and 'Authorization' in session.last_headers


@pytest.mark.asyncio
async def test_check_torbox_cache_chunking():
    # Create 350 hashes to ensure chunking into >1
    hashes = [f"HASH{i:03d}" for i in range(350)]
    # Create a response mapping function that returns mapping for each chunk
    def make_map():
        return {h.lower(): True for h in hashes}

    # The FakeSession will be called twice when chunk size is 200
    session = FakeSession([(200, make_map), (200, make_map)])
    out = await check_torbox_cache(session, hashes)
    # The combined result should have 350 entries, lowercased
    assert len(out) == 350
    for k in hashes:
        assert out.get(k.lower()) is True
    # verify at least one chunk was posted using 'hashes' and Authorization header
    assert session.last_payload and isinstance(session.last_payload, dict)
    assert 'hashes' in session.last_payload
    assert session.last_headers and 'Authorization' in session.last_headers


@pytest.mark.asyncio
async def test_check_torbox_cache_401():
    # If Torbox responds with 401, function should return empty mapping
    session = FakeSession([(401, {})])
    out = await check_torbox_cache(session, ["ABC123"])
    assert out == {}


@pytest.mark.asyncio
async def test_check_torbox_cache_list_data_response():
    # Torbox returns {'data': [{...}, ...]}
    def data_fn():
        return {"data": [{"hash": "ABC123", "name": "file1"}]}
    session = FakeSession([(200, data_fn)])
    out = await check_torbox_cache(session, ["ABC123"]) 
    assert out == {"abc123": {"hash": "ABC123", "name": "file1"}}


@pytest.mark.asyncio
async def test_check_torbox_cache_direct_list_response():
    # Torbox returns a list directly
    data = [{"hash": "ABC123", "name": "file1"}]
    session = FakeSession([(200, data)])
    out = await check_torbox_cache(session, ["ABC123"]) 
    assert out == {"abc123": {"hash": "ABC123", "name": "file1"}}


@pytest.mark.asyncio
async def test_check_torbox_cache_deduplication_order():
    # ensure duplicates are removed (case-insensitively) and ordering preserved
    responses = [(200, {"data": {"abc123": True}})]
    session = FakeSession(responses)
    # include duplicates with different case
    input_hashes = ["ABC123", "abc123", "AbC123"]
    out = await check_torbox_cache(session, input_hashes)
    # ensure only one hash posted and normalized to lower-case
    assert session.last_payload == {"hashes": ["abc123"]}
    assert out == {"abc123": True}


def test_extract_info_hashes_order():
    # Create a fake prowlarr result with mixed-case infoHash and duplicates
    from main import extract_info_hashes
    sample = [
        {'infoHash': 'AAABBBccc111'},
        {'infoHash': 'aaabbbCCC111'},
        {'infoHash': 'zzzyyyxxx999'},
        {'infoHash': 'ZZZyyyXXX999'},
    ]
    out = extract_info_hashes(sample)
    # Ensure order is preserved and duplicates removed (lowercased)
    assert out == ['aaabbbccc111', 'zzzyyyxxx999']


def test_consolidate_uncached_items_merges_trackers():
    from main import consolidate_uncached_items
    # Two items with same hash, different trackers
    sample = [
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://tracker1/announce'
        },
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://tracker2/announce'
        }
    ]
    # No cached status
    cs = {}
    out = consolidate_uncached_items(sample, cs)
    # Expect single consolidated item
    assert len(out) == 1
    merged = out[0]
    assert 'magnetUri' in merged
    assert 'tr=http://tracker1/announce' in merged['magnetUri']
    assert 'tr=http://tracker2/announce' in merged['magnetUri']


def test_consolidate_all_items_dedupe_and_merge_cached():
    from main import consolidate_all_items
    # Two items with same hash, different trackers and seeders, mark as cached
    sample = [
        {'infoHash': 'ABC123', 'title': 'A', 'seeders': 1, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://tracker1/announce'},
        {'infoHash': 'ABC123', 'title': 'B', 'seeders': 10, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://tracker2/announce'}
    ]
    cached_status = {'abc123': True}
    out = consolidate_all_items(sample, cached_status)
    # Expect single item
    assert len(out) == 1
    m = out[0]
    # cached -> seeders should be boosted to at least CACHEBOX_SEEDERS_BOOST
    assert int(m['seeders']) >= 10000
    # trackers merged
    assert 'tr=http://tracker1/announce' in m['magnetUri']
    assert 'tr=http://tracker2/announce' in m['magnetUri']


def test_consolidated_magnet_uses_ampersand_between_xt_and_tr():
    from main import consolidate_all_items, consolidate_uncached_items, parse_trackers_from_magnet
    # Two items with same hash, different trackers
    sample = [
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://tracker1/announce'
        },
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://tracker2/announce'
        }
    ]
    out_all = consolidate_all_items(sample, {})
    assert len(out_all) == 1
    mag = out_all[0]['magnetUri']
    # Ensure we used '&' to join trackers (xt param followed by &)
    assert '?tr=' not in mag
    assert '&tr=' in mag
    # Ensure parse_trackers_from_magnet extracts both trackers
    trackers = parse_trackers_from_magnet(mag)
    assert 'http://tracker1/announce' in trackers
    assert 'http://tracker2/announce' in trackers

    out_uncached = consolidate_uncached_items(sample, {})
    assert len(out_uncached) == 1
    mag2 = out_uncached[0]['magnetUri']
    assert '?tr=' not in mag2
    assert '&tr=' in mag2



def test_generate_torznab_uses_uncached_seeders():
    from main import generate_torznab_xml
    # One uncached item that has seeders 1 but we have tracker numbers > 5
    sample = [
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=udp://tracker1:6969/announce',
            'seeders': 1,
            'leechers': 0,
            'guid': 'g1',
            'link': 'http://example.com/t1',
            'size': 12345
        }
    ]
    cached = {}
    uncached_seeders = {'abc123': 50}
    xml = generate_torznab_xml(sample, cached, uncached_seeders)
    # parse xml to find seeders
    import re
    m = re.search(r'torznab:attr name="seeders" value="(\d+)"', xml.decode())
    assert m and m.group(1) == '50'


def test_generate_torznab_emission_dedupe():
    from main import generate_torznab_xml
    sample = [
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=udp://tracker1:6969/announce',
            'seeders': 1,
            'leechers': 0,
            'guid': 'g1',
            'link': 'http://example.com/t1',
            'size': 12345
        },
        # Duplicate entry with same infoHash; the final XML should only contain one <item>
        {
            'infoHash': 'ABC123',
            'title': 'T1-dup',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=udp://tracker2:6969/announce',
            'seeders': 2,
            'leechers': 0,
            'guid': 'g2',
            'link': 'http://example.com/t1dup',
            'size': 12345
        }
    ]
    xml = generate_torznab_xml(sample, {})
    # Count occurrences of <item> to ensure we only emitted one for the duplicate infohash
    assert xml.decode().count('<item>') == 1


def test_generate_torznab_pubdate_present():
    from main import generate_torznab_xml
    sample = [
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123',
            'seeders': 1,
            'leechers': 0,
            'guid': 'g1',
            'link': 'http://example.com/t1',
            'size': 12345,
            'publishDate': '2025-05-10T16:57:09Z'
        }
    ]
    xml = generate_torznab_xml(sample, {})
    s = xml.decode()
    assert '<pubDate>' in s
    import re
    # Simple RFC-1123 style check (Fri, 10 May 2025 16:57:09 GMT)
    m = re.search(r'<pubDate>\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT</pubDate>', s)
    assert m is not None


def test_generate_torznab_enclosure_populated():
    from main import generate_torznab_xml
    sample = [
        {
            'infoHash': 'ABC123',
            'title': 'T1',
            'magnetUri': 'magnet:?xt=urn:btih:ABC123',
            'seeders': 1,
            'leechers': 0,
            'guid': 'magnet:?xt=urn:btih:ABC123',
            'link': '',
            'size': 12345,
        }
    ]
    xml = generate_torznab_xml(sample, {})
    s = xml.decode()
    # Ensure we emitted an enclosure and it contains something (magnet or http)
    assert 'enclosure url' in s
    import re
    m = re.search(r'enclosure url="([^"]+)"', s)
    assert m and m.group(1) != ''


@pytest.mark.asyncio
async def test_scrape_trackers_inverted_max(monkeypatch):
    # Setup a fake _udp_scrape_one to return different seeders per tracker
    from main import scrape_trackers_inverted
    async def fake_udp_scrape(host, port, hashes, timeout=5.0):
        # For tracker1 return abc1:5, abc2:4. For tracker2 return abc1:10
        if host.endswith('tracker1'):
            return {h: (5 if h=='abc1' else 4) for h in hashes}
        if host.endswith('tracker2'):
            return {h: (10 if h=='abc1' else 0) for h in hashes}
        return {}

    monkeypatch.setattr('main._udp_scrape_one', fake_udp_scrape)
    tracker_map = {
        'udp://tracker1:6969/announce': ['abc1', 'abc2'],
        'udp://tracker2:6969/announce': ['abc1']
    }
    out = await scrape_trackers_inverted(tracker_map)
    assert out['abc1'] == 10
    assert out['abc2'] == 4

    def test_consolidate_all_items_union_and_canonical():
        from main import consolidate_all_items
        # Items with the same infoHash with different trackers and seeders
        sample = [
            {'infoHash': 'ABC123', 'title': 'A', 'seeders': 5, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://t1/announce'},
            {'infoHash': 'ABC123', 'title': 'B', 'seeders': 12, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://t2/announce'},
            {'infoHash': 'ABC123', 'title': 'C', 'seeders': 3, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://t3/announce'}
        ]
        cached_status = {}
        # Simulate tracker scraping found 20 seeders for the uncached hash
        uncached_seeders = {'abc123': 20}
        out = consolidate_all_items(sample, cached_status, uncached_seeders)
        # One consolidated item should be returned
        assert len(out) == 1
        m = out[0]
        # The canonical title should be from the item with highest seeders (B)
        assert m['title'] == 'B'
        # Trackers from all three should be present in the magnetUri
        assert 'tr=http://t1/announce' in m['magnetUri']
        assert 'tr=http://t2/announce' in m['magnetUri']
        assert 'tr=http://t3/announce' in m['magnetUri']
        # Seeders should reflect max(seeders, uncached_seeders)
        assert int(m['seeders']) == 20

    @pytest.mark.asyncio
    async def test_full_pipeline_integration(monkeypatch):
        # Simulate a small pipeline run covering extract, torbox cache check, consolidation, xml generation
        from main import extract_info_hashes, check_torbox_cache, consolidate_all_items, generate_torznab_xml
        # Build a fake prowlarr result with two hashes, one cached, one not
        sample = [
            {'infoHash': 'ABC123', 'title': 'CachedTitle', 'seeders': 1, 'leechers': 0, 'guid': 'g1', 'link': 'http://a', 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://t1/announce', 'size': 1000},
            {'infoHash': 'DEF456', 'title': 'UncachedTitle', 'seeders': 1, 'leechers': 0, 'guid': 'g2', 'link': 'http://b', 'magnetUri': 'magnet:?xt=urn:btih:DEF456&tr=http://t2/announce', 'size': 2000}
        ]
        # Check info hashes
        hashes = extract_info_hashes(sample)
        assert hashes == ['abc123', 'def456']

    @pytest.mark.asyncio
    async def test_prowlarr_has_duplicates_but_cachebox_dedupes(monkeypatch):
        """Simulate a rich query (Rick and Morty S01E02) returning duplicates from Prowlarr
        and ensure cachebox output (post-consolidation and generate_torznab_xml) contains unique items only.
        """
        from main import search_prowlarr, extract_info_hashes, check_torbox_cache, consolidate_all_items, generate_torznab_xml
        # Create duplicate results (two sets of the same infoHash with different magnet trackers/titles)
        dup_hash = 'F7EF4D7C1A7697B055726959AA2380BF35A600D5'
        prowlarr_raw = [
            {'infoHash': dup_hash, 'title': 'Rick and Morty S01E02 - indexerA', 'magnetUri': f'magnet:?xt=urn:btih:{dup_hash}&tr=http://t1/announce'},
            {'infoHash': dup_hash, 'title': 'Rick and Morty S01E02 - indexerB', 'magnetUri': f'magnet:?xt=urn:btih:{dup_hash}&tr=http://t2/announce'},
            {'infoHash': '2222222222222222222222222222222222222222', 'title': 'Other Show', 'magnetUri': 'magnet:?xt=urn:btih:2222'},
        ]

        # Create a fake session that returns the prowlarr_raw when search_prowlarr calls GET
        class FakeGetPostSession:
            def __init__(self, get_data, post_data_mapping=None):
                self._get_data = get_data
                self.post_data_mapping = post_data_mapping or {}
                self.last_payload = None
                self.last_headers = None
            def get(self, url, headers=None, params=None):
                return FakeCtx(200, self._get_data)
            def post(self, url, json, headers):
                # store last_payload for assertions
                self.last_payload = json
                self.last_headers = headers
                # Return mapping if any, else empty
                # emulate torbox mapping: {hash: True}
                res = {}
                for h in (json.get('hashes') or []):
                    k = h.lower()
                    if k in self.post_data_mapping:
                        res[k] = self.post_data_mapping[k]
                return FakeCtx(200, res)

        # Ensure PROWLARR_URL is set for search_prowlarr to build URL
        import main as m
        m.PROWLARR_URL = 'http://fake-prowlarr.test'
        # Create a session where Torbox returns no cached items for the hashes
        session = FakeGetPostSession(prowlarr_raw, post_data_mapping={})

        # Run Prowlarr search (should return raw items with duplicates)
        params = {'query': 'Rick and Morty S01E02', 'categories': [], 'type': 'tvsearch'}
        prowlarr_results = await search_prowlarr(session, params)
        assert len(prowlarr_results) == len(prowlarr_raw)
        # Confirm duplicates exist in raw results (more items than unique infohashes)
        hashes = [it.get('infoHash') or '' for it in prowlarr_results]
        assert len(hashes) > len(set(h.lower() for h in hashes if h))

        # Extract unique hashes
        unique_hashes = extract_info_hashes(prowlarr_results)
        # Check Torbox cache (simulate empty cache)
        cached_status = await check_torbox_cache(session, unique_hashes)
        assert cached_status == {}

        # Consolidate items and generate XML
        consolidated = consolidate_all_items(prowlarr_results, cached_status, {})
        xml = generate_torznab_xml(consolidated, cached_status, {})
        decoded = xml.decode()
        # Number of <item> should equal number of unique hashes
        item_count = decoded.count('<item>')
        assert item_count == len(unique_hashes)
        # The duplicate infoHash should appear only once
        assert decoded.count(dup_hash.lower()) == 1


        def test_consolidate_includes_guid_trackers():
            from main import consolidate_all_items
            # Simulate two items where magnet is present in 'guid' instead of 'magnetUri'
            ih = '8cadfe07aaba94e59d1ab4d73235591c1874892b'
            sample = [
                {
                    'infoHash': ih,
                    'guid': f'magnet:?xt=urn:btih:{ih}&dn=foo&tr=udp://tracker-a/announce',
                    'title': 'T1',
                    'seeders': 1
                },
                {
                    'infoHash': ih,
                    'guid': f'magnet:?xt=urn:btih:{ih}&dn=foo&tr=http://tracker-b/announce',
                    'title': 'T1b',
                    'seeders': 2
                }
            ]
            out = consolidate_all_items(sample, {})
            assert len(out) == 1
            m = out[0]
            # Ensure both trackers are present in the consolidated magnet
            assert 'tr=udp://tracker-a/announce' in m['magnetUri']
            assert 'tr=http://tracker-b/announce' in m['magnetUri']


        def test_consolidate_creates_canonical_magnet_when_missing():
            from main import consolidate_all_items
            ih = 'aaaa1111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            sample = [
                {'infoHash': ih, 'magnetUri': 'magnet:?xt=urn:btih:'+ih+'&tr=udp://t1/announce', 'title': 'A', 'seeders': 1},
                {'infoHash': ih, 'title': 'B', 'seeders': 10},
            ]
            out = consolidate_all_items(sample, {})
            assert len(out) == 1
            m = out[0]
            # canonical magnetUri should be created for the item that initially lacked it
            assert 'magnet:?xt=urn:btih:'+ih in m['magnetUri']
            assert 'tr=udp://t1/announce' in m['magnetUri']
            assert m.get('guid') and 'magnet:?' in m['guid']


        def test_generate_xml_emits_canonical_guid():
            from main import consolidate_all_items, generate_torznab_xml
            # Duplicate items; ensure emitted guid equals canonical magnetUri
            dup_hash = 'ABC123'
            sample = [
                {'infoHash': dup_hash, 'title': 'A', 'seeders': 1, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://t1/announce'},
                {'infoHash': dup_hash, 'title': 'B', 'seeders': 5, 'magnetUri': 'magnet:?xt=urn:btih:ABC123&tr=http://t2/announce'}
            ]
            consolidated = consolidate_all_items(sample, {})
            xml = generate_torznab_xml(consolidated, {})
            # parse XML and extract guid
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            # find item and guid
            items = root.findall('.//item')
            assert len(items) == 1
            guid = items[0].find('guid').text
            assert guid == consolidated[0]['magnetUri']


        def test_consolidate_includes_enclosure_trackers():
            from main import consolidate_all_items
            ih = 'bbbb2222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
            sample = [
                {'infoHash': ih, 'enclosure': {'url': 'magnet:?xt=urn:btih:'+ih+'&tr=udp://e1/announce'}, 'seeders': 1},
                {'infoHash': ih, 'magnetUri': 'magnet:?xt=urn:btih:'+ih+'&tr=udp://m2/announce', 'seeders': 2},
            ]
            out = consolidate_all_items(sample, {})
            assert len(out) == 1
            m = out[0]
            # canonical should have union of trackers including those from enclosure
            assert 'tr=udp://e1/announce' in m['magnetUri']
            assert 'tr=udp://m2/announce' in m['magnetUri']


        def test_generate_guid_contains_unioned_trackers():
            from main import generate_torznab_xml
            ih = '8cadfe07aaba94e59d1ab4d73235591c1874892b'
            sample = [
                {'infoHash': ih, 'title': 'A', 'magnetUri': 'magnet:?xt=urn:btih:'+ih+'&tr=udp://tracker.opentrackr.org:1337/announce', 'guid': None, 'seeders': 1},
                {'infoHash': ih, 'title': 'B', 'magnetUri': 'magnet:?xt=urn:btih:'+ih+'&tr=udp://9.rarbg.me:2970/announce', 'guid': None, 'seeders': 2},
            ]
            xml = generate_torznab_xml(sample, {})
            decoded = xml.decode()
            # Should include both trackers in the GUID (magnetUri used as guid)
            assert 'tr=udp://9.rarbg.me:2970/announce' in decoded
            assert 'tr=udp://tracker.opentrackr.org:1337/announce' in decoded
        # Fake Torbox session to return ABC123 as cached
        class DummySession:
            def __init__(self, responses):
                self._responses = responses
                self._idx = 0
                self.last_payload = None
                self.last_headers = None
            def post(self, url, json, headers):
                self.last_payload = json
                self.last_headers = headers
                # Return only one response mapping cached abc123
                return FakeCtx(200, {'abc123': True})

        # Use the existing FakeCtx helper defined earlier
        session = DummySession({})
        cached_status = await check_torbox_cache(session, hashes)
        # ABC123 should be cached
        assert 'abc123' in cached_status and cached_status['abc123'] is True

        # Consolidate and then generate XML: apply uncached seeders for DEF456
        conc = consolidate_all_items(sample, cached_status, {'def456': 7})
        xml = generate_torznab_xml(conc, cached_status, {'def456': 7})
        decoded = xml.decode()
        # There should be two items (one per unique hash)
        assert decoded.count('<item>') == 2
        # Ensure cached item has [CACHED] in title
        assert '[CACHED] CachedTitle' in decoded
        # Ensure uncached item has seeders from unsourced tracker scrape (7)
        assert 'torznab:attr name="seeders" value="7"' in decoded
