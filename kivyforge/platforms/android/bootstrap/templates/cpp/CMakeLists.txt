cmake_minimum_required(VERSION 3.10)
project(kivyforge_launcher)

# The kivyforge native launcher: exports SDL_main, initializes CPython.
# Headers + libpython come from the python.org Android runtime prefix.
#
# Multi-ABI: AGP invokes CMake once per ABI; PYTHON_PREFIX_DIR arrives with a
# literal {{triplet}} placeholder that resolves to this ABI's target triplet
# (aarch64-linux-android / x86_64-linux-android) — the same mechanism the
# python.org testbed uses, so each ABI's launcher links its own libpython.
string(
    REPLACE {{triplet}} ${CMAKE_LIBRARY_ARCHITECTURE}
    PYTHON_PREFIX_DIR ${PYTHON_PREFIX_DIR}
)

include_directories(${PYTHON_PREFIX_DIR}/include/python${PYTHON_VERSION})
link_directories(${PYTHON_PREFIX_DIR}/lib)

add_library(main SHARED main.c)
target_link_libraries(main log python${PYTHON_VERSION})
