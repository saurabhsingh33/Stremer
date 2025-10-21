"""
Simple test script to verify if streaming is working at HTTP level
"""
import requests
import sys

# Update these values based on your setup
SERVER_URL = "http://192.168.1.9:8080"
TOKEN = "token-admin"  # Your token
VIDEO_PATH = "/Online Learning 2025/Prompt Engineering/ChatGPT Prompting - Coursera/Mod 01/Introduction to Prompt Engineering with Generative AI - Week 1.mp4"

def test_stream():
    print("Testing stream endpoint...")
    stream_url = f"{SERVER_URL}/stream?path={requests.utils.quote(VIDEO_PATH)}&token={TOKEN}"
    print(f"URL: {stream_url}")

    try:
        # Make HEAD request to check headers
        print("\n1. Testing HEAD request...")
        head_response = requests.head(stream_url, timeout=10)
        print(f"Status Code: {head_response.status_code}")
        print("Headers:")
        for key, value in head_response.headers.items():
            print(f"  {key}: {value}")

        # Make GET request for first 1KB to test streaming
        print("\n2. Testing GET request (first 1KB)...")
        get_response = requests.get(stream_url, stream=True, timeout=10)
        print(f"Status Code: {get_response.status_code}")
        print("Headers:")
        for key, value in get_response.headers.items():
            print(f"  {key}: {value}")

        # Read first chunk
        chunk_count = 0
        total_bytes = 0
        for chunk in get_response.iter_content(chunk_size=1024):
            if chunk:
                chunk_count += 1
                total_bytes += len(chunk)
                if chunk_count == 1:
                    print(f"\nFirst chunk received: {len(chunk)} bytes")
                if total_bytes >= 1024:  # Stop after 1KB
                    break

        print(f"Total received: {total_bytes} bytes in {chunk_count} chunks")
        print("\n✓ Stream is working at HTTP level!")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_stream()
