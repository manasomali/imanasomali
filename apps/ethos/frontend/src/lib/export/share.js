// Entregar um arquivo gerado no navegador: compartilhar pela Web Share API, onde ela aceita
// arquivos, ou baixar. Nada sai do navegador para o servidor.
//
// `navigator.canShare({files})` decide: com suporte, abre a folha de compartilhamento do sistema
// (redes sociais, mensagens); sem suporte (a maioria dos desktops, Firefox), baixa. O share exige
// um gesto recente da pessoa: chame logo no clique, com o arquivo já pronto (a tela do relatório
// gera a imagem antes e mostra a prévia). Se o share falhar por outro motivo que não o cancelamento
// (ex.: NotAllowedError, gesto expirado), baixa no lugar, para a pessoa não ficar sem o arquivo.

// Tempo até liberar a URL do blob: o download começa no clique, mas alguns navegadores leem a URL
// depois de o evento terminar
const REVOKE_DELAY_MS = 60_000;

/** O navegador compartilha este arquivo? (`navigator.canShare({files})`, sem lançar.) */
export function canShareFile(file, nav = globalThis.navigator) {
  try {
    return (
      typeof nav?.share === 'function'
      && typeof nav.canShare === 'function'
      && nav.canShare({ files: [file] }) === true
    );
  } catch {
    return false;
  }
}

/** Baixa `blob` com o nome `filename` (link temporário com `download`). */
export function downloadBlob(blob, filename, doc = globalThis.document) {
  const url = URL.createObjectURL(blob);
  const link = doc.createElement('a');
  link.href = url;
  link.download = filename;
  link.hidden = true;
  doc.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
  }
}

/**
 * Compartilha o arquivo ou, sem suporte, baixa. Devolve 'shared', 'downloaded' ou 'canceled'
 * (a pessoa fechou a folha de compartilhamento: nada a fazer).
 */
export async function shareOrDownload(file, { nav = globalThis.navigator, doc = globalThis.document, title } = {}) {
  if (canShareFile(file, nav)) {
    try {
      await nav.share(title ? { files: [file], title } : { files: [file] });
      return 'shared';
    } catch (error) {
      if (error?.name === 'AbortError') return 'canceled';
    }
  }
  downloadBlob(file, file.name, doc);
  return 'downloaded';
}
