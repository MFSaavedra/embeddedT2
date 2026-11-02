idf_component_register(
    SRCS "main.c"
         "protocol.c"
         "uart_link.c"
         "commands.c"
         "bme688.c"
         "sampler.c"
         "sampler_cfg.c"
         "temp_proc.c"
    INCLUDE_DIRS "."
    # MINIMAL_BUILD is ON (see ../CMakeLists.txt): a component missing here is not built.
    # bme68x is the Bosch SensorAPI vendored in ../components/bme68x.
    PRIV_REQUIRES bme68x esp_driver_uart esp_driver_i2c esp_timer esp_hw_support vfs
)
