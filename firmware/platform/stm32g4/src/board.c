#include "board.h"

#include "stm32g4xx.h"

static GPIO_TypeDef *const k_ports[7] = {GPIOA, GPIOB, GPIOC, GPIOD, GPIOE, GPIOF, GPIOG};
static bool g_brake_nc;

static bool is_gate_pin(uint8_t port, uint8_t pin)
{
    return (port == BOARD_PWM_A_HI_PORT && pin == BOARD_PWM_A_HI_PIN) ||
           (port == BOARD_PWM_B_HI_PORT && pin == BOARD_PWM_B_HI_PIN) ||
           (port == BOARD_PWM_C_HI_PORT && pin == BOARD_PWM_C_HI_PIN) ||
           (port == BOARD_PWM_A_LO_PORT && pin == BOARD_PWM_A_LO_PIN) ||
           (port == BOARD_PWM_B_LO_PORT && pin == BOARD_PWM_B_LO_PIN) ||
           (port == BOARD_PWM_C_LO_PORT && pin == BOARD_PWM_C_LO_PIN);
}

static void pin_mode(uint8_t port, uint8_t pin, uint32_t mode)
{
    GPIO_TypeDef *g = k_ports[port];
    g->MODER = (g->MODER & ~(3uL << (pin * 2u))) | (mode << (pin * 2u));
}

static void pin_write(uint8_t port, uint8_t pin, bool level)
{
    k_ports[port]->BSRR = level ? (1uL << pin) : (1uL << (pin + 16u));
}

static bool pin_read(uint8_t port, uint8_t pin)
{
    return (k_ports[port]->IDR & (1uL << pin)) != 0u;
}

static void pin_af(uint8_t port, uint8_t pin, uint8_t af)
{
    GPIO_TypeDef *g = k_ports[port];
    const uint32_t idx = pin >> 3u, sh = (pin & 7u) * 4u;
    g->AFR[idx] = (g->AFR[idx] & ~(0xFuL << sh)) | ((uint32_t)af << sh);
}

void board_gpio_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN | RCC_AHB2ENR_GPIOCEN | RCC_AHB2ENR_GPIODEN |
                    RCC_AHB2ENR_GPIOEEN | RCC_AHB2ENR_GPIOFEN | RCC_AHB2ENR_GPIOGEN;
    (void)RCC->AHB2ENR;
    for (uint32_t i = 0; i < BOARD_PIN_COUNT; i++) {
        const board_pin_t *p = &board_pins[i];
        GPIO_TypeDef *g = k_ports[p->port];
        g->PUPDR &= ~(3uL << (p->pin * 2u));              /* external pull resistors on the board */
        g->OSPEEDR |= (1uL << (p->pin * 2u));             /* medium speed */
        if (p->mode == BOARD_MODE_OUTPUT || is_gate_pin(p->port, p->pin)) {
            /* Level before mode, so the pin never glitches to the wrong state. */
            pin_write(p->port, p->pin, p->mode == BOARD_MODE_OUTPUT ? p->level != 0u : false);
            pin_mode(p->port, p->pin, 1u);
        } else if (p->mode == BOARD_MODE_AF) {
            pin_af(p->port, p->pin, p->af);
            pin_mode(p->port, p->pin, 2u);
        } else if (p->mode == BOARD_MODE_INPUT) {
            pin_mode(p->port, p->pin, 0u);
        } else {
            pin_mode(p->port, p->pin, 3u);
        }
    }
    /* I2C lines are open drain (pull-ups on sheet 06). */
    k_ports[BOARD_I2C_SCL_PORT]->OTYPER |= 1uL << BOARD_I2C_SCL_PIN;
    k_ports[BOARD_I2C_SDA_PORT]->OTYPER |= 1uL << BOARD_I2C_SDA_PIN;
}

void board_pwm_pins_to_timer(void)
{
    for (uint32_t i = 0; i < BOARD_PIN_COUNT; i++) {
        const board_pin_t *p = &board_pins[i];
        if (!is_gate_pin(p->port, p->pin)) continue;
        pin_af(p->port, p->pin, p->af);
        k_ports[p->port]->OSPEEDR |= (3uL << (p->pin * 2u)); /* very high speed for the gate signals */
        pin_mode(p->port, p->pin, 2u);
    }
}

