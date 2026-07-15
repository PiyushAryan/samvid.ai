from pathlib import Path

import pytest

from contractmate.db.repositories.contracts import ContractRepository
from contractmate.db.repositories.signing import SigningConflict, SigningRepository
from contractmate.db.session import connect
from contractmate.schemas.signing import SignerCreate, SignerStatus, SignerStatusEventCreate, SigningRequestCreate


def test_signing_request_enforces_case_insensitive_signer_uniqueness(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'samvid.db'}")
    contract_id = _contract(connection)
    signing = SigningRepository(connection)

    with pytest.raises(SigningConflict) as exc:
        signing.create_request(
            workspace_id="W1",
            contract_id=contract_id,
            payload=SigningRequestCreate(
                signers=[
                    SignerCreate(name="A", email="legal@example.com"),
                    SignerCreate(name="B", email="LEGAL@example.com"),
                ]
            ),
            actor_email="actor@example.com",
            actor_name="Actor",
        )

    assert exc.value.code == "duplicate_signer_email"


def test_signing_request_enforces_one_active_request_per_contract(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'samvid.db'}")
    contract_id = _contract(connection)
    signing = SigningRepository(connection)

    signing.create_request(
        workspace_id="W1",
        contract_id=contract_id,
        payload=SigningRequestCreate(signers=[]),
        actor_email="actor@example.com",
        actor_name="Actor",
    )

    with pytest.raises(SigningConflict) as exc:
        signing.create_request(
            workspace_id="W1",
            contract_id=contract_id,
            payload=SigningRequestCreate(signers=[]),
            actor_email="actor@example.com",
            actor_name="Actor",
        )

    assert exc.value.code == "active_request_exists"


def test_status_events_are_idempotent_and_reject_consecutive_duplicates(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'samvid.db'}")
    contract_id = _contract(connection)
    signing = SigningRepository(connection)
    request = signing.create_request(
        workspace_id="W1",
        contract_id=contract_id,
        payload=SigningRequestCreate(signers=[SignerCreate(name="A", email="a@example.com")]),
        actor_email="actor@example.com",
        actor_name="Actor",
    )
    signer_id = request.signers[0].id

    event = SignerStatusEventCreate(id="event-1", status=SignerStatus.SENT, note="Sent manually.")
    first = signing.append_event(
        workspace_id="W1",
        signer_id=signer_id,
        payload=event,
        actor_email="actor@example.com",
        actor_name="Actor",
    )
    retry = signing.append_event(
        workspace_id="W1",
        signer_id=signer_id,
        payload=event,
        actor_email="actor@example.com",
        actor_name="Actor",
    )

    assert first.signers[0].latest_status is SignerStatus.SENT
    assert len(retry.signers[0].events) == len(first.signers[0].events)
    with pytest.raises(SigningConflict) as exc:
        signing.append_event(
            workspace_id="W1",
            signer_id=signer_id,
            payload=SignerStatusEventCreate(id="event-2", status=SignerStatus.SENT),
            actor_email="actor@example.com",
            actor_name="Actor",
        )
    assert exc.value.code == "duplicate_consecutive_status"


def test_request_completes_only_after_all_required_signers_are_signed(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'samvid.db'}")
    contract_id = _contract(connection)
    signing = SigningRepository(connection)
    request = signing.create_request(
        workspace_id="W1",
        contract_id=contract_id,
        payload=SigningRequestCreate(
            signers=[
                SignerCreate(name="Required A", email="a@example.com", required=True),
                SignerCreate(name="Required B", email="b@example.com", required=True),
                SignerCreate(name="Optional C", email="c@example.com", required=False),
            ]
        ),
        actor_email="actor@example.com",
        actor_name="Actor",
    )

    one_signed = signing.append_event(
        workspace_id="W1",
        signer_id=request.signers[0].id,
        payload=SignerStatusEventCreate(id="event-a", status=SignerStatus.SIGNED),
        actor_email="actor@example.com",
        actor_name="Actor",
    )
    completed = signing.append_event(
        workspace_id="W1",
        signer_id=request.signers[1].id,
        payload=SignerStatusEventCreate(id="event-b", status=SignerStatus.SIGNED),
        actor_email="actor@example.com",
        actor_name="Actor",
    )

    assert one_signed.status.value == "in_progress"
    assert completed.status.value == "completed"
    assert completed.active is False


def test_terminal_status_can_be_corrected_by_appending_new_event(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'samvid.db'}")
    contract_id = _contract(connection)
    signing = SigningRepository(connection)
    request = signing.create_request(
        workspace_id="W1",
        contract_id=contract_id,
        payload=SigningRequestCreate(signers=[SignerCreate(name="A", email="a@example.com")]),
        actor_email="actor@example.com",
        actor_name="Actor",
    )
    signer_id = request.signers[0].id

    declined = signing.append_event(
        workspace_id="W1",
        signer_id=signer_id,
        payload=SignerStatusEventCreate(id="declined", status=SignerStatus.DECLINED),
        actor_email="actor@example.com",
        actor_name="Actor",
    )
    corrected = signing.append_event(
        workspace_id="W1",
        signer_id=signer_id,
        payload=SignerStatusEventCreate(id="signed", status=SignerStatus.SIGNED, note="Corrected manual entry."),
        actor_email="actor@example.com",
        actor_name="Actor",
    )

    assert declined.status.value == "declined"
    assert corrected.status.value == "completed"
    assert [event.status for event in corrected.signers[0].events][-2:] == [SignerStatus.DECLINED, SignerStatus.SIGNED]


def test_signer_creation_and_status_changes_are_audited(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'samvid.db'}")
    contract_id = _contract(connection)
    signing = SigningRepository(connection)
    request = signing.create_request(
        workspace_id="W1",
        contract_id=contract_id,
        payload=SigningRequestCreate(signers=[SignerCreate(name="A", email="a@example.com")]),
        actor_email="actor@example.com",
        actor_name="Actor",
    )
    signing.append_event(
        workspace_id="W1",
        signer_id=request.signers[0].id,
        payload=SignerStatusEventCreate(id="viewed", status=SignerStatus.VIEWED),
        actor_email="actor@example.com",
        actor_name="Actor",
    )

    event_types = {
        row["event_type"]
        for row in connection.execute("SELECT event_type FROM audit_events WHERE contract_id = ?", (contract_id,)).fetchall()
    }
    assert {"signing_request.created", "signer.created", "signer.status_changed"} <= event_types


def _contract(connection) -> str:
    contract_id, _version_id = ContractRepository(connection).create_contract_with_version(
        workspace_id="W1",
        email_thread_id="thread-1",
        title="Vendor agreement",
        original_filename="vendor.txt",
        mime_type="text/plain",
        size_bytes=10,
        sha256="abc123",
        object_key="W1/ab/abc123.txt",
        uploaded_by="actor@example.com",
    )
    return contract_id
