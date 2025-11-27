#!/usr/bin/env python3
"""One-time script to get Spotify refresh token via OAuth."""

import http.server
import socketserver
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CLIENT_ID = "e6c00b53dccd4c47906411813bf327f5"
CLIENT_SECRET = "44db6c0852f64e508e0575c26a7eaa82"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
PORT = 8888

SCOPES = " ".join(
    [
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "user-read-recently-played",
        "user-library-read",
        "user-library-modify",
        "playlist-read-private",
        "playlist-modify-public",
        "playlist-modify-private",
    ]
)

# Global to store the auth code
auth_code = None


class CallbackHandler(http.server.SimpleHTTPRequestHandler):
    """Handle the OAuth callback."""

    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)

        if parsed.path == "/callback":
            query = parse_qs(parsed.query)
            if "code" in query:
                auth_code = query["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Success!</h1>"
                    b"<p>You can close this window and return to the terminal.</p>"
                    b"</body></html>"
                )
            elif "error" in query:
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                error = query.get("error", ["unknown"])[0]
                self.wfile.write(
                    f"<html><body><h1>Error: {error}</h1></body></html>".encode()
                )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logging


def main():
    global auth_code

    # Step 1: Build authorization URL
    auth_url = "https://accounts.spotify.com/authorize?" + urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        }
    )

    # Step 2: Start local server to receive callback
    print(f"Starting local server on port {PORT}...")
    with socketserver.TCPServer(("127.0.0.1", PORT), CallbackHandler) as httpd:
        httpd.timeout = 120  # 2 minute timeout

        print("Opening browser for Spotify authorization...")
        print(f"\nIf browser doesn't open, go to:\n{auth_url}\n")
        webbrowser.open(auth_url)

        print("Waiting for authorization (timeout: 2 minutes)...")

        # Handle requests until we get the code
        while auth_code is None:
            httpd.handle_request()

    if not auth_code:
        print("Error: No authorization code received")
        return

    # Step 3: Exchange code for tokens
    print("\nExchanging code for tokens...")
    response = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        return

    data = response.json()

    print("\n" + "=" * 50)
    print("SUCCESS! Here's your refresh token:")
    print("=" * 50)
    print(f"\nSPOTIFY_REFRESH_TOKEN={data['refresh_token']}")
    print("\n" + "=" * 50)
    print("\nAdd this to your .env file and Google Cloud Secret Manager")


if __name__ == "__main__":
    main()
