import { useCallback, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiDroplet } from 'react-icons/fi';
import useHabitColor from '../../hooks/useHabitColor';
import { MIN_COLOR_CONTRAST, THEMES, THEME_COLORS, lowContrastThemes } from '../../lib/customColor';
import { HABIT_COLORS, isCustomColor, readPaletteHex } from '../../lib/palette';
import HabitSwatch from '../HabitSwatch';
import styles from './styles.module.css';

/** Contraste para o texto, cortado (não arredondado) em uma casa: 2,96 vira 2,9, nunca 3. */
function formatRatio(ratio, language) {
  return new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(Math.floor(ratio * 10) / 10);
}

// Cor do hábito no formulário (ETH-49): as 12 cores da paleta primeiro e, por último, a opção
// "personalizada", com um seletor de cor (<input type="color">). A cor própria é um hex só, usado
// nos dois temas: a prévia a mostra sobre o fundo de cada tema, e um aviso aparece quando ela tem
// menos de MIN_COLOR_CONTRAST:1 contra o fundo de algum deles (a cor é aceita mesmo assim).
// Props: `color` (nome da paleta ou "#rrggbb"), `customColor` (a última cor própria escolhida, ou
// ''), `onChange(color)` e `error` (o erro já traduzido, ou null) com o id dele em `errorId`
export default function ColorField({ color, customColor, onChange, error, errorId }) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const pickerRef = useRef(null);
  // Onde o seletor começa: a cor própria salva ou a cor atual da paleta no tema da página (sem o
  // CSS, o padrão do navegador)
  const [initialPick] = useState(() => customColor || readPaletteHex(color) || undefined);
  const custom = isCustomColor(color);
  const warnings = custom ? lowContrastThemes(color) : [];
  const name = t(`habit_form.colors.${custom ? 'custom' : color}`);
  const hintId = `${id}-custom-hint`;
  const warningsId = `${id}-contrast`;
  const describedBy = [hintId, warnings.length > 0 ? warningsId : null, error ? errorId : null]
    .filter(Boolean)
    .join(' ');

  // O navegador já devolve "#rrggbb" em minúsculas; o resto (nunca deveria vir) é ignorado
  const pick = (value) => {
    const hex = value.toLowerCase();
    if (isCustomColor(hex)) onChange(hex);
  };

  return (
    <fieldset className={styles.colors}>
      <legend className={styles.label}>
        {t('habit_form.color')}: {custom ? `${name} (${color})` : name}
      </legend>
      <div className={styles.palette}>
        {HABIT_COLORS.map((option) => (
          <label key={option} className={styles.colorOption} title={t(`habit_form.colors.${option}`)}>
            <input
              type="radio"
              name="color"
              value={option}
              className={`visually-hidden ${styles.colorRadio}`}
              checked={color === option}
              onChange={() => onChange(option)}
            />
            <HabitSwatch className={styles.colorSwatch} color={option} />
            <span className="visually-hidden">{t(`habit_form.colors.${option}`)}</span>
          </label>
        ))}
        <label className={styles.colorOption} title={t('habit_form.colors.custom')}>
          <input
            type="radio"
            name="color"
            value="custom"
            className={`visually-hidden ${styles.colorRadio}`}
            checked={custom}
            aria-describedby={describedBy}
            // Volta a última cor própria; na primeira vez, a que está no seletor
            onChange={() => pick(customColor || pickerRef.current.value)}
          />
          <CustomSwatch color={customColor} />
          <span className="visually-hidden">{t('habit_form.colors.custom')}</span>
        </label>
      </div>
      <div className={styles.customColor}>
        <label className={styles.customLabel} htmlFor={`${id}-picker`}>
          {t('habit_form.custom_color')}
        </label>
        <input
          ref={pickerRef}
          type="color"
          id={`${id}-picker`}
          className={styles.picker}
          defaultValue={initialPick}
          aria-describedby={describedBy}
          onChange={(event) => pick(event.target.value)}
        />
        {custom && <code className={styles.hex}>{color}</code>}
      </div>
      <p id={hintId} className={styles.hint}>
        {t('habit_form.custom_color_hint')}
      </p>
      {custom && (
        <div className={styles.colorPreview}>
          <p className={styles.previewLabel}>{t('habit_form.color_preview')}</p>
          <div className={styles.themePreviews}>
            {THEMES.map((theme) => (
              <ThemePreview key={theme} theme={theme} color={color} />
            ))}
          </div>
        </div>
      )}
      <div id={warningsId} aria-live="polite">
        {warnings.map(({ theme, ratio }) => (
          <p key={theme} className={styles.warning}>
            {t(`habit_form.low_contrast.${theme}`, {
              ratio: formatRatio(ratio, i18n.resolvedLanguage),
              min: MIN_COLOR_CONTRAST,
            })}
          </p>
        ))}
      </div>
      {error && (
        <p id={errorId} className={styles.fieldError}>
          {error}
        </p>
      )}
    </fieldset>
  );
}

// Bolinha da opção "personalizada": a última cor própria, ou um ícone antes da primeira escolha
function CustomSwatch({ color }) {
  const colorRef = useHabitColor(color || undefined);
  return (
    <span ref={colorRef} className={`${styles.colorSwatch} ${styles.customSwatch}`} aria-hidden="true">
      {!color && <FiDroplet size={16} />}
    </span>
  );
}

// A cor própria sobre o fundo de um tema: um dia marcado (com o número no texto que a tela usa) e
// um ponto sobre a superfície. As cores do tema vêm dos tokens (THEME_COLORS) e entram pelo CSSOM,
// como a cor do hábito
function ThemePreview({ theme, color }) {
  const { t } = useTranslation();
  const themeRef = useCallback(
    (element) => {
      if (!element) return;
      const colors = THEME_COLORS[theme];
      element.style.setProperty('--preview-bg', colors.bg);
      element.style.setProperty('--preview-surface', colors.surface);
      element.style.setProperty('--preview-fg', colors.fg);
    },
    [theme],
  );
  const dayRef = useHabitColor(color);
  return (
    <div ref={themeRef} className={styles.themePreview}>
      <span className={styles.themeName}>{t(`habit_form.themes.${theme}`)}</span>
      <span className={styles.previewSamples} aria-hidden="true">
        <span ref={dayRef} className={styles.previewDay}>
          12
        </span>
        <span className={styles.previewSurface}>
          <HabitSwatch className={styles.previewDot} color={color} />
        </span>
      </span>
    </div>
  );
}