void board_read_inputs(board_inputs_t *in)
{
    const bool brake_contact_closed = !pin_read(BOARD_BRAKE_SWITCH_PORT, BOARD_BRAKE_SWITCH_PIN);
    in->brake = g_brake_nc ? !brake_contact_closed : brake_contact_closed;
    in->cancel = !pin_read(BOARD_ECO_CANCEL_PORT, BOARD_ECO_CANCEL_PIN);
    in->mode_eco = !pin_read(BOARD_MODE_SWITCH_PORT, BOARD_MODE_SWITCH_PIN);
    in->arm = !pin_read(BOARD_ARM_SWITCH_PORT, BOARD_ARM_SWITCH_PIN);
    in->fault_reset = !pin_read(BOARD_FAULT_RESET_PORT, BOARD_FAULT_RESET_PIN);
    in->driver_present = !pin_read(BOARD_DEADMAN_SENSE_PORT, BOARD_DEADMAN_SENSE_PIN);
    in->hw_permit = pin_read(BOARD_ESTOP_CHAIN_SENSE_PORT, BOARD_ESTOP_CHAIN_SENSE_PIN);
    in->drv_en_gated = pin_read(BOARD_OUTPUT_ENABLE_FEEDBACK_PORT, BOARD_OUTPUT_ENABLE_FEEDBACK_PIN);
    in->drv_nfault = !pin_read(BOARD_DRV_NFAULT_PORT, BOARD_DRV_NFAULT_PIN);
    in->ext_wdg_reset = !pin_read(BOARD_EXT_WDG_RST_SENSE_PORT, BOARD_EXT_WDG_RST_SENSE_PIN);
    in->ina_alert = !pin_read(BOARD_INA_ALERT_PORT, BOARD_INA_ALERT_PIN);
}

void board_set_brake_switch_nc(bool nc) { g_brake_nc = nc; }

void board_set_drv_enable(bool on) { pin_write(BOARD_DRV_ENABLE_PORT, BOARD_DRV_ENABLE_PIN, on); }
void board_set_precharge_bypass(bool on) { pin_write(BOARD_PRECHG_EN_PORT, BOARD_PRECHG_EN_PIN, on); }
void board_set_led_status(bool on) { pin_write(BOARD_LED_STATUS_PORT, BOARD_LED_STATUS_PIN, on); }
void board_set_led_fault(bool on) { pin_write(BOARD_LED_FAULT_PORT, BOARD_LED_FAULT_PIN, on); }

bool board_drv_enable_commanded(void)
{
    return (k_ports[BOARD_DRV_ENABLE_PORT]->ODR & (1uL << BOARD_DRV_ENABLE_PIN)) != 0u;
}

bool board_break_inputs_active(void)
{
    return !pin_read(BOARD_PWM_BREAK_PORT, BOARD_PWM_BREAK_PIN) || !pin_read(BOARD_PWM_BREAK2_PORT, BOARD_PWM_BREAK2_PIN);
}

void board_toggle_ext_wdg(void)
{
    GPIO_TypeDef *g = k_ports[BOARD_EXT_WDG_WDI_PORT];
    pin_write(BOARD_EXT_WDG_WDI_PORT, BOARD_EXT_WDG_WDI_PIN, (g->ODR & (1uL << BOARD_EXT_WDG_WDI_PIN)) == 0u);
}

void board_force_safe(void)
{
    /* No function calls that touch RAM: this runs from fault handlers with an untrusted stack. */
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    k_ports[BOARD_DRV_ENABLE_PORT]->BSRR = 1uL << (BOARD_DRV_ENABLE_PIN + 16u);
    k_ports[BOARD_PRECHG_EN_PORT]->BSRR = 1uL << (BOARD_PRECHG_EN_PIN + 16u);
#define SAFE_GATE(F)                                                                                    \
    do {                                                                                                \
        GPIO_TypeDef *g_ = k_ports[BOARD_##F##_PORT];                                                   \
        g_->BSRR = 1uL << (BOARD_##F##_PIN + 16u);                                                      \
        g_->MODER = (g_->MODER & ~(3uL << (BOARD_##F##_PIN * 2u))) | (1uL << (BOARD_##F##_PIN * 2u));   \
    } while (0)
    SAFE_GATE(PWM_A_HI);
    SAFE_GATE(PWM_B_HI);
    SAFE_GATE(PWM_C_HI);
    SAFE_GATE(PWM_A_LO);
    SAFE_GATE(PWM_B_LO);
    SAFE_GATE(PWM_C_LO);
#undef SAFE_GATE
}
