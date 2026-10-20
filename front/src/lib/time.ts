import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

export function formatTime(value: string | null, zone: string): string {
  return value ? dayjs(value).tz(zone).format('YYYY-MM-DD HH:mm:ss') : '—'
}

export function localTime(value: string, zone: string): string {
  return dayjs(value).tz(zone).format('YYYY-MM-DDTHH:mm')
}

export function zonedTime(value: string, zone: string): string {
  const parsed = dayjs.tz(value, zone)
  if (!parsed.isValid() || parsed.format('YYYY-MM-DDTHH:mm') !== value) throw new Error('该时区的执行时间不存在，请重新选择')
  for (const offset of [parsed.subtract(1, 'day').tz(zone).utcOffset(), parsed.add(1, 'day').tz(zone).utcOffset()]) {
    const alternative = parsed.utcOffset(offset, true).tz(zone)
    if (alternative.valueOf() !== parsed.valueOf() && alternative.format('YYYY-MM-DDTHH:mm') === value) {
      throw new Error('该时间因夏令时重复，请改用 UTC 时区指定准确时刻')
    }
  }
  return parsed.toISOString()
}
