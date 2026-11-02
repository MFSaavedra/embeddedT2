idf_component_register(
    SRCS "main.c"
         "protocol.c"
         "uart_link.c"
         "commands.c"
         "bme688.c"
         "sampler.c"
         "temp_proc.c"
    INCLUDE_DIRS "."
    # MINIMAL_BUILD is ON (see ../CMakeLists.txt): a component missing here is not built.
    # Adding the Bosch BME68x SensorAPI as components/bme68x means adding "bme68x" here too.
    PRIV_REQUIRES esp_driver_uart esp_driver_i2c esp_timer esp_hw_support vfs
)
