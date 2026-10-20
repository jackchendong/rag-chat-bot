export async function refreshVisiblePages<T>(
  visibleCount: number, pageSize: number, fetchPage: (offset: number) => Promise<T[]>,
): Promise<{ rows: T[]; hasMore: boolean }> {
  const rows: T[] = []
  const pages = Math.max(1, Math.ceil(visibleCount / pageSize))
  let hasMore = false
  for (let page = 0; page < pages; page++) {
    const batch = await fetchPage(page * pageSize)
    rows.push(...batch)
    hasMore = batch.length === pageSize
    if (!hasMore) break
  }
  return { rows, hasMore }
}
