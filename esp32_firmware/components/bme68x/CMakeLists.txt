# Bosch Sensortec BME68x SensorAPI v4.4.8 (BSD-3-Clause, see LICENSE), vendored unmodified from
# https://github.com/boschsensortec/BME68x_SensorAPI commit 80ea120a8b8ac987d7d79eb68a9ed796736be845.
# Built with the default floating-point compensation (BME68X_USE_FPU): degC, Pa, %RH.
# Used by main/bme688.c, which supplies the I2C and delay callbacks. Listed in main's
# PRIV_REQUIRES because the project builds with MINIMAL_BUILD.
idf_component_register(
    SRCS "bme68x.c"
    INCLUDE_DIRS "."
)
