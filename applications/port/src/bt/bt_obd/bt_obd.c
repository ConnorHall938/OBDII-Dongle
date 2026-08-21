#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/drivers/led.h>
#include <zephyr/logging/log.h>

#include <zephyr/app_version.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/hci.h>

#include "bt_constants.h"

LOG_MODULE_REGISTER(bt_obd, CONFIG_APP_LOG_LEVEL);

static const struct bt_uuid_128 OBD_uuid = BT_UUID_INIT_128(BT_UUID_OBD_SVC_VAL);
static const struct bt_uuid_128 OBD_RPM_uuid = BT_UUID_INIT_128(BT_UUID_RPM_VAL);
static const struct bt_uuid_128 OBD_SPEED_uuid = BT_UUID_INIT_128(BT_UUID_SPEED_VAL);

static uint16_t rpm_value = 1000;
static uint8_t  speed_value;

static ssize_t gatt_read_u16(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                        void *buf, uint16_t len, uint16_t offset)
{

    uint16_t val = sys_cpu_to_le16(*(const uint16_t *)attr->user_data);
	LOG_DBG("GATT_READ_U16: conn=%p, len=%u, offset=%u\n", conn, len, offset);
    return bt_gatt_attr_read(conn, attr, buf, len, offset, &val, sizeof(val));
}

static ssize_t gatt_read_u8(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                       void *buf, uint16_t len, uint16_t offset)
{
	LOG_DBG("GATT_READ_U8: conn=%p, len=%u, offset=%u\n", conn, len, offset);
    return bt_gatt_attr_read(conn, attr, buf, len, offset,
                             attr->user_data, sizeof(uint8_t));
}


static void rpm_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    LOG_INF("RPM notify %s", value == BT_GATT_CCC_NOTIFY ? "on" : "off");
}

static void speed_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    LOG_INF("SPEED notify %s", value == BT_GATT_CCC_NOTIFY ? "on" : "off");
}



BT_GATT_SERVICE_DEFINE(obd_svc,
	BT_GATT_PRIMARY_SERVICE(&OBD_uuid),
	BT_GATT_CHARACTERISTIC(&OBD_RPM_uuid.uuid,
							BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
							BT_GATT_PERM_READ,
							gatt_read_u16, NULL, &rpm_value),	
	BT_GATT_CCC(rpm_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(&OBD_SPEED_uuid.uuid,
							BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
							BT_GATT_PERM_READ,
							gatt_read_u8, NULL, &speed_value),
	BT_GATT_CCC(speed_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
						);

static int bt_obd_init()
{
    int ret = 0;
    
    return ret;
}

SYS_INIT(bt_obd_init, APPLICATION, CONFIG_APP_BT_OBD_INIT_PRIORITY);