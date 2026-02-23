import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Global mock for circle dependencies to allow tests to run without the package installed
if "circle" not in sys.modules:
    sys.modules["circle"] = MagicMock()
    sys.modules["circle.web3"] = MagicMock()
    sys.modules["circle.web3.developer_controlled_wallets"] = MagicMock()


@pytest.fixture(autouse=True)
def mock_circle_client(monkeypatch):
    """Automatically mock CircleClient for all tests to prevent network calls."""
    mock_client = AsyncMock()

    # Default positive balance for most tests
    mock_client.get_wallet_balance.return_value = {"amount": "1000.00", "currency": "USD"}

    # Default wallet info
    mock_client.get_wallet.return_value = MagicMock(
        id="wallet-123", blockchain="MATIC-MUMBAI", address="0x123"
    )

    # Default transfer
    mock_client.create_transaction.return_value = {
        "id": "tx-123",
        "state": "CONFIRMED",
        "transactionHash": "0xabc",
    }

    # Patch the class in omniclaw.core.circle_client
    # We patch it where it is imported/used, which is effectively the class definition
    with monkeypatch.context() as m:
        m.setattr(
            "omniclaw.core.circle_client.CircleClient", MagicMock(return_value=mock_client)
        )
        yield mock_client
