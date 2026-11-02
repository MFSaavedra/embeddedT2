"""@file conftest.py
@brief Make `import protocol` etc. work when running `pytest` from the repository root, and
keep Qt headless.

Prepends gui_python/ to sys.path so the tests import the modules exactly as the application
does (`import protocol`, not `gui_python.protocol`), and selects Qt's offscreen platform
plugin so widget tests need no display and pop up no windows.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gui_python")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest    # noqa: E402 - after the sys.path/env setup above


@pytest.fixture(scope="session")
def qapp():
    """@brief The single QApplication every widget test shares.

    @return The application instance; never exec()'d, the tests call slots directly.
    """
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
