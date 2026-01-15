import http.server
import socketserver
import json
import base64
import sys

PORT = 8000
PAYMENT_ADDRESS = "0x8979313437651086C21235D62DD8685e13D30B9f"  # Demo Address
AMOUNT = "100000"  # 0.1 USDC (6 decimals)

class X402Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/premium":
            self.handle_premium()
        else:
            self.send_error(404, "Not Found")
            
    def handle_premium(self):
        # Check for V2 Header
        sig_header = self.headers.get("PAYMENT-SIGNATURE")
        
        if sig_header:
            print(f"[Server] Received PAYMENT-SIGNATURE: {sig_header[:20]}...")
            try:
                # Basic decoding to verify structure
                decoded_json = base64.b64decode(sig_header).decode()
                payload = json.loads(decoded_json)
                
                # Verify payload structure (mock verification)
                if payload.get("x402Version") == 2 and "transactionHash" in payload.get("payload", {}):
                    print(f"[Server] Valid Signature! Tx: {payload['payload']['transactionHash']}")
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("PAYMENT-RESPONSE", "proof-of-service-token")
                    self.end_headers()
                    
                    response = {"data": "PREMIUM DATA UNLOCKED", "status": "paid"}
                    self.wfile.write(json.dumps(response).encode())
                    return
                else:
                    print("[Server] Invalid Signature Payload")
            except Exception as e:
                print(f"[Server] Signature Decode Error: {e}")
        
        # Default: 402 Payment Required
        print("[Server] Sending 402 Payment Required")
        self.send_response(402)
        self.send_header("Content-Type", "application/json")
        # Legacy header for backward compat testing (optional, but good practice)
        # self.send_header("X-Payment-Required", "...") 
        self.end_headers()
        
        requirements = {
            "requirements": {
                "scheme": "exact",
                "network": "base",
                "amount": AMOUNT,
                "token": "USDC",
                "paymentAddress": PAYMENT_ADDRESS,
                "resource": "http://localhost:8000/premium",
                "description": "Access to premium content (E2E Test)"
            }
        }
        self.wfile.write(json.dumps(requirements).encode())

if __name__ == "__main__":
    # Allow address reuse to avoid "Address already in use" during quick restarts
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), X402Handler) as httpd:
        print(f"Serving x402 V2 at port {PORT}")
        print(f"Test URL: http://localhost:{PORT}/premium")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            httpd.server_close()
