/* McA.jsontree: PURE lossless JSON parser for the tree view. Unlike JSON.parse it keeps every number's
   original lexeme (1.50, 1e-7, 20-digit integers) so nothing is reformatted or rounded, keeps object key
   order and duplicate keys, and accepts Python's NaN / Infinity / -Infinity.

   Node: {type: 'object'|'array'|'string'|'number'|'boolean'|'null'|'error', key, value, raw, children}
     key       property name (objects), index (arrays) or null at the root
     value     decoded string / boolean / null; for numbers the lexeme string; for containers the child count
     raw       number lexeme, else the source text of the scalar; for 'error' the whole input
     children  [node] for containers, else []
   Invalid input yields a single node {type:'error', message, index, line, column, raw}. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else (root.McA = root.McA || {}).jsontree = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var MAX_DEPTH = 512;

  function ParseError(msg, idx) { this.message = msg; this.index = idx; }

  function parseText(text) {
    var s = String(text), i = 0, n = s.length;
    if (s.charCodeAt(0) === 0xFEFF) i = 1;

    function ws() { while (i < n) { var c = s.charCodeAt(i); if (c === 32 || c === 9 || c === 10 || c === 13) i++; else break; } }
    function fail(msg) { throw new ParseError(msg, i); }

    function value(key, depth) {
      if (depth > MAX_DEPTH) fail('Nesting is too deep');
      ws();
      if (i >= n) fail('Unexpected end of input');
      var c = s.charAt(i);
      if (c === '{') return obj(key, depth);
      if (c === '[') return arr(key, depth);
      if (c === '"') { var st = i, v = str(); return { type: 'string', key: key, value: v, raw: s.slice(st, i), children: [] }; }
      if (s.substr(i, 4) === 'true') { i += 4; return lit(key, 'boolean', true, 'true'); }
      if (s.substr(i, 5) === 'false') { i += 5; return lit(key, 'boolean', false, 'false'); }
      if (s.substr(i, 4) === 'null') { i += 4; return lit(key, 'null', null, 'null'); }
      return num(key);
    }
    function lit(key, type, v, raw) { return { type: type, key: key, value: v, raw: raw, children: [] }; }

    function num(key) {
      var st = i;
      var m = /^(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|NaN|-?Infinity)/.exec(s.slice(i, i + 4096));
      if (!m) fail('Unexpected character ' + JSON.stringify(s.charAt(i)));
      i += m[0].length;
      return { type: 'number', key: key, value: s.slice(st, i), raw: s.slice(st, i), children: [] };
    }

    function str() {
      i++;                                                    // opening quote
      var out = '';
      for (;;) {
        if (i >= n) fail('Unterminated string');
        var c = s.charAt(i);
        if (c === '"') { i++; return out; }
        if (c === '\\') {
          var e = s.charAt(i + 1);
          var map = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
          if (e in map) { out += map[e]; i += 2; }
          else if (e === 'u') {
            var hex = s.substr(i + 2, 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) { i += 2; fail('Invalid \\u escape'); }
            out += String.fromCharCode(parseInt(hex, 16)); i += 6;
          } else { i++; fail('Invalid escape sequence'); }
        } else if (c.charCodeAt(0) < 0x20) fail('Control character in string');
        else { out += c; i++; }
      }
    }

    function arr(key, depth) {
      i++;
      var kids = [];
      ws();
      if (s.charAt(i) === ']') { i++; return { type: 'array', key: key, value: 0, raw: '[]', children: kids }; }
      for (;;) {
        kids.push(value(kids.length, depth + 1));
        ws();
        var c = s.charAt(i);
        if (c === ',') { i++; continue; }
        if (c === ']') { i++; break; }
        fail(i >= n ? 'Unexpected end of input' : 'Expected "," or "]"');
      }
      return { type: 'array', key: key, value: kids.length, raw: '', children: kids };
    }

    function obj(key, depth) {
      i++;
      var kids = [];
      ws();
      if (s.charAt(i) === '}') { i++; return { type: 'object', key: key, value: 0, raw: '{}', children: kids }; }
      for (;;) {
        ws();
        if (s.charAt(i) !== '"') fail('Expected a property name');
        var k = str();
        ws();
        if (s.charAt(i) !== ':') fail('Expected ":"');
        i++;
        kids.push(value(k, depth + 1));
        ws();
        var c = s.charAt(i);
        if (c === ',') { i++; continue; }
        if (c === '}') { i++; break; }
        fail(i >= n ? 'Unexpected end of input' : 'Expected "," or "}"');
      }
      return { type: 'object', key: key, value: kids.length, raw: '', children: kids };
    }

    var rootNode = value(null, 0);
    ws();
    if (i < n) fail('Unexpected data after the JSON value');
    return rootNode;
  }

  function parse(text) {
    if (text === null || text === undefined) return errorNode('No text', 0, '');
    var src = String(text);
    try { return parseText(src); }
    catch (e) {
      if (!(e instanceof ParseError)) throw e;
      return errorNode(e.message, e.index, src);
    }
  }
  function errorNode(message, index, src) {
    var before = src.slice(0, index), lines = before.split('\n');
    return { type: 'error', key: null, value: message, message: message, index: index, line: lines.length,
             column: lines[lines.length - 1].length + 1, raw: src, children: [] };
  }

  /** "{12}" or "[3]" for containers, else the scalar as written. */
  function summary(node) {
    if (node.type === 'object') return '{' + node.value + '}';
    if (node.type === 'array') return '[' + node.value + ']';
    if (node.type === 'string') return node.raw;
    return String(node.type === 'number' ? node.raw : node.value);
  }

  /** Re-serialize with the original lexemes (strings re-escaped with JSON.stringify). indent default 2. */
  function toText(node, indent) {
    var ind = indent === undefined ? 2 : indent;
    function w(nd, level) {
      if (nd.type === 'error') return nd.raw;
      if (nd.type === 'number') return nd.raw;
      if (nd.type === 'string') return JSON.stringify(nd.value);
      if (nd.type === 'boolean' || nd.type === 'null') return String(nd.value);
      if (!nd.children.length) return nd.type === 'array' ? '[]' : '{}';
      var pad = new Array(level * ind + 1).join(' '), pad2 = new Array((level + 1) * ind + 1).join(' ');
      var parts = nd.children.map(function (c) {
        return pad2 + (nd.type === 'object' ? JSON.stringify(c.key) + ': ' : '') + w(c, level + 1);
      });
      var open = nd.type === 'array' ? '[' : '{', close = nd.type === 'array' ? ']' : '}';
      return open + '\n' + parts.join(',\n') + '\n' + pad + close;
    }
    return w(node, 0);
  }

  /** Case-insensitive search over keys and scalar lexemes. Returns [{path:[...], node, where:'key'|'value'}]. */
  function find(node, query) {
    var q = String(query || '').toLowerCase(), out = [];
    if (!q) return out;
    (function walk(nd, path) {
      if (nd.key !== null && typeof nd.key === 'string' && nd.key.toLowerCase().indexOf(q) !== -1) out.push({ path: path, node: nd, where: 'key' });
      if (nd.type === 'object' || nd.type === 'array') nd.children.forEach(function (c) { walk(c, path.concat([c.key])); });
      else if (nd.type !== 'error') {
        var v = nd.type === 'number' ? nd.raw : String(nd.value);
        if (v.toLowerCase().indexOf(q) !== -1) out.push({ path: path, node: nd, where: 'value' });
      }
    })(node, []);
    return out;
  }

  return { parse: parse, summary: summary, toText: toText, find: find };
});
