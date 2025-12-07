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
