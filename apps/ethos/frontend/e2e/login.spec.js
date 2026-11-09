import { importedAdminEmail } from './env.js';
import {
  enterCode,
  expect,
  expectAccessible,
  goByMenu,
  loginPath,
  test,
  uniqueEmail,
  waitForPath,
} from './support.js';

// Max-Age do cookie da sessão: 400 dias, o máximo do Chrome (apps/imago/backend/app/auth/cookies.py)
const COOKIE_MAX_AGE = 400 * 24 * 60 * 60;

// Os X-User-* que o nginx põe a partir do imago, mandados pelo navegador como se fossem dele: o
// usuário 1, admin. As formas com "_" o nginx descarta (underscores_in_headers off)
const SPOOFED = {
  'X-User-Id': '1',
  'X-User-Email': 'intrusa@example.com',
  'X-User-Locale': 'en',
  'X-User-Timezone': 'Europe/Lisbon',
  'X-User-Admin': '1',
  X_User_Id: '1',
  X_User_Admin: '1',
};

test('sem login, uma tela do ethos leva ao /imago/entrar e, depois do código, volta para ela', async ({ page, request }, testInfo) => {
  const email = uniqueEmail(testInfo, 'next');

  // O 401 da API do ethos manda para a tela de entrar com a tela atual no `next`
  await page.goto('/ethos/relatorio');
  await waitForPath(page, loginPath('/ethos/relatorio'));
  await expectAccessible(page);
  const verified = await enterCode(page, request, email);

  await waitForPath(page, '/ethos/relatorio');
  await expect(page.getByRole('heading', { level: 1, name: 'Relatório' })).toBeVisible();

  // O cookie da sessão como em produção (o Chromium trata http://127.0.0.1 como origem segura)
  const setCookie = await verified.headerValue('set-cookie');
  expect(setCookie).toMatch(/^__Host-imago_session=[^;]+;/);
  const attributes = setCookie.split(';').slice(1).map((part) => part.trim().toLowerCase());
  expect(attributes).toEqual(
    expect.arrayContaining(['httponly', 'secure', 'samesite=lax', 'path=/', `max-age=${COOKIE_MAX_AGE}`]),
  );
  expect(attributes.filter((attribute) => attribute.startsWith('domain='))).toEqual([]);
  const now = Date.now() / 1000;
  const cookies = await page.context().cookies();
  expect(cookies).toEqual([
    expect.objectContaining({
      name: '__Host-imago_session',
      domain: '127.0.0.1',
      path: '/',
      httpOnly: true,
      secure: true,
      sameSite: 'Lax',
    }),
  ]);
  expect(cookies[0].expires).toBeGreaterThan(now + COOKIE_MAX_AGE - 300);
  expect(cookies[0].expires).toBeLessThan(now + COOKIE_MAX_AGE + 300);

  // Com a sessão, os X-User-* do navegador não mudam quem é a pessoa para o ethos: ele recebe os
  // do imago (a conta nova, que não é admin)
  const imagoMe = await (await page.request.get('/api/imago/me')).json();
  const ethosMe = await page.request.get('/api/ethos/me', { headers: SPOOFED });
  expect(ethosMe.status()).toBe(200);
  expect(await ethosMe.json()).toEqual({
    id: imagoMe.id,
    email,
    locale: 'pt',
    timezone: 'America/Sao_Paulo',
    is_admin: false,
  });
  const admin = await page.request.get('/api/ethos/admin/users', { headers: SPOOFED });
  expect(admin.status()).toBe(403);
});

test('X-User-* mandados pelo navegador sem sessão não chegam ao ethos', async ({ request }) => {
  for (const path of ['/api/ethos/me', '/api/ethos/habits', '/api/ethos/admin/users']) {
    const response = await request.get(path, { headers: SPOOFED });
    expect(response.status(), path).toBe(401);
    expect(await response.json(), path).toEqual({ error: 'not_authenticated', field: null });
  }
  // A API interna não passa pelo nginx
  const internal = await request.post('/api/ethos/internal/users/1/delete', { headers: SPOOFED });
  expect(internal.status()).toBe(404);
});

test('conta importada do ethos: aceita os termos novos, volta ao ethos e chega como admin', async ({ page, request }, testInfo) => {
  // Uma por projeto (o --imported-admin do stack), sem os termos aceitos, como as da passagem
  const email = importedAdminEmail(testInfo.project.name);

  await page.goto('/ethos/');
  await waitForPath(page, loginPath('/ethos/'));
  await enterCode(page, request, email);

  // Termos pendentes: o imago pede o aceite, e para o ethos a pessoa ainda não entrou
  await expect(page.getByRole('heading', { level: 1, name: 'Novos termos de uso' })).toBeVisible();
  await expect(page.getByText(`Você entrou como ${email}.`)).toBeVisible();
  expect((await page.request.get('/api/ethos/me')).status()).toBe(401);
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Aceitar e continuar' }).click();

  await waitForPath(page, '/ethos/');
  await expect(page.getByRole('heading', { level: 1, name: 'Hábitos' })).toBeVisible();
  // O X-User-Admin do imago chega ao ethos: o painel de admin abre e lista quem já abriu o ethos
  const me = await (await page.request.get('/api/ethos/me')).json();
  expect(me).toEqual(expect.objectContaining({ email, is_admin: true }));
  await goByMenu(page, 'Admin');
  await expect(page.getByRole('heading', { level: 1, name: 'Quem usa o ethos' })).toBeVisible();
  await expect(page.getByText(email, { exact: true })).toBeVisible();
  await expectAccessible(page);
});
