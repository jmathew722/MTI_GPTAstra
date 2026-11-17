'use strict';
const fs = require('fs');
const path = require('path');
const FX = path.join(__dirname, '..', 'fixtures');
const LOGIC = path.join(__dirname, '..', '..', 'web', 'static', 'js', 'logic');
const CORE = path.join(__dirname, '..', '..', 'web', 'static', 'js', 'core');

exports.logic = (n) => require(path.join(LOGIC, n));
exports.core = (n) => require(path.join(CORE, n));
exports.lines = (name) => fs.readFileSync(path.join(FX, name), 'utf8').split('\n').filter((l, i, a) => !(i === a.length - 1 && l === ''));
exports.text = (name) => fs.readFileSync(path.join(FX, name), 'utf8');
exports.payload = () => JSON.parse(fs.readFileSync(path.join(FX, 'payload_sw.json'), 'utf8'));
exports.replay = (stages, kind, lines) => lines.reduce((t, l) => stages.reduce(t, l), stages.initial(kind));
exports.states = (track) => track.final.stages.map((s) => s.state);
