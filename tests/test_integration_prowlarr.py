def test_search_prowlarr_does_not_forward_limit_zero(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {"query": "Love Death and Robots", "limit": "0", "offset": "0", "categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get("limit") is None
import json
from urllib.parse import unquote, parse_qs

from main import extract_info_hashes, consolidate_all_items, generate_torznab_xml


def _get_magnet(item):
    if item.get("magnetUri"):
        return item.get("magnetUri")
    g = item.get("guid")
    if isinstance(g, str) and "magnet:?" in g:
        return g
    enc = item.get("enclosure")
    if isinstance(enc, dict) and isinstance(enc.get("url"), str) and "magnet:?" in enc.get("url"):
        return enc.get("url")
    if isinstance(enc, str) and "magnet:?" in enc:
        return enc
    return None


def parse_trs(magnet):
    if not magnet:
        return set()
    try:
        qs = parse_qs(unquote(magnet.split("?", 1)[1]))
        return set(qs.get("tr", []))
    except Exception:
        return set()


def test_search_prowlarr_does_not_forward_limit_zero(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {"query": "Love Death and Robots", "limit": "0", "offset": "0", "categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get("limit") is None
import json
from urllib.parse import unquote, parse_qs

from main import extract_info_hashes, consolidate_all_items, generate_torznab_xml


def _get_magnet(item):
    if item.get("magnetUri"):
        return item.get("magnetUri")
    g = item.get("guid")
    if isinstance(g, str) and "magnet:?" in g:
        return g
    enc = item.get("enclosure")
    if isinstance(enc, dict) and isinstance(enc.get("url"), str) and "magnet:?" in enc.get("url"):
        return enc.get("url")
    if isinstance(enc, str) and "magnet:?" in enc:
        return enc
    return None


def parse_trs(magnet):
    if not magnet:
        return set()
    try:
        qs = parse_qs(unquote(magnet.split("?", 1)[1]))
        return set(qs.get("tr", []))
    except Exception:
        return set()


def test_integration_unioned_trackers_and_dedupe():
    # Load fixture captured from a live Prowlarr query
    with open("tests/fixtures/prowlarr_rm_s01e02.json") as f:
        pr = json.load(f)

    items = (
        pr
        if isinstance(pr, list)
        else pr.get("records") or pr.get("results") or pr.get("items") or pr.get("data") or []
    )

    pr_map = {}
    for it in items:
        ih = it.get("infoHash")
        if not ih:
            mag = _get_magnet(it)
            if mag:
                try:
                    parsed = parse_qs(unquote(mag.split("?", 1)[1]))
                    if "xt" in parsed:
                        ih = parsed["xt"][0].split(":")[-1]
                except Exception:
                    ih = None
        if not ih:
            continue
        ih = ih.lower()
        pr_map.setdefault(ih, set())
        pr_map[ih] |= parse_trs(_get_magnet(it))

    consolidated = consolidate_all_items(items, {})
    xml = generate_torznab_xml(consolidated, {})
    xml_decoded = xml.decode()

    import re

    emitted_hashes = set(
        re.findall(r'torznab:attr name="infohash" value="([0-9a-fA-F]+)"', xml_decoded)
    )
    assert len(emitted_hashes) == len(pr_map)

    for ih, pr_trs in pr_map.items():
        if not pr_trs:
            continue
        assert re.search(ih, xml_decoded, re.I), f"Infohash {ih} not present in generated XML"
        if f"xt=urn:btih:{ih}" in xml_decoded:
            start = xml_decoded.find(f"xt=urn:btih:{ih}")
            before = xml_decoded.rfind("<guid>", 0, start)
            after = xml_decoded.find("</guid>", start)
            if before == -1 or after == -1:
                continue
            guid_text = xml_decoded[before + len("<guid>") : after]
            for tr in pr_trs:
                assert tr in guid_text, f"Missing tracker {tr} for {ih} in GUID\nGUID: {guid_text}"


async def _fake_search(session, kwargs):
    q = kwargs.get("query") or ""
    ih = "AAA111" if q else "BBB222"
    return [
        {
            "infoHash": ih,
            "title": "Test",
            "magnetUri": f"magnet:?xt=urn:btih:{ih}&tr=http://t1/announce",
        }
    ]


def test_search_prowlarr_fallback_and_categories_list(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    monkeypatch.setenv("CACHEBOX_TEST_FALLBACK_QUERY", "a")
    m.CACHEBOX_TEST_FALLBACK_QUERY = "a"

    session = FakeSession()
    kwargs = {"categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params is not None
    assert session.last_params.get("query") == "a"
    assert isinstance(session.last_params.get("categories"), list)


def test_search_prowlarr_forwards_paging(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {"query": "Love Death and Robots", "limit": "100", "offset": "0", "categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get("limit") == "100"
    assert session.last_params.get("offset") == "0"


def test_search_prowlarr_does_not_forward_limit_zero(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {"query": "Love Death and Robots", "limit": "0", "offset": "0", "categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get("limit") is None


def test_handle_search_forwards_limit_offset(monkeypatch):
    import main as m
    from fastapi import Request
    from starlette.datastructures import QueryParams

    async def fake_search(session, kwargs):
        assert kwargs.get("limit") == "100"
        assert kwargs.get("offset") == "0"
        return [{"infoHash": "AAA111", "title": "T1", "magnetUri": "magnet:?xt=urn:btih:AAA111"}]

    monkeypatch.setattr("main.search_prowlarr", fake_search)
    params = QueryParams({"cat": "5030,5040", "t": "tvsearch", "limit": "100", "offset": "0"})
    import asyncio

    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
    assert resp.body is not None
    assert "<item>" in resp.body.decode()


def test_handle_search_category_only_fallback_returns_nonempty_xml(monkeypatch):
    import main as m
    from fastapi import Request
    from starlette.datastructures import QueryParams

    monkeypatch.setenv("CACHEBOX_TEST_FALLBACK_QUERY", "a")
    m.CACHEBOX_TEST_FALLBACK_QUERY = "a"

    async def fake_search(session, kwargs):
        assert kwargs.get("query") == "a"
        return [{"infoHash": "AAA111", "title": "T1", "magnetUri": "magnet:?xt=urn:btih:AAA111"}]

    monkeypatch.setattr("main.search_prowlarr", fake_search)
    params = QueryParams({"cat": "5030,5040", "t": "tvsearch"})
    import asyncio

    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
    assert resp.body is not None
    xml = resp.body.decode()
    assert "<item>" in xml
import json
from urllib.parse import unquote, parse_qs

from main import extract_info_hashes, consolidate_all_items, generate_torznab_xml


def _get_magnet(item):
    if item.get("magnetUri"):
        return item.get("magnetUri")
    g = item.get("guid")
    if isinstance(g, str) and "magnet:?" in g:
        return g
    enc = item.get("enclosure")
    if isinstance(enc, dict) and isinstance(enc.get("url"), str) and "magnet:?" in enc.get("url"):
        return enc.get("url")
    if isinstance(enc, str) and "magnet:?" in enc:
        return enc
    return None


def parse_trs(magnet):
    if not magnet:
        return set()
    try:
        qs = parse_qs(unquote(magnet.split("?", 1)[1]))
        return set(qs.get("tr", []))
    except Exception:
        return set()


def test_integration_unioned_trackers_and_dedupe():
    # Load fixture captured from a live Prowlarr query
    with open("tests/fixtures/prowlarr_rm_s01e02.json") as f:
        pr = json.load(f)

    items = (
        pr
        if isinstance(pr, list)
        else pr.get("records") or pr.get("results") or pr.get("items") or pr.get("data") or []
    )

    pr_map = {}
    for it in items:
        ih = it.get("infoHash")
        if not ih:
            mag = _get_magnet(it)
            if mag:
                try:
                    parsed = parse_qs(unquote(mag.split("?", 1)[1]))
                    if "xt" in parsed:
                        ih = parsed["xt"][0].split(":")[-1]
                except Exception:
                    ih = None
        if not ih:
            continue
        ih = ih.lower()
        pr_map.setdefault(ih, set())
        pr_map[ih] |= parse_trs(_get_magnet(it))

    consolidated = consolidate_all_items(items, {})
    xml = generate_torznab_xml(consolidated, {})
    xml_decoded = xml.decode()

    import re

    emitted_hashes = set(
        re.findall(r'torznab:attr name="infohash" value="([0-9a-fA-F]+)"', xml_decoded)
    )
    assert len(emitted_hashes) == len(pr_map)

    for ih, pr_trs in pr_map.items():
        if not pr_trs:
            continue
        assert re.search(ih, xml_decoded, re.I), f"Infohash {ih} not present in generated XML"
        if f"xt=urn:btih:{ih}" in xml_decoded:
            start = xml_decoded.find(f"xt=urn:btih:{ih}")
            before = xml_decoded.rfind("<guid>", 0, start)
            after = xml_decoded.find("</guid>", start)
            if before == -1 or after == -1:
                continue
            guid_text = xml_decoded[before + len("<guid>") : after]
            for tr in pr_trs:
                assert tr in guid_text, f"Missing tracker {tr} for {ih} in GUID\nGUID: {guid_text}"


async def _fake_search(session, kwargs):
    q = kwargs.get("query") or ""
    ih = "AAA111" if q else "BBB222"
    return [
        {
            "infoHash": ih,
            "title": "Test",
            "magnetUri": f"magnet:?xt=urn:btih:{ih}&tr=http://t1/announce",
        }
    ]


def test_search_prowlarr_fallback_and_categories_list(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    monkeypatch.setenv("CACHEBOX_TEST_FALLBACK_QUERY", "a")
    m.CACHEBOX_TEST_FALLBACK_QUERY = "a"

    session = FakeSession()
    kwargs = {"categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params is not None
    assert session.last_params.get("query") == "a"
    assert isinstance(session.last_params.get("categories"), list)


def test_search_prowlarr_forwards_paging(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {"query": "Love Death and Robots", "limit": "100", "offset": "0", "categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get("limit") == "100"
    assert session.last_params.get("offset") == "0"


def test_search_prowlarr_does_not_forward_limit_zero(monkeypatch):
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._data

        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None

        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {"query": "Love Death and Robots", "limit": "0", "offset": "0", "categories": ["5030", "5040"]}
    import asyncio

    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get("limit") is None


def test_handle_search_forwards_limit_offset(monkeypatch):
    import main as m
    from fastapi import Request
    from starlette.datastructures import QueryParams

    async def fake_search(session, kwargs):
        assert kwargs.get("limit") == "100"
        assert kwargs.get("offset") == "0"
        return [{"infoHash": "AAA111", "title": "T1", "magnetUri": "magnet:?xt=urn:btih:AAA111"}]

    monkeypatch.setattr("main.search_prowlarr", fake_search)
    params = QueryParams({"cat": "5030,5040", "t": "tvsearch", "limit": "100", "offset": "0"})
    import asyncio

    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
    assert resp.body is not None
    assert "<item>" in resp.body.decode()


def test_handle_search_category_only_fallback_returns_nonempty_xml(monkeypatch):
    import main as m
    from fastapi import Request
    from starlette.datastructures import QueryParams

    monkeypatch.setenv("CACHEBOX_TEST_FALLBACK_QUERY", "a")
    m.CACHEBOX_TEST_FALLBACK_QUERY = "a"

    async def fake_search(session, kwargs):
        assert kwargs.get("query") == "a"
        return [{"infoHash": "AAA111", "title": "T1", "magnetUri": "magnet:?xt=urn:btih:AAA111"}]

    monkeypatch.setattr("main.search_prowlarr", fake_search)
    params = QueryParams({"cat": "5030,5040", "t": "tvsearch"})
    import asyncio

    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
    assert resp.body is not None
    xml = resp.body.decode()
    assert "<item>" in xml
import json
from urllib.parse import unquote, parse_qs

from main import extract_info_hashes, consolidate_all_items, generate_torznab_xml


def _get_magnet(item):
    if item.get('magnetUri'):
        return item.get('magnetUri')
    g = item.get('guid')
    if isinstance(g, str) and 'magnet:?' in g:
        return g
    enc = item.get('enclosure')
    if isinstance(enc, dict) and isinstance(enc.get('url'), str) and 'magnet:?' in enc.get('url'):
        return enc.get('url')
    if isinstance(enc, str) and 'magnet:?' in enc:
        return enc
    return None


def parse_trs(magnet):
    if not magnet:
        return set()
    try:
        qs = parse_qs(unquote(magnet.split('?', 1)[1]))
        return set(qs.get('tr', []))
    except Exception:
        return set()


def test_integration_unioned_trackers_and_dedupe():
    # Load fixture captured from a live Prowlarr query
    with open('tests/fixtures/prowlarr_rm_s01e02.json') as f:
        pr = json.load(f)

    items = pr if isinstance(pr, list) else pr.get('records') or pr.get('results') or pr.get('items') or pr.get('data') or []

    # Build Prowlarr tv hashes map
    pr_map = {}
    for it in items:
        ih = it.get('infoHash')
        if not ih:
            mag = _get_magnet(it)
            if mag:
                try:
                    parsed = parse_qs(unquote(mag.split('?', 1)[1]))
                    if 'xt' in parsed:
                        ih = parsed['xt'][0].split(':')[-1]
                except Exception:
                    ih = None
        if not ih:
            continue
        ih = ih.lower()
        pr_map.setdefault(ih, set())
        pr_map[ih] |= parse_trs(_get_magnet(it))

    # Consolidate items with empty cached status
    consolidated = consolidate_all_items(items, {})
    xml = generate_torznab_xml(consolidated, {})
    xml_decoded = xml.decode()

    # Dedup: unique infohash values emitted should match number of unique prowlarr hashes
    import re
    emitted_hashes = set(re.findall(r'torznab:attr name="infohash" value="([0-9a-fA-F]+)"', xml_decoded))
    assert len(emitted_hashes) == len(pr_map)

    # For each prowlarr hash, ensure all trackers are included in the GUID of emitted XML
    for ih, pr_trs in pr_map.items():
        if not pr_trs:
            # no trackers to assert, skip
            continue
        # find the GUID line for this infohash
        import re
        assert re.search(ih, xml_decoded, re.I), f"Infohash {ih} not present in generated XML"
        # find the GUID magnet
        if f'xt=urn:btih:{ih}' in xml_decoded:
            # find the magnet substring
            start = xml_decoded.find(f'xt=urn:btih:{ih}')
            # find the enclosing <guid> tag start
            before = xml_decoded.rfind('<guid>', 0, start)
            after = xml_decoded.find('</guid>', start)
            if before == -1 or after == -1:
                continue
            guid_text = xml_decoded[before+len('<guid>'):after]
            for tr in pr_trs:
                assert tr in guid_text, f"Missing tracker {tr} for {ih} in GUID\nGUID: {guid_text}"


async def _fake_search(session, kwargs):
    """Helper fake search that returns a predictable item when called."""
    # respond with a simple item using the query in kwargs to prove it was set
    q = kwargs.get('query') or ''
    ih = 'AAA111' if q else 'BBB222'
    return [{'infoHash': ih, 'title': 'Test', 'magnetUri': f'magnet:?xt=urn:btih:{ih}&tr=http://t1/announce'}]


def test_search_prowlarr_fallback_and_categories_list(monkeypatch):
    """Ensure search_prowlarr adds fallback query when categories-only call and that categories are passed as a list."""
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def json(self):
            return self._data
        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None
        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            # return an empty list of results
            return FakeCtx(200, [])

    # Set fallback env variable on the module
    monkeypatch.setenv('CACHEBOX_TEST_FALLBACK_QUERY', 'a')
    # Update module var reference (the module reads it at import-time)
    m.CACHEBOX_TEST_FALLBACK_QUERY = 'a'

    session = FakeSession()
    kwargs = {'categories': ['5030', '5040']}
    # Call the function under test
    import asyncio
    res = asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    # Ensure get was called and params show categories as list and query is fallback 'a'
    assert session.last_params is not None
    assert session.last_params.get('query') == 'a'
    # categories should be a list
    assert isinstance(session.last_params.get('categories'), list)


def test_search_prowlarr_forwards_paging(monkeypatch):
    """Ensure search_prowlarr forwards limit and offset to Prowlarr GET params"""
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def json(self):
            return self._data
        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None
        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {'query': 'Love Death and Robots', 'limit': '100', 'offset': '0', 'categories': ['5030', '5040']}
    import asyncio
    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get('limit') == '100'
    assert session.last_params.get('offset') == '0'


def test_search_prowlarr_does_not_forward_limit_zero(monkeypatch):
    """Ensure search_prowlarr does not forward limit=0 to Prowlarr"""
    import main as m

    class FakeCtx:
        def __init__(self, status, data):
            self.status = status
            self._data = data
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def json(self):
            return self._data
        def raise_for_status(self):
            if self.status >= 400:
                raise Exception(f"status {self.status}")

    class FakeSession:
        def __init__(self):
            self.last_params = None
            self.last_headers = None
        def get(self, url, headers=None, params=None):
            self.last_params = params
            self.last_headers = headers
            return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {'query': 'Love Death and Robots', 'limit': '0', 'offset': '0', 'categories': ['5030', '5040']}
    import asyncio
    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
    assert session.last_params.get('limit') is None


def test_handle_search_forwards_limit_offset(monkeypatch):
    """Ensure handle_search extracts limit/offset from incoming Request QueryParams and forwards them to Prowlarr"""
    import main as m
    from fastapi import Request
    from starlette.datastructures import QueryParams

    async def fake_search(session, kwargs):
        assert kwargs.get('limit') == '100'
        assert kwargs.get('offset') == '0'
        return [{'infoHash': 'AAA111', 'title': 'T1', 'magnetUri': 'magnet:?xt=urn:btih:AAA111'}]

    monkeypatch.setattr('main.search_prowlarr', fake_search)
    params = QueryParams({'cat': '5030,5040', 't': 'tvsearch', 'limit': '100', 'offset': '0'})
    import asyncio
    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
    assert resp.body is not None
    assert '<item>' in resp.body.decode()


def test_handle_search_category_only_fallback_returns_nonempty_xml(monkeypatch):
    """Ensure handle_search substitutes fallback query and returns XML when Prowlarr returns items."""
    import main as m
    from fastapi import Request
    from starlette.datastructures import QueryParams

    # Ensure module fallback is set
    monkeypatch.setenv('CACHEBOX_TEST_FALLBACK_QUERY', 'a')
    m.CACHEBOX_TEST_FALLBACK_QUERY = 'a'

    # Monkeypatch search_prowlarr to our fake one that returns an item when query is set
    async def fake_search(session, kwargs):
        assert kwargs.get('query') == 'a'
        return [{'infoHash': 'AAA111', 'title': 'T1', 'magnetUri': 'magnet:?xt=urn:btih:AAA111'}]

    monkeypatch.setattr('main.search_prowlarr', fake_search)
    # Build a fake request params with categories but no q
    params = QueryParams({'cat': '5030,5040', 't': 'tvsearch'})
    # call handle_search directly (it's async)
    import asyncio
    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
    # The response should be an XML string (bytes) and not be the empty feed
    assert resp.body is not None
    xml = resp.body.decode()
    assert '<item>' in xml
import json
from urllib.parse import unquote, parse_qs

from main import extract_info_hashes, consolidate_all_items, generate_torznab_xml


def _get_magnet(item):
    if item.get('magnetUri'):
        return item.get('magnetUri')
    g = item.get('guid')
    if isinstance(g, str) and 'magnet:?' in g:
        return g
    enc = item.get('enclosure')
    if isinstance(enc, dict) and isinstance(enc.get('url'), str) and 'magnet:?' in enc.get('url'):
        return enc.get('url')
    if isinstance(enc, str) and 'magnet:?' in enc:
        return enc
    return None


def parse_trs(magnet):
    if not magnet:
        return set()
    try:
        qs = parse_qs(unquote(magnet.split('?', 1)[1]))
        return set(qs.get('tr', []))
    except Exception:
        return set()


def test_integration_unioned_trackers_and_dedupe():
    # Load fixture captured from a live Prowlarr query
    with open('tests/fixtures/prowlarr_rm_s01e02.json') as f:
        pr = json.load(f)

    items = pr if isinstance(pr, list) else pr.get('records') or pr.get('results') or pr.get('items') or pr.get('data') or []

    # Build Prowlarr tv hashes map
    pr_map = {}
    for it in items:
        ih = it.get('infoHash')
        if not ih:
            mag = _get_magnet(it)
            if mag:
                try:
                    parsed = parse_qs(unquote(mag.split('?', 1)[1]))
                    if 'xt' in parsed:
                        ih = parsed['xt'][0].split(':')[-1]
                except Exception:
                    ih = None
        if not ih:
            continue
        ih = ih.lower()
        pr_map.setdefault(ih, set())
        pr_map[ih] |= parse_trs(_get_magnet(it))

    # Consolidate items with empty cached status
    consolidated = consolidate_all_items(items, {})
    xml = generate_torznab_xml(consolidated, {})
    xml_decoded = xml.decode()

    # Dedup: unique infohash values emitted should match number of unique prowlarr hashes
    import re
    emitted_hashes = set(re.findall(r'torznab:attr name="infohash" value="([0-9a-fA-F]+)"', xml_decoded))
    assert len(emitted_hashes) == len(pr_map)

    # For each prowlarr hash, ensure all trackers are included in the GUID of emitted XML
    for ih, pr_trs in pr_map.items():
        if not pr_trs:
            # no trackers to assert, skip
            continue
        # find the GUID line for this infohash
        import re
        assert re.search(ih, xml_decoded, re.I), f"Infohash {ih} not present in generated XML"
        # find the GUID magnet
        if f'xt=urn:btih:{ih}' in xml_decoded:
            # find the magnet substring
            start = xml_decoded.find(f'xt=urn:btih:{ih}')
            # find the enclosing <guid> tag start
            before = xml_decoded.rfind('<guid>', 0, start)
            after = xml_decoded.find('</guid>', start)
            if before == -1 or after == -1:
                continue
            guid_text = xml_decoded[before+len('<guid>'):after]
            for tr in pr_trs:
                assert tr in guid_text, f"Missing tracker {tr} for {ih} in GUID\nGUID: {guid_text}"


    # end test_integration_unioned_trackers_and_dedupe


async def _fake_search(session, kwargs):
    """Helper fake search that returns a predictable item when called."""
    # respond with a simple item using the query in kwargs to prove it was set
    q = kwargs.get('query') or ''
    ih = 'AAA111' if q else 'BBB222'
    return [{'infoHash': ih, 'title': 'Test', 'magnetUri': f'magnet:?xt=urn:btih:{ih}&tr=http://t1/announce'}]


def test_search_prowlarr_fallback_and_categories_list(monkeypatch):
        """Ensure search_prowlarr adds fallback query when categories-only call and that categories are passed as a list."""
        import main as m

        class FakeCtx:
            def __init__(self, status, data):
                self.status = status
                self._data = data
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def json(self):
                return self._data
            def raise_for_status(self):
                if self.status >= 400:
                    raise Exception(f"status {self.status}")

        class FakeSession:
            def __init__(self):
                self.last_params = None
                self.last_headers = None
            def get(self, url, headers=None, params=None):
                self.last_params = params
                self.last_headers = headers
                # return an empty list of results
                return FakeCtx(200, [])

        # Set fallback env variable on the module
        monkeypatch.setenv('CACHEBOX_TEST_FALLBACK_QUERY', 'a')
        # Update module var reference (the module reads it at import-time)
        m.CACHEBOX_TEST_FALLBACK_QUERY = 'a'

    session = FakeSession()
    kwargs = {'categories': ['5030', '5040']}
        # Call the function under test
    import asyncio
    res = asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
        # Ensure get was called and params show categories as list and query is fallback 'a'
        assert session.last_params is not None
        assert session.last_params.get('query') == 'a'
        # categories should be a list
        assert isinstance(session.last_params.get('categories'), list)


def test_search_prowlarr_forwards_paging(monkeypatch):
        """Ensure search_prowlarr forwards limit and offset to Prowlarr GET params"""
        import main as m

        class FakeCtx:
            def __init__(self, status, data):
                self.status = status
                self._data = data
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def json(self):
                return self._data
            def raise_for_status(self):
                if self.status >= 400:
                    raise Exception(f"status {self.status}")

        class FakeSession:
            def __init__(self):
                self.last_params = None
                self.last_headers = None
            def get(self, url, headers=None, params=None):
                self.last_params = params
                self.last_headers = headers
                return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {'query': 'Love Death and Robots', 'limit': '100', 'offset': '0', 'categories': ['5030', '5040']}
    import asyncio
    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
        assert session.last_params.get('limit') == '100'
        assert session.last_params.get('offset') == '0'


def test_search_prowlarr_does_not_forward_limit_zero(monkeypatch):
        """Ensure search_prowlarr does not forward limit=0 to Prowlarr"""
        import main as m

        class FakeCtx:
            def __init__(self, status, data):
                self.status = status
                self._data = data
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def json(self):
                return self._data
            def raise_for_status(self):
                if self.status >= 400:
                    raise Exception(f"status {self.status}")

        class FakeSession:
            def __init__(self):
                self.last_params = None
                self.last_headers = None
            def get(self, url, headers=None, params=None):
                self.last_params = params
                self.last_headers = headers
                return FakeCtx(200, [])

    session = FakeSession()
    kwargs = {'query': 'Love Death and Robots', 'limit': '0', 'offset': '0', 'categories': ['5030', '5040']}
    import asyncio
    asyncio.get_event_loop().run_until_complete(m.search_prowlarr(session, kwargs))
        assert session.last_params.get('limit') is None


def test_handle_search_forwards_limit_offset(monkeypatch):
        """Ensure handle_search extracts limit/offset from incoming Request QueryParams and forwards them to Prowlarr"""
        import main as m
        from fastapi import Request
        from starlette.datastructures import QueryParams

        async def fake_search(session, kwargs):
            assert kwargs.get('limit') == '100'
            assert kwargs.get('offset') == '0'
            return [{'infoHash': 'AAA111', 'title': 'T1', 'magnetUri': 'magnet:?xt=urn:btih:AAA111'}]

        monkeypatch.setattr('main.search_prowlarr', fake_search)
        params = QueryParams({'cat': '5030,5040', 't': 'tvsearch', 'limit': '100', 'offset': '0'})
    import asyncio
    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
        assert resp.body is not None
        assert '<item>' in resp.body.decode()


def test_handle_search_category_only_fallback_returns_nonempty_xml(monkeypatch):
        """Ensure handle_search substitutes fallback query and returns XML when Prowlarr returns items."""
        import main as m
        from fastapi import Request
        from starlette.datastructures import QueryParams

        # Ensure module fallback is set
        monkeypatch.setenv('CACHEBOX_TEST_FALLBACK_QUERY', 'a')
        m.CACHEBOX_TEST_FALLBACK_QUERY = 'a'

        # Monkeypatch search_prowlarr to our fake one that returns an item when query is set
        async def fake_search(session, kwargs):
            assert kwargs.get('query') == 'a'
            return [{'infoHash': 'AAA111', 'title': 'T1', 'magnetUri': 'magnet:?xt=urn:btih:AAA111'}]

        monkeypatch.setattr('main.search_prowlarr', fake_search)
        # Build a fake request params with categories but no q
        params = QueryParams({'cat': '5030,5040', 't': 'tvsearch'})
        # call handle_search directly (it's async)
    import asyncio
    resp = asyncio.get_event_loop().run_until_complete(m.handle_search(params))
        # The response should be an XML string (bytes) and not be the empty feed
        assert resp.body is not None
        xml = resp.body.decode()
        assert '<item>' in xml
