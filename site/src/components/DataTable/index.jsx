import ScrollArea from '../ScrollArea';
import styles from './styles.module.css';

// Simple data table: `columns` are the header labels, `rows` arrays of cells (the first cell
// of each row is its header). `numeric` lists the column indexes aligned to the end, and
// `nowrap` the ones whose short labels must not break ("Cleats 1").
// `label` names the table for screen readers; the heading above it is the visible title.
// Rows are static content that is never reordered, so their position is a stable key.
function DataTable({
  label, columns, rows, numeric = [], nowrap = [],
}) {
  const align = (index) => [
    numeric.includes(index) && styles.numeric,
    nowrap.includes(index) && styles.nowrap,
  ].filter(Boolean).join(' ') || undefined;
  return (
    <ScrollArea label={label}>
      <table className={styles.table} aria-label={label}>
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th key={column} scope="col" className={align(index)}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, index) => (index === 0 ? (
                <th key="head" scope="row" className={align(0)}>{cell}</th>
              ) : (
                <td key={index} className={align(index)}>{cell}</td>
              )))}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollArea>
  );
}

export default DataTable;
