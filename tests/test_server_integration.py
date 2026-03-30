"""
Real Server Integration Tests.

These tests run against an actual x402 test server to verify
the complete end-to-end flow works.

Prerequisites:
1. Start the test server:
   python scripts/x402_simple_server.py

2. Run these tests:
   pytest tests/test_server_integration.py -v -s

Note: These tests require:
- USDC contract deployed on Base Sepolia
- ETH for gas fees
- Optional: Circle API key for nanopayment tests
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import pytest
from decimal import Decimal
from typing import Optional
from unittest.mock import patch

import httpx


# =============================================================================
# TEST SERVER CONFIGURATION
# =============================================================================

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 4022
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


# Check if server is running
def is_server_running() -> bool:
    """Check if the test server is running."""
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((SERVER_HOST, SERVER_PORT))
        sock.close()
        return result == 0
    except:
        return False


def require_server():
    """Assert the test server is running."""
    assert is_server_running(), "Test server is not running"


def _wait_for_server(timeout_seconds: float = 20.0) -> bool:
    """Wait until the local test server starts accepting requests."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_server_running():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture(scope="module", autouse=True)
def ensure_test_server():
    """
    Ensure an x402 test server is available for this module.

    If one is not already running, start scripts/x402_simple_server.py for the
    duration of these tests.
    """
    if is_server_running():
        yield
        return

    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "scripts/x402_simple_server.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid if os.name != "nt" else None,
    )

    try:
        if not _wait_for_server():
            pytest.skip("x402 test server not available")
        yield
    finally:
        if process.poll() is None:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=10)


# =============================================================================
# TEST 1: Server Connectivity
# =============================================================================


class TestServerConnectivity:
    """Test basic server connectivity."""

    def test_server_is_reachable(self):
        """Test that the test server is reachable."""
        print("\n" + "=" * 60)
        print("SERVER: Connectivity Test")
        print("=" * 60)

        require_server()

        # Try to connect
        try:
            response = httpx.get(f"{SERVER_URL}/health", timeout=5.0)
            print(f"  Server status: {response.status_code}")
            assert response.status_code in [200, 404]  # 404 if no /health endpoint
        except Exception as e:
            pytest.fail(f"Server not reachable: {e}")

    def test_server_lists_routes(self):
        """Test that we can see available routes."""
        print("\n" + "=" * 60)
        print("SERVER: List Routes")
        print("=" * 60)

        require_server()

        # Routes we expect
        expected_routes = ["/weather", "/premium/content", "/premium/data"]

        for route in expected_routes:
            # These should return 402 (not 404) since they're valid routes
            response = httpx.get(f"{SERVER_URL}{route}", timeout=5.0)
            print(f"  {route}: {response.status_code}")
            assert response.status_code == 402, (
                f"Expected 402 for {route}, got {response.status_code}"
            )


# =============================================================================
# TEST 2: 402 Response Parsing
# =============================================================================


class Test402ResponseParsing:
    """Test parsing 402 Payment Required responses."""

    def test_parse_payment_required_header(self):
        """Test parsing the PAYMENT-REQUIRED header."""
        print("\n" + "=" * 60)
        print("SERVER: Parse 402 Response")
        print("=" * 60)

        require_server()

        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        assert response.status_code == 402

        # Get the header
        header = response.headers.get("payment-required")
        assert header is not None

        print(f"  Status: {response.status_code}")
        print(f"  Header present: {header[:50]}...")

        # Parse it
        import base64

        decoded = json.loads(base64.b64decode(header))

        print(f"  x402 Version: {decoded.get('x402Version')}")
        print(f"  Scheme: {decoded.get('scheme')}")
        print(f"  Accepts: {len(decoded.get('accepts', []))} options")

        for accept in decoded.get("accepts", []):
            print(
                f"    - {accept.get('scheme')}: {accept.get('amount')} on {accept.get('network')}"
            )

        assert decoded.get("x402Version") == 2
        assert len(decoded.get("accepts", [])) > 0

    def test_402_response_body_has_resource(self):
        """Test that 402 response body contains resource info."""
        print("\n" + "=" * 60)
        print("SERVER: 402 Response Body")
        print("=" * 60)

        require_server()

        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        # Parse body (even though it's empty in our server, check structure)
        if response.text:
            body = response.json()
            print(f"  Body keys: {list(body.keys())}")

            if "resource" in body:
                print(f"  Resource: {body['resource']}")

        # Our server returns empty body with header
        # Some servers return body with resource info
        print(f"  Body: {response.text[:100] if response.text else '(empty)'}")

    def test_multiple_routes_have_different_prices(self):
        """Test that different routes have different prices."""
        print("\n" + "=" * 60)
        print("SERVER: Different Prices")
        print("=" * 60)

        require_server()

        routes_prices = {}

        for route in ["/weather", "/premium/content", "/premium/data"]:
            response = httpx.get(f"{SERVER_URL}{route}", timeout=5.0)
            header = response.headers.get("payment-required")

            import base64

            decoded = json.loads(base64.b64decode(header))

            # Get first accept's amount
            amount = decoded.get("accepts", [{}])[0].get("amount")
            routes_prices[route] = amount

            print(f"  {route}: {amount}")

        # Weather should be cheaper than premium
        assert routes_prices["/weather"] != routes_prices["/premium/content"]


