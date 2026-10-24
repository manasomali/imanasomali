import { afterEach, expect } from 'vitest';
import { cleanup } from '@testing-library/react';
import * as axeMatchers from 'vitest-axe/matchers';

// expect(await axe(container)).toHaveNoViolations() em todo teste de tela
expect.extend(axeMatchers);

// Sem globals do vitest, o Testing Library não desmonta sozinho entre os testes
afterEach(cleanup);
