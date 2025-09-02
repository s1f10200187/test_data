WITH RECURSIVE SplitLines(id, line, rest) AS (
  SELECT 
    id,
    SUBSTR(text_column, 1, INSTR(text_column || CHAR(13) || CHAR(10), CHAR(13) || CHAR(10)) - 1),
    SUBSTR(text_column, INSTR(text_column || CHAR(13) || CHAR(10), CHAR(13) || CHAR(10)) + 2)
  FROM your_table
  UNION ALL
  SELECT
    id,
    SUBSTR(rest, 1, INSTR(rest || CHAR(13) || CHAR(10), CHAR(13) || CHAR(10)) - 1),
    SUBSTR(rest, INSTR(rest || CHAR(13) || CHAR(10), CHAR(13) || CHAR(10)) + 2)
  FROM SplitLines
  WHERE rest <> ''
)
SELECT id, line
FROM SplitLines
WHERE line <> '';
