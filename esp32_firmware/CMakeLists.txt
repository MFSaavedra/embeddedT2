# ESP-IDF project: Tarea 2 CC5328 - BME688 acquisition + on-device temperature processing.
# Build:  idf.py build      Flash + serial monitor:  idf.py -p /dev/ttyUSB0 flash monitor
cmake_minimum_required(VERSION 3.22)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# Only build the components "main" actually depends on (faster builds). Consequence: every
# component used by main must be listed in main/CMakeLists.txt PRIV_REQUIRES, or it is not
# compiled at all.
idf_build_set_property(MINIMAL_BUILD ON)
project(tarea2_bme688)
