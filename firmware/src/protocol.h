// Host <-> dongle protocol constants. Source of truth: docs/protocol.md.
#pragma once

#include <stdint.h>

namespace proto {

constexpr uint8_t kVersion = 1;
constexpr uint8_t kMagic[4] = {'M', 'D', 'S', 'W'};

constexpr uint8_t kCapFramed = 1u << 0;
constexpr uint8_t kCapRaw = 1u << 1;
constexpr uint8_t kCapWifi = 1u << 2;

constexpr unsigned kMaxFrame = 300;     // decoded frame (type + payload)
constexpr unsigned kMaxIrPacket = 256;  // IR packet bytes
constexpr unsigned kMaxPing = 32;

// Host -> dongle
constexpr uint8_t kIrTx = 0x01;
constexpr uint8_t kIdentify = 0x02;
constexpr uint8_t kSetConfig = 0x03;
constexpr uint8_t kRawMode = 0x04;
constexpr uint8_t kPing = 0x05;

// Dongle -> host
constexpr uint8_t kIrRx = 0x81;
constexpr uint8_t kIdentifyResp = 0x82;
constexpr uint8_t kConfigAck = 0x83;
constexpr uint8_t kTxDone = 0x84;
constexpr uint8_t kPong = 0x85;
constexpr uint8_t kLog = 0x8E;
constexpr uint8_t kError = 0x8F;

// SET_CONFIG keys
constexpr uint8_t kCfgGapUs = 0x01;
constexpr uint8_t kCfgEchoGuardUs = 0x02;
constexpr uint8_t kCfgTransceiverEnable = 0x03;
constexpr uint8_t kCfgRawModeAckKey = 0xFF;  // CONFIG_ACK key for RAW_MODE

// CONFIG_ACK status
constexpr uint8_t kStatusOk = 0;
constexpr uint8_t kStatusBadLength = 1;
constexpr uint8_t kStatusBadValue = 2;

// Defaults
constexpr uint16_t kDefaultGapUs = 1000;
constexpr uint16_t kDefaultEchoGuardUs = 50;  // walker replies ~150 us after our packet ends
constexpr uint16_t kMinGapUs = 200;  // < ~2 byte times would split every packet

// ERROR codes
constexpr uint8_t kErrMalformed = 0x01;
constexpr uint8_t kErrUnknownType = 0x02;
constexpr uint8_t kErrRxOverflow = 0x03;
constexpr uint8_t kErrTxTooLong = 0x04;
constexpr uint8_t kErrBadConfigKey = 0x05;
constexpr uint8_t kErrTxQueueFull = 0x06;

}  // namespace proto
