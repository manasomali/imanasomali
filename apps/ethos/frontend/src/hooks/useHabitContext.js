import { useOutletContext } from 'react-router';

/**
 * Dentro de uma seção da aba do hábito (rota filha do HabitLayout): `{habit, timeZone}`, com o
 * hábito já carregado (HabitOut) e o fuso da conta. As telas do hábito (ETH-33 a 35) partem daqui.
 */
export default function useHabitContext() {
  return useOutletContext();
}
