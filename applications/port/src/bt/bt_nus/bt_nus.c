#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/drivers/led.h>
#include <zephyr/logging/log.h>

#include <zephyr/app_version.h>


#include <zephyr/bluetooth/services/nus.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/hci.h>

LOG_MODULE_REGISTER(bt_nus, CONFIG_APP_LOG_LEVEL);

static void notif_enabled(bool enabled, void *ctx)
{
	ARG_UNUSED(ctx);

	LOG_DBG("%s() - %s", __func__, (enabled ? "Enabled" : "Disabled"));
}

static void received(struct bt_conn *conn, const void *data, uint16_t len, void *ctx)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(ctx);

	LOG_DBG("%s() - Len: %d, Message: %.*s", __func__, len, len, (char *)data);
}

struct bt_nus_cb nus_listener = {
	.notif_enabled = notif_enabled,
	.received = received,
};

static int bt_nus_init()
{
    int ret = 0;

	ret = bt_nus_cb_register(&nus_listener, NULL);
	if (ret) {
		LOG_ERR("Failed to register NUS callbacks: %d", ret);
		return ret;
	}

    return ret;
}

SYS_INIT(bt_nus_init, APPLICATION, CONFIG_APP_BT_NUS_INIT_PRIORITY);