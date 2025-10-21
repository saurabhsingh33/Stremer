# Android Server

Hosts external/mobile storage over LAN with authentication and file operations.

## Planned Architecture

- Kotlin Android app using Jetpack Compose for modern UI.
- Embedded Ktor HTTP server exposing REST endpoints:
  - POST /auth/login — returns token
  - GET /files?path=/ — list directories/files
  - GET /stream?path=/file.mp4 — stream file over HTTP
  - DELETE /file?path=/ — delete file/folder
  - POST /copy {src,dst} — copy file/folder
- Storage Access Framework (SAF) to let users select attached storage (USB/SD/external).
- Basic username/password stored securely; token-based requests.

Client (Windows) will consume these endpoints to browse, stream, copy and delete without downloading.
