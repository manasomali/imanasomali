# Export JSON do ethos

Arquivo gerado no navegador pelo botão "Baixar JSON" do relatório (`/ethos/relatorio`) e pelo "Exportar tudo" (`toJson` em `json.js`). Este documento é a referência do formato. O bloco `json` no fim é um JSON Schema (draft 2020-12) que `json.test.js` usa para validar a saída: mudou o formato, mude o schema junto, ou o teste falha.

## Visão geral

```text
{
  "version": 1,
  "generated_at": "2026-10-24T15:00:00.000Z",
  "timezone": "America/Sao_Paulo",
  "period": { "from": "2026-01-01", "to": "2026-10-24" },
  "options": { "score": true, "reward": true, ... },
  "habits": [ { configuração, "marks": [...], "periods": [...] } ]
}
```

- `version`: versão do formato, hoje `1`. Sobe quando um leitor da versão anterior deixaria de entender o arquivo (campo removido ou com outro significado). Campo novo e opcional não muda a versão.
- `generated_at`: instante da geração, em UTC (ISO 8601).
- `timezone`: fuso IANA da conta. Todas as datas locais do arquivo (`period`, `date`, `time`, `first_day`, `last_day`) estão nesse fuso, como no app.
- `period`: o período do relatório, datas locais `AAAA-MM-DD`, as duas incluídas. No "Exportar tudo", vai da primeira marcação (ou da criação do hábito mais antigo) até hoje.
- `options`: as informações escolhidas na tela (no "Exportar tudo", todas `true`). Uma informação desligada, ou de um recurso desligado no hábito, some do arquivo: a chave nem aparece.
- `habits`: os hábitos do relatório, por id.

## Hábito

| Campo | Tipo | Quando aparece |
|---|---|---|
| `id` | inteiro | sempre |
| `name`, `color`, `status`, `role` | texto | sempre. `color`: um dos 12 nomes da paleta ou uma cor própria `#rrggbb` (minúsculas, a mesma nos dois temas); `status`: `active`, `paused`, `archived`; `role`: o papel de quem exportou (`owner`, `editor`, `viewer`) |
| `code`, `description` | texto ou null | sempre |
| `created_at`, `archived_at` | instante UTC (ISO 8601); `archived_at` null se não arquivado | sempre |
| `goal` | `{type, count, period, target, unit}` | sempre. `type`: `min`, `max`, `exact`; `period`: `week`, `month`, `year`; `target`: o alvo na unidade de `value` dos períodos; `unit`: `days` (uma marcação por dia), `marks` (várias por dia) ou `minutes` (duração ligada) |
| `multi_mark` | booleano | sempre |
| `duration_minutes` | inteiro ou null | duração escolhida e ligada no hábito |
| `score` | `{value, success, threshold}` | pontuação escolhida e ligada. `value` de 0 a 100 e `success` booleano, ou os dois null ("sem dados"). É a pontuação atual do hábito, não recortada pelo período |
| `reward`, `punishment` | texto ou null | escolhidos e com a pontuação ligada |
| `cost` | `{level, cents, limit_cents, limit_period, spend_cents}` | custo escolhido e ligado. `level`: `habit` ou `mark`; valores em centavos; `spend_cents`: o gasto das marcações do período |
| `marks` | lista de marcações | sempre (pode ser vazia) |
| `periods` | lista de períodos da meta | sempre |
| `cost_periods` | lista de períodos do limite | custo escolhido e ligado, com limite |

## Marcação (`marks[]`)

Só as do período, por instante.

| Campo | Tipo | Quando aparece |
|---|---|---|
| `id` | inteiro | sempre |
| `marked_at` | instante UTC (ISO 8601) | sempre |
| `date`, `time` | `AAAA-MM-DD` e `HH:MM` (24 h) no `timezone` | sempre |
| `author` | `{id, email}` ou null ("usuário removido") | autor escolhido |
| `duration_minutes` | inteiro ou null | duração escolhida e ligada |
| `cost_cents` | inteiro ou null | custo escolhido e ligado |
| `note` | texto ou null | observação escolhida e ligada |

## Períodos (`periods[]` e `cost_periods[]`)

Como o `GET /habits/progress` manda: os períodos que tocam o relatório, inteiros (o primeiro e o último podem começar antes e acabar depois do `period`). Não descontam criação nem pausa: são os números do que foi marcado.

- `periods[]`: `{first_day, last_day, value, met}` e, com o custo escolhido e ligado, `spend_cents`. `value` está na unidade de `goal.unit`; `met`: a meta foi cumprida no período.
- `cost_periods[]`: `{first_day, last_day, spend_cents, limit_percent}`, nos períodos do limite (`cost.limit_period`). `limit_percent` é o gasto em porcentagem do limite (pode passar de 100), ou null com limite 0.

## JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ethos export",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "generated_at", "timezone", "period", "options", "habits"],
  "properties": {
    "version": { "const": 1 },
    "generated_at": { "$ref": "#/$defs/instant" },
    "timezone": { "type": "string", "minLength": 1 },
    "period": {
      "type": "object",
      "additionalProperties": false,
      "required": ["from", "to"],
      "properties": {
        "from": { "$ref": "#/$defs/day" },
        "to": { "$ref": "#/$defs/day" }
      }
    },
    "options": {
      "type": "object",
      "additionalProperties": false,
      "required": ["score", "reward", "punishment", "cost", "duration", "note", "author"],
      "properties": {
        "score": { "type": "boolean" },
        "reward": { "type": "boolean" },
        "punishment": { "type": "boolean" },
        "cost": { "type": "boolean" },
        "duration": { "type": "boolean" },
        "note": { "type": "boolean" },
        "author": { "type": "boolean" }
      }
    },
    "habits": { "type": "array", "items": { "$ref": "#/$defs/habit" } }
  },
  "$defs": {
    "day": { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
    "time": { "type": "string", "pattern": "^\\d{2}:\\d{2}$" },
    "instant": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$"
    },
    "cents": { "type": "integer", "minimum": 0 },
    "period": { "enum": ["week", "month", "year"] },
    "habit": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id", "name", "code", "description", "color", "status", "role", "created_at",
        "archived_at", "goal", "multi_mark", "marks", "periods"
      ],
      "properties": {
        "id": { "type": "integer", "minimum": 1 },
        "name": { "type": "string" },
        "code": { "type": ["string", "null"] },
        "description": { "type": ["string", "null"] },
        "color": {
          "oneOf": [
            {
              "enum": [
                "red", "orange", "amber", "yellow", "lime", "green", "teal", "cyan", "blue",
                "indigo", "violet", "pink"
              ]
            },
            { "type": "string", "pattern": "^#[0-9a-f]{6}$" }
          ]
        },
        "status": { "enum": ["active", "paused", "archived"] },
        "role": { "enum": ["owner", "editor", "viewer"] },
        "created_at": { "$ref": "#/$defs/instant" },
        "archived_at": { "oneOf": [{ "$ref": "#/$defs/instant" }, { "type": "null" }] },
        "goal": {
          "type": "object",
          "additionalProperties": false,
          "required": ["type", "count", "period", "target", "unit"],
          "properties": {
            "type": { "enum": ["min", "max", "exact"] },
            "count": { "type": "integer", "minimum": 0 },
            "period": { "$ref": "#/$defs/period" },
            "target": { "type": "integer", "minimum": 0 },
            "unit": { "enum": ["days", "marks", "minutes"] }
          }
        },
        "multi_mark": { "type": "boolean" },
        "duration_minutes": { "type": ["integer", "null"], "minimum": 1 },
        "score": {
          "type": "object",
          "additionalProperties": false,
          "required": ["value", "success", "threshold"],
          "properties": {
            "value": { "type": ["integer", "null"], "minimum": 0, "maximum": 100 },
            "success": { "type": ["boolean", "null"] },
            "threshold": { "type": "integer", "minimum": 1, "maximum": 100 }
          }
        },
        "reward": { "type": ["string", "null"] },
        "punishment": { "type": ["string", "null"] },
        "cost": {
          "type": "object",
          "additionalProperties": false,
          "required": ["level", "cents", "limit_cents", "limit_period", "spend_cents"],
          "properties": {
            "level": { "enum": ["habit", "mark"] },
            "cents": { "oneOf": [{ "$ref": "#/$defs/cents" }, { "type": "null" }] },
            "limit_cents": { "oneOf": [{ "$ref": "#/$defs/cents" }, { "type": "null" }] },
            "limit_period": { "oneOf": [{ "$ref": "#/$defs/period" }, { "type": "null" }] },
            "spend_cents": { "$ref": "#/$defs/cents" }
          }
        },
        "marks": { "type": "array", "items": { "$ref": "#/$defs/mark" } },
        "periods": { "type": "array", "items": { "$ref": "#/$defs/goalPeriod" } },
        "cost_periods": { "type": "array", "items": { "$ref": "#/$defs/costPeriod" } }
      }
    },
    "mark": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "marked_at", "date", "time"],
      "properties": {
        "id": { "type": "integer", "minimum": 1 },
        "marked_at": { "$ref": "#/$defs/instant" },
        "date": { "$ref": "#/$defs/day" },
        "time": { "$ref": "#/$defs/time" },
        "author": {
          "oneOf": [
            {
              "type": "object",
              "additionalProperties": false,
              "required": ["id", "email"],
              "properties": {
                "id": { "type": "integer", "minimum": 1 },
                "email": { "type": "string", "minLength": 3 }
              }
            },
            { "type": "null" }
          ]
        },
        "duration_minutes": { "type": ["integer", "null"], "minimum": 1 },
        "cost_cents": { "oneOf": [{ "$ref": "#/$defs/cents" }, { "type": "null" }] },
        "note": { "type": ["string", "null"] }
      }
    },
    "goalPeriod": {
      "type": "object",
      "additionalProperties": false,
      "required": ["first_day", "last_day", "value", "met"],
      "properties": {
        "first_day": { "$ref": "#/$defs/day" },
        "last_day": { "$ref": "#/$defs/day" },
        "value": { "type": "integer", "minimum": 0 },
        "met": { "type": "boolean" },
        "spend_cents": { "$ref": "#/$defs/cents" }
      }
    },
    "costPeriod": {
      "type": "object",
      "additionalProperties": false,
      "required": ["first_day", "last_day", "spend_cents", "limit_percent"],
      "properties": {
        "first_day": { "$ref": "#/$defs/day" },
        "last_day": { "$ref": "#/$defs/day" },
        "spend_cents": { "$ref": "#/$defs/cents" },
        "limit_percent": { "type": ["integer", "null"], "minimum": 0 }
      }
    }
  }
}
```
