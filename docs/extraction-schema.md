# Extraction schema reference

A schema describes the fields you want from a page, using CSS selectors. It is plain JSON, so you can keep it in a file and use it from the command line (`politescrape extract URL --schema FILE`) or from Python (`page.extract(schema)`).

## Shape

```json
{
  "description": "Optional note for people reading the file",
  "items": "article.product_pod",
  "fields": {
    "title": "h3 a@title",
    "price": { "selector": ".price_color", "type": "number" }
  }
}
```

- `fields` (required) maps each output name to a field.
- `items` (optional) is a CSS selector for a repeated element, such as each product on a listing page. With `items`, the result is a list with one object per match, and field selectors are applied inside each match. Without `items`, the result is one object for the whole page.

## Fields

A field is either a short string or an object.

### Short form

| Short form | Meaning |
| --- | --- |
| `"h1"` | The text of the first `h1`. |
| `"a.next@href"` | The `href` attribute of the first `a.next`. |
| `"@data-id"` | The `data-id` attribute of the current element (useful with `items`). |

### Object form

| Option | Default | Meaning |
| --- | --- | --- |
| `selector` | the current element | CSS selector, relative to the page or to the current item. |
| `attr` | `"text"` | What to read: `"text"` (visible text, whitespace collapsed), `"html"` (inner HTML), `"markdown"`, or the name of any attribute. |
| `all` | `false` | Return a list of every match instead of the first one. |
| `type` | `"string"` | `"string"`, `"number"`, `"integer"`, `"url"` or `"boolean"`. |
| `pattern` | none | A regular expression applied to the value. If it has a group, the first group is kept; otherwise the whole match. No match gives the default. |
| `default` | `null` | Returned when nothing matches. |
| `fields` | none | Nested fields, read inside each matched element. Gives an object (or a list of objects with `all`). |

### Types

- `number` reads the first number in the text and drops thousands separators: `"Rs. 1,250.50"` gives `1250.5` and `"12 reviews"` gives `12`. Commas are always treated as thousands separators, so `"1.234,56"` style numbers need a `pattern`.
- `integer` is the same, with any fractional part dropped (`"4.9"` gives `4`).
- `url` resolves relative addresses against the page address.
- `boolean` is `true` when the selector matches anything, and ignores `attr`.

Empty values are treated as missing, so they fall back to `default`.

## A complete example

```json
{
  "items": ".job-card",
  "fields": {
    "id": "@data-job-id",
    "title": "h2",
    "company": { "selector": ".company", "default": "Unknown" },
    "salary": { "selector": ".salary", "pattern": "([\\d,]+)", "type": "integer" },
    "remote": { "selector": ".badge-remote", "type": "boolean" },
    "skills": { "selector": ".skill", "all": true },
    "apply_url": { "selector": "a.apply", "attr": "href", "type": "url" },
    "location": {
      "selector": ".location",
      "fields": { "city": ".city", "country": ".country" }
    }
  }
}
```

## Errors

Schemas are checked before anything is fetched. Mistakes raise `SchemaError` (or exit with code 2 on the command line) with a message naming the field, for example `fields.price: 'type' must be one of boolean, integer, number, string, url`.
