"""@file main.py
@brief Entry point of the PyQt application.

Run from the repository root:

    python gui_python/main.py
"""
import sys

from PyQt5.QtWidgets import QApplication

from main_window import MainWindow


def main() -> int:
    """@brief Create the QApplication and the main window, then run the Qt event loop.

    @return Exit code of the event loop (0 after a normal close).
    """
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
