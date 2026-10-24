import styles from './styles.module.css';

function Title({ as: Component = 'h1', children }) {
  return <Component className={styles.title}>{children}</Component>;
}

export default Title;
