import styles from './styles.module.css';

// Long-form text (posts). Children sit in a centered reading column; a direct child with
// data-width="wide" (a wide <Figure>) spans the page's full width. Use it on a page with
// PageDefault width="wide".
function Prose({ as: Component = 'div', children }) {
  return <Component className={styles.prose}>{children}</Component>;
}

export default Prose;
