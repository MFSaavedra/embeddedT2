/**
 * @file bme688.c
 * @brief I2C bring-up and identification of the BME688; measurement path TODO(FW1).
 *
 * Uses the I2C master driver (driver/i2c_master.h, component esp_driver_i2c), which exists in
 * ESP-IDF v5.5 and v6.x alike. Do not use the legacy driver/i2c.h API: it is deprecated in
 * v5.x and the team builds on both versions. Public API: bme688.h.
 */
#include "bme688.h"
#include "app_config.h"

#include "driver/i2c_master.h"
#include "esp_log.h"

/** Log tag of this module. */
static const char *TAG = "bme688";

#define REG_CHIP_ID    0xD0   /**< Chip id register. */
#define REG_VARIANT_ID 0xF0   /**< Variant id register. */
#define CHIP_ID_BME68X 0x61   /**< Content of REG_CHIP_ID on a BME680 or BME688. */
#define VARIANT_BME688 0x01   /**< Content of REG_VARIANT_ID on a BME688 (0x00 is a BME680). */

static i2c_master_bus_handle_t s_bus;   /**< I2C master bus, created by the first bme688_init(). */
static i2c_master_dev_handle_t s_dev;   /**< The sensor on s_bus; NULL until found. */
static uint8_t                 s_addr;  /**< Address the sensor answered at; 0 if not found. */
static bool                    s_ready; /**< True once the chip id has been verified. */

/**
 * @brief Read consecutive registers of the sensor (register address write, then read).
 * @param      reg   First register.
 * @param[out] data  Destination.
 * @param      len   Number of bytes.
 * @return Result of the I2C transaction.
 */
static esp_err_t read_regs(uint8_t reg, uint8_t *data, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, data, len, BME688_I2C_TIMEOUT_MS);
}

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

esp_err_t bme688_init(void)
{
    s_ready = false;
    s_addr = 0;
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

    uint8_t chip_id = 0;
    uint8_t variant = 0xFF;
    err = read_regs(REG_CHIP_ID, &chip_id, 1);
    if (err == ESP_OK) {
        err = read_regs(REG_VARIANT_ID, &variant, 1);
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "id read at 0x%02X failed: %s", addr, esp_err_to_name(err));
        return err;
    }
    if (chip_id != CHIP_ID_BME68X) {
        ESP_LOGE(TAG, "device at 0x%02X has chip id 0x%02X, expected 0x%02X (not a BME68x)",
                 addr, chip_id, CHIP_ID_BME68X);
        return ESP_ERR_INVALID_RESPONSE;
    }

    /* TODO(FW1): configure the sensor before declaring it ready: soft reset, calibration
     * data, T/P/H oversampling, IIR filter, gas off (run_gas = 0, heater disabled). With the
     * Bosch BME68x SensorAPI: bme68x_init() + bme68x_set_conf() + bme68x_set_heatr_conf()
     * with .enable = BME68X_DISABLE, on top of read_regs() and an equivalent write.
     * That sequence (API v4.4.8, float output) is proven on this board: init takes ~17 ms
     * at 100 kHz and the write callback can send [reg, data...] as one transaction. */
    s_addr = addr;
    s_ready = true;
    ESP_LOGI(TAG, "%s found at 0x%02X (chip id 0x%02X, variant 0x%02X)",
             variant == VARIANT_BME688 ? "BME688" : "BME680", addr, chip_id, variant);
    return ESP_OK;
}

bool bme688_is_ready(void) { return s_ready; }

uint8_t bme688_address(void) { return s_addr; }

esp_err_t bme688_read(bme688_reading_t *out)
{
    (void)out;
    if (!s_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    /* TODO(FW1): trigger a forced-mode conversion, wait for it (bme68x_get_meas_dur(), rounded
     * UP to whole FreeRTOS ticks - see TODO.md "Conversion time"), read and compensate, and
     * convert Pa -> hPa. Measured on this board with T x2 / P x16 / H x1, IIR off: 40.3 ms,
     * against 42.6 ms from bme68x_get_meas_dur(), so the predicted time is enough once it is
     * not rounded down. Until then every read fails, which already exercises the
     * "no invented values" path end to end. */
    return ESP_ERR_NOT_SUPPORTED;
}
