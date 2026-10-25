// Validador mínimo de JSON Schema para os testes (sem dependência nova). Cobre só o que o schema
// do export (src/lib/export/schema.md) usa: type (texto ou lista), const, enum, pattern,
// minLength, minimum, maximum, properties, required, additionalProperties: false, items, oneOf e
// $ref local ("#/$defs/<nome>"). Palavra-chave desconhecida lança, para o schema não usar algo que
// este validador ignoraria em silêncio.

const KNOWN = new Set([
  '$schema',
  'title',
  '$defs',
  '$ref',
  'type',
  'const',
  'enum',
  'pattern',
  'minLength',
  'minimum',
  'maximum',
  'properties',
  'required',
  'additionalProperties',
  'items',
  'oneOf',
]);

function typeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (Number.isInteger(value)) return 'integer';
  return typeof value;
}

function matchesType(value, type) {
  const actual = typeOf(value);
  return actual === type || (type === 'number' && actual === 'integer');
}

function resolve(root, ref) {
  const match = /^#\/\$defs\/([A-Za-z0-9_]+)$/.exec(ref);
  if (!match || !root.$defs?.[match[1]]) throw new Error(`$ref desconhecido: ${ref}`);
  return root.$defs[match[1]];
}

function check(root, schema, value, path, errors) {
  for (const key of Object.keys(schema)) {
    if (!KNOWN.has(key)) throw new Error(`palavra-chave não suportada: ${key} em ${path}`);
  }
  if (schema.$ref) {
    check(root, resolve(root, schema.$ref), value, path, errors);
    return;
  }
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((type) => matchesType(value, type))) {
      errors.push(`${path}: esperava ${types.join('|')}, veio ${typeOf(value)}`);
      return;
    }
  }
  if ('const' in schema && value !== schema.const) errors.push(`${path}: esperava ${schema.const}`);
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${path}: ${value} fora do enum`);
  if (typeof value === 'string') {
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) {
      errors.push(`${path}: "${value}" não casa com ${schema.pattern}`);
    }
    if (schema.minLength !== undefined && value.length < schema.minLength) {
      errors.push(`${path}: menor que ${schema.minLength}`);
    }
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path}: < ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path}: > ${schema.maximum}`);
  }
  if (schema.oneOf) {
    const passing = schema.oneOf.filter((option) => {
      const inner = [];
      check(root, option, value, path, inner);
      return inner.length === 0;
    });
    if (passing.length !== 1) errors.push(`${path}: casa com ${passing.length} opções do oneOf`);
  }
  if (typeOf(value) === 'object') {
    for (const key of schema.required ?? []) {
      if (!(key in value)) errors.push(`${path}: falta "${key}"`);
    }
    for (const [key, child] of Object.entries(value)) {
      const property = schema.properties?.[key];
      if (property) check(root, property, child, `${path}.${key}`, errors);
      else if (schema.additionalProperties === false) errors.push(`${path}: campo extra "${key}"`);
    }
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, index) => check(root, schema.items, item, `${path}[${index}]`, errors));
  }
}

/** Erros de `value` contra `schema` (lista vazia: válido). */
export function validateSchema(schema, value) {
  const errors = [];
  check(schema, schema, value, '$', errors);
  return errors;
}

/** O bloco ```json de um texto Markdown (o primeiro). */
export function jsonBlock(markdown) {
  const match = /```json\r?\n([\s\S]*?)\r?\n```/.exec(markdown);
  if (!match) throw new Error('bloco ```json não encontrado');
  return JSON.parse(match[1]);
}
