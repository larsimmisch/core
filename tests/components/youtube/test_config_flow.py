"""Test the YouTube config flow."""
from unittest.mock import patch

from googleapiclient.errors import HttpError
from httplib2 import Response
import pytest

from homeassistant import config_entries
from homeassistant.components.youtube.const import CONF_CHANNELS, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow

from . import MockService
from .conftest import CLIENT_ID, GOOGLE_AUTH_URI, GOOGLE_TOKEN_URI, SCOPES, TITLE

from tests.common import MockConfigEntry, load_fixture
from tests.test_util.aiohttp import AiohttpClientMocker
from tests.typing import ClientSessionGenerator


async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
) -> None:
    """Check full flow."""
    result = await hass.config_entries.flow.async_init(
        "youtube", context={"source": config_entries.SOURCE_USER}
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": "https://example.com/auth/external/callback",
        },
    )

    assert result["url"] == (
        f"{GOOGLE_AUTH_URI}?response_type=code&client_id={CLIENT_ID}"
        "&redirect_uri=https://example.com/auth/external/callback"
        f"&state={state}&scope={'+'.join(SCOPES)}"
        "&access_type=offline&prompt=consent"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    with patch(
        "homeassistant.components.youtube.async_setup_entry", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.youtube.api.build", return_value=MockService()
    ), patch(
        "homeassistant.components.youtube.config_flow.build", return_value=MockService()
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "channels"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CHANNELS: ["UC_x5XG1OV2P6uZZ5FSM9Ttw"]}
        )

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert len(mock_setup.mock_calls) == 1

    assert result["type"] == "create_entry"
    assert result["title"] == TITLE
    assert "result" in result
    assert result["result"].unique_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert "token" in result["result"].data
    assert result["result"].data["token"]["access_token"] == "mock-access-token"
    assert result["result"].data["token"]["refresh_token"] == "mock-refresh-token"
    assert result["options"] == {CONF_CHANNELS: ["UC_x5XG1OV2P6uZZ5FSM9Ttw"]}


async def test_flow_http_error(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
) -> None:
    """Check full flow."""
    result = await hass.config_entries.flow.async_init(
        "youtube", context={"source": config_entries.SOURCE_USER}
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": "https://example.com/auth/external/callback",
        },
    )

    assert result["url"] == (
        f"{GOOGLE_AUTH_URI}?response_type=code&client_id={CLIENT_ID}"
        "&redirect_uri=https://example.com/auth/external/callback"
        f"&state={state}&scope={'+'.join(SCOPES)}"
        "&access_type=offline&prompt=consent"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    with patch(
        "homeassistant.components.youtube.config_flow.build",
        side_effect=HttpError(
            Response(
                {
                    "vary": "Origin, X-Origin, Referer",
                    "content-type": "application/json; charset=UTF-8",
                    "date": "Mon, 15 May 2023 21:25:42 GMT",
                    "server": "scaffolding on HTTPServer2",
                    "cache-control": "private",
                    "x-xss-protection": "0",
                    "x-frame-options": "SAMEORIGIN",
                    "x-content-type-options": "nosniff",
                    "alt-svc": 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
                    "transfer-encoding": "chunked",
                    "status": "403",
                    "content-length": "947",
                    "-content-encoding": "gzip",
                }
            ),
            b'{"error": {"code": 403,"message": "YouTube Data API v3 has not been used in project 0 before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=0 then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry.","errors": [  {    "message": "YouTube Data API v3 has not been used in project 0 before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=0 then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry.",    "domain": "usageLimits",    "reason": "accessNotConfigured",    "extendedHelp": "https://console.developers.google.com"  }],"status": "PERMISSION_DENIED"\n  }\n}\n',
        ),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "access_not_configured"
        assert (
            result["description_placeholders"]["message"]
            == "YouTube Data API v3 has not been used in project 0 before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=0 then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry."
        )


@pytest.mark.parametrize(
    ("fixture", "abort_reason", "placeholders", "calls", "access_token"),
    [
        ("get_channel", "reauth_successful", None, 1, "updated-access-token"),
        (
            "get_channel_2",
            "wrong_account",
            {"title": "Linus Tech Tips"},
            0,
            "mock-access-token",
        ),
    ],
)
async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host,
    config_entry: MockConfigEntry,
    fixture: str,
    abort_reason: str,
    placeholders: dict[str, str],
    calls: int,
    access_token: str,
) -> None:
    """Test the re-authentication case updates the correct config entry.

    Make sure we abort if the user selects the
    wrong account on the consent screen.
    """
    config_entry.add_to_hass(hass)

    config_entry.async_start_reauth(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    result = flows[0]
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": "https://example.com/auth/external/callback",
        },
    )
    assert result["url"] == (
        f"{GOOGLE_AUTH_URI}?response_type=code&client_id={CLIENT_ID}"
        "&redirect_uri=https://example.com/auth/external/callback"
        f"&state={state}&scope={'+'.join(SCOPES)}"
        "&access_type=offline&prompt=consent"
    )
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        GOOGLE_TOKEN_URI,
        json={
            "refresh_token": "mock-refresh-token",
            "access_token": "updated-access-token",
            "type": "Bearer",
            "expires_in": 60,
        },
    )

    with patch(
        "homeassistant.components.youtube.async_setup_entry", return_value=True
    ) as mock_setup, patch(
        "httplib2.Http.request",
        return_value=(
            Response({}),
            bytes(load_fixture(f"youtube/{fixture}.json"), encoding="UTF-8"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    assert result["type"] == "abort"
    assert result["reason"] == abort_reason
    assert result["description_placeholders"] == placeholders
    assert len(mock_setup.mock_calls) == calls

    assert config_entry.unique_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert "token" in config_entry.data
    # Verify access token is refreshed
    assert config_entry.data["token"]["access_token"] == access_token
    assert config_entry.data["token"]["refresh_token"] == "mock-refresh-token"


async def test_flow_exception(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
) -> None:
    """Check full flow."""
    result = await hass.config_entries.flow.async_init(
        "youtube", context={"source": config_entries.SOURCE_USER}
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": "https://example.com/auth/external/callback",
        },
    )

    assert result["url"] == (
        f"{GOOGLE_AUTH_URI}?response_type=code&client_id={CLIENT_ID}"
        "&redirect_uri=https://example.com/auth/external/callback"
        f"&state={state}&scope={'+'.join(SCOPES)}"
        "&access_type=offline&prompt=consent"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    with patch(
        "homeassistant.components.youtube.config_flow.build", side_effect=Exception
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "unknown"
