# Third-party notices

CleanYourMail app 0.5.0 is built from several open-source components. This file
is installed next to the application by `CleanYourMail-Setup-0.5.0.exe` and is
also present in the source repository.

## CleanYourMail app

The desktop application source in this repository is licensed under the MIT
License. See [LICENSE](LICENSE). Copyright (c) 2026 CleanYourMail contributors.

## CleanYourMail CLI (sidecar)

The app ships a frozen build of the CleanYourMail CLI at tag `v1.3.0` from
<https://github.com/jparedesDS/cleanyourmail/tree/v1.3.0>. The CLI is licensed
under the MIT License, copyright (c) 2026 CleanYourMail contributors. The
pinned tag is the exact source of `resources/cli/cym-cli.exe`; the app does not
modify it.

The sidecar is started as a separate process from `resources/cli/cym-cli.exe`.
It owns IMAP access, OAuth device-code flow, classification, plans, moves and
the undo journal. The app passes it a config path and reads JSON; it never
imports the CLI as a library.

## PySide6, Qt for Python and Qt

The user interface uses PySide6 (Qt for Python), which is provided under the
GNU Lesser General Public License version 3 (LGPLv3), the GNU General Public
License version 3 (GPLv3), or a commercial Qt license. This application uses
PySide6 under the LGPLv3.

Qt 6 and the Qt libraries bundled with PySide6 are also available under the
LGPLv3 (or GPLv3/commercial terms). The Qt libraries are shipped unmodified as
separate dynamic libraries next to `CleanYourMail.exe`, so they can be replaced
with compatible builds as allowed by the LGPL.

- Project: <https://www.qt.io/qt-for-python>
- PySide6 source: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Qt source: <https://code.qt.io/cgit/qt/>
- LGPLv3 text: <https://www.gnu.org/licenses/lgpl-3.0.html>
- GPLv3 text: <https://www.gnu.org/licenses/gpl-3.0.html>

PySide6 and Qt include third-party components with their own permissive
licenses (for example PCRE2, zlib, FreeType, HarfBuzz and libpng). Their notices
and license texts are included in the PySide6/Qt distributions and source
archives linked above.

## Python

The frozen application embeds the CPython runtime. Python is distributed under
the Python Software Foundation License Version 2. See
<https://docs.python.org/3/license.html>.

## PyInstaller

The application and sidecar are frozen with PyInstaller. PyInstaller is
distributed under the GNU General Public License version 2 with a special
exception that permits distribution of frozen applications under their own
terms. See <https://pyinstaller.org/en/stable/license.html>.

## Inno Setup

The Windows installer is produced with Inno Setup 6. Inno Setup is free
software and permits royalty-free distribution of installers it creates. See
<https://jrsoftware.org/isinfo.php> and
<https://jrsoftware.org/files/is/license.txt>.

## MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
