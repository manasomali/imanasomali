// localStorage que nunca lança: modo privado e armazenamento bloqueado fazem o acesso lançar
// exceção (até o próprio window.localStorage). Sem armazenamento, a leitura dá null e a escrita
// some no reload. Chave só do ethos leva o prefixo "ethos:" (contrato em packages/tokens/README.md)

export function readItem(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeItem(key, value) {
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}
