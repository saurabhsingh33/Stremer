# Windows Client

Connects to Android server, browses files, streams videos, and manages storage.

## Setup

Install Python 3.10+ and then install dependencies:

```
pip install -r requirements.txt
```

Optionally run the mock server for testing:

```
pip install -r mock-server/requirements.txt
python -m uvicorn mock-server.app:app --host 0.0.0.0 --port 8000
```

Run the client:

```
python src/main.py
```

On first run, click Login and enter:

- Server URL: http://127.0.0.1:8000
- Username: admin
- Password: password

To play videos, ensure VLC is installed. The client will attempt to launch VLC with the stream URL.
