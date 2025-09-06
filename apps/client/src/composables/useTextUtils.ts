export const useTextUtils = () => {
  const truncateText = (text: string, maxLength: number = 200): string => {
    if (!text || text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
  }

  return {
    truncateText,
  }
}
