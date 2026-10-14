// A tiny SQL tokenizer for syntax highlighting. It only colours text for
// display; it never interprets or runs SQL.

export type TokenKind = 'keyword' | 'function' | 'string' | 'number' | 'comment' | 'operator' | 'text'
export interface Token {
  kind: TokenKind
  text: string
}

const KEYWORDS = new Set(
  `select from where group by order having limit offset join inner left right outer full cross on
  using as and or not in is null like between case when then else end with recursive union all
  intersect except distinct asc desc exists cast over partition rows range preceding following
  current row unbounded filter true false`
    .split(/\s+/)
    .filter(Boolean),
)

const PATTERN =
  /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)(?=\s*\()|([A-Za-z_][A-Za-z0-9_]*)|([<>=!]=?|\|\||[-+*/%,()])/g

export function tokenizeSql(sql: string): Token[] {
  const tokens: Token[] = []
  let last = 0
  for (const m of sql.matchAll(PATTERN)) {
    const index = m.index ?? 0
    if (index > last) tokens.push({ kind: 'text', text: sql.slice(last, index) })
    const [whole, comment, str, num, func, word, op] = m
    if (comment) tokens.push({ kind: 'comment', text: whole })
    else if (str) tokens.push({ kind: 'string', text: whole })
    else if (num) tokens.push({ kind: 'number', text: whole })
    else if (func) tokens.push({ kind: KEYWORDS.has(func.toLowerCase()) ? 'keyword' : 'function', text: whole })
    else if (word) tokens.push({ kind: KEYWORDS.has(word.toLowerCase()) ? 'keyword' : 'text', text: whole })
    else if (op) tokens.push({ kind: 'operator', text: whole })
    last = index + whole.length
  }
  if (last < sql.length) tokens.push({ kind: 'text', text: sql.slice(last) })
  return tokens
}
