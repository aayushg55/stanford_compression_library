cmake_minimum_required(VERSION 3.16)
project(scl_fse_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(SCL_FSE_BUILD_EXAMPLE "Build the small FSE example binary" ON)

add_library(scl_fse STATIC
    src/fse.cpp
)

target_include_directories(scl_fse
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

if(CMAKE_BUILD_TYPE STREQUAL "Release")
    target_compile_options(scl_fse PRIVATE -O3 -DNDEBUG -march=native)
endif()

if(SCL_FSE_BUILD_EXAMPLE)
    add_executable(fse_example src/main.cpp)
    target_link_libraries(fse_example PRIVATE scl_fse)
endif()
