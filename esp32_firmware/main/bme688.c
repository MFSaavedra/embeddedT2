/**
 * @file bme688.c
 * @brief BME688 driver: the I2C bus, the three platform callbacks the Bosch BME68x SensorAPI
 *        needs (read, write, delay) and the measurement settings. Public API: bme688.h.
 *
 * Uses the I2C master driver (driver/i2c_master.h, component esp_driver_i2c), which exists in
 * ESP-IDF v5.5 and v6.x alike. The legacy driver/i2c.h API is deprecated: do not use it.
 */
#include "bme688.h"
#include "app_config.h"

#include <string.h>

#include "bme68x.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/** Log tag of this module. */
static const char *TAG = "bme688";

static i2c_master_bus_handle_t s_bus;    /**< I2C master bus, created by the first bme688_init(). */
static i2c_master_dev_handle_t s_dev;    /**< The sensor on s_bus; NULL until found. */
static struct bme68x_dev       s_bme;    /**< Bosch API state: callbacks and calibration data. */
static struct bme68x_conf      s_conf;   /**< Oversampling and filter in use. */
static uint32_t                s_meas_us; /**< Conversion time predicted by bme68x_get_meas_dur(). */
static bool                    s_ready;  /**< True between a successful init and a failed read. */

/* ------------------------- Bosch API platform callbacks ------------------------- */

/**
 * @brief Read @p len consecutive registers starting at @p reg (Bosch API read callback).
 * @param      reg       First register.
 * @param[out] data      Destination.
 * @param      len       Number of bytes.
 * @param      intf_ptr  Unused (the device is s_dev).
 * @return BME68X_INTF_RET_SUCCESS, or -1 if the I2C transaction failed.
 */
static BME68X_INTF_RET_TYPE bme_read(uint8_t reg, uint8_t *data, uint32_t len, void *intf_ptr)
{
    (void)intf_ptr;
    return i2c_master_transmit_receive(s_dev, &reg, 1, data, len, BME688_I2C_TIMEOUT_MS) == ESP_OK
           ? BME68X_INTF_RET_SUCCESS : -1;
}

/**
 * @brief Write @p len bytes after register address @p reg in one transaction (Bosch API
 *        write callback).
 *
 * The API writes at most BME68X_LEN_INTERLEAVE_BUFF - 1 bytes per call (register/value pairs
 * interleaved by bme68x_set_regs()), so the register address and the data fit in one buffer.
 *
 * @param reg       Register address, sent first.
 * @param data      Bytes that follow it.
 * @param len       Number of bytes in @p data.
 * @param intf_ptr  Unused (the device is s_dev).
 * @return BME68X_INTF_RET_SUCCESS, or -1 if the data does not fit or the transaction failed.
 */
static BME68X_INTF_RET_TYPE bme_write(uint8_t reg, const uint8_t *data, uint32_t len, void *intf_ptr)
{
    (void)intf_ptr;
    uint8_t buf[1 + BME68X_LEN_INTERLEAVE_BUFF];
    if (len >= sizeof buf) {
        return -1;
    }
    buf[0] = reg;
    memcpy(&buf[1], data, len);
    return i2c_master_transmit(s_dev, buf, len + 1, BME688_I2C_TIMEOUT_MS) == ESP_OK
           ? BME68X_INTF_RET_SUCCESS : -1;
}

/**
 * @brief Wait at least @p us microseconds (Bosch API delay callback; also used to wait for a
 *        conversion).
 *
 * The FreeRTOS tick is 10 ms and vTaskDelay(n) may return after only n - 1 whole ticks, so
 * the wait is rounded UP to whole ticks plus one: rounding down would read the sensor before
 * the conversion ends (spec 2.1.4). Waits shorter than a tick busy-wait instead.
 *
 * @param us        Minimum wait, microseconds.
 * @param intf_ptr  Unused.
 */
static void bme_delay_us(uint32_t us, void *intf_ptr)
{
    (void)intf_ptr;
    const uint32_t tick_us = portTICK_PERIOD_MS * 1000;
    if (us < tick_us) {
        esp_rom_delay_us(us);
    } else {
        vTaskDelay((us + tick_us - 1) / tick_us + 1);
    }
}

/* ---------------------------------- bus setup ---------------------------------- */

/**
 * @brief Create the I2C master bus if it does not exist yet.
 * @return ESP_OK if the bus exists (now or already).
 */
static esp_err_t ensure_bus(void)
{
    if (s_bus != NULL) {
        return ESP_OK;
    }
    const i2c_master_bus_config_t cfg = {
        .i2c_port          = BME688_I2C_PORT,
        .sda_io_num        = BME688_SDA_GPIO,
        .scl_io_num        = BME688_SCL_GPIO,
        .clk_source        = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        /* Weak (~45 kOhm) fallback only: breakout boards carry real pull-ups (the team's does). */
        .flags.enable_internal_pullup = true,
    };
    return i2c_new_master_bus(&cfg, &s_bus);
}

/**
 * @brief Find which of the two possible sensor addresses acknowledges.
 * @param[out] addr_out  Address that answered, written only on success.
 * @return ESP_OK, ESP_ERR_NOT_FOUND (no ack at either address) or ESP_ERR_TIMEOUT (bus stuck,
 *         typically missing pull-ups; the second address is not tried).
 */
