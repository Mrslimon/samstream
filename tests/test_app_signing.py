"""App signing: options menus, Samsung sign-in hand-off, import, signed installs."""

import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from aiosamstream import SAMSTREAM_APP_ID, InstallResult
from aiosamstream.samsung_cert import SamsungAccount, SamsungCertError
from aiosamstream.signing import SigningIdentity
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream import installer
from custom_components.samstream.app_signing import (
    SOURCE_IMPORT,
    SOURCE_SAMSUNG,
    SigningSetup,
    async_load_signing,
    async_save_signing,
)
from custom_components.samstream.config_flow import callback_body

DUID = "EXCBZZZZGFIFJSY"
OTHER_DUID = "ABCD1234WXYZ"
ACCOUNT = SamsungAccount("token", "user-1", "me@example.com")
INSTALL_BUTTON = "button.65_neo_qled_8k_install_samstream_app"


def identity(duids: list[str] | None = None) -> SigningIdentity:
    """A key and a one-certificate chain, optionally listing DUIDs in its SAN."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=365))
    )
    if duids is not None:
        uris = [x509.UniformResourceIdentifier("URN:tizen:packageid=")] + [
            x509.UniformResourceIdentifier(f"URN:tizen:deviceid={d}") for d in duids
        ]
        builder = builder.add_extension(
            x509.SubjectAlternativeName(uris), critical=False
        )
    return SigningIdentity(key=key, chain=(builder.sign(key, hashes.SHA256()),))


def setup_for(duids: list[str], source: str = SOURCE_SAMSUNG) -> SigningSetup:
    return SigningSetup(
        author=identity(),
        distributor=identity(duids),
        source=source,
        email="me@example.com",
    )


def write_p12(path: Path, ident: SigningIdentity, password: bytes) -> None:
    path.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"usercertificate",
            ident.key,
            ident.chain[0],
            None,
            serialization.BestAvailableEncryption(password),
        )
    )


async def _options(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


@pytest.mark.usefixtures("mock_tv")
async def test_store_round_trip(hass: HomeAssistant) -> None:
    assert await async_load_signing(hass) is None
    setup = setup_for([DUID])
    await async_save_signing(hass, setup)

    loaded = await async_load_signing(hass)
    assert loaded is not None
    assert loaded.duids == [DUID]
    assert loaded.covers(DUID)
    assert not loaded.covers(OTHER_DUID)
    assert loaded.source == SOURCE_SAMSUNG
    assert loaded.email == "me@example.com"
    assert loaded.author.chain == setup.author.chain
    assert loaded.expires == setup.expires


async def test_app_signing_menu_status(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await _options(hass, setup_entry, "app_signing")
    assert result["type"] is FlowResultType.MENU
    assert result["description_placeholders"] == {"status": "not set up"}
    assert result["menu_options"] == [
        "samsung_sign_in",
        "samsung_paste",
        "import_certificates",
    ]


async def test_sign_in_through_helper_view(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    obtained = setup_for([DUID])
    with patch(
        "custom_components.samstream.config_flow.async_obtain_samsung_certificates",
        AsyncMock(return_value=obtained),
    ) as obtain:
        result = await _options(hass, setup_entry, "app_signing")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "samsung_sign_in"}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        command = result["description_placeholders"]["command"]
        assert command.startswith("npx samstream-signin ")
        code = command.split()[-1]

        # What `npx samstream-signin <ha> <code>` does:
        client = await hass_client_no_auth()
        response = await client.get(f"/api/samstream/signin/{code}")
        assert response.status == 200
        url = (await response.json())["sign_in_url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        callback = urlencode(
            {
                "code": json.dumps(
                    {
                        "access_token": "token",
                        "userId": "user-1",
                        "inputEmailID": "me@example.com",
                        "state": state,
                    }
                )
            }
        )
        response = await client.post(
            f"/api/samstream/signin/{code}", json={"body": callback}
        )
        assert response.status == 200
        # The code is single-use.
        again = await client.post(f"/api/samstream/signin/{code}", json={"body": "x"})
        assert again.status == 404

        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "signing_ready"
    assert "1 TV(s)" in result["description_placeholders"]["status"]
    obtain.assert_awaited_once()
    assert obtain.await_args.args[2] == ACCOUNT


async def test_sign_in_timeout_then_retry(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with patch("custom_components.samstream.config_flow.SIGN_IN_TIMEOUT", 0.01):
        result = await _options(hass, setup_entry, "app_signing")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "samsung_sign_in"}
        )
        while result["type"] in (
            FlowResultType.SHOW_PROGRESS,
            FlowResultType.SHOW_PROGRESS_DONE,
        ):
            await hass.async_block_till_done()
            result = await hass.config_entries.options.async_configure(
                result["flow_id"]
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "signing_failed"
        assert result["errors"] == {"base": "sign_in_timeout"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
    hass.config_entries.options.async_abort(result["flow_id"])


async def test_view_rejects_unknown_and_bad_requests(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    client = await hass_client_no_auth()
    assert (await client.get("/api/samstream/signin/nope")).status == 404
    assert (
        await client.post("/api/samstream/signin/nope", json={"body": "x"})
    ).status == 404

    result = await _options(hass, setup_entry, "app_signing")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "samsung_sign_in"}
    )
    code = result["description_placeholders"]["command"].split()[-1]
    bad = await client.post(f"/api/samstream/signin/{code}", data=b"not json")
    assert bad.status == 400
    hass.config_entries.options.async_abort(result["flow_id"])


async def test_sign_in_by_paste(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    obtained = setup_for([DUID])
    with patch(
        "custom_components.samstream.config_flow.async_obtain_samsung_certificates",
        AsyncMock(return_value=obtained),
    ):
        result = await _options(hass, setup_entry, "app_signing")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "samsung_paste"}
        )
        assert result["type"] is FlowResultType.FORM
        url = result["description_placeholders"]["url"]
        state = parse_qs(urlparse(url).query)["state"][0]

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"code": "garbage"}
        )
        assert result["errors"] == {"base": "sign_in_failed"}

        pasted = json.dumps(
            {
                "access_token": "token",
                "userId": "user-1",
                "inputEmailID": "me@example.com",
                "state": state,
            }
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"code": pasted}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "signing_ready"


@pytest.mark.parametrize(
    "pasted",
    [
        '{"a": 1}',
        "%7B%22a%22%3A%201%7D",
        "code=%7B%22a%22%3A%201%7D",
        "state=x&code=%7B%22a%22%3A%201%7D",
    ],
)
def test_callback_body_accepts_devtools_formats(pasted: str) -> None:
    assert parse_qs(callback_body(pasted))["code"] == ['{"a": 1}']


async def test_import_certificates(
    hass: HomeAssistant, setup_entry: MockConfigEntry, tmp_path: Path
) -> None:
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    write_p12(tmp_path / "author.p12", identity(), b"pw")
    write_p12(tmp_path / "distributor.p12", identity([DUID]), b"pw")
    form = {
        "author_p12": str(tmp_path / "author.p12"),
        "distributor_p12": str(tmp_path / "distributor.p12"),
        "password": "wrong",
    }
    with patch(
        "custom_components.samstream.installer.async_read_duid",
        AsyncMock(return_value=DUID),
    ):
        result = await _options(hass, setup_entry, "app_signing")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "import_certificates"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], form
        )
        assert result["errors"] == {"base": "bad_certificate"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**form, "password": "pw"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "signing_ready"
    stored = await async_load_signing(hass)
    assert stored is not None
    assert stored.source == SOURCE_IMPORT
    assert stored.covers(DUID)


async def test_import_rejects_certificate_for_other_tv(
    hass: HomeAssistant, setup_entry: MockConfigEntry, tmp_path: Path
) -> None:
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    write_p12(tmp_path / "author.p12", identity(), b"pw")
    write_p12(tmp_path / "distributor.p12", identity([OTHER_DUID]), b"pw")
    with (
        patch(
            "custom_components.samstream.installer.async_read_duid",
            AsyncMock(return_value=DUID),
        ),
        pytest.raises(ServiceValidationError) as err,
    ):
        await installer.async_import_certificates(
            hass,
            setup_entry,
            (tmp_path / "author.p12", tmp_path / "distributor.p12"),
            "pw",
        )
    assert err.value.translation_key == "duid_not_covered"


async def test_import_missing_file(
    hass: HomeAssistant, setup_entry: MockConfigEntry, tmp_path: Path
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await installer.async_import_certificates(
            hass, setup_entry, (tmp_path / "a.p12", tmp_path / "d.p12"), "pw"
        )
    assert err.value.translation_key == "file_not_found"


async def test_obtain_new_certificates(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    author = identity()
    distributor = identity([DUID])
    with (
        patch(
            "custom_components.samstream.installer.async_read_duid",
            AsyncMock(return_value=DUID),
        ),
        patch(
            "custom_components.samstream.installer.request_author",
            AsyncMock(return_value=author),
        ) as request_author,
        patch(
            "custom_components.samstream.installer.request_distributor",
            AsyncMock(return_value=(distributor, b"<profile/>")),
        ) as request_distributor,
    ):
        setup = await installer.async_obtain_samsung_certificates(
            hass, setup_entry, ACCOUNT
        )

    request_author.assert_awaited_once()
    assert request_distributor.await_args.args[3] == [DUID]
    assert setup.source == SOURCE_SAMSUNG
    assert setup.email == "me@example.com"
    assert (await async_load_signing(hass)) is not None


async def test_obtain_adds_tv_and_keeps_author(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    current = setup_for([OTHER_DUID])
    await async_save_signing(hass, current)
    with (
        patch(
            "custom_components.samstream.installer.async_read_duid",
            AsyncMock(return_value=DUID),
        ),
        patch(
            "custom_components.samstream.installer.request_author", AsyncMock()
        ) as request_author,
        patch(
            "custom_components.samstream.installer.request_distributor",
            AsyncMock(return_value=(identity([OTHER_DUID, DUID]), b"")),
        ) as request_distributor,
    ):
        setup = await installer.async_obtain_samsung_certificates(
            hass, setup_entry, ACCOUNT
        )

    request_author.assert_not_awaited()
    _session, _account, key, duids = request_distributor.await_args.args
    assert key.private_numbers() == current.author.key.private_numbers()
    assert duids == sorted([OTHER_DUID, DUID])
    assert setup.author.chain == current.author.chain
    assert setup.covers(DUID)


async def test_obtain_when_already_covered(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    await async_save_signing(hass, setup_for([DUID]))
    with (
        patch(
            "custom_components.samstream.installer.async_read_duid",
            AsyncMock(return_value=DUID),
        ),
        patch(
            "custom_components.samstream.installer.request_distributor", AsyncMock()
        ) as request,
    ):
        setup = await installer.async_obtain_samsung_certificates(
            hass, setup_entry, ACCOUNT
        )

    request.assert_not_awaited()
    assert setup.covers(DUID)


async def test_obtain_samsung_refuses(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with (
        patch(
            "custom_components.samstream.installer.async_read_duid",
            AsyncMock(return_value=DUID),
        ),
        patch(
            "custom_components.samstream.installer.request_author",
            AsyncMock(side_effect=SamsungCertError("401")),
        ),
        pytest.raises(HomeAssistantError) as err,
    ):
        await installer.async_obtain_samsung_certificates(hass, setup_entry, ACCOUNT)
    assert err.value.translation_key == "samsung_refused"


@pytest.fixture
def sdb() -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.duid = AsyncMock(return_value=DUID)
    client.install = AsyncMock(
        return_value=InstallResult(SAMSTREAM_APP_ID, ["install completed"])
    )
    with patch("custom_components.samstream.installer.SdbClient", return_value=client):
        yield client


@pytest.mark.usefixtures("sdb")
async def test_button_needs_signing(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "button", "press", {"entity_id": INSTALL_BUTTON}, blocking=True
        )
    assert err.value.translation_key == "signing_not_set_up"


async def test_button_signs_bundled_app(
    hass: HomeAssistant, setup_entry: MockConfigEntry, sdb: MagicMock
) -> None:
    await async_save_signing(hass, setup_for([DUID]))
    await hass.services.async_call(
        "button", "press", {"entity_id": INSTALL_BUTTON}, blocking=True
    )

    pushed, app_id = sdb.install.await_args.args
    assert app_id == SAMSTREAM_APP_ID
    names = zipfile.ZipFile(io.BytesIO(pushed)).namelist()
    assert names[:2] == ["author-signature.xml", "signature1.xml"]
    assert "config.xml" in names


async def test_read_duid(
    hass: HomeAssistant, setup_entry: MockConfigEntry, sdb: MagicMock
) -> None:
    assert await installer.async_read_duid(hass, setup_entry) == DUID
    sdb.close.assert_awaited()