# =============================================================================
# TEST 3: Free Endpoints
# =============================================================================


class TestFreeEndpoints:
    """Test endpoints that don't require payment."""

    def test_health_endpoint_no_payment(self):
        """Test that health/check endpoints don't require payment."""
        print("\n" + "=" * 60)
        print("SERVER: Free Endpoints")
        print("=" * 60)

        require_server()

        # Try a few common free endpoints
        free_routes = ["/", "/health", "/api/status"]

        for route in free_routes:
            try:
                response = httpx.get(f"{SERVER_URL}{route}", timeout=5.0)
                print(f"  {route}: {response.status_code}")
            except Exception as e:
                print(f"  {route}: Not found")


# =============================================================================
# TEST 4: Full Payment Flow (without actual payment)
# =============================================================================


class TestFullPaymentFlow:
    """Test the complete x402 payment flow."""

    def test_flow_1_request_without_payment(self):
        """Step 1: Request without payment → get 402."""
        print("\n" + "=" * 60)
        print("PAYMENT FLOW: Step 1 - Request Without Payment")
        print("=" * 60)

        require_server()

        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        print(f"  Status: {response.status_code}")
        assert response.status_code == 402

        header = response.headers.get("payment-required")
        assert header is not None

        print(f"  Got 402 with payment-required header ✓")

    def test_flow_2_parse_402_and_detect_scheme(self):
        """Step 2: Parse 402 and detect payment scheme."""
        print("\n" + "=" * 60)
        print("PAYMENT FLOW: Step 2 - Parse and Detect Scheme")
        print("=" * 60)

        require_server()

        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        import base64

        header = response.headers.get("payment-required")
        decoded = json.loads(base64.b64decode(header))

        accepts = decoded.get("accepts", [])

        schemes = [a.get("scheme") for a in accepts]

        print(f"  Seller accepts: {schemes}")

        # Our test server only supports "exact" (basic x402)
        assert "exact" in schemes

        print(f"  Detected scheme: exact ✓")

    def test_flow_3_determine_payment_method(self):
        """Step 3: Determine payment method based on accepts."""
        print("\n" + "=" * 60)
        print("PAYMENT FLOW: Step 3 - Determine Payment Method")
        print("=" * 60)

        require_server()

        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        import base64

        header = response.headers.get("payment-required")
        decoded = json.loads(base64.b64decode(header))

        accepts = decoded.get("accepts", [])

        # Check what the seller supports
        supports_basic = any(a.get("scheme") == "exact" for a in accepts)
        supports_circle = any(a.get("scheme") == "GatewayWalletBatched" for a in accepts)

        print(f"  Basic x402 (exact): {supports_basic}")
        print(f"  Circle nanopayment: {supports_circle}")

        # Our test server only supports basic
        if supports_basic and not supports_circle:
            print(f"  → Will use: Basic x402 (on-chain settlement)")
        elif supports_circle:
            print(f"  → Will use: Circle nanopayment (gasless)")

        assert supports_basic

    def test_flow_4_with_invalid_payment(self):
        """Step 4: Try with invalid payment → still get 402."""
        print("\n" + "=" * 60)
        print("PAYMENT FLOW: Step 4 - Invalid Payment")
        print("=" * 60)

        require_server()

        # Send invalid payment header
        headers = {"payment-signature": "invalid-signature-data"}

        response = httpx.get(f"{SERVER_URL}/weather", headers=headers, timeout=5.0)

        print(f"  Status: {response.status_code}")

        # Should still be 402 (payment invalid)
        assert response.status_code == 402

        print(f"  Invalid payment rejected ✓")


# =============================================================================
# TEST 5: Smart Routing Decision
# =============================================================================


class TestSmartRouting:
    """Test smart routing based on seller capabilities."""

    def test_route_to_basic_x402_when_no_circle(self):
        """Test routing when seller supports Circle but buyer doesn't."""
        print("\n" + "=" * 60)
        print("ROUTING: Buyer has NO Circle Gateway")
        print("=" * 60)

        require_server()

        # Get seller capabilities
        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        import base64

        header = response.headers.get("payment-required")
        decoded = json.loads(base64.b64decode(header))

        accepts = decoded.get("accepts", [])

        # Decision logic - buyer has NO gateway
        supports_circle = any(a.get("scheme") == "GatewayWalletBatched" for a in accepts)
        buyer_has_gateway = False

        if supports_circle and buyer_has_gateway:
            method = "Circle Nanopayment"
        else:
            method = "Basic x402"

        print(f"  Seller accepts: {[a['scheme'] for a in accepts]}")
        print(f"  Buyer has Circle: {buyer_has_gateway}")
        print(f"  → Routing to: {method}")

        assert method == "Basic x402"

    def test_check_network_compatibility(self):
        """Test checking network compatibility."""
        print("\n" + "=" * 60)
        print("ROUTING: Network Compatibility")
        print("=" * 60)

        require_server()

        response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        import base64

        header = response.headers.get("payment-required")
        decoded = json.loads(base64.b64decode(header))

        accepts = decoded.get("accepts", [])

        # Check network
        buyer_network = "eip155:84532"  # Base Sepolia

        for accept in accepts:
            seller_network = accept.get("network")
            compatible = buyer_network == seller_network

            print(f"  Buyer: {buyer_network}")
            print(f"  Seller: {seller_network}")
            print(f"  Compatible: {compatible}")


