# Distribution notices

Spark Link desktop code is licensed GPL-3.0-or-later, including its native Qt Quick 3D interface.
The independently usable bundled `dual_spark` engine remains MIT; its license is included as `CLI-LICENSE`.

PySide6 6.8.3, Shiboken6 and Qt are distributed in their unmodified upstream wheel form.
Their copyright and license files are inside each wheel and installed runtime package.
Qt Quick 3D is used under GPLv3. Corresponding upstream source, including build instructions,
is available at https://code.qt.io/cgit/qt/qtquick3d.git/ and
https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag v6.8.3).
The complete corresponding Qt source archive is
https://download.qt.io/archive/qt/6.8/6.8.3/single/qt-everywhere-src-6.8.3.tar.xz;
Qt for Python source archives are under
https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/.
See https://www.qt.io/licensing/open-source-lgpl-obligations and the included GPL text.

The device visualization is original procedural geometry inspired by the DGX Spark chassis;
it does not redistribute NVIDIA product photographs or CAD assets. NVIDIA and DGX Spark
are trademarks of NVIDIA Corporation. This project is independent of NVIDIA and Unsloth.

Encrypted keyring access bundles unmodified SecretStorage 3.3.3 (BSD), Jeepney 0.9.0 (MIT),
cryptography 46.0.3 (Apache-2.0 OR BSD-3-Clause), cffi 2.0.0 (MIT), and pycparser 2.23 (BSD).
Their upstream copyright/license notices, including cryptography's bundled native dependency
notices, are retained inside the distributed wheels and installed runtime packages.
Sources: https://github.com/mitya57/secretstorage, https://gitlab.com/takluyver/jeepney,
https://github.com/pyca/cryptography, https://foss.heptapod.net/pypy/cffi,
and https://github.com/eliben/pycparser. The corresponding version tags identify these releases.
