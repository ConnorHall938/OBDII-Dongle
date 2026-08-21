/*
 * Copyright (c) 2021 Nordic Semiconductor ASA
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/drivers/led.h>
#include <zephyr/logging/log.h>

#include <zephyr/app_version.h>


LOG_MODULE_REGISTER(main, CONFIG_APP_LOG_LEVEL);

#define BLINK_PERIOD_MS 1000U


int main(void)
{
	int ret;
	static const struct led_dt_spec led = LED_DT_SPEC_GET(DT_ALIAS(led0));

	if (!led_is_ready_dt(&led)) {
		LOG_ERR("LED not ready");
		return 0;
	}

	printk("Blinking LED every %u ms\n", BLINK_PERIOD_MS);

	while (1) {
		ret = led_on_dt(&led);
		if (ret < 0) {
			LOG_ERR("Could not turn on LED (%d)", ret);
			return 0;
		}

		k_sleep(K_MSEC(BLINK_PERIOD_MS / 2U));
		ret = led_off_dt(&led);
		if (ret < 0) {
			LOG_ERR("Could not turn off LED (%d)", ret);
			return 0;
		}

		k_sleep(K_MSEC(BLINK_PERIOD_MS / 2U));
	}

	return 0;
}
