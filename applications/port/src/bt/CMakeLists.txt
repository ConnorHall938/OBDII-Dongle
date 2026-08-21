target_sources(app PRIVATE bt_core.c)
target_include_directories(${PROJECT_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_subdirectory(bt_obd)
add_subdirectory_ifdef(CONFIG_BT_ZEPHYR_NUS, bt_nus)