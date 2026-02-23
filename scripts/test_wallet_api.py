import asyncio
import os
import sys
from unittest.mock import MagicMock

# Setup Mocks
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()
os.environ["CIRCLE_API_KEY"] = "sk_test_mock"
os.environ["ENTITY_SECRET"] = "mock_secret"

from omniclaw import Network, OmniClaw  # noqa: E402
from omniclaw.core.types import (  # noqa: E402
    AccountType,
    CustodyType,
    WalletInfo,
    WalletSetInfo,
    WalletState,
)


async def test_wallet_api():
    print("=== Testing Wallet API Facade ===")

    # Init Client
    client = OmniClaw(network=Network.ARC_TESTNET)

    # Mock WalletService methods
    client._wallet_service.create_wallet = MagicMock(
        return_value=WalletInfo(
            id="w-new",
            address="0xNew",
            blockchain="ARC",
            state=WalletState.LIVE,
            wallet_set_id="ws-mock",
            custody_type=CustodyType.DEVELOPER,
            account_type=AccountType.EOA,
        )
    )
    client._wallet_service.create_wallet_set = MagicMock(
        return_value=WalletSetInfo(
            id="ws-new",
            name="set-new",
            custody_type=CustodyType.DEVELOPER,
            create_date="2023-01-01",
            update_date="2023-01-01",
        )
    )

    # 1. Test Explicit Set Reuse
    print("\n1. Testing create_wallet(wallet_set_id='ws-existing')")
    await client.create_wallet(wallet_set_id="ws-existing")

    # Verify create_wallet_set NOT called
    client._wallet_service.create_wallet_set.assert_not_called()
    # Verify create_wallet called with correct set
    client._wallet_service.create_wallet.assert_called_with(
        wallet_set_id="ws-existing", blockchain=None, account_type=AccountType.EOA
    )
    print("   ✅ Explicit set reuse confirmed")

    # Reset mocks
    client._wallet_service.create_wallet_set.reset_mock()
    client._wallet_service.create_wallet.reset_mock()

    # 2. Test Implicit Set Creation
    print("\n2. Testing create_wallet() (No Set)")
    await client.create_wallet(name="my-set")

    # Verify create_wallet_set called
    client._wallet_service.create_wallet_set.assert_called_once()
    args, kwargs = client._wallet_service.create_wallet_set.call_args
    assert kwargs["name"] == "my-set"

    # Verify create_wallet called with NEW set id
    client._wallet_service.create_wallet.assert_called_with(
        wallet_set_id="ws-new",  # from mock return
        blockchain=None,
        account_type=AccountType.EOA,
    )
    print("   ✅ Implicit set creation confirmed")

    print("\n✅ Wallet API Tests Passed!")


if __name__ == "__main__":
    asyncio.run(test_wallet_api())
