import React from 'react';
import { useTranslation } from 'react-i18next';

function FilterItem(props) {
  const { t, i18n } = useTranslation();
  return (<>{t(props.i18nKey)}</>);
}

export default FilterItem;