static esp_err_t probe(uint8_t *addr_out)
{
    const uint8_t candidates[] = { BME688_ADDR_PRIMARY, BME688_ADDR_SECONDARY };
    esp_err_t err = ESP_ERR_NOT_FOUND;
    for (size_t i = 0; i < sizeof candidates; i++) {
        err = i2c_master_probe(s_bus, candidates[i], BME688_I2C_TIMEOUT_MS);
        if (err == ESP_OK) {
            *addr_out = candidates[i];
            return ESP_OK;
        }
        if (err == ESP_ERR_TIMEOUT) {
            return err;
        }
    }
    return err;
}

/**
 * @brief Soft-reset the sensor, read its calibration and apply the measurement settings.
 * @return The first Bosch API error, or BME68X_OK.
 */
static int8_t configure_sensor(void)
{
    s_bme = (struct bme68x_dev){
        .intf     = BME68X_I2C_INTF,
        .read     = bme_read,
        .write    = bme_write,
        .delay_us = bme_delay_us,
        .amb_temp = 25,             /* only used to compute heater settings, and the heater is off */
    };
    s_conf = (struct bme68x_conf){
        .os_temp = BME68X_OS_2X,
        .os_pres = BME68X_OS_16X,
        .os_hum  = BME68X_OS_1X,
        .filter  = BME68X_FILTER_OFF,   /* a filter would delay and flatten the peaks */
        .odr     = BME68X_ODR_NONE,
    };
    const struct bme68x_heatr_conf heater_off = { .enable = BME68X_DISABLE };

    int8_t rslt = bme68x_init(&s_bme);  /* soft reset, chip id check, calibration */
    if (rslt == BME68X_OK) {
        rslt = bme68x_set_conf(&s_conf, &s_bme);
    }
    if (rslt == BME68X_OK) {
        rslt = bme68x_set_heatr_conf(BME68X_FORCED_MODE, &heater_off, &s_bme);
    }
    return rslt;
}

/* ---------------------------------- public API ---------------------------------- */

esp_err_t bme688_init(void)
{
    s_ready = false;
    esp_err_t err = ensure_bus();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C bus init failed: %s", esp_err_to_name(err));
        return err;
    }
    if (s_dev != NULL) {                    /* retry after an earlier attempt */
        i2c_master_bus_rm_device(s_dev);
        s_dev = NULL;
    }

    uint8_t addr = 0;
    err = probe(&addr);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "no sensor at 0x%02X or 0x%02X (%s): check power, SDA=GPIO%d, SCL=GPIO%d, "
                 "pull-ups and SDO", BME688_ADDR_PRIMARY, BME688_ADDR_SECONDARY,
                 esp_err_to_name(err), BME688_SDA_GPIO, BME688_SCL_GPIO);
        return err;
    }

    const i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = addr,
        .scl_speed_hz    = BME688_I2C_HZ,
    };
    err = i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "cannot add device 0x%02X: %s", addr, esp_err_to_name(err));
        return err;
    }

    const int8_t rslt = configure_sensor();
    if (rslt != BME68X_OK) {
        ESP_LOGE(TAG, "device at 0x%02X: Bosch API error %d%s", addr, rslt,
                 rslt == BME68X_E_DEV_NOT_FOUND ? " (not a BME68x)" : "");
        return rslt == BME68X_E_DEV_NOT_FOUND ? ESP_ERR_INVALID_RESPONSE : ESP_FAIL;
    }

    s_meas_us = bme68x_get_meas_dur(BME68X_FORCED_MODE, &s_conf, &s_bme);
    s_ready = true;
    ESP_LOGI(TAG, "%s found at 0x%02X (chip id 0x%02X, variant 0x%02X), conversion %lu us",
             s_bme.variant_id == BME68X_VARIANT_GAS_HIGH ? "BME688" : "BME680", addr,
             s_bme.chip_id, (unsigned)s_bme.variant_id, (unsigned long)s_meas_us);
    return ESP_OK;
}

bool bme688_is_ready(void) { return s_ready; }

esp_err_t bme688_read(bme688_reading_t *out)
{
    if (!s_ready) {
        return ESP_ERR_INVALID_STATE;
    }

    struct bme68x_data data;
    uint8_t n_data = 0;
    int8_t rslt = bme68x_set_op_mode(BME68X_FORCED_MODE, &s_bme);    /* start one conversion */
    if (rslt == BME68X_OK) {
        bme_delay_us(s_meas_us, NULL);                               /* let it finish */
        rslt = bme68x_get_data(BME68X_FORCED_MODE, &data, &n_data, &s_bme);
    }
    if (rslt != BME68X_OK || n_data == 0) {
        ESP_LOGW(TAG, "read failed (Bosch API result %d)", rslt);
        s_ready = false;
        return ESP_FAIL;
    }

    const float t = data.temperature;
    const float h = data.humidity;
    const float p = data.pressure / 100.0f;                         /* Pa -> hPa */
    /* Operating range of the datasheet: anything outside it is a bad read, not a measurement. */
    if (t < -40.0f || t > 85.0f || h < 0.0f || h > 100.0f || p < 300.0f || p > 1100.0f) {
        ESP_LOGW(TAG, "implausible values (T %.2f C, H %.2f %%, P %.2f hPa)", t, h, p);
        s_ready = false;
        return ESP_ERR_INVALID_RESPONSE;
    }
    out->temperature_c = t;
    out->humidity_pct = h;
    out->pressure_hpa = p;
    return ESP_OK;
}
