// USB side of the dongle: native USB (TinyUSB) CDC-ACM, COBS framing,
// command dispatch, raw-mode pass-through and the status LED.
#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/message_buffer.h>
#include <freertos/task.h>

namespace host {

// Configure the USB descriptor, start TinyUSB and the host task.
bool begin();

// Message buffer the IR task writes host-bound messages into (see ir_uart.h).
MessageBufferHandle_t ir_out_buffer();

// The host task, to be notified when ir_out_buffer() has data.
TaskHandle_t task_handle();

}  // namespace host
