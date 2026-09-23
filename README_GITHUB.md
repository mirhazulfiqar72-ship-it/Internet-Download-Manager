# Internet Download Manager

Windows desktop downloader with browser integration, media quality selection, duplicate-link handling, progress windows, and compact professional dialogs.

## Build

Run `BUILD_EXE.bat` on Windows. The generated portable application is placed under `dist\InternetDownloadManager`.

For a Control Panel installable setup, run `BUILD_EXE.bat`, install Inno Setup, and compile `installer\InternetDownloadManager.iss`. GitHub Actions does this automatically on a `v*` tag or from **Actions → Build Windows Installer → Run workflow**.

The installer creates Start Menu/Desktop shortcuts and an uninstall entry in Control Panel. Browser integration is registered by the included `INSTALL_BROWSER_INTEGRATION.bat`; Chrome/Edge may require loading the unpacked extension once because browser security policies do not permit arbitrary applications to silently install extensions.
