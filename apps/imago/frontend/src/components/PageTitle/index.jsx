// Título da aba ("<tela> · imago"); o React 19 leva o <title> para o <head>
export default function PageTitle({ title }) {
  return <title>{title ? `${title} · imago` : 'imago'}</title>;
}
