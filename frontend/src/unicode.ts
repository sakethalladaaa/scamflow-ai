export function codePointToUtf16Offset(text: string, codePointOffset: number): number {
  return Array.from(text).slice(0, codePointOffset).join('').length
}

export function splitEvidence(text: string, start: number, end: number) {
  const utf16Start = codePointToUtf16Offset(text, start)
  const utf16End = codePointToUtf16Offset(text, end)
  return [text.slice(0, utf16Start), text.slice(utf16Start, utf16End), text.slice(utf16End)] as const
}