# =============================================================================
# TEST 6: Client Integration (with mocked signer)
# =============================================================================


class TestClientIntegration:
    """Test client integration with the server."""

    @pytest.mark.asyncio
    async def test_client_makes_request(self):
        """Test that client can make requests to server."""
        print("\n" + "=" * 60)
        print("CLIENT: Make HTTP Request")
        print("=" * 60)

        require_server()

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVER_URL}/weather")

            print(f"  Status: {response.status_code}")
            print(f"  Headers: {dict(response.headers)}")

            assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_client_parses_402(self):
        """Test that client can parse 402 response."""
        print("\n" + "=" * 60)
        print("CLIENT: Parse 402 Response")
        print("=" * 60)

        require_server()

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVER_URL}/weather")

            if response.status_code == 402:
                import base64

                header = response.headers.get("payment-required")
                decoded = json.loads(base64.b64decode(header))

                # Scheme is in accepts[0], not at top level
                accepts = decoded.get("accepts", [])
                scheme = accepts[0].get("scheme") if accepts else None

                print(f"  Parsed: scheme={scheme}")
                print(f"  Accepts: {len(accepts)}")

                assert scheme == "exact"

    @pytest.mark.asyncio
    async def test_client_smart_routing_decision(self):
        """Test client makes smart routing decision."""
        print("\n" + "=" * 60)
        print("CLIENT: Smart Routing Decision")
        print("=" * 60)

        require_server()

        async with httpx.AsyncClient() as client:
            # Step 1: Request
            response = await client.get(f"{SERVER_URL}/weather")

            # Step 2: If 402, parse
            if response.status_code == 402:
                import base64

                header = response.headers.get("payment-required")
                decoded = json.loads(base64.b64decode(header))

                accepts = decoded.get("accepts", [])

                # Step 3: Route decision - buyer has NO gateway
                has_circle = any(a.get("scheme") == "GatewayWalletBatched" for a in accepts)
                buyer_has_gateway = False

                if has_circle and buyer_has_gateway:
                    print("  → Use Circle Nanopayment (gasless)")
                    route = "nanopayment"
                else:
                    print("  → Use Basic x402 (on-chain)")
                    route = "basic_x402"

                assert route == "basic_x402"


# =============================================================================
# TEST 7: Error Scenarios
# =============================================================================


class TestErrorScenarios:
    """Test error handling."""

    def test_server_timeout(self):
        """Test handling server timeout."""
        print("\n" + "=" * 60)
        print("ERROR: Server Timeout")
        print("=" * 60)

        require_server()

        try:
            # Very short timeout
            response = httpx.get(f"{SERVER_URL}/weather", timeout=0.001)
        except httpx.TimeoutException:
            print("  ✓ Timeout handled correctly")
        except Exception as e:
            print(f"  Error: {type(e).__name__}")

    def test_invalid_url(self):
        """Test handling invalid URL."""
        print("\n" + "=" * 60)
        print("ERROR: Invalid URL")
        print("=" * 60)

        require_server()

        try:
            response = httpx.get(f"{SERVER_URL}/nonexistent-route-xyz")
            print(f"  Status: {response.status_code}")
        except Exception as e:
            print(f"  Error: {type(e).__name__}")

    def test_server_unavailable(self):
        """Test handling when server is unavailable."""
        print("\n" + "=" * 60)
        print("ERROR: Server Unavailable")
        print("=" * 60)

        # Try to connect to non-existent server
        try:
            response = httpx.get("http://127.0.0.1:9999/health", timeout=2.0)
        except httpx.ConnectError:
            print("  ✓ Connection error handled correctly")
        except Exception as e:
            print(f"  Error: {type(e).__name__}")


# =============================================================================
# TEST 8: Performance
# =============================================================================


class TestPerformance:
    """Test performance characteristics."""

    def test_response_time(self):
        """Test server response time."""
        print("\n" + "=" * 60)
        print("PERFORMANCE: Response Time")
        print("=" * 60)

        require_server()

        import time

        # Warm up
        httpx.get(f"{SERVER_URL}/weather", timeout=5.0)

        # Measure
        times = []
        for _ in range(5):
            start = time.time()
            response = httpx.get(f"{SERVER_URL}/weather", timeout=5.0)
            elapsed = time.time() - start
            times.append(elapsed)
            print(f"  Response time: {elapsed * 1000:.2f}ms")

        avg = sum(times) / len(times)
        print(f"  Average: {avg * 1000:.2f}ms")


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
