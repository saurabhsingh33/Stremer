# GitHub Actions - Automated Builds & Releases

This workflow automatically builds both the Windows client and Android server, creating GitHub releases on version tags.

## Setup

1. **Push this workflow file** to your repo:

   ```
   .github/workflows/build.yml
   ```

2. **Create a GitHub Actions secret** (optional, for code signing):
   - Go to Settings → Secrets and variables → Actions
   - Add any signing certificates if needed (not required for initial testing)

## How It Works

### Trigger

- **On every push to `main`**: Builds artifacts (stored for 90 days)
- **On version tag push** (e.g., `v1.0.0`): Creates a GitHub Release with both APK and EXE

### Windows Build (`build-windows` job)

1. Checks out code
2. Installs Python 3.11 and dependencies
3. Installs NSIS
4. Runs PyInstaller to create standalone exe
5. Runs NSIS to build installer
6. Uploads `Stremer-Setup.exe`

### Android Build (`build-android` job)

1. Checks out code
2. Sets up Java 11
3. Builds debug APK (for testing)
4. Builds release APK (unsigned, for production)
5. Uploads both APK files

### Release Creation (`create-release` job)

- Runs only when a version tag is pushed (e.g., `git tag v1.0.0`)
- Downloads all artifacts
- Creates a GitHub Release with release notes
- Attaches all build artifacts

## Usage

### To Create a Release

1. **Tag your commit**:

   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

2. **GitHub Actions will**:

   - Build Windows EXE and Android APK
   - Create a GitHub Release at `https://github.com/YourOrg/Stremer/releases/tag/v1.0.0`
   - Attach all artifacts

3. **Share the release link** with testers—they can download directly from GitHub

### To Build Without Releasing

Just push to `main` (without a tag):

- Artifacts are built but not released
- Available in GitHub Actions artifacts for 90 days
- Download from the workflow run details

## Artifacts

### Windows

- `Stremer-Setup.exe` - Installer for target machines

### Android

- `app-debug.apk` - For testing, can reinstall without signing concerns
- `app-release-unsigned.apk` - For distribution (can be signed later)

## Troubleshooting

### Build fails on Windows

- Check Python version compatibility (3.10+)
- Ensure all dependencies in `requirements.txt` are correct
- NSIS must be installable via Chocolatey

### Build fails on Android

- Ensure `gradlew` has execute permissions
- Check that `build.gradle` doesn't require signing for debug builds
- Java 11+ is required

### Release not created

- Tag must start with `v` (e.g., `v1.0.0`)
- Workflow must complete successfully first

## Optional: Code Signing

To sign the Windows installer and Android APK:

1. **Windows**: Add a code signing certificate as a GitHub secret
2. **Android**: Add a keystore file as a secret and uncomment signing steps in the workflow

(Not required for initial testing, but recommended for production distribution)

## Next Steps

1. Commit and push `.github/workflows/build.yml`
2. Create a tag: `git tag v1.0.0 && git push origin v1.0.0`
3. Watch the workflow run: Settings → Actions
4. Release will appear at GitHub Releases once complete

---

**Example workflow run**: https://github.com/your-org/Stremer/actions

**Example release**: https://github.com/your-org/Stremer/releases/tag/v1.0.0
