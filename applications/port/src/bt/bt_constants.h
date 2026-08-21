#ifndef OBDII_PORT_BT_CONSTANTS_H
#define OBDII_PORT_BT_CONSTANTS_H

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/hci.h>

#define BT_UUID_OBD_SVC_VAL BT_UUID_128_ENCODE(0xd50d4d4d,0x0f37,0x41c7,0xa089,0x9c6b8e490640)
#define BT_UUID_RPM_VAL BT_UUID_128_ENCODE(0x7e86f3ad,0xdb47,0x4281,0x8993,0xf791eab26719)
#define BT_UUID_SPEED_VAL BT_UUID_128_ENCODE(0x3228dd8f,0x90b6,0x41f0,0xa991,0xbf7d18306881)

#endif //OBDII_PORT_BT_CONSTANTS_H