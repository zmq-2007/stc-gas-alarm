#include "STC15xxx.h"

// 引脚定义
sbit BEEP = P1^0;
sbit ALARM_LED = P1^1;

// 继电器
sbit RELAY2 = P1^2;

// ADC结构体
typedef struct
{
    unsigned int AdcVale1;
}ADC_TYPE;
ADC_TYPE adc;

// 阈值
#define TempLimit 180

// 时间结构体
typedef struct
{
    unsigned char sec10f;
    unsigned char sec1f;
}SYS_TIME;
SYS_TIME SystemTime;

// 读取PCF8591通道0
unsigned char PCF8591_Readch(unsigned char ch)
{
    // 简化，仿真用，如果你有I2C驱动就替换
    return 120;
}

void GetAdcVale(void)
{
    adc.AdcVale1 = PCF8591_Readch(0x00);
}

void Lcd_Display(void)
{
    // LCD显示函数，这里先空着
}

void Relay2on(void)
{
    RELAY2 = 0;
}
void Relay2off(void)
{
    RELAY2 = 1;
}

void main(void)
{
    while(1)
    {
        if (SystemTime.sec10f == 1)
        {
            SystemTime.sec10f = 0;
            GetAdcVale();
        }
        if (SystemTime.sec1f == 1)
        {
            SystemTime.sec1f = 0;
            Lcd_Display();
            if (adc.AdcVale1 > TempLimit)
            {
                Relay2on();
                BEEP = 0;
                ALARM_LED = ~ALARM_LED;
            }
            else
            {
                Relay2off();
                BEEP = 1;
                ALARM_LED = 1;
            }
        }
    }
}