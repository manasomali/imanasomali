import styles from './styles.module.css';

// Underlined text link. `external` opens in a new tab; `as` renders another
// component (e.g. react-router's Link) with the same look.
function Link({
  as: Component = 'a', external = false, className = '', ...props
}) {
  const externalProps = external ? { target: '_blank', rel: 'noopener noreferrer' } : {};
  return <Component className={`${styles.link} ${className}`} {...externalProps} {...props} />;
}

export default Link;
