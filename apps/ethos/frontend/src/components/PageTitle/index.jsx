// Título da aba ("<tela> · ethos"); o React 19 leva o <title> para o <head>
export default function PageTitle({ title }) {
  return <title>{title ? `${title} · ethos` : 'ethos'}</title>;
}
