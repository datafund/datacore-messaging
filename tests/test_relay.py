import json
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


@pytest.fixture
def relay_app():
    from lib.relay import create_relay_app
    return create_relay_app(relay_secret="test-secret-123")


class TestRelayAuth:
    @pytest.mark.asyncio
    async def test_status_requires_no_user_list(self, relay_app, aiohttp_client):
        """Status endpoint must NOT leak connected usernames."""
        client = await aiohttp_client(relay_app)
        resp = await client.get("/status")
        data = await resp.json()
        assert resp.status == 200
        assert "users" not in data
        assert "users_online" not in data
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_status_shows_count_only(self, relay_app, aiohttp_client):
        client = await aiohttp_client(relay_app)
        resp = await client.get("/status")
        data = await resp.json()
        assert "connected" in data
        assert isinstance(data["connected"], int)


class TestRelayStartup:
    def test_relay_refuses_empty_secret(self):
        from lib.relay import create_relay_app
        with pytest.raises(ValueError, match="RELAY_SECRET"):
            create_relay_app(relay_secret="")

    def test_relay_accepts_valid_secret(self):
        from lib.relay import create_relay_app
        app = create_relay_app(relay_secret="valid-secret")
        assert app is not None


class TestArgParsing:
    def test_host_flag_not_h(self):
        """Verify -h is NOT used for hosting (it's --help)."""
        from lib.relay import parse_relay_args
        args = parse_relay_args(["--host"])
        assert args.host is True
        with pytest.raises(SystemExit):
            parse_relay_args(["-h"])
