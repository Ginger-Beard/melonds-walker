// melonDS-walker IR dongle: USB CDC <-> IrDA SIR bridge for the Pokewalker.
//
// Two FreeRTOS tasks do all the work:
//   ir   (ir_uart.cpp)   priority 20, core 1: UART1 IrDA RX/TX, packet gaps,
//                         echo stripping. Never touches USB.
//   host (host_link.cpp) priority 10: USB CDC, COBS framing, commands.
// They exchange messages through two FreeRTOS message buffers, so a host that
// stops reading can never stall the IR side. The Arduino loop task is not
// needed and deletes itself.

#include <Arduino.h>

#include "host_link.h"
#include "ir_uart.h"

void setup() {
    // First thing: TXD low (LED dark) and transceiver out of shutdown.
    ir::early_init();

    if (!host::begin()) {
        log_e("host link init failed");
    }
    if (!ir::begin(host::ir_out_buffer(), host::task_handle())) {
        log_e("IR init failed");
    }
}

void loop() { vTaskDelete(nullptr); }
