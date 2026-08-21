#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/drivers/led.h>
#include <zephyr/logging/log.h>

#include "bt_constants.h"

#include <zephyr/app_version.h>


#include <zephyr/bluetooth/services/nus.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/hci.h>

LOG_MODULE_REGISTER(bt_core, CONFIG_APP_LOG_LEVEL);

#define DEVICE_NAME		CONFIG_BT_DEVICE_NAME
#define DEVICE_NAME_LEN		(sizeof(DEVICE_NAME) - 1)

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, BT_UUID_OBD_SVC_VAL),
};

static const struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, DEVICE_NAME, DEVICE_NAME_LEN),
};

static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("Connection failed, err 0x%02x %s", err, bt_hci_err_to_str(err));
	} else {
		LOG_INF("Connected");
	}
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	LOG_WRN("Disconnected, reason 0x%02x %s", reason, bt_hci_err_to_str(reason));
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};

static int init_bt()
{
    int ret = 0;

    ret = bt_enable(NULL);
	if (ret != 0) {
		LOG_ERR("Bluetooth init failed (err %d)", ret);
		return ret;
	}

    return ret;
}

SYS_INIT(init_bt, APPLICATION, CONFIG_APP_BT_CORE_INIT_PRIORITY);

static int start_bt()
{
    int ret = 0;

    ret = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (ret) {
		LOG_ERR("Failed to start advertising: %d\n", ret);
		return ret;
	}

    printk("Initialization complete\n");

    return ret;
}

SYS_INIT(start_bt, APPLICATION, CONFIG_APP_BT_FINAL_INIT_PRIORITY);