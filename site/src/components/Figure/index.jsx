import ScrollArea from '../ScrollArea';
import styles from './styles.module.css';

// Figure for a diagram inside <Prose>. `wide` lets it leave the text column and use the
// page's full width. `minWidth` (px) keeps it readable on phones by scrolling sideways
// instead of shrinking; `label` names that scrollable area.
function Figure({
  caption, label, wide = false, minWidth, children,
}) {
  return (
    <figure className={styles.figure} data-width={wide ? 'wide' : undefined}>
      <ScrollArea label={label} minWidth={minWidth}>{children}</ScrollArea>
      {caption && <figcaption className={styles.caption}>{caption}</figcaption>}
    </figure>
  );
}

export default Figure;
