import { useEffect, useRef, useState } from 'react';
import styles from './styles.module.css';

// Scrolls its content sideways when it does not fit (wide tables and diagrams on phones).
// Only while it overflows does it become a named, focusable group, so keyboard users can
// scroll it with the arrow keys without the page gaining a tab stop for every table.
// `minWidth` keeps a diagram from shrinking below the size where its labels are readable.
function ScrollArea({ label, minWidth, children }) {
  const ref = useRef(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => {
      setOverflowing(element.scrollWidth > element.clientWidth + 1);
    });
    // the box itself (viewport changes) and what it holds (a table widening once the web font
    // loads changes the overflow without resizing the box)
    observer.observe(element);
    const content = element.firstElementChild;
    if (content?.firstElementChild) observer.observe(content.firstElementChild);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={styles.scroll}
      tabIndex={overflowing ? 0 : undefined}
      role={overflowing ? 'group' : undefined}
      aria-label={overflowing ? label : undefined}
    >
      <div className={styles.content} style={minWidth ? { minWidth } : undefined}>
        {children}
      </div>
    </div>
  );
}

export default ScrollArea;
